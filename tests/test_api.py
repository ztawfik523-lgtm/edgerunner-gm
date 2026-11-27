import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redkb


def test_api_operational_errors_and_audit(tmp_path, caplog):
    httpx = pytest.importorskip('httpx')
    import asyncio

    async def run():
        transport = httpx.ASGITransport(app=redkb.make_api(tmp_path / 'missing.sqlite'))
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.get('/v1/search', params={'q': 'critical success'})
            assert response.status_code == 503
            assert response.json()['request_id']
            assert 'unavailable' in response.json()['detail']
    asyncio.run(run())
    assert 'corebook_unavailable' in caplog.text


def test_api_search_trace(tmp_path, monkeypatch, caplog):
    httpx = pytest.importorskip('httpx')
    import asyncio
    monkeypatch.setattr(redkb, 'search_pages', lambda *args: [{'pdf_page': 131, 'printed_page': 130, 'source_sha256': 'source', 'excerpt': 'private text'}])

    async def run():
        transport = httpx.ASGITransport(app=redkb.make_api(tmp_path / 'unused'))
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.get('/v1/search', params={'q': 'sensitive player question'})
            data = response.json()
            assert data['request_id'] in caplog.text
            assert data['evidence_status'] == 'candidates_not_verified_answers'
    with caplog.at_level('INFO', logger='uvicorn.error'):
        asyncio.run(run())
    assert 'private text' not in caplog.text
    assert 'sensitive player question' not in caplog.text


def test_creation_reference_endpoint(tmp_path):
    httpx = pytest.importorskip('httpx')
    import asyncio

    async def run():
        app = redkb.make_api(tmp_path / 'missing_rules.sqlite')
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            response = await client.get('/v1/creation/reference')
            assert response.status_code == 200
            data = response.json()
            assert data['request_id']
            assert len(data['roles']) == 10
            assert len(data['stats']) == 10
            assert len(data['methods']) == 4
            assert len(data['shop']['weapon']) >= 50
            assert len(data['shop']['armor']) >= 14
            assert len(data['shop']['hardware']) >= 6
    asyncio.run(run())


