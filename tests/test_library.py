"""Tests for the Organized Rulebook Library and campaign-scoped homebrew catalog."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gameplay import GameplayService
import library
import redkb
import sourcecatalog


def _create_rules_db(path: Path) -> Path:
    """Build a small synthetic index through the real extraction pipeline."""
    from tests import rules_fixture as rf

    skills = rf.page(83, 82, [
        rf.block("Handgun ......................... REF", 74),
        rf.block("Skill for accurately firing one-handed ranged weapons like pistols.\n"
                 "Covers semi-auto pistols and revolvers in Night City firefights.", 95),
        rf.heading("Fighting Skills", 140),
        rf.block("Martial Arts (x2) ............... DEX", 170),
        rf.block("Specialized close-quarters fighting styles such as Karate or Aikido.\n"
                 "Requires x2 Improvement Points to advance.", 190),
        rf.block("Interface ....................... INT", 240),
        rf.block("Netrunner Role Ability skill listed for test layout.", 260),
        rf.block("Perception ...................... INT", 290),
        rf.block("Spotting hidden things.", 310),
        rf.block("Streetwise ...................... COOL", 330),
        rf.block("Knowing who to ask.", 350),
    ])
    role_lists = rf.page(89, 88, [rf.table([
        ["Rockerboy Skills", "Solo Skills", "Netrunner Skills"],
        ["Athletics", "Athletics", "Athletics"],
        ["Handgun", "Handgun", "Interface"],
    ], 100)])
    role = rf.page(143, 142, [
        rf.heading("SOLO", 18, size=36.0),
        rf.block("Combat Sense specialists who rule the street.", 231),
        rf.heading("▶Role Ability: Combat Awareness", 566, size=12.5),
        rf.block("The Solo's Role Ability is Combat Awareness, sharpening reflexes in a firefight.", 587),
    ])
    gear = rf.page(341, 340, [
        rf.heading("Ranged Weapons", 60),
        rf.table([rf.RANGED_HEADER,
                  ["Medium Pistol", "Handgun", "2d6", "12 (M Pistol)", "2", "1", "YES", "50eb (Costly)"],
                  ["Alt. Fire Modes & Special Features: None", "", "", "", "", "", "", ""],
                  ["Heavy Pistol", "Handgun", "3d6", "8 (H Pistol)", "2", "1", "YES", "100eb (Premium)"],
                  ["Alt. Fire Modes & Special Features: None", "", "", "", "", "", "", ""],
                  ["Assault Rifle", "Shoulder Arms", "5d6", "25 (Rifle)", "1", "2", "NO", "500eb (Expensive)"],
                  ["Alt. Fire Modes & Special Features: Autofire (4)", "", "", "", "", "", "", ""]], 90),
        rf.table([rf.ARMOR_HEADER,
                  ["Light Armorjack", "A woven mesh of synthetic fibers and plates.", "11", "None", "100eb (Premium)"]], 300),
    ])
    cyber = rf.page(361, 360, [
        rf.heading("▶Neuralware (Foundational Cyberware: Neural Link)", 68, size=12.5),
        rf.table([rf.CYBERWARE_HEADER,
                  ["Kerenzikov", "Clinic", "Neural speedware adding +2 to Initiative.", "500eb (Expensive)", "14 (4d6)"]], 97),
    ])
    toc = [[1, "Fitted for the Future", 82], [2, "Skills", 83], [1, "Getting it Done", 140], [2, "Solo", 143],
           [1, "The New Street Economy", 340], [2, "Ranged Weapons", 341]]
    return rf.build(path, [skills, role_lists, role, gear, cyber], toc, digest="deadbeef1234")


def _setup_campaign(tmp_path: Path, rules_db: Path):
    camp_db = tmp_path / "campaign.sqlite"
    svc = GameplayService(camp_db, rules_db)
    camp = svc.execute("create_campaign", {"name": "Watson Run", "operation_id": "op-c1"})["result"]
    return camp_db, svc, camp["id"]


def test_corebook_library_skills_items_and_roles(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")

    handgun_hits = library.search_library(rules_db, q="Handgun", category="skill")
    assert len(handgun_hits) == 1
    hg = handgun_hits[0]
    assert hg["name"] == "Handgun"
    assert hg["stats"] == {"stat": "REF", "cost_multiplier": 1, "specializable": False}
    assert "one-handed ranged weapons like pistols" in hg["description"]
    assert hg["printed_page"] == 82

    ma = library.search_library(rules_db, q="Martial Arts", category="skill")[0]
    assert ma["stats"]["stat"] == "DEX"
    assert ma["stats"]["cost_multiplier"] == 2
    assert ma["stats"]["specializable"] is True

    pistol = library.search_library(rules_db, q="Heavy Pistol", category="weapon")[0]
    assert pistol["stats"]["damage"] == "3d6"
    assert pistol["stats"]["rof"] == 2
    assert pistol["stats"]["cost_eb"] == 100
    assert pistol["stats"]["skill"] == "Handgun"

    armor = library.search_library(rules_db, q="Light Armorjack", category="armor")[0]
    assert armor["stats"]["sp"] == 11
    assert armor["stats"]["cost_eb"] == 100

    ker = library.search_library(rules_db, q="Kerenzikov", category="cyberware")[0]
    assert ker["stats"]["humanity_loss"] == "4d6"
    assert ker["stats"]["hl"] == 14
    assert ker["stats"]["install"] == "Clinic"
    assert "+2 to Initiative" in ker["description"]

    solo = library.search_library(rules_db, q="Solo", category="role")[0]
    assert solo["category"] == "role"
    assert solo["section_id"] == "solo-143"


def test_campaign_homebrew_validation_and_search(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db, svc, camp_id = _setup_campaign(tmp_path, rules_db)
    lib = library.CampaignLibrary(svc.store, rules_path=rules_db)

    entry = lib.add_entry(
        camp_id,
        name="Arasaka Mantis Wire",
        category="cyberware",
        description="Concealed monofilament forearm spool used for silent takedowns.",
        stats={"damage": "3d6", "humanity_loss": "2d6", "cost_eb": 1200, "install": "Clinic"},
        tags=["homebrew", "arasaka"],
        created_by="ai",
        operation_id="hb-1",
    )
    assert entry["source"] == "homebrew"
    assert entry["created_by"] == "ai"

    # Idempotent replay returns identical record
    replay = lib.add_entry(
        camp_id,
        name="Arasaka Mantis Wire",
        category="cyberware",
        description="Concealed monofilament forearm spool used for silent takedowns.",
        stats={"damage": "3d6", "humanity_loss": "2d6", "cost_eb": 1200, "install": "Clinic"},
        tags=["homebrew", "arasaka"],
        created_by="ai",
        operation_id="hb-1",
    )
    assert replay["id"] == entry["id"]

    # Unified search includes both corebook & campaign homebrew
    merged = library.search_library(rules_db, q="Clinic", campaign_path=camp_db, campaign_id=camp_id, limit=100)
    names = {m["name"] for m in merged}
    assert "Kerenzikov" in names
    assert "Arasaka Mantis Wire" in names

    # Rejects Corebook overwrite and out-of-universe stats
    with pytest.raises(ValueError, match="official Corebook"):
        lib.add_entry(camp_id, name="Handgun", category="skill", stats={"stat": "REF"}, operation_id="hb-bad1")
    with pytest.raises(ValueError, match="cost_eb"):
        lib.add_entry(camp_id, name="Bad Gun", category="weapon", stats={"cost_eb": -50}, operation_id="hb-bad2")
    with pytest.raises(ValueError, match="stat must be one of"):
        lib.add_entry(camp_id, name="Fake Skill", category="skill", stats={"stat": "MANA"}, operation_id="hb-bad3")


@pytest.mark.anyio
async def test_library_http_endpoints(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db, _, camp_id = _setup_campaign(tmp_path, rules_db)
    app = redkb.make_api(rules_db, allowed_origins=("http://localhost:5173",), campaign_path=camp_db)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/v1/library", params={"q": "Handgun", "category": "skill"})
        assert res.status_code == 200
        assert res.json()["items"][0]["name"] == "Handgun"

        blocked = await client.post(
            "/v1/library/homebrew",
            headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
            json={"campaign_id": camp_id, "name": "Test", "category": "gear"},
        )
        assert blocked.status_code == 403

        created = await client.post(
            "/v1/library/homebrew",
            headers={"Origin": "http://localhost:5173", "Content-Type": "application/json"},
            json={
                "campaign_id": camp_id,
                "name": "Chrome Optics",
                "category": "cyberware",
                "description": "Custom targeting reticle.",
                "stats": {"cost_eb": 300, "humanity_loss": 4},
                "operation_id": "http-hb-1",
            },
        )
        assert created.status_code == 200
        entry_id = created.json()["item"]["id"]

        fetched = await client.get(f"/v1/library/{entry_id}", params={"campaign_id": camp_id})
        assert fetched.status_code == 200
        assert fetched.json()["item"]["name"] == "Chrome Optics"

        deleted = await client.delete(
            f"/v1/library/homebrew/{entry_id}",
            params={"campaign_id": camp_id},
            headers={"Origin": "http://localhost:5173"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_strict_names_and_deduplication(tmp_path: Path):
    import sqlite3
    import library

    rules_db = _create_rules_db(tmp_path / "rules_dup.sqlite")
    # Insert a duplicate Cyberarm entry on an earlier printed_page to verify dedup keeps earliest page.
    with sqlite3.connect(rules_db) as conn:
        for idx, page in enumerate((358, 366), start=1):
            eid = f"corebook:cyberware:cyberarm:{idx}"
            conn.execute(
                """
                INSERT INTO rule_entries(
                    id, name, norm_name, category, source, summary, description,
                    stats_json, tags_json, printed_page, pdf_page, source_sha256
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    eid,
                    "Cyberarm",
                    "cyberarm",
                    "cyberware",
                    "corebook",
                    f"Cybernetic arm replacement (p.{page}).",
                    "Contains the word question or character in prose description.",
                    '{"cost_eb": 500}',
                    '["cyberware", "arm"]',
                    page,
                    page + 2,
                    "testsha",
                ),
            )
            conn.execute(
                "INSERT INTO rule_entries_fts(entry_id, name, category, summary, description, tags_text) VALUES (?,?,?,?,?,?)",
                (eid, "Cyberarm", "cyberware", f"p.{page}", "question character prose", "cyberware arm"),
            )

    # Greetings and conversational filler should return zero citations in strict_names mode
    assert library.search_library(rules_db, q="yo", strict_names=True, limit=5) == []
    assert (
        library.search_library(
            rules_db,
            q="i already have a character, why wasnt it loaded? i just wanna question them idk smth",
            strict_names=True,
            limit=5,
        )
        == []
    )

    # Explicit rule/gear mention still resolves cleanly and deduplicates identical (source, category, norm_name)
    matched = library.search_library(rules_db, q="Check my Cyberarm and Handgun", strict_names=True, limit=10)
    names = [m["name"] for m in matched]
    assert "Handgun" in names
    cyberarms = [m for m in matched if m["name"] == "Cyberarm"]
    assert len(cyberarms) == 1
    assert cyberarms[0]["printed_page"] == 358


