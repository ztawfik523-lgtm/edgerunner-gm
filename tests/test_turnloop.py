"""Tests for the improved AI turn loop, LLM adapter, and branching chat tree."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gameplay import GameplayService
import redkb
from server.coop import _CoopHub
from tests.test_library import _create_rules_db
from turnloop import ChatTreeStore, LLMConfig, OpenAICompatibleLLM, TurnEngine


class ScriptedLLM:
    """Deterministic local LLM stub implementing complete() and stream()."""

    def __init__(self, *, mode: str = "two_pass", complete_reply: str = "{}", stream_chunks: list[str] | None = None):
        self.config = LLMConfig(model="scripted-gm", mode=mode)
        self.complete_reply = complete_reply
        self.stream_chunks = stream_chunks or ["Neon rain ", "lashes the alley."]
        self.planner_calls: list[list[dict[str, str]]] = []
        self.narrator_calls: list[list[dict[str, str]]] = []

    async def complete(self, messages, **_kwargs):
        self.planner_calls.append(messages)
        return self.complete_reply

    def pop_call_meta(self):
        return {}

    async def stream(self, messages, **_kwargs):
        self.narrator_calls.append(messages)
        for chunk in self.stream_chunks:
            yield chunk


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    events = []
    for block in raw.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name, data_line = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev_name = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].strip()
        if ev_name and data_line is not None:
            events.append({"event": ev_name, "data": json.loads(data_line)})
    return events


def _seed_campaign(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
    camp_db = tmp_path / "campaign.sqlite"
    svc = GameplayService(camp_db, rules_db)
    camp = svc.execute("create_campaign", {"name": "Kabuki Heist", "operation_id": "seed-c1"})["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    char = svc.execute(
        "create_character",
        {"name": "Vee Mercer", "stats": stats, "skills": {"Handgun": 4}, "operation_id": "seed-ch1"},
    )["result"]
    svc.execute(
        "attach_character",
        {"campaign_id": camp["id"], "character_id": char["id"], "expected_revision": camp["revision"], "reason": "join", "operation_id": "seed-att1"},
    )
    svc.execute(
        "update_campaign",
        {"campaign_id": camp["id"], "expected_revision": 2, "changes": {"scene": "Back alley behind Afterlife"}, "reason": "init", "operation_id": "seed-sc1"},
    )
    return rules_db, camp_db, svc, camp["id"], char["id"]


@pytest.mark.anyio
async def test_openai_compatible_adapter_http_and_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body.get("stream"):
            sse = (
                'data: {"choices":[{"delta":{"content":"First "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"shot"}}]}\n\n'
                'data: [DONE]\n\n'
            ).encode()
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    llm = OpenAICompatibleLLM(
        LLMConfig(base_url="http://local.llm/v1", model="local-qwen"),
        transport=httpx.MockTransport(handler),
    )
    reply = await llm.complete([{"role": "user", "content": "hi"}], json_mode=True)
    assert reply == '{"ok":true}'
    chunks = [c async for c in llm.stream([{"role": "user", "content": "narrate"}])]
    assert "".join(chunks) == "First shot"


@pytest.mark.anyio
async def test_two_pass_turn_overclock_fuzzy_actor_and_homebrew(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    plan = {
        "checks": [
            {"actor": "vee", "skill": "Handgun", "dv": 13, "reason": "Quick draw in the alley"},
            {"actor": "vee", "skill": "Laser Magic", "dv": 10, "reason": "Hallucinated skill"},
        ],
        "state_ops": [
            {"type": "update_character", "actor": "Vee Mercer", "changes": {"money": 250}, "reason": "Credchip pickup"},
        ],
        "new_homebrew": [
            {
                "name": "Malorian Proto-Sub",
                "category": "weapon",
                "summary": "Prototype silenced smart SMG.",
                "stats": {"damage": "3d6", "rof": 1, "cost_eb": 1500},
            }
        ],
        "gm_notes": "Resolve gunshot and credchip loot.",
    }
    llm = ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps(plan),
        stream_chunks=["You pull ", "the trigger with chrome humming."],
    )
    engine = TurnEngine(svc, llm)
    events = [ev async for ev in engine.run_turn(camp_id, "I overclock my optics and shoot with my Handgun", overclock=True)]
    kinds = [e["event"] for e in events]

    assert "rule_citation" in kinds
    assert "dice_roll" in kinds
    assert "state_patch" in kinds
    assert "library_added" in kinds
    assert "warning" in kinds
    assert kinds[-1] == "turn_done"

    done = events[-1]["data"]
    assert done["assistant_message"]["content"] == "You pull the trigger with chrome humming."
    # Check Handgun citation was auto-retrieved in preprocess
    assert any(c["name"] == "Handgun" for c in done["citations"])
    # Check Overclock deducted 2 humanity and added +2 modifier
    assert done["rolls"][0]["overclock"] is True
    assert done["rolls"][0]["modifier"] == 2
    assert done["rolls"][0]["actor"] == "Vee Mercer"
    # Unverified skill was blocked with warning
    assert any("Laser Magic" in w for w in done["warnings"])
    # State + library updates landed in DB
    char = svc.execute("get_character", {"character_id": char_id})["result"]
    assert char["humanity"] == 58
    assert char["money"] == 250
    assert done["library_added"][0]["name"] == "Malorian Proto-Sub"


@pytest.mark.anyio
async def test_single_pass_tagged_mode_strips_control_tags(tmp_path: Path):
    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    llm = ScriptedLLM(
        mode="single_pass_tagged",
        stream_chunks=[
            "The fixer slides a black ",
            'datashard across the table.<gm_ops>{"state_ops":[{"type":"update_campaign","changes":{"scene":"Afterlife Booth 4"},"reason":"Moved inside"}]}</gm_ops>',
        ],
    )
    engine = TurnEngine(svc, llm)
    events = [ev async for ev in engine.run_turn(camp_id, "I head inside the Afterlife", mode="single_pass_tagged")]
    streamed = "".join(e["data"]["delta"] for e in events if e["event"] == "text_delta")
    assert "<gm_ops>" not in streamed
    assert streamed == "The fixer slides a black datashard across the table."

    done = events[-1]["data"]
    assert "<gm_ops>" not in done["assistant_message"]["content"]
    assert "<gm_ops>" in done["assistant_message"]["raw_content"]
    camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    assert camp["state"]["scene"] == "Afterlife Booth 4"


@pytest.mark.anyio
async def test_message_tree_branching_swipes_and_revision_warning(tmp_path: Path):
    rules_db, camp_db, svc, camp_id, _ = _seed_campaign(tmp_path)

    class TwoBranchLLM(ScriptedLLM):
        async def stream(self, messages, **_kwargs):
            count = len(self.narrator_calls)
            self.narrator_calls.append(messages)
            if count == 0:
                yield "Branch One: you walk left."
            else:
                yield "Branch Two: you walk right."

    plan_branch1 = json.dumps({"state_ops": [{"type": "update_character", "actor": "Vee Mercer", "changes": {"hp": 25}, "reason": "Trap hit"}]})
    llm = TwoBranchLLM(mode="two_pass", complete_reply=plan_branch1)
    engine = TurnEngine(svc, llm)

    t1 = [ev async for ev in engine.run_turn(camp_id, "First move")][-1]["data"]
    first_user_id = t1["user_message"]["id"]
    first_asst_id = t1["assistant_message"]["id"]

    # Branch as sibling of first_asst (swipe / alternate turn from user turn)
    llm.complete_reply = json.dumps({"checks": []})
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Run an alternate branch starting from first_user_id (simulating assistant swipe/regeneration)
        resp = await client.post(
            "/v1/chat/turn",
            headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "user_text": "Wait, let's check carefully", "parent_id": first_user_id},
        )
        assert resp.status_code == 200
        alt_events = _parse_sse(resp.text)
        alt_done = alt_events[-1]["data"]
        assert alt_done["assistant_message"]["content"] == "Branch Two: you walk right."

        tree = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id})).json()
        assert len(tree["active_branch"]) == 3  # first_user -> alt_user -> alt_asst
        # Child nodes under first_user_id now have 2 siblings (first_asst_id and alt_user_id)
        asst_node = next(n for n in tree["nodes"] if n["id"] == first_asst_id)
        assert asst_node["sibling_count"] == 2

        # Further state mutation advances character/campaign outside branch
        svc.execute(
            "update_campaign",
            {"campaign_id": camp_id, "expected_revision": 3, "changes": {"scene": "Vault"}, "reason": "Outside edit", "operation_id": "rev-bump"},
        )
        switched = await client.post(
            "/v1/chat/branch",
            headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "message_id": first_asst_id},
        )
        assert switched.status_code == 200
        sw_data = switched.json()
        assert sw_data["active_leaf_id"] == first_asst_id
        assert sw_data["revision_mismatch"] is True


@pytest.mark.anyio
async def test_regenerate_branch_from_root_settings_and_ui_serving(tmp_path: Path):
    rules_db, camp_db, _, camp_id, _ = _seed_campaign(tmp_path)
    settings_file = tmp_path / "settings.json"
    ui_dist = tmp_path / "ui_dist"
    (ui_dist / "assets").mkdir(parents=True)
    (ui_dist / "index.html").write_text("<html><body>Cyberpunk RED UI</body></html>", encoding="utf-8")
    (ui_dist / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")

    class CountingLLM(ScriptedLLM):
        def __init__(self):
            super().__init__(mode="two_pass", complete_reply=json.dumps({"checks": []}))
            self.turn_count = 0

        async def stream(self, messages, **_kwargs):
            self.narrator_calls.append(messages)
            self.turn_count += 1
            yield f"Reply #{self.turn_count}"

    llm = CountingLLM()
    app = redkb.make_api(
        rules_db,
        allowed_origins=(),
        campaign_path=camp_db,
        llm=llm,
        settings_path=settings_file,
        ui_dist=ui_dist,
    )

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        # Same-origin static UI serving
        root_resp = await client.get("/")
        assert root_resp.status_code == 200
        assert "Cyberpunk RED UI" in root_resp.text
        assert (await client.get("/assets/app.js")).status_code == 200
        assert (await client.get("/v1/nonexistent")).status_code == 404

        # Settings persistence and API key masking
        save_resp = await client.post(
            "/v1/settings/llm",
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
            json={
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen2.5:14b",
                "api_key": "sk-secret-value-9876",
                "temperature": 0.3,
                "mode": "two_pass",
            },
        )
        assert save_resp.status_code == 200
        saved = save_resp.json()
        assert saved["has_api_key"] is True
        assert "secret-value" not in saved["api_key_masked"]
        assert saved["model"] == "qwen2.5:14b"

        got = (await client.get("/v1/settings/llm")).json()
        assert got["model"] == "qwen2.5:14b"
        assert got["has_api_key"] is True

        # Turn 1
        t1 = await client.post(
            "/v1/chat/turn",
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "user_text": "Original opening"},
        )
        assert t1.status_code == 200
        t1_done = _parse_sse(t1.text)[-1]["data"]
        u1_id = t1_done["user_message"]["id"]
        a1_id = t1_done["assistant_message"]["id"]
        assert t1_done["assistant_message"]["content"] == "Reply #1"

        # Regenerate assistant reply without duplicating user message
        regen = await client.post(
            "/v1/chat/regenerate",
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "message_id": a1_id},
        )
        assert regen.status_code == 200
        regen_done = _parse_sse(regen.text)[-1]["data"]
        assert regen_done["user_message"]["id"] == u1_id
        assert regen_done["assistant_message"]["content"] == "Reply #2"

        # Edit root user message cleanly via branch_from_root=True
        edited = await client.post(
            "/v1/chat/turn",
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "user_text": "Edited opening", "branch_from_root": True},
        )
        assert edited.status_code == 200
        edited_done = _parse_sse(edited.text)[-1]["data"]
        assert edited_done["user_message"]["parent_id"] is None

        tree = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id})).json()
        assert len(tree["active_branch"]) == 2
        assert tree["active_branch"][0]["content"] == "Edited opening"
        assert tree["active_branch"][0]["sibling_count"] == 2


@pytest.mark.anyio
async def test_health_graceful_when_rules_missing(tmp_path: Path):
    missing_rules = tmp_path / "missing_rules.sqlite"
    app = redkb.make_api(missing_rules, campaign_path=tmp_path / "campaign.sqlite")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        data = health.json()
        assert data["status"] == "ok"
        assert data["rules_indexed"] is False
        skills = await client.get("/v1/skills")
        assert skills.status_code == 200
        assert skills.json()["rules_indexed"] is False


@pytest.mark.anyio
async def test_delete_update_guided_regen_export_and_coop(tmp_path: Path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    campaign_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    captured_prompts: list[str] = []

    class GuidedFakeLLM:
        def __init__(self):
            self.config = LLMConfig(model="coop-test-model")
            self.count = 0

        async def complete(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
            captured_prompts.append(messages[0]["content"])
            return '{"checks":[],"state_ops":[],"new_homebrew":[],"gm_notes":"ok"}'

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, *, temperature=None, max_tokens=None):
            self.count += 1
            captured_prompts.append(messages[0]["content"])
            yield f"Scene take #{self.count}"

    app = redkb.make_api(
        rules_db,
        campaign_path=campaign_db,
        llm=GuidedFakeLLM(),
        server_host="0.0.0.0",
        server_port=8765,
        room_pin="9911",
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as client:
        # Bootstrap an admin first (required for create_campaign)
        bootstrap_token = "test-bootstrap-token-" + ("a" * 40)
        setup_res = await client.post(
            "/v1/auth/setup",
            headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
            json={"admin_username": "admin", "admin_password": "admin-pass", "bootstrap_token": bootstrap_token},
        )
        assert setup_res.status_code == 200
        admin_token = setup_res.json()["token"]
        admin_headers = {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"}

        # Create campaign as admin
        camp_res = await client.post(
            "/v1/game",
            headers=admin_headers,
            json={"action": "create_campaign", "arguments": {"name": "LAN Night City", "operation_id": "op-coop-c1"}},
        )
        assert camp_res.status_code == 200
        camp_id = camp_res.json()["result"]["id"]

        # After admin bootstrap, unauthenticated requests need sign-in (use fresh client to avoid cookie persistence)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as unauth_client:
            unauth = await unauth_client.post(
                "/v1/chat/turn",
                headers={"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json"},
                json={"campaign_id": camp_id, "user_text": "Sneak in"},
            )
        assert unauth.status_code == 401
        assert unauth.json()["auth_required"] is True

        pin_headers = {
            "Origin": "http://127.0.0.1:8765",
            "Host": "127.0.0.1:8765",
            "Content-Type": "application/json",
            "X-RedGM-Pin": "9911",
            "X-RedGM-Client-Id": "player-a",
        }
        # Register co-op presence & inspect network info
        pres = await client.post(
            f"/v1/campaigns/{camp_id}/presence",
            headers=pin_headers,
            json={"client_id": "player-a", "player_name": "Alex", "is_host": True},
        )
        assert pres.status_code == 200
        assert pres.json()["players"][0]["player_name"] == "Alex"
        net = (await client.get("/v1/network/info", params={"campaign_id": camp_id})).json()
        assert net["lan_enabled"] is True
        # room_pin is configured, so pin_required is True regardless of PIN-only mode
        assert net["pin_required"] is True

        # Run initial turn with speaker attribution, then guided regenerate
        turn = await client.post(
            "/v1/chat/turn",
            headers=pin_headers,
            json={"campaign_id": camp_id, "user_text": "Open the hatch", "speaker_name": "Vee"},
        )
        assert turn.status_code == 200
        done1 = _parse_sse(turn.text)[-1]["data"]
        u1_id = done1["user_message"]["id"]
        a1_id = done1["assistant_message"]["id"]
        assert done1["user_message"]["metadata"]["speaker_name"] == "Vee"

        regen = await client.post(
            "/v1/chat/regenerate",
            headers=pin_headers,
            json={"campaign_id": camp_id, "message_id": a1_id, "guidance": "Make it rain outside"},
        )
        assert regen.status_code == 200
        done2 = _parse_sse(regen.text)[-1]["data"]
        a2_id = done2["assistant_message"]["id"]
        assert any("Make it rain outside" in p for p in captured_prompts)

        # Update message in place & export Markdown
        upd = await client.post(
            "/v1/chat/message/update",
            headers=pin_headers,
            json={"campaign_id": camp_id, "message_id": a2_id, "content": "Edited GM narration"},
        )
        assert upd.status_code == 200
        assert upd.json()["active_branch"][-1]["content"] == "Edited GM narration"
        exp = (await client.get("/v1/chat/export", params={"campaign_id": camp_id})).json()
        assert "Edited GM narration" in exp["markdown"]
        assert "## Vee (user)" in exp["markdown"]

        # Delete second reply -> reactivates sibling a1; then delete user node u1 -> empties branch
        deleted_reply = await client.post(
            "/v1/chat/delete",
            headers=pin_headers,
            json={"campaign_id": camp_id, "message_id": a2_id},
        )
        assert deleted_reply.status_code == 200
        assert deleted_reply.json()["active_branch"][-1]["id"] == a1_id

        deleted_root = await client.post(
            "/v1/chat/delete",
            headers=pin_headers,
            json={"campaign_id": camp_id, "message_id": u1_id},
        )
        assert deleted_root.status_code == 200
        assert deleted_root.json()["active_branch"] == []


@pytest.mark.anyio
async def test_failed_turn_rolls_back_orphaned_user_message(tmp_path: Path):
    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)

    class BrokenLLM(ScriptedLLM):
        async def complete(self, messages, **_kwargs):
            raise RuntimeError("401 Unauthorized")

    engine = TurnEngine(svc, BrokenLLM(mode="two_pass"))
    with pytest.raises(RuntimeError, match="401 Unauthorized"):
        _ = [ev async for ev in engine.run_turn(camp_id, "yo")]

    tree = engine.tree.get_tree(camp_id)
    assert tree["active_branch"] == []
    assert tree["nodes"] == []


@pytest.mark.anyio
async def test_prompts_include_inventory_and_state_ops_merge_safely(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    char = svc.execute("get_character", {"character_id": char_id})["result"]
    svc.execute(
        "update_character",
        {
            "character_id": char_id,
            "expected_revision": char["revision"],
            "changes": {"inventory": {"Medium Pistol": 1}},
            "reason": "Seed pistol",
            "operation_id": "seed-inv-1",
        },
        campaign_id=camp_id,
    )
    camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    svc.execute(
        "update_campaign",
        {
            "campaign_id": camp_id,
            "expected_revision": camp["revision"],
            "changes": {"npcs": {"Rogue": "Fixer"}},
            "reason": "Seed fixer",
            "operation_id": "seed-npc-1",
        },
        campaign_id=camp_id,
    )

    plan_json = json.dumps(
        {
            "checks": [],
            "state_ops": [
                {
                    "type": "update_character",
                    "actor": "Vee Mercer",
                    "changes": {"eddies": 900, "inventory": {"Data Shard": 1}},
                    "reason": "Found datashard",
                },
                {
                    "type": "update_campaign",
                    "changes": {
                        "location": "Kabuki Alley",
                        "npcs": {"Tiny Mike": {"role": "Techie", "mood": "Wary"}},
                    },
                    "reason": "Met Tiny Mike",
                },
            ],
        }
    )
    llm = ScriptedLLM(mode="two_pass", complete_reply=plan_json, stream_chunks=["You pocket the shard."])
    engine = TurnEngine(svc, llm)
    events = [ev async for ev in engine.run_turn(camp_id, "Inspect the shard")]
    assert events[-1]["event"] == "turn_done"

    # Both Planner and Narrator saw existing gear inventory
    assert "Medium Pistol" in llm.planner_calls[0][0]["content"]
    assert "Medium Pistol" in llm.narrator_calls[0][0]["content"]

    updated_char = svc.execute("get_character", {"character_id": char_id})["result"]
    assert updated_char["money"] == 900
    assert updated_char["inventory"] == {"Medium Pistol": 1, "Data Shard": 1}

    updated_camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    assert updated_camp["state"]["scene"] == "Kabuki Alley"
    assert updated_camp["state"]["npcs"]["Rogue"] == "Fixer"
    assert "Tiny Mike" in updated_camp["state"]["npcs"]
    assert "Techie" in updated_camp["state"]["npcs"]["Tiny Mike"]


@pytest.mark.anyio
async def test_readonly_game_actions_do_not_publish_sync_events(tmp_path: Path, monkeypatch):
    rules_db, camp_db, _, camp_id, _ = _seed_campaign(tmp_path)
    published: list[tuple[str, str, dict[str, Any]]] = []
    orig_publish = _CoopHub.publish

    def spy_publish(self, campaign_id: str, event: str, data: dict[str, Any]) -> None:
        published.append((campaign_id, event, data))
        orig_publish(self, campaign_id, event, data)

    monkeypatch.setattr(_CoopHub, "publish", spy_publish)
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}
        ro = await client.post(
            "/v1/game",
            headers=headers,
            json={"action": "campaign_context", "arguments": {}, "campaign_id": camp_id},
        )
        assert ro.status_code == 200
        assert published == []

        mut = await client.post(
            "/v1/game",
            headers=headers,
            json={
                "action": "update_campaign",
                "campaign_id": camp_id,
                "arguments": {
                    "expected_revision": ro.json()["result"]["campaign"]["revision"],
                    "changes": {"scene": "Heywood"},
                    "reason": "Sync test",
                    "operation_id": "sync-test-1",
                },
            },
        )
        assert mut.status_code == 200
        assert len(published) == 1
        assert published[0][1] == "sync"
        assert published[0][2]["action"] == "update_campaign"


@pytest.mark.anyio
async def test_delete_single_message_preserves_descendants(tmp_path: Path):
    rules_db, camp_db, _, camp_id, _ = _seed_campaign(tmp_path)
    llm = ScriptedLLM(mode="two_pass", complete_reply=json.dumps({"checks": []}), stream_chunks=["Reply"])
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        t1 = _parse_sse((await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "yo"})).text)[-1]["data"]
        t2 = _parse_sse((await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Actual move"})).text)[-1]["data"]
        u1_id = t1["user_message"]["id"]
        a1_id = t1["assistant_message"]["id"]
        u2_id = t2["user_message"]["id"]
        a2_id = t2["assistant_message"]["id"]

        res = await client.post(
            "/v1/chat/delete",
            headers=headers,
            json={"campaign_id": camp_id, "message_id": u1_id, "scope": "single"},
        )
        assert res.status_code == 200
        branch_ids = [m["id"] for m in res.json()["active_branch"]]
        assert branch_ids == [a1_id, u2_id, a2_id]
        assert res.json()["active_branch"][0]["parent_id"] is None


@pytest.mark.anyio
async def test_narrator_prompt_character_voice_and_temperature_split(tmp_path: Path):
    rules_db, camp_db, _, camp_id, _ = _seed_campaign(tmp_path)
    assert LLMConfig().temperature >= 0.7

    class CapturingLLM(ScriptedLLM):
        def __init__(self):
            super().__init__(mode="two_pass", complete_reply=json.dumps({"checks": []}), stream_chunks=["Vivid scene."])
            self.calls: list[tuple[str, float | None, str]] = []

        async def complete(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
            self.calls.append(("complete", temperature, messages[0]["content"]))
            return await super().complete(messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, *, temperature=None, max_tokens=None):
            self.calls.append(("stream", temperature, messages[0]["content"]))
            async for ch in super().stream(messages, temperature=temperature, max_tokens=max_tokens):
                yield ch

    cap = CapturingLLM()
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=cap)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Talk to the fixer"})
        assert res.status_code == 200

    planner_call = [c for c in cap.calls if c[0] == "complete"][0]
    narrator_call = [c for c in cap.calls if c[0] == "stream"][0]
    assert planner_call[1] == 0.1
    assert narrator_call[1] is None
    assert "personality" in narrator_call[2] and "speech_style" in narrator_call[2]
    assert "street economy" in narrator_call[2]
    assert "NEVER control, decide, or narrate the player character" in narrator_call[2]
    assert "without forcing off-screen contacts into unrelated scenes" in narrator_call[2]
    assert "Officer Vane" not in narrator_call[2]
    assert "Treat `Characters` JSON as canonical truth" in narrator_call[2]


@pytest.mark.anyio
async def test_gm_secrets_fog_of_war_persistence_and_isolation(tmp_path: Path):
    rules_db, camp_db, _, camp_id, _ = _seed_campaign(tmp_path)

    plans = [
        {
            "checks": [],
            "state_ops": [
                {
                    "type": "update_campaign",
                    "changes": {"npcs": {"Tomasz Nowak": "Tired dock clerk, guarded"}},
                    "reason": "PC met clerk",
                }
            ],
            "gm_secrets": {
                "nowak_employer": "Works off-books for Continental Brands",
                "dock_trap": "EMP mine taped under shutter",
            },
        },
        {
            "checks": [],
            "state_ops": [
                {
                    "type": "update_campaign",
                    "changes": {"discoveries": {"Dock Shutter": "Spotted and bypassed EMP mine"}},
                    "reason": "PC spotted trap",
                }
            ],
            "gm_secrets": {"dock_trap": None},
        },
        {"checks": []},
    ]

    class SecretCapturingLLM(ScriptedLLM):
        def __init__(self):
            super().__init__(mode="two_pass", complete_reply="{}", stream_chunks=["Clerk eyes the door."])
            self.planner_prompts: list[str] = []
            self.narrator_prompts: list[str] = []
            self.turn = 0

        async def complete(self, messages, *, temperature=None, max_tokens=None, json_mode=False):
            self.planner_prompts.append(messages[0]["content"])
            reply = json.dumps(plans[self.turn])
            self.turn += 1
            return reply

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, *, temperature=None, max_tokens=None):
            self.narrator_prompts.append(messages[0]["content"])
            async for ch in super().stream(messages, temperature=temperature, max_tokens=max_tokens):
                yield ch

    cap = SecretCapturingLLM()
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=cap)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Ask Tomasz who pays him."})
        assert r1.status_code == 200
        events1 = _parse_sse(r1.text)
        assert "Continental Brands" not in r1.text
        assert "EMP mine" not in r1.text
        assert not any(ev["event"] == "state_patch" and "gm_secrets" in json.dumps(ev["data"]) for ev in events1)

        ctx1 = (
            await client.post(
                "/v1/game",
                headers=headers,
                json={"action": "campaign_context", "arguments": {}, "campaign_id": camp_id},
            )
        ).json()
        state_str = json.dumps(ctx1["result"]["campaign"]["state"])
        assert "Tomasz Nowak" in state_str
        assert "Continental Brands" not in state_str
        assert "EMP mine taped under shutter" not in state_str
        tree1 = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id})).json()
        assert "Continental Brands" not in json.dumps(tree1)
        assert "EMP mine taped under shutter" not in json.dumps(tree1)

        r2 = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Check the shutter."})
        assert r2.status_code == 200
        r3 = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Wait inside."})
        assert r3.status_code == 200

    assert "Information Fog-of-War & Earned Intel" in cap.narrator_prompts[0]
    assert "Works off-books for Continental Brands" in cap.narrator_prompts[0]
    assert "Works off-books for Continental Brands" in cap.planner_prompts[1]
    assert "EMP mine taped under shutter" in cap.planner_prompts[1]
    assert "Works off-books for Continental Brands" in cap.planner_prompts[2]
    assert "EMP mine taped under shutter" not in cap.planner_prompts[2]
    assert "EMP mine taped under shutter" not in cap.narrator_prompts[2]


@pytest.mark.anyio
async def test_luck_spend_solo_ops_and_wound_awareness(tmp_path: Path):
    rules_db, camp_db, svc, camp_id, char_id = _seed_campaign(tmp_path)
    # Injure character below half HP (max_hp=40 -> hp=15 triggers Seriously Wounded -2)
    ch = svc.store.get_character(char_id)
    svc.execute(
        "update_character",
        {
            "character_id": char_id,
            "expected_revision": ch["revision"],
            "changes": {"hp": 15},
            "reason": "test wound",
            "operation_id": "wound-1",
        },
    )

    class SoloPlannerLLM:
        def __init__(self):
            self.planner_prompts: list[str] = []

        async def complete(self, messages, **_kwargs):
            self.planner_prompts.append("\n".join(m["content"] for m in messages))
            return json.dumps(
                {
                    "checks": [
                        {
                            "actor": "Vee Mercer",
                            "skill": "Handgun",
                            "dv": 13,
                            "reason": "Snap shot through smoke",
                        }
                    ],
                    "solo_ops": [
                        {
                            "action": "economy_action",
                            "actor": "Vee Mercer",
                            "mode": "job_reward",
                            "amount": 500,
                            "reason": "Fixer down-payment",
                        }
                    ],
                    "state_ops": [],
                    "gm_secrets": {},
                    "homebrew_entries": [],
                    "narration_notes": "Paid advance.",
                }
            )

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            yield "Vee takes the cash despite the bleeding."

    llm = SoloPlannerLLM()
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={"campaign_id": camp_id, "user_text": "Take the shot and grab the credchip.", "luck_spend": 2},
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

    roll_evs = [ev["data"] for ev in events if ev["event"] == "dice_roll"]
    assert len(roll_evs) == 1
    assert roll_evs[0]["luck_spent"] == 2
    assert roll_evs[0]["wound_modifier"] == -2
    assert "die" in roll_evs[0]

    done = [ev["data"] for ev in events if ev["event"] == "turn_done"][0]
    assert done["user_message"]["metadata"]["luck_spend"] == 2
    assert any(p["target"] == "character" and p["after"].get("money") == 500 for p in done["state_patches"])

    updated_char = svc.store.get_character(char_id)
    assert updated_char["luck_remaining"] == 4  # 6 - 2 committed luck
    assert updated_char["money"] == 500
    assert '"name": "serious"' in llm.planner_prompts[0]
    assert '"action_penalty": -2' in llm.planner_prompts[0]


@pytest.mark.anyio
async def test_world_clocks_branch_isolation_and_compress_memory(tmp_path: Path):
    rules_db, camp_db, svc, camp_id, _ = _seed_campaign(tmp_path)

    class ClockAndCompressLLM:
        def __init__(self):
            self.turn = 0
            self.planner_prompts: list[str] = []
            self.narrator_prompts: list[str] = []

        async def complete(self, messages, **_kwargs):
            sys_prompt = messages[0]["content"]
            user_prompt = messages[-1]["content"]
            if "campaign archivist" in sys_prompt.lower():
                return json.dumps(
                    {
                        "campaign_updates": {
                            "summary": "Met [NPC: Kira Sato] at [Location: Dock 14] and tracked patrol heat.",
                        },
                        "library_entries": [
                            {
                                "name": "Kira Sato",
                                "category": "npc",
                                "summary": "Ex-Trauma medic [Friendly +1]",
                                "description": "Patches runners off-grid inside Dock 14.",
                                "stats": {"disposition": 1, "role": "Medtech"},
                                "tags": ["npc", "medtech"],
                            },
                            {
                                "name": "Dock 14",
                                "category": "location",
                                "summary": "Flooded Watson freight slip",
                                "description": "Rusting container crane and cold-storage lockup.",
                                "stats": {"district": "Watson"},
                                "tags": ["location"],
                            },
                        ],
                    }
                )
            self.turn += 1
            self.planner_prompts.append("\n".join(m["content"] for m in messages))
            if self.turn == 1:
                return json.dumps(
                    {
                        "checks": [],
                        "state_ops": [
                            {"op": "set_npc", "key": "Kira Sato", "value": "Ex-Trauma medic [Friendly +1]"}
                        ],
                        "clock_ops": [
                            {"id": "ncpd-heat", "name": "NCPD Heat", "segments": 4, "filled": 1, "visibility": "public", "note": "Patrol sweeps block"},
                            {"id": "corp-hit-team", "name": "Corp Hit Team", "segments": 4, "filled": 2, "visibility": "secret", "note": "Ambush arrives"},
                        ],
                        "gm_secrets": {"Ambush": "Two Militech snipers on Pier 15"},
                        "homebrew_entries": [],
                        "narration_notes": "",
                    }
                )
            return json.dumps(
                {
                    "checks": [],
                    "state_ops": [],
                    "clock_ops": [],
                    "gm_secrets": {},
                    "homebrew_entries": [],
                    "narration_notes": "",
                }
            )

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            self.narrator_prompts.append("\n".join(m["content"] for m in messages))
            yield "Sirens echo over Watson while Kira checks the lock."

    llm = ClockAndCompressLLM()
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Meet Kira at Dock 14."})
        assert r1.status_code == 200
        user_id_1 = [ev["data"] for ev in _parse_sse(r1.text) if ev["event"] == "turn_done"][0]["user_message"]["id"]

        gm_clocks = (await client.get(f"/v1/campaigns/{camp_id}/clocks")).json()
        assert [c["name"] for c in gm_clocks["clocks"]] == ["NCPD Heat", "Corp Hit Team"]

        clocks_res = (await client.get(f"/v1/campaigns/{camp_id}/clocks", headers={"X-RedGM-View-Role": "user"})).json()
        assert [c["name"] for c in clocks_res["clocks"]] == ["NCPD Heat"]
        assert clocks_res["clocks"][0]["filled"] == 1

        tick_res = (
            await client.post(
                f"/v1/campaigns/{camp_id}/clocks",
                headers=headers,
                json={"action": "tick", "id": clocks_res["clocks"][0]["id"], "delta": 1},
            )
        ).json()
        assert tick_res["clocks"][0]["filled"] == 2

        comp_res = await client.post("/v1/chat/compress", headers=headers, json={"campaign_id": camp_id})
        assert comp_res.status_code == 200
        comp_body = comp_res.json()
        assert len(comp_body["library_upserted"]) == 2
        assert "[NPC: Kira Sato]" in comp_body["campaign"]["state"]["summary"]
        assert "Pier 15" not in json.dumps(comp_body)
        assert "Corp Hit Team" not in json.dumps(comp_body)

        # Next turn auto-retrieves cited [NPC: Kira Sato] dossier and keeps ticked NCPD Heat + secret clock
        r2 = await client.post("/v1/chat/turn", headers=headers, json={"campaign_id": camp_id, "user_text": "Check outside."})
        assert r2.status_code == 200
        assert "Ex-Trauma medic [Friendly +1]" in llm.planner_prompts[-1]
        assert "Patches runners off-grid inside Dock 14." in llm.narrator_prompts[-1]
        assert "NCPD Heat" in llm.planner_prompts[-1]
        assert "Corp Hit Team" in llm.planner_prompts[-1]

        # Regenerating Turn 1 only re-narrates it: no re-plan, and the new sibling keeps Turn 1's branch clocks.
        planner_calls_before = llm.turn
        regen = await client.post("/v1/chat/regenerate", headers=headers, json={"campaign_id": camp_id, "message_id": user_id_1})
        assert regen.status_code == 200
        assert llm.turn == planner_calls_before
        clocks_after_regen = (await client.get(f"/v1/campaigns/{camp_id}/clocks")).json()
        assert [c["name"] for c in clocks_after_regen["clocks"]] == ["NCPD Heat", "Corp Hit Team"]


@pytest.mark.anyio
async def test_ai_time_management_and_multi_call_chronicler(tmp_path: Path):
    rules_db, camp_db, svc, camp_id, char_id = _seed_campaign(tmp_path)

    class MultiCallLLM:
        enable_multi_call = True

        def __init__(self):
            self.narrator_prompts: list[str] = []
            self.chronicler_prompts: list[str] = []

        async def complete(self, messages, **_kwargs):
            sys_prompt = messages[0]["content"]
            if "post-turn chronicler" in sys_prompt.lower():
                self.chronicler_prompts.append("\n".join(m["content"] for m in messages))
                return json.dumps(
                    {
                        "time_elapsed_minutes": 120,
                        "state_ops": [
                            {
                                "type": "update_campaign",
                                "changes": {
                                    "npcs": {
                                        "Marek Kowalski": "Night-shift dock guard, Watson Pier 4 — Wary (-1); let Vee slip past the gate"
                                    }
                                },
                                "reason": "Record NPC introduced in narration",
                            }
                        ],
                        "clock_ops": [
                            {
                                "id": "shift-change",
                                "name": "Guard Shift Change",
                                "segments": 4,
                                "filled": 1,
                                "visibility": "secret",
                                "note": "Relief crew checks gate logs",
                            }
                        ],
                        "gm_secrets": {"Marek": "Takes synth-coke bribes on third shift"},
                    }
                )
            return json.dumps(
                {
                    "checks": [],
                    "time_elapsed_minutes": 45,
                    "state_ops": [],
                    "gm_secrets": {},
                    "new_homebrew": [],
                    "gm_notes": "Transit across Watson.",
                }
            )

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            self.narrator_prompts.append("\n".join(m["content"] for m in messages))
            yield "Forty-five minutes later at Watson Pier 4, night-shift guard Marek Kowalski waves you through."

    llm = MultiCallLLM()
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={"campaign_id": camp_id, "user_text": "Take the back streets to Watson Pier 4."},
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

    done = [ev["data"] for ev in events if ev["event"] == "turn_done"][0]
    assert "Day 1, 00:45 (Late Night)" in llm.narrator_prompts[0]
    assert len(llm.chronicler_prompts) == 1
    assert "Marek Kowalski" in llm.chronicler_prompts[0]

    # Planner time elapsed 45m was applied; Chronicler should not double-advance time in the same turn.
    ctx = svc.campaign_context(camp_id)
    assert ctx["solo"]["runtime"]["clock_minutes"] == 45
    assert "Marek Kowalski" in ctx["campaign"]["state"]["npcs"]
    assert any(
        p.get("target") == "solo" and p.get("after", {}).get("time") == "Day 1, 00:45 (Late Night)"
        for p in done["state_patches"]
    )
    assert "synth-coke bribes" not in json.dumps(done)

    # Direct SoloService advance_time updates both runtime and character detail clocks.
    adv_resp = svc.execute(
        "advance_time",
        {"elapsed_minutes": 30, "expected_revision": ctx["solo"]["revision"], "reason": "Wait for contact", "operation_id": "time-extra-1"},
        campaign_id=camp_id,
    )["result"]
    assert adv_resp["result"]["after_minutes"] == 75
    ctx2 = svc.campaign_context(camp_id)
    assert ctx2["solo"]["runtime"]["clock_minutes"] == 75
    assert ctx2["characters"][0]["detail"]["clock_minutes"] == 75


@pytest.mark.anyio
async def test_role_checks_solo_update_character_start_time_and_roll_ledger(tmp_path: Path):
    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    # Create & attach a Netrunner character with Interface stored in skills to verify role ability resolution.
    netrunner = svc.execute(
        "create_character",
        {
            "name": "Rook Sato",
            "stats": {"INT": 8, "REF": 7, "DEX": 7, "TECH": 6, "COOL": 6, "WILL": 7, "LUCK": 6, "MOVE": 6, "BODY": 5, "EMP": 6},
            "skills": {"Interface": 6, "Handgun": 4},
            "operation_id": "seed-netrunner-1",
        },
    )["result"]
    camp_rec = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    svc.execute(
        "attach_character",
        {
            "campaign_id": camp_id,
            "character_id": netrunner["id"],
            "expected_revision": camp_rec["revision"],
            "reason": "Attach netrunner",
            "operation_id": "attach-netrunner-1",
        },
        campaign_id=camp_id,
    )

    plan_1 = {
        "checks": [
            {"actor": "Rook Sato", "skill": "Interface", "dv": 10, "reason": "Scan local architecture"},
        ],
        "start_time": "22:15",
        "time_elapsed_minutes": 15,
        "solo_ops": [
            {"action": "update_character", "actor": "Rook Sato", "changes": {"money": 120, "inventory": {"Cyberdeck": 1}}, "reason": "Seed starting gear"},
        ],
        "gm_notes": "Interface scan + start time.",
    }
    llm = ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps(plan_1),
        stream_chunks=["You map the node cleanly."],
    )
    engine = TurnEngine(svc, llm)
    events = [ev async for ev in engine.run_turn(camp_id, "Jack in at 22:15 and scan.")]
    done = events[-1]["data"]

    # Interface check succeeded without getting blocked
    assert not any("Interface" in w for w in done["warnings"])
    assert not any("update_character" in w for w in done["warnings"])
    assert len(done["rolls"]) == 1
    assert done["rolls"][0]["stat"] == "ROLE"
    assert done["rolls"][0]["skill"] == "Interface"
    assert done["rolls"][0]["base"] == 6

    # Starting time 22:15 + 15m -> Day 1, 22:30 (Night)
    ctx = svc.campaign_context(camp_id)
    assert ctx["solo"]["runtime"]["clock_minutes"] == 22 * 60 + 30
    rook = next(c for c in ctx["characters"] if c["id"] == netrunner["id"])
    assert rook["money"] == 120
    assert rook["inventory"]["Cyberdeck"] == 1

    # Narrator prompt includes Authoritative Dice Roll Ledger with exact roll breakdown
    narrator_sys = llm.narrator_calls[0][0]["content"]
    assert "Authoritative Dice Roll Ledger:" in narrator_sys
    assert "Interface (ROLE): base 6" in narrator_sys

    # Turn 2 with no checks + luck_spend surfaces explicit NONE ledger & unspent LUCK note
    plan_2 = {"checks": [], "gm_notes": "Hold fire and ask player."}
    llm2 = ScriptedLLM(mode="two_pass", complete_reply=json.dumps(plan_2), stream_chunks=["Call your action first."])
    engine2 = TurnEngine(svc, llm2)
    awaitable = [ev async for ev in engine2.run_turn(camp_id, "Wait and watch.", luck_spend=2)]
    assert awaitable[-1]["event"] == "turn_done"
    narrator_sys_2 = llm2.narrator_calls[0][0]["content"]
    assert "NONE (0 rolls executed this turn" in narrator_sys_2
    assert "PRE-COMMITTED LUCK NOT SPENT: player offered 2 LUCK" in narrator_sys_2


@pytest.mark.anyio
async def test_start_encounter_normalizes_actors_and_failure_ledger(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    # Planner passes name + unknown NPC + duplicate + extra keys in start_encounter
    plan = {
        "checks": [
            {"actor": "Vee Mercer", "skill": "Handgun", "dv": 35, "reason": "Long shot"},
        ],
        "solo_ops": [
            {
                "action": "start_encounter",
                "actor": "Vee Mercer",
                "arguments": {
                    "character_ids": ["Vee Mercer", "Maelstrom Ganger", char_id],
                    "enemies": ["Maelstrom Ganger"],
                },
                "reason": "Alley ambush",
            }
        ],
    }
    llm = ScriptedLLM(mode="two_pass", complete_reply=json.dumps(plan), stream_chunks=["Shot missed."])
    engine = TurnEngine(svc, llm)
    events = [ev async for ev in engine.run_turn(camp_id, "Fire into the dark.")]
    done = events[-1]["data"]

    assert not any("start_encounter" in w for w in done["warnings"])
    ctx = svc.campaign_context(camp_id)
    enc = ctx["solo"]["runtime"]["encounter"]
    assert enc and enc["active"] is True
    assert enc["queue"] == [char_id]

    narrator_sys = llm.narrator_calls[0][0]["content"]
    assert "CLEAR FAILURE by" in narrator_sys
    assert "action DENIED/BLOCKED" in narrator_sys

    # Repeat start_encounter while active should cleanly no-op without warning
    llm2 = ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps({"solo_ops": [{"action": "start_encounter", "actor": "Vee Mercer"}]}),
        stream_chunks=["Still in combat."],
    )
    engine2 = TurnEngine(svc, llm2)
    done2 = [ev async for ev in engine2.run_turn(camp_id, "Hold position.")][-1]["data"]
    assert not any("start_encounter" in w for w in done2["warnings"])


@pytest.mark.anyio
async def test_gm_thinking_mode_balanced_and_quality(tmp_path: Path):
    import httpx
    from turnloop import LLMConfig, OpenAICompatibleLLM, _validate_llm_settings

    assert _validate_llm_settings({"gm_thinking_mode": "balanced"})["gm_thinking_mode"] == "balanced"
    with pytest.raises(ValueError, match="gm_thinking_mode"):
        _validate_llm_settings({"gm_thinking_mode": "fast"})

    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(body)
        if body.get("stream"):
            # Simulate strict provider rejecting chat_template_kwargs on first stream attempt
            if "chat_template_kwargs" in body and len([p for p in seen_payloads if p.get("stream")]) == 1:
                return httpx.Response(400, json={"error": "unsupported chat_template_kwargs"})
            sse = 'data: {"choices":[{"delta":{"content":"Rain falls."}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})
        if "Post-Turn Chronicler" in body["messages"][0]["content"]:
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"time_elapsed_minutes": 1})}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"checks": []})}}]})

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    llm = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="nemotron", mode="two_pass", retry_attempts=0),
        transport=httpx.MockTransport(handler),
    )

    balanced_engine = TurnEngine(svc, llm, turn_settings={"gm_thinking_mode": "balanced", "enable_chronicler": True})
    [ev async for ev in balanced_engine.run_turn(camp_id, "Look around the alley.")]

    # 1: Planner (no chat_template_kwargs), 2: Narrator 1st try (enable_thinking=False -> 400 fallback),
    # 3: Narrator retry (stripped), 4: Chronicler (enable_thinking=False)
    assert len(seen_payloads) == 4
    assert "chat_template_kwargs" not in seen_payloads[0]
    assert seen_payloads[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in seen_payloads[2]
    assert seen_payloads[3]["chat_template_kwargs"] == {"enable_thinking": False}

    seen_payloads.clear()
    quality_engine = TurnEngine(svc, llm, turn_settings={"gm_thinking_mode": "quality", "enable_chronicler": True})
    [ev async for ev in quality_engine.run_turn(camp_id, "Check my pockets.")]
    assert len(seen_payloads) == 3
    assert all("chat_template_kwargs" not in p for p in seen_payloads)


def test_delete_message_single_and_branch_preserves_active_invariants(tmp_path: Path):
    from turnloop import ChatTreeStore

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    tree = ChatTreeStore(svc)

    # Branch A: u1 -> a1 -> u2 -> a2
    u1 = tree.append_message(camp_id, parent_id=None, role="user", content="u1", campaign_revision=1, solo_revision=0)
    a1 = tree.append_message(camp_id, parent_id=u1["id"], role="assistant", content="a1", campaign_revision=1, solo_revision=0)
    u2 = tree.append_message(camp_id, parent_id=a1["id"], role="user", content="u2", campaign_revision=1, solo_revision=0)
    a2 = tree.append_message(camp_id, parent_id=u2["id"], role="assistant", content="a2", campaign_revision=1, solo_revision=0)

    # Sibling branch B under u1: a1_alt (becomes active; u2/a2 still had is_active=1 in DB!)
    a1_alt = tree.append_message(camp_id, parent_id=u1["id"], role="assistant", content="a1_alt", campaign_revision=1, solo_revision=0)
    assert [m["id"] for m in tree.get_tree(camp_id)["active_branch"]] == [u1["id"], a1_alt["id"]]

    # Deleting inactive a1 with scope="single" re-parents u2 under u1 WITHOUT making u2 active over a1_alt
    after_single_inactive = tree.delete_message(camp_id, a1["id"], scope="single")
    assert [m["id"] for m in after_single_inactive["active_branch"]] == [u1["id"], a1_alt["id"]]
    active_under_u1 = [n for n in after_single_inactive["nodes"] if n["parent_id"] == u1["id"] and n["is_active"]]
    assert [n["id"] for n in active_under_u1] == [a1_alt["id"]]

    # Now switch to u2 -> a2, then delete active u2 with scope="single" -> a2 re-parents to u1 and stays active!
    tree.switch_branch(camp_id, a2["id"])
    after_single_active = tree.delete_message(camp_id, u2["id"], scope="single")
    assert [m["id"] for m in after_single_active["active_branch"]] == [u1["id"], a2["id"]]
    active_under_u1_after = [n for n in after_single_active["nodes"] if n["parent_id"] == u1["id"] and n["is_active"]]
    assert [n["id"] for n in active_under_u1_after] == [a2["id"]]

    # Delete active a2 with scope="branch" -> reactivates sibling a1_alt cleanly
    after_branch_del = tree.delete_message(camp_id, a2["id"], scope="branch")
    assert [m["id"] for m in after_branch_del["active_branch"]] == [u1["id"], a1_alt["id"]]


@pytest.mark.anyio
async def test_intro_turn_uses_dedicated_prompt_token_limit_and_reports_generation_stats(tmp_path: Path):
    import httpx
    from turnloop import LLMConfig, OpenAICompatibleLLM

    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(body)
        sse = (
            'data: {"choices":[{"delta":{"content":"Welcome to 2045! "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"Roll 1d10 + STAT + Skill."}}],"usage":{"prompt_tokens":120,"completion_tokens":40,"total_tokens":160}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    llm = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="nemotron", max_tokens=900, mode="two_pass", retry_attempts=0),
        transport=httpx.MockTransport(handler),
    )
    engine = TurnEngine(
        svc,
        llm,
        turn_settings={"intro_max_tokens": 5120, "enable_chronicler": True},
        prompt_settings={"intro_prompt": "CUSTOM INTRO BRIEFING PROMPT"},
    )

    events = [ev async for ev in engine.run_turn(camp_id, "Introduce Cyberpunk RED", is_intro=True)]
    done = events[-1]["data"]

    # Intro turn runs a single stream call (no Planner/Chronicler) with its own prompt & token limit
    assert len(seen_payloads) == 1
    assert seen_payloads[0]["max_tokens"] == 5120
    assert "CUSTOM INTRO BRIEFING PROMPT" in str(seen_payloads[0]["messages"][0]["content"])
    assert seen_payloads[0]["stream_options"] == {"include_usage": True}

    stats = done["generation_stats"]
    assert stats["completion_tokens"] == 40
    assert stats["estimated"] is False
    assert stats["elapsed_seconds"] > 0
    assert stats["tokens_per_second"] > 0
    assert done["assistant_message"]["metadata"]["generation_stats"] == stats
    assert done["assistant_message"]["metadata"]["is_intro"] is True


@pytest.mark.anyio
async def test_coop_gatekeeper_manual_chat_roll_identity_privacy_and_ownership(tmp_path: Path):
    import httpx
    from turnloop import _summarize_character

    rules_db, camp_db, svc, camp_id, char_id = _seed_campaign(tmp_path)

    # 1. Update character profile with Handle vs hidden Real Name, Portrait URL, Color, and Owner
    ch = svc.store.get_character(char_id)
    updated_ch = svc.execute(
        "update_character_profile",
        {
            "character_id": char_id,
            "expected_revision": ch["revision"],
            "profile": {
                "handle": "Ghostwire",
                "real_name": "Elena Vance",
                "real_name_hidden": True,
                "portrait_url": "https://example.com/ghostwire.jpg",
                "color": "violet",
                "owner_username": "alice",
            },
            "reason": "Set identity privacy and ownership",
            "operation_id": "prof-ident-1",
        },
    )["result"]
    assert updated_ch["name"] == "Ghostwire"
    assert updated_ch["detail"]["handle"] == "Ghostwire"
    assert updated_ch["detail"]["real_name"] == "Elena Vance"
    assert updated_ch["detail"]["real_name_hidden"] is True
    assert updated_ch["detail"]["color"] == "violet"
    assert updated_ch["detail"]["owner_username"] == "alice"

    summary = _summarize_character(updated_ch)
    assert summary["handle"] == "Ghostwire"
    assert summary["real_name"] == "Elena Vance"
    assert summary["real_name_hidden"] is True
    assert "SECRET" in summary["identity_note"]

    # 2. Test Smart GM Gatekeeper (hold_gm + auto co-op party banter + auto intervention after 2 turns)
    llm = ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps(
            {
                "checks": [
                    {
                        "actor": "Ghostwire",
                        "skill": "Handgun",
                        "dv": 13,
                        "reason": "Suppressing fire",
                    }
                ],
                "state_ops": [],
                "narration_notes": "Resolved party turn",
            }
        ),
        stream_chunks=["Ghostwire's shot sparks off the bulkhead."],
    )
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Hold GM mode appends user message without assistant message
        r_hold = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={
                "campaign_id": camp_id,
                "user_text": "\"Cover the left flank, choom.\"",
                "speaker_character_id": char_id,
                "speaker_name": "Ghostwire",
                "gm_mode": "hold_gm",
            },
        )
        assert r_hold.status_code == 200
        ev_hold = _parse_sse(r_hold.text)
        done_hold = [e["data"] for e in ev_hold if e["event"] == "turn_done"][0]
        assert done_hold["gm_deferred"] is True
        assert done_hold["assistant_message"] is None

        # Force GM resolves the turn and attaches inline dice rolls to the user message metadata
        r_force = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={
                "campaign_id": camp_id,
                "user_text": "I fire at the drone.",
                "speaker_character_id": char_id,
                "speaker_name": "Ghostwire",
                "gm_mode": "force_gm",
            },
        )
        assert r_force.status_code == 200
        ev_force = _parse_sse(r_force.text)
        done_force = [e["data"] for e in ev_force if e["event"] == "turn_done"][0]
        assert done_force.get("gm_deferred") is not True
        assert done_force["assistant_message"] is not None
        assert len(done_force["user_message"]["metadata"]["rolls"]) == 1

        # 3. Manual Skill Roll endpoint (/v1/chat/roll) posts roll directly to chat and keeps revision_mismatch False
        r_roll = await client.post(
            "/v1/chat/roll",
            headers=headers,
            json={
                "campaign_id": camp_id,
                "character_id": char_id,
                "stat": "REF",
                "skill": "Handgun",
                "dv": 13,
                "modifier": 1,
                "luck": 0,
                "reason": "Manual table check",
            },
        )
        assert r_roll.status_code == 200
        roll_body = r_roll.json()
        assert roll_body["roll"]["skill"] == "Handgun"
        assert roll_body["message"]["metadata"]["manual_roll"] is True
        assert roll_body["tree"]["revision_mismatch"] is False

        # 4. Out-of-band state mutation via /v1/game with auto_revision=True syncs leaf revisions automatically
        r_game = await client.post(
            "/v1/game",
            headers=headers,
            json={
                "action": "update_character",
                "campaign_id": camp_id,
                "auto_revision": True,
                "arguments": {
                    "character_id": char_id,
                    "expected_revision": 0,  # stale revision auto-resolved!
                    "changes": {"money": 999},
                    "reason": "Loot credchip",
                    "operation_id": "auto-rev-test-1",
                },
            },
        )
        assert r_game.status_code == 200
        tree_after = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id})).json()
        assert tree_after["revision_mismatch"] is False

        # 5. Admin switching to User View via X-RedGM-View-Role: user enforces ownership & characterless lock
        user_view_headers = {**headers, "X-RedGM-View-Role": "user"}
        # Speaking without a character when require_character_to_speak is True returns 403
        r_no_char = await client.post(
            "/v1/chat/turn",
            headers=user_view_headers,
            json={
                "campaign_id": camp_id,
                "user_text": "Hello from characterless observer",
            },
        )
        assert r_no_char.status_code == 403
        assert "create or claim a character" in r_no_char.json()["detail"].lower()


@pytest.mark.anyio
async def test_hybrid_intro_primer_and_gender_pronouns(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    char = svc.store.get_character(char_id)
    updated_char = svc.execute(
        "update_character_profile",
        {
            "character_id": char_id,
            "expected_revision": char["revision"],
            "profile": {"gender": "Non-Binary", "pronouns": "they/them"},
            "reason": "Set gender and pronouns",
            "operation_id": "set-gp-1",
        },
        campaign_id=camp_id,
    )["result"]
    assert updated_char["detail"]["gender"] == "Non-Binary"
    assert updated_char["detail"]["pronouns"] == "they/them"

    llm = ScriptedLLM(
        mode="two_pass",
        complete_reply="{}",
        stream_chunks=["Welcome to Heywood Glen. Talk to Marta or inspect the depot chip."],
    )
    engine = TurnEngine(svc, llm)
    events = [
        ev
        async for ev in engine.run_turn(
            camp_id,
            "Give me an introductory first message explaining what Cyberpunk RED is, how the rules and stats work, and what roles or characters I can play.",
            speaker_character_id=char_id,
            is_intro=True,
        )
    ]
    deltas = "".join(ev["data"]["delta"] for ev in events if ev["event"] == "text_delta")
    assert "WELCOME TO CYBERPUNK RED" in deltas
    assert "1d10 + STAT + Skill" in deltas
    assert "Netrunner" in deltas and "Nomad" in deltas
    assert "CAMPAIGN TABLE WELCOME" in deltas
    assert "Welcome to Heywood Glen" in deltas

    done = [ev["data"] for ev in events if ev["event"] == "turn_done"][0]
    assert done["assistant_message"]["metadata"]["is_intro"] is True


@pytest.mark.anyio
async def test_npc_privacy_user_account_update_and_split_scene_channels(tmp_path: Path):
    import httpx
    from auth import AuthManager
    from redkb import make_api

    db_path = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
    camp_path = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"

    auth = AuthManager(settings_path)
    auth.setup_initial(admin_username="gm", admin_password="gm-password", user_username="alice", user_password="alice-password")
    gm_token = auth.authenticate(username="gm", password="gm-password")["token"]
    alice_token = auth.authenticate(username="alice", password="alice-password")["token"]

    app = make_api(db_path, campaign_path=camp_path, settings_path=settings_path, llm=ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps({"checks": [], "gm_notes": "Resolve split scene."}),
        stream_chunks=["Neon flickers over the loading dock."],
    ))
    gm_headers = {"Authorization": f"Bearer {gm_token}", "Origin": "http://test"}
    alice_headers = {"Authorization": f"Bearer {alice_token}", "Origin": "http://test"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Create campaign and two PCs (one owned by alice)
        camp_res = (await client.post("/v1/game", headers=gm_headers, json={
            "action": "create_campaign",
            "arguments": {"name": "Split Ops", "operation_id": "c-split-1"},
        })).json()["result"]
        camp_id = camp_res["id"]

        c1 = (await client.post("/v1/game", headers=alice_headers, json={
            "action": "create_character",
            "arguments": {
                "name": "Ghostwire",
                "stats": {"INT": 7, "REF": 6, "DEX": 6, "TECH": 6, "COOL": 6, "WILL": 6, "LUCK": 6, "MOVE": 6, "BODY": 5, "EMP": 6},
                "skills": {"Interface": 6},
                "detail": {"handle": "Ghostwire", "gender": "Female", "pronouns": "she/her"},
                "operation_id": "char-gw-1",
            },
        })).json()["result"]
        c2 = (await client.post("/v1/game", headers=gm_headers, json={
            "action": "create_character",
            "arguments": {
                "name": "Brick",
                "stats": {"INT": 5, "REF": 7, "DEX": 6, "TECH": 5, "COOL": 6, "WILL": 6, "LUCK": 6, "MOVE": 6, "BODY": 8, "EMP": 5},
                "skills": {"Handgun": 6},
                "detail": {"handle": "Brick", "owner_username": "bob"},
                "operation_id": "char-br-1",
            },
        })).json()["result"]
        for idx, cid in enumerate((c1["id"], c2["id"]), start=1):
            await client.post("/v1/game", headers=gm_headers, json={
                "action": "attach_character",
                "campaign_id": camp_id,
                "auto_revision": True,
                "arguments": {
                    "campaign_id": camp_id,
                    "character_id": cid,
                    "expected_revision": 1,
                    "reason": "Attach PC",
                    "operation_id": f"att-split-{idx}",
                },
            })

        # 1. Self-service account username & password update migrates character ownership
        me_res = await client.post("/v1/auth/me", headers=alice_headers, json={
            "current_password": "alice-password",
            "new_username": "alice_net",
            "new_password": "new-alice-password",
        })
        assert me_res.status_code == 200
        new_alice_token = me_res.json()["token"]
        assert me_res.json()["username"] == "alice_net"
        alice_headers = {"Authorization": f"Bearer {new_alice_token}", "Origin": "http://test"}

        ctx_after_rename = (await client.post("/v1/game", headers=alice_headers, json={
            "action": "campaign_context",
            "campaign_id": camp_id,
            "arguments": {"campaign_id": camp_id},
        })).json()["result"]
        gw_after = next(c for c in ctx_after_rename["characters"] if c["id"] == c1["id"])
        assert gw_after["detail"]["owner_username"] == "alice_net"

        # 2. NPC Handle vs Real Name Privacy: Admin sees hidden real name, normal player does NOT
        npc_res = await client.post(f"/v1/campaigns/{camp_id}/npc-identity", headers=gm_headers, json={
            "handle": "Drone-Mother",
            "description": "Disgraced Zhirafa rigger — Neutral 0",
            "real_name": "Marta Koval",
            "real_name_hidden": True,
        })
        assert npc_res.status_code == 200
        assert npc_res.json()["npc_profiles"]["Drone-Mother"]["real_name"] == "Marta Koval"

        ctx_player = (await client.post("/v1/game", headers=alice_headers, json={
            "action": "campaign_context",
            "campaign_id": camp_id,
            "arguments": {"campaign_id": camp_id},
        })).json()["result"]
        assert ctx_player["npc_profiles"]["Drone-Mother"]["real_name_hidden"] is True
        assert "real_name" not in ctx_player["npc_profiles"]["Drone-Mother"]

        # 3. Party Split -> Separate Scene Channels -> Independent Turn + Reunion
        split_res = await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=gm_headers, json={
            "pc_locations": {
                c1["id"]: "Zhirafa Depot Dock",
                c2["id"]: "La Casita Rooftop",
            },
        })
        assert split_res.status_code == 200
        grouping = split_res.json()["party_grouping"]
        assert grouping["mode"] == "split"
        assert len(grouping["channels"]) == 2
        gw_chan = grouping["char_channel_map"][c1["id"]]
        br_chan = grouping["char_channel_map"][c2["id"]]
        assert gw_chan != br_chan

        turn_res = await client.post("/v1/chat/turn", headers=alice_headers, json={
            "campaign_id": camp_id,
            "channel_id": gw_chan,
            "speaker_character_id": c1["id"],
            "speaker_name": "Ghostwire",
            "user_text": "I jack into the dock gate panel.",
            "gm_mode": "force_gm",
        })
        assert turn_res.status_code == 200
        assert "turn_done" in turn_res.text

        # Split channel has the turn, while Brick's channel stays isolated and Main Table only has the split notice
        gw_tree = (await client.get("/v1/chat/tree", headers=alice_headers, params={"campaign_id": camp_id, "channel_id": gw_chan})).json()
        br_tree = (await client.get("/v1/chat/tree", headers=gm_headers, params={"campaign_id": camp_id, "channel_id": br_chan})).json()
        assert len(gw_tree["active_branch"]) == 2
        assert len(br_tree["active_branch"]) == 0

        # Reunite back to Main Table
        reunite_res = await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=gm_headers, json={
            "action": "reunite",
            "location": "Safe House",
        })
        assert reunite_res.status_code == 200
        assert reunite_res.json()["party_grouping"]["mode"] == "together"
        main_tree = (await client.get("/v1/chat/tree", headers=gm_headers, params={"campaign_id": camp_id, "channel_id": "main"})).json()
        assert any("reunited" in m["content"].lower() for m in main_tree["active_branch"])

        # 4. Security & mid-campaign regressions:
        # - Non-admin cannot overwrite NPC hidden identities or move another player's PC
        forb_npc = await client.post(f"/v1/campaigns/{camp_id}/npc-identity", headers=alice_headers, json={
            "handle": "Drone-Mother",
            "real_name_hidden": False,
        })
        assert forb_npc.status_code == 403
        forb_loc = await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=alice_headers, json={
            "pc_locations": {c2["id"]: "Hijacked Location"},
        })
        assert forb_loc.status_code == 403
        # - Mid-campaign hidden NPC identity added after turns still persists in campaign_context
        mid_npc = await client.post(f"/v1/campaigns/{camp_id}/npc-identity", headers=gm_headers, json={
            "handle": "Zero-Cool",
            "description": "Netwatch mole — Neutral 0",
            "real_name": "Elena Vance",
            "real_name_hidden": True,
        })
        assert mid_npc.status_code == 200
        adm_ctx = (await client.post("/v1/game", headers=gm_headers, json={
            "action": "campaign_context",
            "campaign_id": camp_id,
            "arguments": {"campaign_id": camp_id},
        })).json()["result"]
        assert adm_ctx["npc_profiles"]["Zero-Cool"]["real_name"] == "Elena Vance"
        usr_ctx = (await client.post("/v1/game", headers=alice_headers, json={
            "action": "campaign_context",
            "campaign_id": camp_id,
            "arguments": {"campaign_id": camp_id},
        })).json()["result"]
        assert "real_name" not in usr_ctx["npc_profiles"]["Zero-Cool"]
        # - Moving both PCs to the same location via pc_locations automatically collapses mode -> together
        await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=gm_headers, json={
            "pc_locations": {c1["id"]: "Zone A", c2["id"]: "Zone B"},
        })
        same_loc = await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=gm_headers, json={
            "pc_locations": {c1["id"]: "Afterlife Booth", c2["id"]: "Afterlife Booth"},
        })
        assert same_loc.status_code == 200
        assert same_loc.json()["party_grouping"]["mode"] == "together"


def test_summarize_character_equipped_and_anti_rain_prompt():
    from turnloop import DEFAULT_PROMPT_TEMPLATES, _summarize_character

    summary = _summarize_character({
        "id": "c-eq-1",
        "name": "Marek",
        "hp": 35,
        "max_hp": 35,
        "humanity": 60,
        "luck_remaining": 6,
        "money": 500,
        "stats": {"BODY": 6, "MOVE": 6},
        "skills": {"Handgun": 4},
        "inventory": {"Heavy Pistol": 1, "Light Armorjack Body (SP 11)": 1},
        "detail": {
            "equipped_weapon": "Heavy Pistol",
            "equipped_armor": {"name": "Light Armorjack Body (SP 11)", "sp": 11},
            "equipped_head_armor": {"name": "Light Armorjack Head (SP 11)", "sp": 11},
        },
    })
    assert summary["equipped_weapon"] == "Heavy Pistol"
    assert summary["equipped_armor"] == {"name": "Light Armorjack Body (SP 11)", "sp": 11}
    assert summary["equipped_head_armor"] == {"name": "Light Armorjack Head (SP 11)", "sp": 11}
    rules = DEFAULT_PROMPT_TEMPLATES["narrator_core_rules"]
    assert "equipped_weapon" in rules
    assert "equipped_armor" in rules
    assert "Continue in media res" in rules


def test_expanded_style_length_pacing_and_npc_personality_recall(tmp_path: Path):
    from turnloop import (
        _GM_STYLE_HINTS,
        _LENGTH_HINTS,
        _PACING_HINTS,
        _validate_llm_settings,
        build_npc_profiles,
    )

    assert "spy_thriller" in _GM_STYLE_HINTS
    assert "grit_dark" in _GM_STYLE_HINTS
    assert "full_action" in _GM_STYLE_HINTS
    assert "auto" in _LENGTH_HINTS
    assert "novel" in _LENGTH_HINTS
    assert "slow_burn" in _PACING_HINTS

    validated = _validate_llm_settings({
        "gm_style": "spy_thriller",
        "narrator_length": "auto",
        "narrator_pacing": "slow_burn",
    })
    assert validated["gm_style"] == "spy_thriller"
    assert validated["narrator_length"] == "auto"
    assert validated["narrator_pacing"] == "slow_burn"

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    engine = TurnEngine(svc, None)
    engine.library.add_entry(
        camp_id,
        name="Sadia Kouri",
        category="npc",
        summary="Dockside fixer who trades favors for cold-chain manifests.",
        description="Runs a cramped office above Berth 4.",
        stats={"role": "Fixer", "disposition": "Wary (-1)", "personality": "guarded, dry humor", "speech_style": "short clipped sentences"},
        created_by="ai",
        operation_id="npc-lib-1",
    )
    saved = engine._saved_campaign_npcs(camp_id)
    assert len(saved) == 1
    assert saved[0]["personality"] == "guarded, dry humor"
    assert saved[0]["speech_style"] == "short clipped sentences"

    # _collect_citations should recall Sadia Kouri when she is in state.npcs even if not named in user_text
    cits = engine._collect_citations(camp_id, "I look around the loading bay", {"scene": "Docks", "summary": "", "npcs": {"Sadia Kouri": "Fixer — Wary (-1)"}})
    assert any(c["name"] == "Sadia Kouri" for c in cits)

    # build_npc_profiles preserves personality and speech_style from __npc_identities
    state = {
        "npcs": {"Sadia Kouri": "Fixer — Wary (-1)"},
        "discoveries": {
            "__npc_identities": json.dumps({
                "Sadia Kouri": {"handle": "Sadia Kouri", "real_name_hidden": True, "personality": "guarded", "speech_style": "clipped"}
            })
        },
    }
    profs = build_npc_profiles(state)
    assert profs["Sadia Kouri"]["personality"] == "guarded"
    assert profs["Sadia Kouri"]["speech_style"] == "clipped"


def test_session_zero_and_campaign_meta_flow_into_turnloop_prompts(tmp_path):
    from turnloop import encode_campaign_meta_json, encode_session_zero_json

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    camp = svc.memory.get_campaign(camp_id)
    svc.memory.update_campaign(
        camp_id,
        camp["revision"],
        {
            "discoveries": {
                "__campaign_meta": encode_campaign_meta_json({
                    "district": "Heywood",
                    "zone_type": "Moderate Zone",
                    "threat_rating": "Moderate",
                    "caper_style": "Street Turf & Night Market Hustle",
                    "factions": ["6th Street"],
                }),
                "__session_zero": encode_session_zero_json({
                    "gm_style": "noir_mystery",
                    "narrator_length": "concise",
                    "narrator_pacing": "slow_burn",
                    "lethality_dial": "Gritty / High Lethality",
                    "crew_concept": "Ex-paramedic clinic crew",
                    "lines_and_veils": "No torture",
                }),
            }
        },
        "Seed session zero and campaign meta",
        "op-sz-1",
    )
    engine = TurnEngine(svc, None)
    prep = engine.preprocess(camp_id, "Inspect the alley door")
    planner_msgs = engine._build_planner_messages(prep, "Inspect the alley door", overclock=False)
    narrator_msgs = engine._build_narrator_messages(prep, "Inspect the alley door", {"outcomes": {"rolls": []}})
    intro_msgs = engine._build_intro_messages(prep, "Begin")

    assert "Hardboiled investigation" in planner_msgs[0]["content"]
    assert "No torture" in planner_msgs[0]["content"]
    assert "Keep replies crisp (1-2 tight paragraphs)" in narrator_msgs[0]["content"]
    assert "Slow burn and tension" in narrator_msgs[0]["content"]
    assert "Ex-paramedic clinic crew" in narrator_msgs[0]["content"]
    assert "Heywood" in intro_msgs[0]["content"]
    assert "No torture" in intro_msgs[0]["content"]


def test_stream_sanitizer_and_strip_gm_tags_hardening():
    from turnloop import StreamSanitizer, strip_gm_tags

    # strip_gm_tags strips closed & unclosed <think>, <gm_ops>, and [[GM_STATE:...]]
    assert strip_gm_tags("<THINK>hidden</think>\n\nNeon rain.") == "Neon rain."
    assert strip_gm_tags("Visible <think>unclosed secret") == "Visible"
    assert strip_gm_tags('Talk.<gm_ops>{"checks":[{"actor":"V"}]}</gm_ops>') == "Talk."
    assert strip_gm_tags('Talk.<gm_ops>{"unclosed": 1') == "Talk."
    assert strip_gm_tags('Talk.[[GM_STATE:{"a":"x]]y","b":[[1,2]]}]] end') == "Talk. end"
    assert strip_gm_tags('Talk.[[GM_STATE:{"unclosed":1') == "Talk."

    # 1. Leading <think>...</think>\n\n strips immediate trailing whitespace before narrative starts
    s1 = StreamSanitizer()
    deltas = [
        s1.feed("<think>Secret GM plan "),
        s1.feed("and hidden legal name</think>"),
        s1.feed("\n\n  "),
        s1.feed("Neon rain "),
        s1.feed("falls."),
    ]
    trailing, raw = s1.finalize()
    assert "".join(deltas) + trailing == "Neon rain falls."
    assert "Secret GM plan" not in "".join(deltas) + trailing
    assert "<think>" in raw

    # 2. Unclosed trailing <think> / <gm_ops> / [[GM_STATE is held back mid-stream and stripped at finalize
    for unclosed in ("<think>secret", "<gm_ops>{\"a\":1}", "[[GM_STATE:{\"a\":1}"):
        s_unclosed = StreamSanitizer()
        d1 = s_unclosed.feed("Safe line.")
        d2 = s_unclosed.feed(unclosed)
        t_end, _ = s_unclosed.finalize()
        assert d1 == "Safe line."
        assert d2 == ""
        assert t_end == ""

    # 3. Character-by-character partial tag prefix buffering without .strip() slicing corruption
    s_char = StreamSanitizer()
    stream_in = (
        "Hello   "
        "<think>private</think>"
        " world "
        "<gm_ops>{\"checks\":[{\"actor\":\"V\"}]}</gm_ops>"
        "[[GM_STATE:{\"b\":[[1,2]]}]]!"
    )
    emitted_pieces: list[str] = []
    for ch in stream_in:
        piece = s_char.feed(ch)
        assert "<gm" not in piece.lower()
        assert "<th" not in piece.lower()
        assert "[[gm" not in piece.lower()
        emitted_pieces.append(piece)
    t_char, _ = s_char.finalize()
    emitted_pieces.append(t_char)
    assert "".join(emitted_pieces) == "Hello    world !"

    # 4. Non-GM tags and lookalikes (<bold>, [1], <thinker>) flush cleanly once they diverge
    s_look = StreamSanitizer()
    out = [
        s_look.feed("Check <"),
        s_look.feed("bold>text</bold> and ["),
        s_look.feed("1] and <think"),
        s_look.feed("er>reads</thinker>"),
    ]
    t_look, _ = s_look.finalize()
    assert "".join(out) + t_look == "Check <bold>text</bold> and [1] and <thinker>reads</thinker>"


def test_extract_gm_plan_balanced_braces_think_and_fences():
    from turnloop import extract_gm_plan

    # Empty / non-JSON / unclosed <think> return None, while valid {} returns {}
    assert extract_gm_plan("") is None
    assert extract_gm_plan("No JSON here") is None
    assert extract_gm_plan("[1, 2, 3]") is None
    assert extract_gm_plan('<think>{"wrong": true}') is None
    assert extract_gm_plan("{}") == {}
    assert extract_gm_plan("```json\n{}\n```") == {}
    assert extract_gm_plan("<think>ok</think>\n{}") == {}

    # Decoy JSON inside <think> is stripped before extraction
    assert extract_gm_plan('<think>{"wrong": 1}</think>\n{"right": 2}') == {"right": 2}

    # Last fenced JSON block wins; non-dict trailing code fence is skipped
    fenced_text = (
        "```json\n{\"first\": 1}\n```\n"
        "```json\n{\"second\": {\"nested\": true}}\n```\n"
        "```\nnot json\n```"
    )
    assert extract_gm_plan(fenced_text) == {"second": {"nested": True}}

    # Balanced-brace raw_decode ignores prose braces and prefers last top-level dict (not inner dict!)
    prose_text = (
        "Here is {prose brace} and first {\"a\": 1} "
        "then {\"checks\": [{\"actor\": \"V\"}], \"notes\": \"keep outer\"} "
        "and trailing {broken"
    )
    assert extract_gm_plan(prose_text) == {
        "checks": [{"actor": "V"}],
        "notes": "keep outer",
    }

    # Nested JSON inside <gm_ops> and [[GM_STATE:...]] (preferring last occurrence)
    tagged = (
        '<gm_ops>{"first": true}</gm_ops>'
        '<gm_ops>{"checks": [{"actor": "Vee", "meta": {"dv": 13}}]}</gm_ops>'
    )
    assert extract_gm_plan(tagged) == {"checks": [{"actor": "Vee", "meta": {"dv": 13}}]}

    bracketed = 'Text [[GM_STATE:{"checks":[{"actor":"V"}],"arr":[[1,2]]}]] done'
    assert extract_gm_plan(bracketed) == {"checks": [{"actor": "V"}], "arr": [[1, 2]]}


@pytest.mark.anyio
async def test_openai_compatible_llm_resilience_and_metadata(monkeypatch):
    import asyncio
    from turnloop import LLMConfig, OpenAICompatibleLLM

    # Default max_tokens aligned with settings._default_llm_dict
    assert LLMConfig().max_tokens == 2400

    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    # 1. Staged 422/400 fallback in complete() and stream()
    complete_payloads: list[dict[str, Any]] = []

    def complete_fallback_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        complete_payloads.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(422, json={"error": "chat_template_kwargs unsupported"})
        if "response_format" in body:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    llm = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(complete_fallback_handler),
    )
    out = await llm.complete([{"role": "user", "content": "hi"}], json_mode=True, enable_thinking=False)
    assert out == '{"ok": true}'
    assert len(complete_payloads) == 3
    # Stage 1: both present; Stage 2: chat_template_kwargs dropped while response_format preserved; Stage 3: both dropped
    assert "chat_template_kwargs" in complete_payloads[0] and "response_format" in complete_payloads[0]
    assert "chat_template_kwargs" not in complete_payloads[1] and "response_format" in complete_payloads[1]
    assert "chat_template_kwargs" not in complete_payloads[2] and "response_format" not in complete_payloads[2]
    assert llm.last_finish_reason == "length"
    assert llm.last_truncated is True
    assert llm.pop_call_meta() == {
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "finish_reason": "length",
        "truncated": True,
    }

    stream_payloads: list[dict[str, Any]] = []

    def stream_fallback_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        stream_payloads.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(422, json={"error": "no chat_template_kwargs"})
        if "stream_options" in body:
            return httpx.Response(400, json={"error": "no stream_options"})
        sse = (
            'data: {"choices":[{"delta":{"content":"Cut off"},"finish_reason":"length"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}\n\n'
            "data: [DONE]\n\n"
        ).encode("utf-8")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse)

    llm_stream = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(stream_fallback_handler),
    )
    chunks = [c async for c in llm_stream.stream([{"role": "user", "content": "hi"}], enable_thinking=False)]
    assert "".join(chunks) == "Cut off"
    assert len(stream_payloads) == 3
    assert "chat_template_kwargs" in stream_payloads[0] and "stream_options" in stream_payloads[0]
    assert "chat_template_kwargs" not in stream_payloads[1] and "stream_options" in stream_payloads[1]
    assert "chat_template_kwargs" not in stream_payloads[2] and "stream_options" not in stream_payloads[2]
    assert llm_stream.last_finish_reason == "length"
    assert llm_stream.last_truncated is True
    assert llm_stream.pop_call_meta() == {
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        "finish_reason": "length",
        "truncated": True,
    }

    # 2. Retry on 502/503 and pre-first-token TimeoutException
    attempt_log: list[str] = []

    def retry_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        attempt_log.append("stream" if body.get("stream") else "complete")
        if len(attempt_log) == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        if len(attempt_log) == 2:
            return httpx.Response(502, text="bad gateway")
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"choices":[{"delta":{"content":"Recovered"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    llm_retry = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=2),
        transport=httpx.MockTransport(retry_handler),
    )
    assert await llm_retry.complete([{"role": "user", "content": "hi"}]) == "ok"
    assert len(attempt_log) == 3

    attempt_log.clear()
    recovered = [c async for c in llm_retry.stream([{"role": "user", "content": "hi"}])]
    assert "".join(recovered) == "Recovered"
    assert len(attempt_log) == 3

    # 3. Non-retryable stream HTTP error calls resp.aread() so error body is readable
    def stream_err_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found on upstream")

    llm_err = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(stream_err_handler),
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _ = [c async for c in llm_err.stream([{"role": "user", "content": "hi"}])]
    assert exc_info.value.response.text == "model not found on upstream"

    # 4. HTTP 200 {"error": ...} detection in complete(), SSE stream, and non-SSE JSON stream
    llm_env = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"error": {"message": "Context overflow"}})),
    )
    with pytest.raises(RuntimeError, match="Context overflow"):
        await llm_env.complete([{"role": "user", "content": "hi"}])
    with pytest.raises(RuntimeError, match="Context overflow"):
        _ = [c async for c in llm_env.stream([{"role": "user", "content": "hi"}])]

    llm_sse_err = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'data: {"error":{"message":"Upstream stream died"}}\n\n',
            )
        ),
    )
    with pytest.raises(RuntimeError, match="Upstream stream died"):
        _ = [c async for c in llm_sse_err.stream([{"role": "user", "content": "hi"}])]

    # 5. Non-SSE application/json fallback in stream() yields content and records usage/finish_reason
    llm_nonsse = OpenAICompatibleLLM(
        LLMConfig(base_url="http://mock.local/v1", model="m", retry_attempts=0),
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "choices": [{"message": {"content": "Non-SSE reply"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                },
            )
        ),
    )
    nonsse_chunks = [c async for c in llm_nonsse.stream([{"role": "user", "content": "hi"}])]
    assert nonsse_chunks == ["Non-SSE reply"]
    assert llm_nonsse.pop_call_meta() == {
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        "finish_reason": "stop",
        "truncated": False,
    }


@pytest.mark.anyio
async def test_execute_solo_op_combat_outcomes_gear_and_roll_sanitization(tmp_path: Path):
    import sqlite3
    from sourcecatalog import items as catalog_items

    rules_db, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    with sqlite3.connect(rules_db) as db:
        db.execute("INSERT INTO pages VALUES(NULL, 200, 199, 'Weapons', '', 0)")
        db.execute(
            "INSERT INTO source_tables VALUES(200, 1, NULL, ?)",
            (json.dumps([["Name", "WeaponType", "Cost"], ["Medium Pistol", "Medium Pistol", "50eb"]]),),
        )
    pistol_id = next(k for k, v in catalog_items(rules_db).items() if v["name"] == "Medium Pistol")

    # Set street handle + hidden real_name + backstory + owner on PC1, and attach PC2 as combat target
    c1 = svc.store.get_character(char_id)
    svc.execute(
        "update_character_profile",
        {
            "character_id": char_id,
            "expected_revision": c1["revision"],
            "profile": {
                "handle": "Ghostwire",
                "real_name": "Elena Vance",
                "real_name_hidden": True,
                "backstory": {"summary": "Secret corp deserter"},
                "owner_username": "alice",
            },
            "reason": "Profile",
            "operation_id": "prof-b2b-1",
        },
    )
    c1 = svc.store.get_character(char_id)
    svc.execute(
        "update_character",
        {
            "character_id": char_id,
            "expected_revision": c1["revision"],
            "changes": {"money": 1000, "inventory": {pistol_id: 1, "ammo:M Pistol": 24}},
            "reason": "Seed gear",
            "operation_id": "gear-b2b-1",
        },
        campaign_id=camp_id,
    )
    c2 = svc.execute(
        "create_character",
        {
            "name": "Brick",
            "stats": {s: 5 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")},
            "skills": {"Evasion": 2, "Handgun": 3},
            "operation_id": "seed-brick-b2b",
        },
    )["result"]
    camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    svc.execute(
        "attach_character",
        {
            "campaign_id": camp_id,
            "character_id": c2["id"],
            "expected_revision": camp["revision"],
            "reason": "Attach Brick",
            "operation_id": "att-brick-b2b",
        },
        campaign_id=camp_id,
    )

    # Test gear_action with item key already in catalog (pistol_id)
    engine = TurnEngine(svc, ScriptedLLM())
    g_patches, g_warns, g_rolls, g_outcomes = engine.executor.execute_solo_op(
        camp_id,
        {"action": "gear_action", "subaction": "equip_weapon", "actor": "Ghostwire", "item": pistol_id},
        "Ghostwire",
        "gear-eq-b2b",
    )
    assert not g_warns, g_warns
    assert g_outcomes and g_outcomes[0]["subaction"] == "equip_weapon"
    # Reload pistol so it has ammo
    ctx_now = svc.campaign_context(camp_id)
    gw_now = next(c for c in ctx_now["characters"] if c["id"] == char_id)
    w_id = gw_now["detail"]["equipment"]["weapons"][0]["id"]
    svc.execute(
        "start_encounter",
        {"character_ids": [char_id, c2["id"]], "expected_revision": ctx_now["solo"]["revision"], "reason": "Init", "operation_id": "st-enc-b2b"},
        campaign_id=camp_id,
    )
    # Ensure Ghostwire is active in queue
    ctx_enc = svc.campaign_context(camp_id)
    active_id = ctx_enc["solo"]["runtime"]["encounter"]["queue"][0]
    if active_id != char_id:
        svc.execute(
            "encounter_action",
            {"actor_id": active_id, "action": "next_turn", "arguments": {}, "expected_revision": ctx_enc["solo"]["revision"], "reason": "Pass turn", "operation_id": "nt-b2b"},
            campaign_id=camp_id,
        )
        ctx_enc = svc.campaign_context(camp_id)
    svc.execute(
        "encounter_action",
        {"actor_id": char_id, "action": "reload", "arguments": {"weapon_id": w_id}, "expected_revision": ctx_enc["solo"]["revision"], "reason": "Load", "operation_id": "rel-b2b"},
        campaign_id=camp_id,
    )
    # Advance round so Ghostwire has a fresh Action after reloading
    for step in range(2):
        ctx_loop = svc.campaign_context(camp_id)
        cur_actor = ctx_loop["solo"]["runtime"]["encounter"]["queue"][ctx_loop["solo"]["runtime"]["encounter"]["turn_index"]]
        svc.execute(
            "encounter_action",
            {"actor_id": cur_actor, "action": "next_turn", "arguments": {}, "expected_revision": ctx_loop["solo"]["revision"], "reason": "Next turn", "operation_id": f"nt-b2b-round-{step}"},
            campaign_id=camp_id,
        )

    # Now run a turn where Planner emits encounter_action attack + mode="ranged" + target="Brick"
    plan = {
        "checks": [
            {"actor": "Ghostwire", "skill": "Handgun", "dv": 13, "reason": "Snap shot"},
        ],
        "solo_ops": [
            {
                "action": "encounter_action",
                "subaction": "attack",
                "mode": "ranged",
                "actor": "Ghostwire",
                "arguments": {"weapon_id": w_id, "target": "Brick", "range_m": 5},
                "reason": "Pistol shot at Brick",
            }
        ],
    }
    llm = ScriptedLLM(mode="two_pass", complete_reply=json.dumps(plan), stream_chunks=["Ghostwire fires across the dock."])
    eng2 = TurnEngine(svc, llm)
    events = [ev async for ev in eng2.run_turn(camp_id, "I shoot Brick.", speaker_character_id=char_id)]
    dice_evs = [ev["data"] for ev in events if ev["event"] == "dice_roll"]
    assert len(dice_evs) >= 2  # PC skill_check + encounter attack roll
    for r in dice_evs:
        assert "character" not in r
        assert "Elena Vance" not in json.dumps(r)
        assert "Secret corp deserter" not in json.dumps(r)
        assert "alice" not in json.dumps(r)
    assert dice_evs[0]["actor"] == "Ghostwire"
    assert dice_evs[0]["reason"] == "Snap shot"

    narr_sys = llm.narrator_calls[0][0]["content"]
    ledger_section = narr_sys.split("Authoritative Dice Roll Ledger:", 1)[1]
    assert "NONE (0 rolls executed" not in ledger_section
    assert "Combat [attack]: Ghostwire -> Brick" in ledger_section


def test_format_roll_ledger_tied_dv_and_solo_results():
    from turnloop import format_roll_ledger

    tied = {
        "outcomes": {
            "rolls": [
                {
                    "actor": "Ghostwire",
                    "skill": "Handgun",
                    "stat": "REF",
                    "base": 10,
                    "dice": [5],
                    "total": 15,
                    "dv": 15,
                    "success": False,
                    "reason": "Tied shot",
                }
            ],
            "solo_results": [
                {"action": "health_action", "subaction": "stabilize", "actor": "Ghostwire", "success": True},
            ],
        }
    }
    txt = format_roll_ledger(tied)
    assert "[TIED DV — FAILS (needed > 15)]" in txt
    assert "[NARROW MISS by 0]" not in txt
    assert "Combat / Solo Outcomes:" in txt
    assert "health_action:stabilize" in txt


@pytest.mark.anyio
async def test_chronicler_blocks_character_updates_and_preserves_turn1_time(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)

    class ChronTestLLM:
        enable_multi_call = True

        def __init__(self, planner_reply: str, chron_reply: str):
            self.planner_reply = planner_reply
            self.chron_reply = chron_reply

        async def complete(self, messages, **_kwargs):
            sys_p = messages[0]["content"]
            if "post-turn chronicler" in sys_p.lower():
                return self.chron_reply
            return self.planner_reply

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            yield "Twenty minutes pass in Kabuki."

    # 1. start_time ("22:15") + default_time_step_minutes=5 + Chronicler time_elapsed_minutes=20 + blocked update_character
    planner_json = json.dumps({"checks": [], "start_time": "22:15", "time_elapsed_minutes": 0})
    chron_json = json.dumps({
        "time_elapsed_minutes": 20,
        "state_ops": [
            {"type": "update_character", "actor": "Vee Mercer", "changes": {"money": 99999}, "reason": "Hallucinated payout"},
            {"type": "update_campaign", "changes": {"scene": "Kabuki Market"}, "reason": "Moved"},
        ],
    })
    engine = TurnEngine(
        svc,
        ChronTestLLM(planner_json, chron_json),
        turn_settings={"default_time_step_minutes": 5, "enable_chronicler": True},
    )
    events = [ev async for ev in engine.run_turn(camp_id, "Walk into Kabuki Market at 22:15.")]
    done = events[-1]["data"]
    assert any("Blocked disallowed update_character" in w for w in done["warnings"])
    ch_after = svc.store.get_character(char_id)
    assert ch_after["money"] == 0
    ctx = svc.campaign_context(camp_id)
    # 22:15 (1335) + 20m = 22:35 (1355) — default_time_step_minutes (5m) must NOT double-advance!
    assert ctx["solo"]["runtime"]["clock_minutes"] == 22 * 60 + 35

    # 2. Empty JSON object wrapped in <think> returns {} (no empty/unparseable warning), while unparseable returns None (warns)
    engine_empty = TurnEngine(
        svc,
        ChronTestLLM("<think>no ops needed</think>\n{}", "{}"),
        turn_settings={"default_time_step_minutes": 5, "enable_chronicler": True},
    )
    ev_empty = [ev async for ev in engine_empty.run_turn(camp_id, "Pause and listen.")]
    done_empty = ev_empty[-1]["data"]
    assert not any("empty or unparseable" in w for w in done_empty["warnings"])
    # Neither Planner nor Chronicler advanced time -> default_time_step_minutes (+5m) runs once
    assert svc.campaign_context(camp_id)["solo"]["runtime"]["clock_minutes"] == 22 * 60 + 40


@pytest.mark.anyio
async def test_overclock_luck_default_actor_targeting_and_emp_sync(tmp_path: Path):
    _, _, svc, camp_id, c1_id = _seed_campaign(tmp_path)
    c1 = svc.store.get_character(c1_id)
    svc.execute(
        "update_character_profile",
        {"character_id": c1_id, "expected_revision": c1["revision"], "profile": {"handle": "Brick"}, "reason": "h", "operation_id": "h1"},
    )
    c2 = svc.execute(
        "create_character",
        {
            "name": "Ghostwire",
            "stats": {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")},
            "skills": {"Interface": 6, "Handgun": 4},
            "detail": {"handle": "Ghostwire", "real_name": "Elena Vance", "real_name_hidden": True},
            "operation_id": "seed-gw-oc",
        },
    )["result"]
    camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    svc.execute(
        "attach_character",
        {"campaign_id": camp_id, "character_id": c2["id"], "expected_revision": camp["revision"], "reason": "join", "operation_id": "att-gw-oc"},
        campaign_id=camp_id,
    )

    # Brick appears BEFORE Ghostwire in checks, while default_actor is Ghostwire
    plan = {
        "checks": [
            {"actor": "Brick", "skill": "Handgun", "dv": 13, "reason": "Cover fire"},
            {"actor": "Ghostwire", "skill": "Interface", "dv": 13, "reason": "Breach node"},
        ]
    }
    llm = ScriptedLLM(mode="two_pass", complete_reply=json.dumps(plan), stream_chunks=["Ghostwire breaches the node."])
    engine = TurnEngine(svc, llm)
    events = [
        ev
        async for ev in engine.run_turn(
            camp_id,
            "Overclock and breach!",
            speaker_character_id=c2["id"],
            overclock=True,
            luck_spend=2,
        )
    ]
    done = events[-1]["data"]
    assert len(done["rolls"]) == 2
    brick_roll, gw_roll = done["rolls"]
    assert brick_roll["actor"] == "Brick"
    assert brick_roll["overclock"] is False
    assert brick_roll["luck"] == 0

    assert gw_roll["actor"] == "Ghostwire"
    assert gw_roll["overclock"] is True
    assert gw_roll["luck"] == 2
    assert gw_roll["modifier"] == 2

    gw_after = svc.store.get_character(c2["id"])
    assert gw_after["humanity"] == 58
    assert gw_after["stats"]["EMP"] == 5
    assert gw_after["luck_remaining"] == 4

    # Invalid dv on Overclock check must NOT deduct Humanity
    bad_plan = {"checks": [{"actor": "Ghostwire", "skill": "Interface", "dv": "not-an-int", "overclock": True}]}
    eng_bad = TurnEngine(svc, ScriptedLLM(mode="two_pass", complete_reply=json.dumps(bad_plan), stream_chunks=["Skipped."]))
    [ev async for ev in eng_bad.run_turn(camp_id, "Try bad check", speaker_character_id=c2["id"], overclock=True)]
    assert svc.store.get_character(c2["id"])["humanity"] == 58


def test_resolve_character_strictness_and_npc_checks(tmp_path: Path):
    from turnloop import _resolve_character

    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    c1 = svc.store.get_character(char_id)
    svc.execute(
        "update_character_profile",
        {
            "character_id": char_id,
            "expected_revision": c1["revision"],
            "profile": {"handle": "Ghostwire", "real_name": "Elena Vance", "real_name_hidden": True},
            "reason": "Set hidden identity",
            "operation_id": "prof-res-1",
        },
    )
    chars = svc.campaign_context(camp_id)["characters"]
    known_npcs = {"Tomasz Nowak": "Dock clerk — Neutral 0", "Ghost": "Street informant"}

    # Exact handle & id match
    assert _resolve_character("ghostwire", chars, known_npcs=known_npcs)["id"] == char_id
    assert _resolve_character(char_id, chars, known_npcs=known_npcs)["id"] == char_id
    # Permissive substring & low-cutoff fuzzy match are rejected
    assert _resolve_character("wire", chars, known_npcs=known_npcs) is None
    assert _resolve_character("Ghostwire 2", chars, known_npcs=known_npcs) is None
    # Hidden real name is not matched when real_name_hidden=True
    assert _resolve_character("Elena", chars, known_npcs=known_npcs) is None
    # Known NPC names/handles are rejected
    assert _resolve_character("Tomasz Nowak", chars, known_npcs=known_npcs) is None
    assert _resolve_character("Ghost", chars, known_npcs=known_npcs) is None

    # execute_npc_check runs non-PC check via mechanics.skill_check and lands in executed["rolls"]
    engine = TurnEngine(svc, ScriptedLLM())
    executed = engine.executor.execute_plan(
        camp_id,
        {
            "checks": [
                {"actor": "Tomasz Nowak", "skill": "Perception", "dv": 13, "base": 14, "npc": True, "reason": "Spotting trespasser"},
                {"actor": "Maelstrom Ganger", "skill": "Handgun", "dv": 13, "reason": "Return fire"},
            ]
        },
        {"turn_id": "npc-chk-1", "gm_secrets": {}, "clocks": []},
    )
    assert len(executed["rolls"]) == 2
    assert executed["rolls"][0]["actor"] == "Tomasz Nowak"
    assert executed["rolls"][0]["npc"] is True
    assert executed["rolls"][0]["base"] == 14
    assert executed["rolls"][1]["actor"] == "Maelstrom Ganger"
    assert executed["rolls"][1]["npc"] is True
    assert executed["rolls"][1]["base"] == 10


def test_verify_skill_non_string_guard_and_static_fallback(tmp_path: Path):
    camp_db = tmp_path / "camp_norules.sqlite"
    svc = GameplayService(camp_db, rules_path=None)
    camp = svc.execute("create_campaign", {"name": "No Rules DB", "operation_id": "nr-c1"})["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    char = svc.execute(
        "create_character",
        {"name": "SoloV", "stats": stats, "skills": {"Handgun": 4, "Language (Streetslang)": 2}, "operation_id": "nr-ch1"},
    )["result"]
    engine = TurnEngine(svc, ScriptedLLM())

    # Non-string skill_name never raises TypeError
    assert engine.executor.verify_skill(camp["id"], 123, "REF") == (False, None, None, None)
    assert engine.executor.verify_skill(camp["id"], ["Handgun"], "REF") == (False, None, None, None)

    # Case-insensitive & specialty resolution
    ok, cname, cstat, _ = engine.executor.verify_skill(camp["id"], "field expertise", None)
    assert ok is True and cname == "Field Expertise" and cstat == "TECH"
    ok_p, pname, pstat, _ = engine.executor.verify_skill(camp["id"], "pharmaceuticals", None)
    assert ok_p is True and pname == "Pharmaceuticals" and pstat == "TECH"

    # Static Cyberpunk RED skill->STAT fallback works when corebook_skills() is empty
    ok_hp, hp_name, hp_stat, _ = engine.executor.verify_skill(camp["id"], "human perception", None, character=char)
    assert ok_hp is True and hp_name == "Human Perception" and hp_stat == "EMP"
    ok_lang, lang_name, lang_stat, _ = engine.executor.verify_skill(camp["id"], "language (japanese)", None, character=char)
    assert ok_lang is True and lang_name == "Language (japanese)" and lang_stat == "INT"

    # Hallucinated skills still blocked
    ok_bad, _, _, _ = engine.executor.verify_skill(camp["id"], "Laser Magic", None, character=char)
    assert ok_bad is False


@pytest.mark.anyio
async def test_smart_gm_router_mixed_ooc_solo_punctuation_and_deferred_clear(tmp_path: Path):
    from turnloop import should_gm_intervene

    _, _, svc, camp_id, c1_id = _seed_campaign(tmp_path)
    c1 = svc.store.get_character(c1_id)
    svc.execute(
        "update_character_profile",
        {"character_id": c1_id, "expected_revision": c1["revision"], "profile": {"handle": "V.", "real_name": "Valerie", "real_name_hidden": True}, "reason": "h", "operation_id": "h-vdot"},
    )
    c2 = svc.execute(
        "create_character",
        {
            "name": "K-9!",
            "stats": {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")},
            "skills": {"Perception": 4},
            "detail": {"handle": "K-9!"},
            "operation_id": "seed-k9",
        },
    )["result"]
    camp = svc.execute("get_campaign", {"campaign_id": camp_id})["result"]
    svc.execute(
        "attach_character",
        {"campaign_id": camp_id, "character_id": c2["id"], "expected_revision": camp["revision"], "reason": "attach", "operation_id": "att-k9"},
        campaign_id=camp_id,
    )
    chars = svc.campaign_context(camp_id)["characters"]
    spk_v = {"id": c1_id, "name": "V."}
    spk_k9 = {"id": c2["id"], "name": "K-9!"}

    # 1. Mixed OOC + IC never swallowed even in co-op
    assert should_gm_intervene("((note)) I kick the door", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=2)[0] is True
    assert should_gm_intervene("((a)) I walk inside ((b))", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=2)[0] is True
    assert should_gm_intervene("[OOC: quick check] I scan the door", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=2)[0] is True

    # 2. Pure OOC in solo (coop_player_count=1) triggers GM, while in co-op (2+) stands by
    assert should_gm_intervene("((Can I ask the GM something?))", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=1)[0] is True
    assert should_gm_intervene("((Table note only))", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=2)[0] is False

    # 3. Punctuation handles (V., K-9!) and NPC first-name matching
    assert should_gm_intervene("Hey V., cover my six.", branch=[], characters=chars, npcs={}, speaker=spk_k9, coop_player_count=2)[0] is False
    assert should_gm_intervene("Hey @K-9!, watch the alley.", branch=[], characters=chars, npcs={}, speaker=spk_v, coop_player_count=2)[0] is False
    assert should_gm_intervene("Hey V., ask Tomasz what he saw.", branch=[], characters=chars, npcs={"Tomasz Nowak": "Clerk"}, speaker=spk_k9, coop_player_count=2)[0] is True

    # 4. consecutive_user_turns ignores system dividers, pure OOC, and manual_roll
    ignored_branch = [
        {"role": "assistant", "content": "Prior GM reply"},
        {"role": "system", "content": "Session 2", "metadata": {"session_started": True}},
        {"role": "user", "content": "((pure ooc))", "metadata": {}},
        {"role": "user", "content": "Rolled Handgun", "metadata": {"manual_roll": True}},
    ]
    assert should_gm_intervene("Hey V., ready?", branch=ignored_branch, characters=chars, npcs={}, speaker=spk_k9, coop_player_count=2)[0] is False

    # 5. Multi-turn deferred resolution clears gm_deferred across ALL trailing deferred user turns
    # and forwards consolidated turns to citations & Chronicler, without writing pool:d10/d6 to SQLite rolls.
    class MultiChronLLM:
        enable_multi_call = True

        def __init__(self):
            self.chron_user_contents: list[str] = []

        async def complete(self, messages, **_kwargs):
            if "post-turn chronicler" in messages[0]["content"].lower():
                self.chron_user_contents.append(messages[-1]["content"])
                return "{}"
            return "{}"

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            yield "The fixer slides over a datashard."

    llm_multi = MultiChronLLM()
    engine = TurnEngine(svc, llm_multi)
    ev1 = [ev async for ev in engine.run_turn(camp_id, "First deferred Handgun check", speaker_character_id=c1_id, gm_mode="hold_gm")]
    m1_id = ev1[-1]["data"]["user_message"]["id"]
    ev2 = [ev async for ev in engine.run_turn(camp_id, "Second deferred note", speaker_character_id=c2["id"], gm_mode="hold_gm")]
    m2_id = ev2[-1]["data"]["user_message"]["id"]
    assert engine.tree.get_message(camp_id, m1_id)["metadata"]["gm_deferred"] is True
    assert engine.tree.get_message(camp_id, m2_id)["metadata"]["gm_deferred"] is True

    ev3 = [ev async for ev in engine.run_turn(camp_id, "Now resolve everything.", speaker_character_id=c1_id, gm_mode="force_gm")]
    done3 = ev3[-1]["data"]
    assert any(c["name"] == "Handgun" for c in done3["citations"])
    assert "gm_deferred" not in engine.tree.get_message(camp_id, m1_id)["metadata"]
    assert "gm_deferred" not in engine.tree.get_message(camp_id, m2_id)["metadata"]
    assert "First deferred Handgun check" in llm_multi.chron_user_contents[0]
    assert "Second deferred note" in llm_multi.chron_user_contents[0]

    # Verify preprocess() did NOT pollute SQLite rolls table with pool:d10 / pool:d6
    import sqlite3
    with sqlite3.connect(svc.store.path) as conn:
        pool_rows = conn.execute("SELECT operation_id FROM rolls WHERE operation_id LIKE '%:pool:%'").fetchall()
        assert pool_rows == []


@pytest.mark.anyio
async def test_prompt_hygiene_history_normalization_single_pass_and_truncation_warnings(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    c1 = svc.store.get_character(char_id)
    svc.execute(
        "update_character_profile",
        {
            "character_id": char_id,
            "expected_revision": c1["revision"],
            "profile": {"handle": "Ghostwire", "real_name": "Elena Vance", "real_name_hidden": True},
            "reason": "Profile",
            "operation_id": "prof-hyg-1",
        },
    )
    engine = TurnEngine(svc, ScriptedLLM(), turn_settings={"history_window": 4, "gm_thinking_mode": "balanced"})

    # 1. Intro prompt omits hidden real_name; Planner & Narrator omit _DEFAULT_MULTIPLAYER_RULES for 1 PC
    # and strip __npc_real:* keys from gm_secrets.
    prep = engine.preprocess(camp_id, "Look around")
    prep["gm_secrets"] = {"__npc_real:Rogue": "Secret Name", "dock_trap": "EMP mine"}
    prep["branch"] = [
        {"role": "user", "content": "Early msg 1", "metadata": {"speaker_name": "Ghostwire"}},
        {"role": "assistant", "content": "Early reply 1", "metadata": {}},
        {"role": "system", "content": "Session 1", "metadata": {"session_started": True}},
        {"role": "system", "content": "Party moved", "metadata": {"party_transition": True}},
        {"role": "user", "content": "Deferred 1", "metadata": {"speaker_name": "Ghostwire"}},
        {"role": "user", "content": "Deferred 2", "metadata": {"speaker_name": "Ghostwire"}},
    ]
    intro_msgs = engine._build_intro_messages(prep, "Intro")
    assert "Elena Vance" not in intro_msgs[0]["content"]
    assert "Ghostwire" in intro_msgs[0]["content"]

    planner_msgs = engine._build_planner_messages(prep, "Current move", overclock=False)
    assert "Multi-Player / Co-op Turn Rules" not in planner_msgs[0]["content"]
    assert "__npc_real:" not in planner_msgs[0]["content"]
    assert "EMP mine" in planner_msgs[0]["content"]
    # Dividers were filtered BEFORE [-4:] slice so "Early msg 1" and "Early reply 1" survive,
    # and consecutive user messages ("Deferred 1", "Deferred 2", "Current move") are merged!
    roles = [m["role"] for m in planner_msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert "Early msg 1" in planner_msgs[1]["content"]
    assert "Deferred 1" in planner_msgs[3]["content"] and "Current move" in planner_msgs[3]["content"]

    # 2. single_pass_tagged injects <gm_ops> schema, passes enable_thinking=False in balanced mode,
    # resolves active_mode from turn_settings["mode"], and warns on finish_reason="length" / empty text.
    class SinglePassInspectLLM:
        def __init__(self):
            self.config = LLMConfig(model="sp-test", mode="two_pass")
            self.stream_calls: list[tuple[list[dict[str, str]], dict[str, Any]]] = []
            self._meta = {"usage": {"completion_tokens": 12}, "finish_reason": "length", "truncated": True}

        def pop_call_meta(self):
            m = self._meta
            self._meta = {"usage": None, "finish_reason": "stop", "truncated": False}
            return m

        async def complete(self, messages, **kwargs):
            return "{}"

        async def stream(self, messages, **kwargs):
            self.stream_calls.append((messages, kwargs))
            yield "<think>secret thought</think>You duck behind the crate."

    sp_llm = SinglePassInspectLLM()
    sp_engine = TurnEngine(svc, sp_llm, turn_settings={"mode": "single_pass_tagged", "gm_thinking_mode": "balanced"})
    sp_events = [ev async for ev in sp_engine.run_turn(camp_id, "Take cover", overclock=True, luck_spend=1)]
    assert sp_llm.stream_calls[0][1].get("enable_thinking") is False
    sp_sys = sp_llm.stream_calls[0][0][0]["content"]
    assert "<gm_ops>{" in sp_sys
    assert "Overclock requested=True" in sp_sys
    assert "Pre-committed LUCK=1" in sp_sys
    sp_done = sp_events[-1]["data"]
    assert sp_done["assistant_message"]["content"] == "You duck behind the crate."
    assert any("max_tokens" in w for w in sp_done["warnings"])


@pytest.mark.anyio
async def test_think_mode_zero_time_no_mutations_and_chronicler_gating(tmp_path: Path):
    from turn_engine.router import should_gm_intervene

    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    ctx_init = svc.campaign_context(camp_id)
    chars = ctx_init["characters"]
    spk = {"id": char_id, "name": "Vee Mercer"}

    # 1. Router ALWAYS returns (True, "") for turn_intent="think" or leading /think
    assert should_gm_intervene(
        "((pure ooc note))",
        branch=[],
        characters=chars,
        npcs={},
        speaker=spk,
        coop_player_count=2,
        turn_intent="think",
    ) == (True, "")
    assert should_gm_intervene(
        "/think Hey Brick, what is on his belt?",
        branch=[],
        characters=chars,
        npcs={},
        speaker=spk,
        coop_player_count=2,
    ) == (True, "")

    # 2. Failed/empty check -> Pass 1 mutations blocked, Chronicler skipped, default_time_step skipped,
    #    and trailing gm_deferred user turn is NOT cleared.
    class ThinkTrackingLLM:
        enable_multi_call = True

        def __init__(self, planner_plan: dict[str, Any], chron_plan: dict[str, Any]):
            self.config = LLMConfig(model="think-test", mode="two_pass")
            self.planner_plan = planner_plan
            self.chron_plan = chron_plan
            self.planner_calls: list[list[dict[str, str]]] = []
            self.narrator_calls: list[list[dict[str, str]]] = []
            self.chron_calls: list[list[dict[str, str]]] = []

        async def complete(self, messages, **_kwargs):
            sys_txt = messages[0]["content"]
            if "post-turn chronicler" in sys_txt.lower():
                self.chron_calls.append(messages)
                return json.dumps(self.chron_plan)
            self.planner_calls.append(messages)
            return json.dumps(self.planner_plan)

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            self.narrator_calls.append(messages)
            yield "You spot the scuff marks under the counter."

    # Seed a deferred party turn first to verify /think does not clear it
    llm_idle = ThinkTrackingLLM({}, {})
    eng_idle = TurnEngine(svc, llm_idle)
    held_ev = [ev async for ev in eng_idle.run_turn(camp_id, "Hold the door.", speaker_character_id=char_id, gm_mode="hold_gm")]
    held_id = held_ev[-1]["data"]["user_message"]["id"]
    assert eng_idle.tree.get_message(camp_id, held_id)["metadata"]["gm_deferred"] is True

    adversarial_plan = {
        "checks": [{"actor": "Vee Mercer", "skill": "Perception", "dv": 45, "reason": "Spot concealed tracker"}],
        "time_elapsed_minutes": 25,
        "start_time": "23:00",
        "state_ops": [
            {"type": "update_campaign", "changes": {"scene": "Hijacked Scene", "discoveries": {"Leak": "Nope"}}},
            {"type": "update_character", "actor": "Vee Mercer", "changes": {"money": 9999}},
        ],
        "solo_ops": [{"action": "advance_time", "elapsed_minutes": 10}],
        "clock_ops": [{"id": "heat", "name": "Heat", "delta": 2, "segments": 4}],
        "gm_secrets": {"secret": "mutated"},
    }
    llm_fail = ThinkTrackingLLM(adversarial_plan, {"time_elapsed_minutes": 10})
    eng_fail = TurnEngine(
        svc,
        llm_fail,
        turn_settings={"default_time_step_minutes": 15, "enable_chronicler": True},
    )
    events_fail = [
        ev
        async for ev in eng_fail.run_turn(
            camp_id,
            "/think Do I spot anything hidden under the counter?",
            speaker_character_id=char_id,
            gm_mode="hold_gm",  # Must NOT defer /think!
        )
    ]
    done_fail = events_fail[-1]["data"]
    assert done_fail.get("gm_deferred") is not True
    assert done_fail["user_message"]["content"] == "Do I spot anything hidden under the counter?"
    assert done_fail["user_message"]["metadata"]["turn_intent"] == "think"
    assert done_fail["assistant_message"]["metadata"]["turn_intent"] == "think"
    assert len(done_fail["rolls"]) == 1
    assert done_fail["rolls"][0]["success"] is False
    assert done_fail["state_patches"] == []
    assert len(llm_fail.chron_calls) == 0  # Chronicler skipped when check fails!
    assert eng_fail.tree.get_message(camp_id, held_id)["metadata"]["gm_deferred"] is True

    planner_sys = llm_fail.planner_calls[0][0]["content"]
    assert "Observation & Recall Planner" in planner_sys
    assert "Perception" in planner_sys and "Conceal/Reveal Object" in planner_sys
    narrator_sys = llm_fail.narrator_calls[0][0]["content"]
    assert "ZERO TIME ELAPSED" in narrator_sys
    assert "NEVER advance the scene" in narrator_sys
    assert "NEVER trigger NPC reactions" in narrator_sys
    assert "NEVER consume encounter/combat actions" in narrator_sys
    assert "NEVER move, act for, speak for, or puppet the PC" in narrator_sys

    ctx_after_fail = svc.campaign_context(camp_id)
    assert ctx_after_fail["solo"]["runtime"]["clock_minutes"] == 0
    assert ctx_after_fail["campaign"]["state"]["scene"] != "Hijacked Scene"
    assert ctx_after_fail["characters"][0]["money"] != 9999
    assert eng_fail.list_all_clocks(camp_id) == []

    # 3. Successful /think check -> Chronicler runs, strictly discoveries-only!
    success_plan = {
        "checks": [{"actor": "Vee Mercer", "skill": "Perception", "dv": 2, "reason": "Read faint badge"}],
    }
    adversarial_chron = {
        "time_elapsed_minutes": 30,
        "clock_ops": [{"id": "heat", "name": "Heat", "delta": 1, "segments": 4}],
        "gm_secrets": {"trap": "mutated"},
        "state_ops": [
            {
                "type": "update_campaign",
                "changes": {
                    "scene": "Changed Scene",
                    "summary": "Changed Summary",
                    "objectives": {"Obj": "Changed"},
                    "unresolved": {"Thread": "Changed"},
                    "npcs": {"New NPC": "Should be stripped"},
                    "npc_identities": {"New NPC": {"real_name": "Nope"}},
                    "pc_locations": {"Vee Mercer": "Elsewhere"},
                    "all_together": "Elsewhere",
                    "discoveries": {"Militech Badge": "Serial matches Dock 9 manifest"},
                },
            },
            {"type": "update_character", "actor": "Vee Mercer", "changes": {"hp": 1}},
        ],
    }
    llm_ok = ThinkTrackingLLM(success_plan, adversarial_chron)
    eng_ok = TurnEngine(
        svc,
        llm_ok,
        turn_settings={"default_time_step_minutes": 15, "enable_chronicler": True},
    )
    events_ok = [
        ev
        async for ev in eng_ok.run_turn(
            camp_id,
            "What badge is clipped to his coat?",
            speaker_character_id=char_id,
            turn_intent="think",
        )
    ]
    done_ok = events_ok[-1]["data"]
    assert done_ok["rolls"][0]["success"] is True
    assert len(llm_ok.chron_calls) == 1
    assert "Hold the door." not in llm_ok.chron_calls[0][-1]["content"]

    ctx_after_ok = svc.campaign_context(camp_id)
    assert ctx_after_ok["solo"]["runtime"]["clock_minutes"] == 0
    assert ctx_after_ok["campaign"]["state"]["discoveries"]["Militech Badge"] == "Serial matches Dock 9 manifest"
    assert ctx_after_ok["campaign"]["state"]["scene"] != "Changed Scene"
    assert "New NPC" not in ctx_after_ok["campaign"]["state"]["npcs"]
    assert eng_ok.list_all_clocks(camp_id) == []

    # 4. Regenerate inherits turn_intent="think"
    regen_events = [
        ev async for ev in eng_fail.regenerate_turn(camp_id, done_fail["assistant_message"]["id"])
    ]
    regen_done = regen_events[-1]["data"]
    assert regen_done["assistant_message"]["metadata"]["turn_intent"] == "think"
    assert len(llm_fail.narrator_calls) == 2

    # 5. single_pass_tagged with turn_intent="think" enforces zero-time / observation-only constraints
    class SinglePassThinkLLM:
        def __init__(self):
            self.config = LLMConfig(model="sp-think", mode="single_pass_tagged")
            self.stream_msgs: list[list[dict[str, str]]] = []

        async def complete(self, messages, **_kwargs):
            return "{}"

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            self.stream_msgs.append(messages)
            yield (
                "You recall the courier route."
                '<gm_ops>{"checks":[{"actor":"Vee Mercer","skill":"Streetwise","dv":2,"reason":"Recall route"}],'
                '"time_elapsed_minutes":20,"state_ops":[{"type":"update_campaign","changes":{"scene":"Bad Scene"}}],'
                '"solo_ops":[{"action":"advance_time","elapsed_minutes":10}],"clock_ops":[{"id":"c","name":"C","delta":1}]}</gm_ops>'
            )

    sp_llm = SinglePassThinkLLM()
    sp_eng = TurnEngine(svc, sp_llm, turn_settings={"mode": "single_pass_tagged", "default_time_step_minutes": 10})
    sp_events = [ev async for ev in sp_eng.run_turn(camp_id, "Do I know this courier route?", speaker_character_id=char_id, turn_intent="think")]
    sp_done = sp_events[-1]["data"]
    assert "Zero-time observation-only constraint" in sp_llm.stream_msgs[0][0]["content"]
    assert sp_done["assistant_message"]["metadata"]["turn_intent"] == "think"
    assert len(sp_done["rolls"]) == 1
    assert sp_done["state_patches"] == []
    assert svc.campaign_context(camp_id)["solo"]["runtime"]["clock_minutes"] == 0
    assert svc.campaign_context(camp_id)["campaign"]["state"]["scene"] != "Bad Scene"


@pytest.mark.anyio
async def test_think_mode_api_slash_command_and_validation(tmp_path: Path):
    import httpx

    rules_db, camp_db, _, camp_id, char_id = _seed_campaign(tmp_path)
    llm = ScriptedLLM(
        mode="two_pass",
        complete_reply=json.dumps({"checks": [], "gm_notes": "Obvious visual detail."}),
        stream_chunks=["You notice the holstered sidearm under his jacket."],
    )
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db, llm=llm)
    headers = {"Origin": "http://localhost:5173", "Content-Type": "application/json"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Empty /think returns 400 with clear validation detail
        r_empty = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={"campaign_id": camp_id, "user_text": "/think   ", "speaker_character_id": char_id},
        )
        assert r_empty.status_code == 400
        assert r_empty.json()["detail"] == "Enter a thought or observation question after /think."

        r_empty_intent = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={"campaign_id": camp_id, "user_text": "   ", "turn_intent": "think", "speaker_character_id": char_id},
        )
        assert r_empty_intent.status_code == 400
        assert r_empty_intent.json()["detail"] == "Enter a thought or observation question after /think."

        r_bad_intent = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={"campaign_id": camp_id, "user_text": "Look around", "turn_intent": "invalid"},
        )
        assert r_bad_intent.status_code == 400

        # /think <question> parses intent, strips prefix, bypasses hold_gm, and tags both messages
        r_think = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={
                "campaign_id": camp_id,
                "user_text": "/THINK   Is the fixer armed?",
                "speaker_character_id": char_id,
                "gm_mode": "hold_gm",
            },
        )
        assert r_think.status_code == 200
        ev_think = _parse_sse(r_think.text)
        done_think = [e["data"] for e in ev_think if e["event"] == "turn_done"][0]
        assert done_think.get("gm_deferred") is not True
        assert done_think["user_message"]["content"] == "Is the fixer armed?"
        assert done_think["user_message"]["metadata"]["turn_intent"] == "think"
        assert done_think["assistant_message"]["metadata"]["turn_intent"] == "think"

        # Non-command prefix like /thinking is NOT treated as /think
        r_non = await client.post(
            "/v1/chat/turn",
            headers=headers,
            json={
                "campaign_id": camp_id,
                "user_text": "/thinking out loud",
                "speaker_character_id": char_id,
                "gm_mode": "force_gm",
            },
        )
        assert r_non.status_code == 200
        done_non = [e["data"] for e in _parse_sse(r_non.text) if e["event"] == "turn_done"][0]
        assert done_non["user_message"]["content"] == "/thinking out loud"
        assert "turn_intent" not in done_non["user_message"]["metadata"]


def test_latest_snapshot_leaf_ignores_orphaned_inactive_branch_nodes(tmp_path: Path):
    from contextlib import closing

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    engine = TurnEngine(svc, ScriptedLLM())
    revs = engine.tree._current_revisions(camp_id)
    u1 = engine.tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="Knock on the door",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    a1 = engine.tree.append_message(
        camp_id,
        parent_id=u1["id"],
        role="assistant",
        content="Branch 1",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    engine.private_state.save_branch_private_state(camp_id, a1["id"], u1["id"], {"branch": "one"}, [])

    # Create a newer sibling assistant branch with its own snapshot, then corrupt its is_active=1 while keeping a1 active
    a2 = engine.tree.append_message(
        camp_id,
        parent_id=u1["id"],
        role="assistant",
        content="Branch 2",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    engine.private_state.save_branch_private_state(camp_id, a2["id"], u1["id"], {"branch": "two"}, [])
    engine.tree.switch_branch(camp_id, a1["id"])
    with closing(svc.store._connect()) as conn, conn:
        conn.execute("UPDATE chat_messages SET is_active=1 WHERE id=?", (a2["id"],))
        # Ensure a1 is still first in creation order so get_tree's active_branch follows a1
        conn.execute("UPDATE chat_messages SET is_active=1 WHERE id=?", (a1["id"],))

    assert engine.private_state.latest_snapshot_leaf(camp_id) == a1["id"]
    assert engine._get_gm_secrets(camp_id) == {"branch": "one"}


def test_split_party_channel_seeds_private_state_from_main_leaf(tmp_path: Path):
    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    engine = TurnEngine(svc, ScriptedLLM())
    engine.seed_initial_gm_state(camp_id, secrets={"root_secret": "Turn-0"})
    revs = engine.tree._current_revisions(camp_id)
    u1 = engine.tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="Scout ahead",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    a1 = engine.tree.append_message(
        camp_id,
        parent_id=u1["id"],
        role="assistant",
        content="You spot guards.",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    engine.private_state.save_branch_private_state(
        camp_id,
        a1["id"],
        u1["id"],
        {"root_secret": "Turn-0", "live_secret": "From main leaf"},
        [{"id": "alert", "name": "Site Alert", "filled": 2, "segments": 6, "category": "heat", "visibility": "secret", "note": ""}],
    )

    prep = engine.preprocess(camp_id, "Check the dock", channel_id="scene-dock")
    assert prep["gm_secrets"]["live_secret"] == "From main leaf"
    assert prep["clocks"][0]["id"] == "alert"
    assert prep["clocks"][0]["filled"] == 2


def test_merge_gm_secrets_pins_npc_real_keys_during_eviction():
    from turnloop import BranchPrivateStateStore

    current = {"__npc_real:Vex": "Viktor K.", "__npc_real:Nyx": "Nadia R."}
    updates = {f"note_{i}": f"Secret note {i}" for i in range(60)}
    merged = BranchPrivateStateStore.merge_gm_secrets(current, updates)
    assert len(merged) <= 50
    assert merged["__npc_real:Vex"] == "Viktor K."
    assert merged["__npc_real:Nyx"] == "Nadia R."


def test_chat_tree_cycle_guards_and_export_branch_no_duplicate_rolls(tmp_path: Path):
    from contextlib import closing

    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    tree = ChatTreeStore(svc)
    revs = tree._current_revisions(camp_id)
    roll = {"actor": "Vee Mercer", "skill": "Handgun", "stat": "REF", "total": 15, "dv": 13}
    u1 = tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="I shoot the lock",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
        metadata={"speaker_name": "Vee Mercer", "rolls": [roll]},
    )
    a1 = tree.append_message(
        camp_id,
        parent_id=u1["id"],
        role="assistant",
        content="The lock shatters.",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
        metadata={"rolls": [roll]},
    )
    exported = tree.export_branch(camp_id)
    assert exported["markdown"].count("- Roll (Vee Mercer): Handgun = 15 vs DV 13") == 1

    # Corrupt parent pointers into a cycle; cycle guards must prevent infinite loops
    with closing(svc.store._connect()) as conn, conn:
        conn.execute("UPDATE chat_messages SET parent_id=? WHERE id=?", (a1["id"], u1["id"]))
    chain = tree.get_branch_to(camp_id, a1["id"])
    assert len(chain) == 2
    switched = tree.switch_branch(camp_id, a1["id"])
    assert switched["campaign_id"] == camp_id


@pytest.mark.anyio
async def test_campaign_compressions_per_channel_and_archivist_hides_internal_keys(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)

    archivist_llm = ScriptedLLM(
        complete_reply=json.dumps(
            {
                "library_entries": [],
                "campaign_updates": {"summary": "Short recap"},
                "gm_secrets": {},
                "clock_ops": [],
            }
        )
    )
    engine = TurnEngine(svc, archivist_llm)
    engine.private_state.set_compressed_count(camp_id, None, 3, channel_id="main")
    assert engine.private_state.get_compressed_count(camp_id, channel_id="main") == 3
    assert engine.private_state.get_compressed_count(camp_id, channel_id="scene-dock") == 0
    engine.private_state.set_compressed_count(camp_id, None, 5, channel_id="scene-dock")
    assert engine.private_state.get_compressed_count(camp_id, channel_id="main") == 3
    assert engine.private_state.get_compressed_count(camp_id, channel_id="scene-dock") == 5

    # Seed internal __* keys into campaign discoveries and verify Archivist does not see them
    camp = svc.campaign_context(camp_id)["campaign"]
    svc.execute(
        "update_campaign",
        {
            "campaign_id": camp_id,
            "expected_revision": camp["revision"],
            "changes": {
                "summary": "Crew met Fixer",
                "discoveries": {
                    "__campaign_meta": json.dumps({"district": "Watson"}),
                    "__npc_identities": json.dumps({"Ghost": {"handle": "Ghost", "real_name_hidden": True}}),
                    "Dock Keycard": "Found on guard",
                },
            },
            "reason": "Seed discoveries",
            "operation_id": "comp-seed-1",
        },
        campaign_id=camp_id,
    )
    revs = engine.tree._current_revisions(camp_id)
    u1 = engine.tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="Let's recap",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
    )
    await engine.compress_memory(camp_id, leaf_id=u1["id"])
    sys_prompt = archivist_llm.planner_calls[-1][0]["content"]
    assert "__campaign_meta" not in sys_prompt
    assert "__npc_identities" not in sys_prompt
    assert "Dock Keycard" in sys_prompt


def test_sync_all_active_leaf_revisions(tmp_path: Path):
    _, _, svc, camp_id, _ = _seed_campaign(tmp_path)
    tree = ChatTreeStore(svc)
    revs = tree._current_revisions(camp_id)
    tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="Main chat",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
        channel_id="main",
    )
    tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="Dock chat",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
        channel_id="scene-dock",
    )
    camp = svc.campaign_context(camp_id)["campaign"]
    svc.execute(
        "update_campaign",
        {
            "campaign_id": camp_id,
            "expected_revision": camp["revision"],
            "changes": {"scene": "Afterlife VIP"},
            "reason": "Scene shift",
            "operation_id": "sync-all-1",
        },
        campaign_id=camp_id,
    )
    assert tree.get_tree(camp_id, channel_id="main")["revision_mismatch"] is True
    assert tree.get_tree(camp_id, channel_id="scene-dock")["revision_mismatch"] is True
    tree.sync_all_active_leaf_revisions(camp_id)
    assert tree.get_tree(camp_id, channel_id="main")["revision_mismatch"] is False
    assert tree.get_tree(camp_id, channel_id="scene-dock")["revision_mismatch"] is False


def test_normalize_campaign_changes_protects_internal_keys_and_enforces_caps(tmp_path: Path):
    from campaign import _json
    from turnloop import _encode_party_locations_json, _normalize_campaign_changes, parse_npc_identities_public

    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    ctx = svc.campaign_context(camp_id)

    # 1. LLM-emitted __* discovery keys are ignored; omitted real_name_hidden preserves previous value
    cur_state = {
        "scene": "Alley",
        "summary": "Intro",
        "npcs": {},
        "objectives": {},
        "discoveries": {
            "__campaign_meta": '{"district":"Watson"}',
            "__npc_identities": json.dumps({"Rogue": {"handle": "Rogue", "real_name_hidden": False, "real_name": "Rogue Amendiares"}}),
            **{f"clue_{i}": f"detail {i}" for i in range(38)},
        },
        "unresolved": {},
    }
    clean, _ = _normalize_campaign_changes(
        {
            "discoveries": {"__campaign_meta": "CORRUPT", "__evil": "bad", "new_clue": "Camera feed"},
            "pc_locations": {char_id: "Kabuki Market"},
            "npc_identities": {"Rogue": {"personality": "Guarded"}},
        },
        cur_state,
        characters=ctx["characters"],
    )
    assert clean["discoveries"]["__campaign_meta"] == '{"district":"Watson"}'
    assert "__evil" not in clean["discoveries"]
    assert "new_clue" in clean["discoveries"]
    assert "__party_locations" in clean["discoveries"]
    assert "__npc_identities" in clean["discoveries"]
    assert len(clean["discoveries"]) == 40
    parsed_ids = parse_npc_identities_public({"discoveries": clean["discoveries"]})
    assert parsed_ids["Rogue"]["real_name_hidden"] is False
    assert parsed_ids["Rogue"]["real_name"] == "Rogue Amendiares"
    assert parsed_ids["Rogue"]["personality"] == "Guarded"

    # 2. 24,000-char ceiling trims oldest non-__* discoveries / summary without dropping __* keys
    huge_state = {
        "scene": "S" * 3500,
        "summary": "M" * 3500,
        "npcs": {f"npc_{i}": "N" * 800 for i in range(15)},
        "objectives": {},
        "discoveries": {
            "__campaign_meta": '{"district":"Watson"}',
            **{f"old_clue_{i}": "D" * 900 for i in range(10)},
        },
        "unresolved": {},
    }
    capped, _ = _normalize_campaign_changes({"summary": "M" * 3900}, huge_state)
    merged = {**huge_state, **capped}
    assert len(_json(merged)) <= 24000
    assert "__campaign_meta" in merged["discoveries"]

    # 3. _encode_party_locations_json never produces invalid JSON even with many long locations
    many_locs = {f"char-{i:03d}-long-uuid": f"Very Long Night City District Sector Location Name {i}" for i in range(60)}
    encoded = _encode_party_locations_json("split", many_locs, {})
    assert len(encoded) <= 2000
    assert isinstance(json.loads(encoded), dict)


@pytest.mark.anyio
async def test_run_turn_resolves_channel_from_parent_and_abort_preserves_persisted_assistant(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    tree = ChatTreeStore(svc)
    revs = tree._current_revisions(camp_id)
    dock_root = tree.append_message(
        camp_id,
        parent_id=None,
        role="user",
        content="At the dock",
        campaign_revision=revs["campaign_revision"],
        solo_revision=revs["solo_revision"],
        channel_id="scene-dock",
    )

    class FailAfterNarratorLLM:
        enable_multi_call = True

        def __init__(self):
            self.config = LLMConfig(model="stub", mode="two_pass")
            self.calls = 0

        async def complete(self, messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return "{}"
            raise BaseException("Simulated Chronicler abort")

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            yield "The cargo crane groans overhead."

    eng = TurnEngine(svc, FailAfterNarratorLLM())
    events: list[dict[str, Any]] = []
    with pytest.raises(BaseException, match="Simulated Chronicler abort"):
        async for ev in eng.run_turn(
            camp_id,
            "Look at the crane",
            parent_id=dock_root["id"],
            speaker_character_id=char_id,
        ):
            events.append(ev)

    dock_tree = eng.tree.get_tree(camp_id, channel_id="scene-dock")
    # Channel was resolved from parent_id, and both user_msg + persisted assistant_msg survived the post-Narrator abort
    assert len(dock_tree["active_branch"]) == 3
    assert dock_tree["active_branch"][-1]["role"] == "assistant"
    assert "cargo crane groans" in dock_tree["active_branch"][-1]["content"]

    # Conversely, an abort BEFORE Narrator completes deletes the un-replied user_msg
    class FailInNarratorLLM:
        def __init__(self):
            self.config = LLMConfig(model="stub", mode="two_pass")

        async def complete(self, messages, **_kwargs):
            return "{}"

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            raise RuntimeError("LLM stream dropped")
            yield ""  # pragma: no cover

    eng2 = TurnEngine(svc, FailInNarratorLLM())
    with pytest.raises(RuntimeError, match="LLM stream dropped"):
        async for _ in eng2.run_turn(
            camp_id,
            "Aborted message",
            parent_id=dock_tree["active_leaf_id"],
            speaker_character_id=char_id,
        ):
            pass
    dock_tree_after = eng2.tree.get_tree(camp_id, channel_id="scene-dock")
    assert len(dock_tree_after["active_branch"]) == 3


class _CheckAndMoneyLLM:
    """Planner always proposes one Handgun check plus money/scene updates; narrator output is scripted."""

    def __init__(self, *, check_extra: dict[str, Any] | None = None, fail_first_stream: bool = False):
        self.config = LLMConfig(model="stub", mode="two_pass")
        self.check_extra = check_extra or {}
        self.fail_first_stream = fail_first_stream
        self.planner_calls = 0
        self.stream_calls = 0
        self.narrator_prompt = ""

    async def complete(self, messages, **_kwargs):
        self.planner_calls += 1
        return json.dumps(
            {
                "checks": [{"actor": "Vee Mercer", "skill": "Handgun", "dv": 13, "reason": f"Attempt {self.planner_calls}", **self.check_extra}],
                "state_ops": [
                    {"type": "update_character", "actor": "Vee Mercer", "changes": {"money": 250}, "reason": "Found credchip"},
                    {"type": "update_campaign", "changes": {"scene": f"Alley branch {self.planner_calls}"}, "reason": "Scene"},
                ],
            }
        )

    def pop_call_meta(self):
        return {}

    async def stream(self, messages, **_kwargs):
        self.stream_calls += 1
        self.narrator_prompt = "\n".join(m["content"] for m in messages)
        yield f"Outcome {self.stream_calls}"
        if self.fail_first_stream and self.stream_calls == 1:
            raise RuntimeError("LLM stream dropped")


@pytest.mark.anyio
async def test_planner_cannot_spend_player_luck_or_overclock(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    eng = TurnEngine(svc, _CheckAndMoneyLLM(check_extra={"luck": 5, "overclock": True}))

    done = [ev async for ev in eng.run_turn(camp_id, "Take the shot", speaker_character_id=char_id)][-1]["data"]
    char = svc.store.get_character(char_id)
    assert (char["luck_remaining"], char["humanity"]) == (6, 60)
    assert done["rolls"][0]["luck_spent"] == 0 and done["rolls"][0]["overclock"] is False

    done = [ev async for ev in eng.run_turn(camp_id, "Shoot again", speaker_character_id=char_id, luck_spend=1)][-1]["data"]
    char = svc.store.get_character(char_id)
    assert (char["luck_remaining"], char["humanity"]) == (5, 60)
    assert done["rolls"][0]["luck_spent"] == 1


@pytest.mark.anyio
async def test_regenerate_renarrates_stored_outcomes_without_touching_state(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    llm = _CheckAndMoneyLLM()
    eng = TurnEngine(svc, llm)
    done1 = [
        ev async for ev in eng.run_turn(camp_id, "Take the shot", speaker_character_id=char_id, luck_spend=2, overclock=True)
    ][-1]["data"]
    a1_id = done1["assistant_message"]["id"]
    char_after_turn = svc.store.get_character(char_id)
    assert (char_after_turn["luck_remaining"], char_after_turn["humanity"], char_after_turn["money"]) == (4, 58, 250)
    ctx_after_turn = svc.campaign_context(camp_id)

    ev2 = [ev async for ev in eng.regenerate_turn(camp_id, a1_id)]
    done2 = ev2[-1]["data"]

    assert llm.planner_calls == 1
    assert not [ev for ev in ev2 if ev["event"] in {"dice_roll", "state_patch", "library_added"}]
    assert svc.store.get_character(char_id) == char_after_turn
    ctx_after_regen = svc.campaign_context(camp_id)
    assert ctx_after_regen["campaign"] == ctx_after_turn["campaign"]
    assert ctx_after_regen["solo"]["revision"] == ctx_after_turn["solo"]["revision"]
    a2 = eng.tree.get_message(camp_id, done2["assistant_message"]["id"])
    a1 = eng.tree.get_message(camp_id, a1_id)
    assert a2["content"] == "Outcome 2"
    assert a2["metadata"]["regenerated_from"] == a1_id
    assert a2["metadata"]["rolls"] == a1["metadata"]["rolls"]
    assert "Roll #1: Vee Mercer — Handgun" in llm.narrator_prompt and "Attempt 1" in llm.narrator_prompt


@pytest.mark.anyio
async def test_failed_narration_keeps_executed_turn_and_retry_does_not_reapply(tmp_path: Path):
    _, _, svc, camp_id, char_id = _seed_campaign(tmp_path)
    llm = _CheckAndMoneyLLM(fail_first_stream=True)
    eng = TurnEngine(svc, llm)

    with pytest.raises(RuntimeError, match="LLM stream dropped"):
        async for _ in eng.run_turn(camp_id, "Take the shot", speaker_character_id=char_id, luck_spend=1):
            pass

    branch = eng.tree.get_tree(camp_id)["active_branch"]
    assert [m["role"] for m in branch] == ["user", "assistant"]
    placeholder = branch[-1]
    assert placeholder["metadata"]["narration_failed"] is True
    assert placeholder["metadata"]["rolls"] and placeholder["metadata"]["patches"]
    char_after_turn = svc.store.get_character(char_id)
    assert (char_after_turn["luck_remaining"], char_after_turn["money"]) == (5, 250)

    # Retrying (regenerate on the user turn) re-narrates the saved outcome instead of re-planning it.
    done = [ev async for ev in eng.regenerate_turn(camp_id, branch[0]["id"])][-1]["data"]
    assert llm.planner_calls == 1
    assert svc.store.get_character(char_id) == char_after_turn
    assert done["assistant_message"]["content"] == "Outcome 2"
    assert done["assistant_message"]["metadata"]["regenerated_from"] == placeholder["id"]


def test_settings_per_key_fault_tolerance(tmp_path: Path):
    from turnloop import (
        DEFAULT_PROMPT_TEMPLATES,
        load_llm_settings,
        load_prompt_settings,
        load_server_settings,
        save_llm_settings,
        save_server_settings,
        write_settings_doc,
    )

    sp = tmp_path / "settings.json"
    write_settings_doc(
        {
            "model": "custom-qwen",
            "temperature": 99.0,  # out of range -> falls back to default
            "max_tokens": "bad",  # wrong type -> falls back to default
            "prompts": {
                "system_persona": 12345,  # invalid type -> falls back to default
                "narrator_extra": "Keep it gritty.",
            },
            "server": {
                "bind_host": "0.0.0.0",
                "port": 99999,  # out of range -> falls back to default
            },
        },
        sp,
    )

    llm = load_llm_settings(sp)
    assert llm["model"] == "custom-qwen"
    assert llm["temperature"] == 0.75
    assert llm["max_tokens"] == 2400

    prompts = load_prompt_settings(sp)
    assert prompts["system_persona"] == DEFAULT_PROMPT_TEMPLATES["system_persona"]
    assert prompts["narrator_extra"] == "Keep it gritty."

    srv = load_server_settings(sp)
    assert srv["bind_host"] == "0.0.0.0"
    assert srv["port"] == 8765

    # Strict validation on save_*_settings still rejects invalid values
    with pytest.raises(ValueError):
        save_llm_settings({"temperature": 99.0}, sp)
    with pytest.raises(ValueError):
        save_server_settings({"port": 99999}, sp)