def test_creation_ai_assist_endpoint_bio_and_contacts(tmp_path):
    httpx = pytest.importorskip('httpx')
    import asyncio
    import json as json_mod

    seen_payloads = []

    class StubCreationLLM:
        async def complete(self, messages, *, json_mode=False, temperature=None, **_kwargs):
            seen_payloads.append(json_mod.loads(messages[1]["content"]))
            req = seen_payloads[-1]
            if req["task"] == "character_bio" and req["mode"] == "scratch":
                return json_mod.dumps({
                    "concept": "Kabuki Trauma Ex-EMT with steady hands and unpaid debts",
                    "summary": "Born in Watson, trained as a Trauma Team paramedic before walking away.",
                    "established_history": "Owes Fixer Rogue a clean medical favor from 2044.",
                    "appearance": "Worn Light Armorjack over scarred scrubs, Cybereye HUD glowing cyan.",
                })
            if req["task"] == "character_bio" and req["mode"] == "expand":
                draft = req["current_draft"]["summary"]
                return json_mod.dumps({
                    "concept": "Kabuki Street Surgeon",
                    "summary": f"{draft} Still carries her old Trauma Team scalpel kit into Combat Zone basements.",
                    "established_history": f"{req['current_draft']['established_history']} Runs back-alley stitchwork after midnight.",
                    "appearance": "Scuffed Armorjack coated with antiseptic mist.",
                })
            return json_mod.dumps({
                "friends": [{"name": "Doc Kurosawa", "relationship": "Mentor street doc", "note": "Slides cheap cryobags your way."}],
                "enemies": [{"who": "Corpo exec", "name": "Hector Vance", "wronged": "They wronged me", "cause": "Dumped blame for a failed evacs", "backup": "Corporate security", "revenge": "Expose his black-site logs"}],
                "tragic_love_affairs": [{"name": "Mina Sato", "outcome": "Fled Night City after the Maelstrom raid"}],
            })

    async def run():
        app = redkb.make_api(tmp_path / 'missing_rules.sqlite', llm=StubCreationLLM())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            base_char = {
                "name": "Nyx",
                "role": "Medtech",
                "method": "complete_package",
                "stats": {"TECH": 8, "WILL": 7, "EMP": 6},
                "skills": {"First Aid": 6, "Paramedic": 6, "Handgun": 4},
                "lifepath": {"cultural_origin": "East Asian"},
                "starting_gear": {"equipped_weapon": "Sternmeyer P-35 (Very Heavy Pistol)"},
            }

            r_scratch = await client.post('/v1/creation/ai-assist', json={
                "target": "bio",
                "mode": "scratch",
                "guidance": "Ex-Trauma Team medic in Kabuki",
                "character": base_char,
                "current": {},
            })
            assert r_scratch.status_code == 200
            d_scratch = r_scratch.json()
            assert d_scratch["concept"].startswith("Kabuki Trauma")
            assert "Trauma Team" in d_scratch["summary"]

            r_expand = await client.post('/v1/creation/ai-assist', json={
                "target": "bio",
                "mode": "expand",
                "character": base_char,
                "current": {
                    "summary": "Saved a kid from Maelstrom.",
                    "established_history": "Owes Viktor Vector.",
                },
            })
            assert r_expand.status_code == 200
            d_expand = r_expand.json()
            assert "Saved a kid from Maelstrom." in d_expand["summary"]
            assert "Owes Viktor Vector." in d_expand["established_history"]

            r_contacts = await client.post('/v1/creation/ai-assist', json={
                "target": "contacts",
                "mode": "scratch",
                "character": base_char,
                "current": {},
            })
            assert r_contacts.status_code == 200
            d_contacts = r_contacts.json()
            assert d_contacts["friends"][0]["name"] == "Doc Kurosawa"
            assert d_contacts["enemies"][0]["name"] == "Hector Vance"
            assert d_contacts["tragic_love_affairs"][0]["name"] == "Mina Sato"

            r_bad = await client.post('/v1/creation/ai-assist', json={"target": "invalid", "mode": "scratch"})
            assert r_bad.status_code == 400

    asyncio.run(run())
    assert len(seen_payloads) == 3
    assert "Paramedic +6" in seen_payloads[0]["sheet"]["top_skills"]
    assert seen_payloads[0]["sheet"]["equipped_weapon"] == "Sternmeyer P-35 (Very Heavy Pistol)"