def test_upsert_and_dossier_categories(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db, svc, camp_id = _setup_campaign(tmp_path, rules_db)
    lib = library.CampaignLibrary(svc.store, rules_path=rules_db)

    npc = lib.upsert_entry(
        camp_id,
        name="Tomasz Nowak",
        category="npc",
        summary="Fixer at the Afterlife back bar [Neutral 0]",
        description="Runs smuggling jobs along the Watson waterfront.",
        stats={"disposition": 0, "role": "Fixer", "status": "Active"},
        tags=["npc", "watson"],
        created_by="ai",
        operation_id="dossier-1",
    )
    assert npc["category"] == "npc"
    assert npc["stats"]["disposition"] == 0

    updated = lib.upsert_entry(
        camp_id,
        name="Tomasz Nowak",
        category="npc",
        summary="Fixer at the Afterlife [Friendly +1]",
        description="Owes the crew a clean evac favor.",
        stats={"disposition": 1, "role": "Fixer", "status": "Active"},
        tags=["npc", "afterlife"],
        created_by="ai",
        operation_id="dossier-2",
    )
    assert updated["id"] == npc["id"]
    assert updated["stats"]["disposition"] == 1
    assert "evac favor" in updated["description"]

    loc = lib.upsert_entry(
        camp_id,
        name="Dock 14 Warehouse",
        category="location",
        summary="Abandoned cold-storage depot",
        description="Rusting shutters, cargo cranes, single roof vent.",
        stats={"district": "Watson"},
        tags=["location"],
        created_by="ai",
        operation_id="dossier-3",
    )
    fac = lib.upsert_entry(
        camp_id,
        name="Maelstrom",
        category="faction",
        summary="Chrome-obsessed booster gang",
        description="Controls lower Kabuki and Watson docks.",
        stats={"stance": "Hostile"},
        tags=["faction"],
        created_by="ai",
        operation_id="dossier-4",
    )
    assert loc["category"] == "location"
    assert fac["category"] == "faction"

    npc_hits = library.search_library(rules_db, q="Tomasz", category="npc", campaign_path=camp_db, campaign_id=camp_id, limit=5)
    assert len(npc_hits) == 1
    assert npc_hits[0]["stats"]["disposition"] == 1


def test_upsert_preserves_existing_fields_and_library_events_idempotency(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db, svc, camp_id = _setup_campaign(tmp_path, rules_db)
    lib = library.CampaignLibrary(svc.store, rules_path=rules_db)

    created = lib.upsert_entry(
        camp_id,
        name="Mirek",
        category="npc",
        summary="Ripperdoc in Kabuki",
        description="Runs an off-grid basement clinic behind a noodle stall.",
        stats={"role": "Medtech", "disposition": 0},
        tags=["npc", "kabuki"],
        created_by="ai",
        operation_id="lib-op-1",
    )

    # Empty description/summary defaults preserve existing rich text, stats, and tags
    updated = lib.upsert_entry(
        camp_id,
        name="Mirek",
        category="npc",
        summary="",
        description="",
        stats={"disposition": 2},
        tags=[],
        created_by="ai",
        operation_id="lib-op-2",
    )
    assert updated["id"] == created["id"]
    assert updated["summary"] == "Ripperdoc in Kabuki"
    assert updated["description"] == "Runs an off-grid basement clinic behind a noodle stall."
    assert updated["stats"] == {"role": "Medtech", "disposition": 2}
    assert updated["tags"] == ["npc", "kabuki"]

    # Replaying op-1 after op-2 still returns op-1's recorded result and rejects mismatched payloads
    replay = lib.upsert_entry(
        camp_id,
        name="Mirek",
        category="npc",
        summary="Ripperdoc in Kabuki",
        description="Runs an off-grid basement clinic behind a noodle stall.",
        stats={"role": "Medtech", "disposition": 0},
        tags=["npc", "kabuki"],
        created_by="ai",
        operation_id="lib-op-1",
    )
    assert replay == created

    with pytest.raises(ValueError, match="operation_id was already used for another library change"):
        lib.upsert_entry(
            camp_id,
            name="Mirek",
            category="npc",
            summary="Different summary",
            description="",
            stats={"disposition": -1},
            tags=[],
            created_by="ai",
            operation_id="lib-op-1",
        )


def test_search_and_get_library_entry_readonly_no_write_lock(tmp_path: Path):
    import os

    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db, svc, camp_id = _setup_campaign(tmp_path, rules_db)
    lib = library.CampaignLibrary(svc.store, rules_path=rules_db)
    entry = lib.add_entry(
        camp_id,
        name="Kestrel Data Shard",
        category="gear",
        description="Encrypted shard from the dockyard.",
        operation_id="ro-hb-1",
    )

    # Make both SQLite files read-only; read-only search & get_library_entry must succeed without BEGIN IMMEDIATE
    os.chmod(rules_db, 0o444)
    os.chmod(camp_db, 0o444)
    try:
        hits = library.search_library(
            rules_db,
            q="Kestrel",
            campaign_path=camp_db,
            campaign_id=camp_id,
            limit=10,
        )
        assert any(h["id"] == entry["id"] for h in hits)
        fetched = library.get_library_entry(
            entry["id"],
            rules_path=rules_db,
            campaign_path=camp_db,
            campaign_id=camp_id,
        )
        assert fetched is not None and fetched["name"] == "Kestrel Data Shard"
    finally:
        os.chmod(rules_db, 0o600)
        os.chmod(camp_db, 0o600)





def test_run_in_paragraphs_become_gang_and_people_entries(tmp_path):
    import layout
    from tests import rules_fixture as rf

    def span(text, bold=False):
        return {"text": text, "font": "Book-Bold" if bold else "Book", "flags": 0}

    assert layout.run_in_name([span("7", True), span("th Row", True), span(": Born here", False)]) == "7th Row"
    assert layout.run_in_name([span("The Wires:", True), span(" a pack")]) == "The Wires"
    assert layout.run_in_name([span("A bold pull quote.", True)]) == ""

    toc = [[1, "Gangs of Night City", 1], [1, "Badasses of Night City", 2]]
    path = rf.build(tmp_path / "rules.sqlite", [
        rf.page(1, 1, [
            rf.heading("Gangs of Night City", 60),
            rf.block("Intro prose.", 90),
            rf.block("The Wires: They splice", 120, runin="The Wires"),
            rf.block("whatever they find.", 135, x=72),
            rf.block("A margin note.", 200, x=15, size=8, width=40),
            rf.block("Glass Row: A quiet crew.", 240, runin="Glass Row"),
        ]),
        rf.page(2, 2, [
            rf.heading("Badasses of Night City", 60),
            rf.block("Sam Test (Fixer): Knows people.", 90, runin="Sam Test (Fixer)"),
        ]),
    ], toc)
    entries = {e["name"]: e for e in sourcecatalog.entries(path)}
    assert entries["The Wires"]["category"] == "faction" and entries["The Wires"]["stats"] == {"kind": "gang"}
    assert entries["The Wires"]["description"] == "They splice whatever they find."
    assert entries["Glass Row"]["description"] == "A quiet crew."
    assert entries["Sam Test"]["category"] == "npc" and entries["Sam Test"]["stats"] == {"kind": "person", "role": "Fixer"}


def test_stat_blocks_become_npc_entries_that_encounters_can_use(tmp_path):
    import layout
    from encounters import build_npc_combatant, expand_npc_specs
    from tests import rules_fixture as rf

    blocks, notes = layout.parse_stat_blocks(rf.stat_block_lines("Test Ganger") + rf.stat_block_lines("Test Boss", 420))
    assert [b["name"] for b in blocks] == ["Test Ganger", "Test Boss"]
    page = rf.page(2, 2, [])
    page["stat_blocks"], page["stat_notes"] = blocks, notes
    path = rf.build(tmp_path / "rules.sqlite", [page])
    rf.add_skill_definitions(path, ["Handgun........REF", "Evasion........DEX", "Local Expert........INT"])

    entry = next(e for e in sourcecatalog.entries(path, "npc") if e["name"] == "Test Ganger")
    stats = entry["stats"]
    assert entry["printed_page"] == 2 and stats["tier"] == "mook"
    assert stats["npc_stats"]["REF"] == 6 and stats["npc_stats"]["LUCK"] == 0 and stats["armor_penalty"] == 2
    assert (stats["hit_points"], stats["sp_head"], stats["sp_body"]) == (30, 7, 11)
    assert [w["name"] for w in stats["weapons"]] == ["Poor Quality VH Pistol", "Medium Melee Weapon"]
    assert stats["skills"] == {"Handgun": 4, "Evasion": 2, "Local Expert (Your Home)": 0}
    assert stats["abilities"] == {"Test Instinct": 4} and stats["unparsed_skills"] == ["Tactics"]
    assert stats["equipment"] == "VH Pistol Ammo x30, Flashlight"

    spec = expand_npc_specs([{"entry": "test ganger", "name": "Rust", "hp": 12, "stats": {"REF": 7}}], path)[0]
    sheet = build_npc_combatant(spec)
    assert (sheet["name"], sheet["hp"], sheet["max_hp"], sheet["stats"]["REF"], sheet["stats"]["DEX"]) == ("Rust", 12, 30, 7, 5)
    assert sheet["detail"]["equipped_weapon"] == "Very Heavy Pistol" and sheet["inventory"]["ammo:VH Pistol"] == 30
    with pytest.raises(ValueError, match="Unknown NPC stat block"):
        expand_npc_specs([{"entry": "Nobody"}], path)
