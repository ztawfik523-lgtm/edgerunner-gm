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
        admin_headers = {"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765", "Content-Type": "application/json", "X-RedGM-Token": admin_token}

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
    orig_publish = redkb._CoopHub.publish

    def spy_publish(self, campaign_id: str, event: str, data: dict[str, Any]) -> None:
        published.append((campaign_id, event, data))
        orig_publish(self, campaign_id, event, data)

    monkeypatch.setattr(redkb._CoopHub, "publish", spy_publish)
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

        clocks_res = (await client.get(f"/v1/campaigns/{camp_id}/clocks")).json()
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

        # Regenerating Turn 1 branches off root and does not inherit Turn 1 post-turn clocks
        regen = await client.post("/v1/chat/regenerate", headers=headers, json={"campaign_id": camp_id, "message_id": user_id_1})
        assert regen.status_code == 200
        clocks_after_regen = (await client.get(f"/v1/campaigns/{camp_id}/clocks")).json()
        assert clocks_after_regen["clocks"] == []


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
            {"actor": "Vee Mercer", "skill": "Handgun", "dv": 30, "reason": "Long shot"},
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