def test_campaign_ai_assist_and_bootstrap_endpoint(tmp_path: Path):
    import asyncio
    import json
    import sqlite3
    import httpx

    class StubCampaignLLM:
        async def complete(self, messages, *, json_mode=False, temperature=None):
            user_data = json.loads(messages[-1]["content"])
            mode = user_data["mode"]
            if mode == "scratch":
                return json.dumps({
                    "name": "Kabuki Voltage",
                    "summary": "High-tension data snatch across Watson & Little China.",
                    "opening_scene": "Rain lashes Neon Alley while Mara Chen slides a hot shard across the booth.",
                    "npcs": {"Mara Chen (Fixer)": "Needs an encrypted Militech manifest before dawn."},
                    "objectives": {"Infiltrate Kabuki Substation": "Pull the manifest before Maelstrom sweeps the block."},
                    "beat_chart": {
                        "hook": "Mara hires the crew.",
                        "developments": "Maelstrom cuts power.",
                        "cliffhanger": "Trauma Team AV arrives.",
                        "climax": "Rooftop extraction.",
                        "resolution": "Split 4,000 eb at Night Market.",
                    },
                    "gm_secrets": "Mara actually works for Kang Tao.",
                    "opening_clock": {"name": "Maelstrom Alert", "segments": 4, "note": "Boostergang lockdown."},
                })
            return json.dumps({
                "name": user_data["current_draft"]["name"] or "Custom Kabuki",
                "summary": user_data["current_draft"]["summary"] + " Expanded with Corebook Fixer intrigue.",
                "opening_scene": "Expanded scene in Kabuki.",
                "npcs": {"Viktor": "Ripperdoc contact."},
                "objectives": {"Trace Signal": "Find the jammer."},
                "beat_chart": {"hook": "H1", "developments": "D1", "cliffhanger": "CF1", "climax": "CL1", "resolution": "R1"},
                "gm_secrets": "Hidden double cross.",
                "opening_clock": {"name": "Trace Clock", "segments": 6, "note": "Signal traced."},
            })

    async def run():
        app = redkb.make_api(tmp_path / "missing.sqlite", campaign_path=tmp_path / "camp.sqlite", llm=StubCampaignLLM())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r_ai = await client.post("/v1/creation/ai-assist", json={
                "target": "campaign",
                "mode": "scratch",
                "guidance": "Watson heist",
                "campaign": {"name": "Kabuki Voltage", "district": "Watson Development", "caper_style": "Corporate Data / Cargo Heist", "factions": ["Maelstrom"]},
                "current": {},
            })
            assert r_ai.status_code == 200
            ai_data = r_ai.json()
            assert ai_data["name"] == "Kabuki Voltage"
            assert ai_data["beat_chart"]["cliffhanger"] == "Trauma Team AV arrives."
            assert ai_data["opening_clock"]["segments"] == 4

            r_create = await client.post("/v1/game", json={
                "action": "create_campaign",
                "arguments": {"name": ai_data["name"], "operation_id": "test-camp-1"},
            })
            assert r_create.status_code == 200
            camp_id = r_create.json()["result"]["id"]

            r_boot = await client.post(f"/v1/campaigns/{camp_id}/bootstrap", json={
                "summary": ai_data["summary"],
                "scene": ai_data["opening_scene"],
                "npcs": ai_data["npcs"],
                "objectives": ai_data["objectives"],
                "gm_secrets": ai_data["gm_secrets"],
                "opening_clock": ai_data["opening_clock"],
            })
            assert r_boot.status_code == 200
            boot = r_boot.json()
            assert boot["campaign"]["state"]["summary"].startswith("High-tension")
            assert "Mara Chen (Fixer)" in boot["campaign"]["state"]["npcs"]
            assert boot["clocks"][0]["name"] == "Maelstrom Alert"
            assert boot["secrets_count"] == 1

            conn = sqlite3.connect(tmp_path / "camp.sqlite")
            try:
                sec = conn.execute("SELECT secrets_json FROM gm_secrets WHERE campaign_id=?", (camp_id,)).fetchone()
            finally:
                conn.close()
            assert sec is not None and "Kang Tao" in sec[0]

    asyncio.run(run())


def test_campaign_ai_assist_auto_and_locked_plus_per_field_regen(tmp_path: Path):
    import asyncio
    import json
    import httpx

    seen_user_payloads: list[dict] = []

    class InspectCampaignLLM:
        async def complete(self, messages, *, json_mode=False, temperature=None):
            user_data = json.loads(messages[-1]["content"])
            seen_user_payloads.append(user_data)
            if user_data.get("target_field") == "opening_scene":
                return json.dumps({"opening_scene": "Fresh neon rooftop drop."})
            if user_data["campaign_seed"].get("lock_choices"):
                return json.dumps({
                    "name": "Locked Gig",
                    "summary": "Locked summary.",
                    "opening_scene": "Locked scene.",
                    "npcs": {"A": "1", "B": "2", "C": "3"},
                    "objectives": {"O1": "Do 1"},
                    "beat_chart": {"hook": "H", "developments": "D", "cliffhanger": "C", "climax": "X", "resolution": "R"},
                    "gm_secrets": "Secret",
                })
            return json.dumps({
                "district": "Old Combat Zone",
                "caper_style": "Street Turf & Night Market Hustle",
                "factions": ["Maelstrom", "Bozos"],
                "name": "Zone Scramble",
                "summary": "Auto-chosen summary.",
                "opening_scene": "Auto-chosen scene.",
                "npcs": {"Fixer A": "Contact", "Boss B": "Rival"},
                "objectives": {"Survive": "Escape the block"},
                "beat_chart": {"hook": "H", "developments": "D", "cliffhanger": "C", "climax": "X", "resolution": "R"},
                "gm_secrets": "Hidden sponsor.",
            })

    async def run():
        app = redkb.make_api(tmp_path / "missing.sqlite", campaign_path=tmp_path / "camp.sqlite", llm=InspectCampaignLLM())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Unlocked scratch: AI decides district, caper_style, factions
            r_auto = await client.post("/v1/creation/ai-assist", json={
                "target": "campaign",
                "mode": "scratch",
                "campaign": {"lock_choices": False, "district": "Watson Development", "caper_style": "Corporate Data / Cargo Heist", "factions": ["Arasaka"]},
                "current": {},
            })
            assert r_auto.status_code == 200
            d_auto = r_auto.json()
            assert d_auto["district"] == "Old Combat Zone"
            assert d_auto["caper_style"] == "Street Turf & Night Market Hustle"
            assert d_auto["factions"] == ["Maelstrom", "Bozos"]

            # 2. Locked scratch: preserves counts and locked options in prompt
            r_locked = await client.post("/v1/creation/ai-assist", json={
                "target": "campaign",
                "mode": "scratch",
                "campaign": {"lock_choices": True, "district": "Heywood", "caper_style": "Badlands Convoy & Smuggling Run", "factions": ["6th Street"], "npc_count": 3, "objective_count": 1},
                "current": {},
            })
            assert r_locked.status_code == 200
            d_locked = r_locked.json()
            assert "district" not in d_locked
            assert len(d_locked["npcs"]) == 3

            # 3. Per-field scratch regen
            r_regen = await client.post("/v1/creation/ai-assist", json={
                "target": "campaign",
                "mode": "scratch",
                "field": "opening_scene",
                "campaign": {"name": "Locked Gig"},
                "current": {"opening_scene": "Old stale scene"},
            })
            assert r_regen.status_code == 200
            assert r_regen.json()["opening_scene"] == "Fresh neon rooftop drop."

    asyncio.run(run())
    assert "available_options" in seen_user_payloads[0]
    assert seen_user_payloads[1]["campaign_seed"]["target_npc_count"] == 3
    assert seen_user_payloads[1]["campaign_seed"]["target_objective_count"] == 1
    assert "completely fresh 'opening_scene' from scratch" in seen_user_payloads[2]["instruction"]


