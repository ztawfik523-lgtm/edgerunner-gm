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