def test_expanded_campaign_bootstrap_rename_library_clocks_and_session_zero(tmp_path: Path):
    import asyncio
    import httpx
    from campaign import CampaignStore
    from library import CampaignLibrary

    async def run():
        app = redkb.make_api(tmp_path / "missing.sqlite", campaign_path=tmp_path / "camp.sqlite")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a standalone character first so we can attach via attach_character_ids
            r_char = await client.post("/v1/game", json={
                "action": "create_character",
                "arguments": {
                    "name": "Kira",
                    "stats": {"INT": 6, "REF": 7, "DEX": 6, "TECH": 5, "COOL": 6, "WILL": 6, "LUCK": 6, "MOVE": 6, "BODY": 6, "EMP": 6},
                    "skills": {"Handgun": 6},
                    "operation_id": "char-attach-seed",
                },
            })
            assert r_char.status_code == 200
            char_id = r_char.json()["result"]["id"]

            r_create = await client.post("/v1/game", json={
                "action": "create_campaign",
                "arguments": {"name": "Initial Title", "operation_id": "camp-exp-1"},
            })
            assert r_create.status_code == 200
            camp_id = r_create.json()["result"]["id"]

            r_boot = await client.post(f"/v1/campaigns/{camp_id}/bootstrap", json={
                "name": "Neon Rain Over Heywood",
                "district": "Heywood",
                "zone_type": "Moderate Zone",
                "threat_rating": "Moderate",
                "caper_style": "Street Turf & Night Market Hustle",
                "factions": ["6th Street", "Tyger Claws"],
                "screamsheet_hook": "WATER MAIN SQUEEZE: Desalination valve locked.",
                "summary": "Surviving a water blockade in Heywood.",
                "scene": "Rancho Coronado pump yard at dusk.",
                "npcs": {"Fixer Toma": "Local water broker — Neutral 0"},
                "npc_identities": {
                    "Fixer Toma": {
                        "handle": "Fixer Toma",
                        "real_name": "Tomasz Kowalski",
                        "real_name_hidden": True,
                        "personality": "Guarded",
                        "speech_style": "Dry, brief",
                    }
                },
                "objectives": {"Break Blockade": "Reopen Valve 3."},
                "discoveries": {"Valve Blueprint": "Sub-level hatch is unguarded."},
                "gm_secrets": {"Premise Secret": "Continental Brands bribed 6th Street.", "Mole": "Guard #2 works for Tyger Claws."},
                "clocks": [
                    {"name": "6th Street Sweep", "segments": 6, "filled": 2, "category": "heat", "visibility": "public", "note": "Patrols tighten."},
                    {"name": "Water Tank Contamination", "segments": 4, "filled": 1, "category": "deadline", "visibility": "secret", "note": "Secret leak."},
                ],
                "world_entities": {
                    "factions": [{"name": "6th Street", "disposition": "Hostile", "turf": "Rancho Coronado"}],
                    "locations": [{"name": "Valve House 3", "district": "Heywood", "security": "Razorwire & drones", "notes": "Rusty pump room."}],
                    "gig": {"title": "Water Main Break", "client": "Fixer Toma", "target": "Valve House 3", "payout_eb": 2500, "deadline": "Dawn"},
                    "screamsheet": {"headline": "WATER MAIN SQUEEZE", "body": "Desalination valve locked down."},
                },
                "session_zero": {
                    "gm_style": "grit_dark",
                    "narrator_length": "concise",
                    "lethality_dial": "Gritty / High Lethality",
                    "lines_and_veils": "No harm to children",
                },
                "starting_clock_minutes": 1140,
                "attach_character_ids": [char_id],
                "clear_missing": True,
            })
            assert r_boot.status_code == 200
            boot = r_boot.json()
            assert boot["campaign"]["name"] == "Neon Rain Over Heywood"
            assert boot["secrets_count"] == 2
            assert len(boot["clocks"]) == 1  # public clock only in public response
            assert boot["library_seeded"] == 4

            # Verify CampaignContext (admin/open role) hydrates all fields
            r_ctx = await client.post("/v1/game", json={
                "action": "campaign_context",
                "campaign_id": camp_id,
                "arguments": {"campaign_id": camp_id},
            })
            ctx = r_ctx.json()["result"]
            assert ctx["campaign"]["name"] == "Neon Rain Over Heywood"
            assert ctx["campaign_meta"]["district"] == "Heywood"
            assert ctx["campaign_meta"]["factions"] == ["6th Street", "Tyger Claws"]
            assert ctx["session_zero"]["gm_style"] == "grit_dark"
            assert ctx["session_zero"]["lines_and_veils"] == "No harm to children"
            assert ctx["solo"]["runtime"]["clock_minutes"] == 1140
            assert len(ctx["clocks"]) == 2
            assert ctx["gm_secrets"]["Premise Secret"] == "Continental Brands bribed 6th Street."
            assert ctx["campaign_meta"]["locations"][0]["security"] == "Razorwire & drones"
            assert ctx["npc_profiles"]["Fixer Toma"]["real_name"] == "Tomasz Kowalski"
            assert char_id in ctx["campaign"]["character_ids"]

            # Re-bootstrapping with same world_entities upserts cleanly without duplicating library rows
            r_boot2 = await client.post(f"/v1/campaigns/{camp_id}/bootstrap", json={
                "world_entities": {
                    "factions": [{"name": "6th Street", "disposition": "Wary", "turf": "Rancho Coronado"}],
                },
            })
            assert r_boot2.status_code == 200
            entries = CampaignLibrary(CampaignStore(tmp_path / "camp.sqlite")).list_entries(camp_id, category="faction")
            assert len(entries) == 1
            assert entries[0]["stats"]["disposition"] == "Wary"

            # clear_missing removes stale locations/gig & flipping real_name_hidden preserves revealed name cleanly
            r_boot3 = await client.post(f"/v1/campaigns/{camp_id}/bootstrap", json={
                "district": "Heywood",
                "clear_missing": True,
                "world_entities": {"locations": [], "gig": None},
                "npc_identities": {
                    "Fixer Toma": {
                        "handle": "Fixer Toma",
                        "real_name_hidden": False,
                    }
                },
            })
            assert r_boot3.status_code == 200
            r_ctx2 = await client.post("/v1/game", json={
                "action": "campaign_context",
                "campaign_id": camp_id,
                "arguments": {"campaign_id": camp_id},
            })
            ctx2 = r_ctx2.json()["result"]
            assert "locations" not in ctx2["campaign_meta"]
            assert "gig" not in ctx2["campaign_meta"]
            assert ctx2["npc_profiles"]["Fixer Toma"]["real_name"] == "Tomasz Kowalski"
            assert ctx2["npc_profiles"]["Fixer Toma"]["real_name_hidden"] is False

    asyncio.run(run())


def test_update_character_profile_does_not_leak_hidden_real_name_into_handle(tmp_path: Path):
    from campaign import CampaignStore

    store = CampaignStore(tmp_path / "camp.sqlite")
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    char = store.create_character("Shade", stats, detail={"handle": "Shade"})
    updated = store.update_character_profile(
        char["id"],
        char["revision"],
        {"handle": None, "real_name": "Marcus Cole", "real_name_hidden": True},
        "Hide legal identity",
        "op-hide-1",
    )
    assert updated["name"] == "Shade"
    assert updated["detail"]["real_name"] == "Marcus Cole"
    assert updated["detail"]["real_name_hidden"] is True


def test_server_side_player_redaction_across_tree_sse_coop_and_game(tmp_path: Path, monkeypatch):
    import asyncio
    import json
    import httpx
    from server.redaction import (
        redact_campaign_context,
        redact_character,
        redact_chat_message,
        redact_chat_tree,
        redact_sse_event,
        redact_state_patch,
    )
    from tests.test_library import _create_rules_db
    from turnloop import LLMConfig

    # 1. Unit tests for redaction helpers
    sample_patch = {
        "target": "campaign",
        "before": {"discoveries": {"__npc_identities": "{}", "Clue": "A"}, "unresolved": {"Mole": "X"}, "gm_secrets": {"S": "1"}},
        "after": {"discoveries": {"__campaign_meta": "{}", "Clue": "B"}, "unresolved": {"Mole": "Y"}},
    }
    red_patch = redact_state_patch(sample_patch, is_gm=False)
    assert "__npc_identities" not in red_patch["before"]["discoveries"]
    assert "__campaign_meta" not in red_patch["after"]["discoveries"]
    assert red_patch["before"]["discoveries"]["Clue"] == "A"
    assert "unresolved" not in red_patch["before"]
    assert "gm_secrets" not in red_patch["before"]

    sample_msg = {
        "id": "m1",
        "channel_id": "main",
        "role": "assistant",
        "content": "Visible prose",
        "raw_content": "<think>secret GM reasoning</think>Visible prose",
        "model": "gpt-secret",
        "metadata": {
            "model": "gpt-secret",
            "generation_stats": {"elapsed_seconds": 1.2},
            "guidance": "Secret director note",
            "citation_cards": [{"id": "c1", "name": "Rule"}],
            "warnings": ["GM warning"],
            "library_added": ["lib-1"],
            "patches": [sample_patch],
        },
    }
    red_msg = redact_chat_message(sample_msg, is_gm=False)
    assert "raw_content" not in red_msg
    assert "model" not in red_msg
    for gm_k in ("model", "generation_stats", "guidance", "citation_cards", "warnings", "library_added"):
        assert gm_k not in red_msg["metadata"]
    assert "__campaign_meta" not in red_msg["metadata"]["patches"][0]["after"]["discoveries"]

    assert redact_sse_event("rule_citation", {"id": "c1"}, is_gm=False) is None
    assert redact_sse_event("warning", {"message": "warn"}, is_gm=False) is None
    assert redact_sse_event("library_added", {"id": "l1"}, is_gm=False) is None
    assert redact_sse_event("peer_stream", {"event": "rule_citation", "data": {"id": "c1"}}, is_gm=False) is None

    red_tree = redact_chat_tree(
        {
            "channels": ["main", "bob-chan"],
            "nodes": [sample_msg, {**sample_msg, "id": "m2", "channel_id": "bob-chan"}],
            "active_branch": [sample_msg],
        },
        is_gm=False,
        allowed_channels={"main"},
    )
    assert red_tree["channels"] == ["main"]
    assert [n["id"] for n in red_tree["nodes"]] == ["m1"]

    bob_char = {
        "id": "c-bob",
        "name": "Hammer",
        "detail": {
            "handle": "Hammer",
            "real_name": "Robert Vance",
            "real_name_hidden": True,
            "owner_username": "bob",
            "appearance": "Chrome arm",
            "backstory": {"summary": "Secret spy", "appearance": "Chrome arm", "private": True},
        },
    }
    assert redact_character(bob_char, is_gm=False, viewer_username="alice")["detail"]["real_name"] == ""
    assert "summary" not in redact_character(bob_char, is_gm=False, viewer_username="alice")["detail"]["backstory"]
    assert redact_character(bob_char, is_gm=False, viewer_username="alice")["detail"]["appearance"] == "Chrome arm"
    assert redact_character(bob_char, is_gm=False, viewer_username="bob")["detail"]["real_name"] == "Robert Vance"

    # 2. Full HTTP integration test across /v1/chat/turn SSE, /v1/chat/tree, /v1/game, and split channels
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "camp.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    class RedactionTestLLM:
        def __init__(self):
            self.config = LLMConfig(model="secret-gm-model", mode="two_pass")

        async def complete(self, messages, **_kwargs):
            system = messages[0]["content"] if messages else ""
            if "Chronicler" in system or "continuity" in system.lower():
                return json.dumps({
                    "campaign_updates": {
                        "discoveries": {"Public Clue": "Keycard on desk"},
                        "unresolved": {"Hidden Bomb": "Armed in basement"},
                    },
                    "gm_secrets": {"Mastermind": "Arasaka exec"},
                })
            return json.dumps({
                "checks": [],
                "citations": ["Skill Checks"],
                "gm_notes": "Secret GM note",
            })

        def pop_call_meta(self):
            return {}

        async def stream(self, messages, **_kwargs):
            yield "<think>Internal GM thought</think>Rain falls over Watson."

    async def run():
        app = redkb.make_api(rules_db, (), camp_db, settings_path=settings_path, llm=RedactionTestLLM())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            boot = await client.post(
                "/v1/auth/setup",
                json={
                    "admin_username": "gm",
                    "admin_password": "gm-password-1",
                    "allow_self_signup": True,
                    "bootstrap_token": "test-bootstrap-token-" + ("a" * 40),
                },
            )
            admin_headers = {"X-RedGM-Token": boot.json()["token"]}
            client.cookies.clear()
            alice_headers = {"X-RedGM-Token": (await client.post("/v1/auth/register", json={"username": "alice", "password": "alice-password"})).json()["token"]}
            client.cookies.clear()
            bob_headers = {"X-RedGM-Token": (await client.post("/v1/auth/register", json={"username": "bob", "password": "bob-password"})).json()["token"]}
            client.cookies.clear()

            camp = (await client.post("/v1/game", headers=admin_headers, json={"action": "create_campaign", "arguments": {"name": "Redaction Run", "operation_id": "red-c1"}})).json()["result"]
            camp_id = camp["id"]
            stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
            alice_pc = (await client.post(
                "/v1/game",
                headers=alice_headers,
                json={"action": "create_character", "arguments": {"name": "Ghost", "stats": stats, "detail": {"handle": "Ghost", "real_name": "Alice Secret", "real_name_hidden": True}, "operation_id": "red-a1"}},
            )).json()["result"]
            bob_pc = (await client.post(
                "/v1/game",
                headers=bob_headers,
                json={"action": "create_character", "arguments": {"name": "Brick", "stats": stats, "detail": {"handle": "Brick", "real_name": "Bob Secret", "real_name_hidden": True, "backstory": {"summary": "Secret spy", "private": True}}, "operation_id": "red-b1"}},
            )).json()["result"]

            await client.post(f"/v1/campaigns/{camp_id}/bootstrap", headers=admin_headers, json={
                "scene": "Watson alley",
                "unresolved": {"Mole": "Fixer is traitor"},
                "gm_secrets": {"Secret": "Hidden lab"},
                "npc_identities": {"Fixer": {"handle": "Fixer", "real_name": "Viktor K", "real_name_hidden": True}},
                "clocks": [
                    {"name": "Public Heat", "segments": 4, "filled": 1, "visibility": "public"},
                    {"name": "Secret Trap", "segments": 4, "filled": 2, "visibility": "secret"},
                ],
                "attach_character_ids": [alice_pc["id"], bob_pc["id"]],
            })

            # Alice runs a turn and receives redacted SSE stream (no rule_citation/warning/library_added, no raw_content/guidance/citation_cards).
            turn_res = await client.post(
                "/v1/chat/turn",
                headers=alice_headers,
                json={"campaign_id": camp_id, "speaker_character_id": alice_pc["id"], "user_text": "I inspect the desk.", "gm_mode": "force_gm"},
            )
            assert turn_res.status_code == 200
            assert "event: rule_citation" not in turn_res.text
            assert "event: warning" not in turn_res.text
            assert "event: library_added" not in turn_res.text
            assert "Internal GM thought" not in turn_res.text
            assert "Hidden Bomb" not in turn_res.text

            # /v1/chat/tree: Admin sees raw_content & citation_cards; Alice does not.
            gm_tree = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id}, headers=admin_headers)).json()
            alice_tree = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id}, headers=alice_headers)).json()
            gm_asst = gm_tree["active_branch"][-1]
            alice_asst = alice_tree["active_branch"][-1]
            assert "Internal GM thought" in gm_asst["raw_content"]
            assert "raw_content" not in alice_asst
            assert "model" not in alice_asst
            assert "generation_stats" not in alice_asst["metadata"]
            assert "citation_cards" not in alice_asst["metadata"]

            # /v1/game reads: campaign_context, get_campaign, get_character, list_characters redacted for Alice.
            alice_ctx = (await client.post("/v1/game", headers=alice_headers, json={"action": "campaign_context", "campaign_id": camp_id, "arguments": {"campaign_id": camp_id}})).json()["result"]
            assert "gm_secrets" not in alice_ctx
            assert alice_ctx["campaign"]["state"]["unresolved"] == {}
            assert not any(k.startswith("__") for k in alice_ctx["campaign"]["state"]["discoveries"])
            assert [c["name"] for c in alice_ctx["clocks"]] == ["Public Heat"]
            assert "real_name" not in alice_ctx["npc_profiles"]["Fixer"]
            alice_view_of_self = next(c for c in alice_ctx["characters"] if c["id"] == alice_pc["id"])
            alice_view_of_bob = next(c for c in alice_ctx["characters"] if c["id"] == bob_pc["id"])
            assert alice_view_of_self["detail"]["real_name"] == "Alice Secret"
            assert alice_view_of_bob["detail"]["real_name"] == ""
            assert "summary" not in (alice_view_of_bob["detail"].get("backstory") or {})

            alice_get_camp = (await client.post("/v1/game", headers=alice_headers, json={"action": "get_campaign", "arguments": {"campaign_id": camp_id}})).json()["result"]
            assert alice_get_camp["state"]["unresolved"] == {}
            assert not any(k.startswith("__") for k in alice_get_camp["state"]["discoveries"])

            alice_get_bob = (await client.post("/v1/game", headers=alice_headers, json={"action": "get_character", "arguments": {"character_id": bob_pc["id"]}})).json()["result"]
            assert alice_get_bob["detail"]["real_name"] == ""

            alice_list_chars = (await client.post("/v1/game", headers=alice_headers, json={"action": "list_characters", "campaign_id": camp_id, "arguments": {}})).json()["result"]
            listed_bob = next(c for c in alice_list_chars if c["id"] == bob_pc["id"])
            assert listed_bob["detail"]["real_name"] == ""

            # Split party: Bob gets his own private channel; Alice cannot post to or read Bob's channel.
            split = (await client.post(f"/v1/campaigns/{camp_id}/party-location", headers=admin_headers, json={
                "pc_locations": {alice_pc["id"]: "Dock 7", bob_pc["id"]: "Penthouse"},
            })).json()
            bob_chan = split["party_grouping"]["char_channel_map"][bob_pc["id"]]
            await client.post("/v1/chat/turn", headers=bob_headers, json={
                "campaign_id": camp_id,
                "channel_id": bob_chan,
                "speaker_character_id": bob_pc["id"],
                "user_text": "Bob whispers to the mole.",
                "gm_mode": "force_gm",
            })

            alice_peek = (await client.get("/v1/chat/tree", params={"campaign_id": camp_id, "channel_id": bob_chan}, headers=alice_headers)).json()
            assert alice_peek["nodes"] == []
            assert bob_chan not in alice_peek["channels"]
            assert (await client.post("/v1/chat/turn", headers=alice_headers, json={
                "campaign_id": camp_id,
                "channel_id": bob_chan,
                "speaker_character_id": alice_pc["id"],
                "user_text": "Spy on Bob",
            })).status_code == 403

    asyncio.run(run())



