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


def _create_rules_db(path: Path, *, materialize: bool = True) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY,
                pdf_page INTEGER NOT NULL UNIQUE,
                printed_page INTEGER,
                header TEXT NOT NULL,
                text TEXT NOT NULL,
                chars INTEGER NOT NULL
            );
            CREATE TABLE source_sections (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                start_pdf INTEGER NOT NULL,
                end_pdf INTEGER NOT NULL,
                printed_start INTEGER
            );
            CREATE TABLE source_tables (
                pdf_page INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                bbox_json TEXT,
                cells_json TEXT NOT NULL,
                PRIMARY KEY(pdf_page, ordinal)
            );
            """
        )
        conn.execute("INSERT INTO metadata VALUES ('source_sha256', 'deadbeef1234')")
        skill_page_text = "\n".join(
            [
                "82",
                "Handgun ......................... REF",
                "Skill for accurately firing one-handed ranged weapons like pistols.",
                "Covers semi-auto pistols and revolvers in Night City firefights.",
                "Martial Arts (x2) ............... DEX",
                "Specialized close-quarters fighting styles such as Karate or Aikido.",
                "Requires x2 Improvement Points to advance.",
                "Interface ....................... INT",
                "Netrunner Role Ability skill; actually wait listed for test layout.",
            ]
        )
        weapon_page_text = "340\nRanged Weapons\nStandard firearms sold across Night City."
        cyber_page_text = "360\nCyberware\nNeural and optical implants."
        role_page_text = "142\nSolo\nCombat Sense specialists who rule the street."
        pages = [
            (82, 82, "Skills", skill_page_text, len(skill_page_text)),
            (142, 142, "Roles: Solo", role_page_text, len(role_page_text)),
            (340, 340, "Ranged Weapons", weapon_page_text, len(weapon_page_text)),
            (360, 360, "Cyberware", cyber_page_text, len(cyber_page_text)),
        ]
        for pdf_p, printed_p, header, txt, chars in pages:
            conn.execute(
                "INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES (?,?,?,?,?)",
                (pdf_p, printed_p, header, txt, chars),
            )
        conn.execute("INSERT INTO source_sections VALUES ('solo-142', 'Solo', 142, 143, 142)")
        conn.execute("INSERT INTO source_sections VALUES ('friday-night-firefight-168', 'Friday Night Firefight', 340, 340, 340)")

        weapon_table = [
            ["Weapon Type", "Skill", "Damage", "Magazine", "ROF", "Hands", "Concealable", "Cost"],
            ["Heavy Pistol", "Handgun", "3d6", "8", "2", "1", "Yes", "100eb"],
            ["Assault Rifle", "Shoulder Arms", "5d6", "25", "1", "2", "No", "500eb"],
        ]
        armor_table = [
            ["Armor Type", "SP", "Armor Penalty", "Cost"],
            ["Light Armorjack", "11", "0", "100eb"],
        ]
        cyber_table = [
            ["Cyberware Name", "Install", "HL", "Description", "Cost"],
            ["Kerenzikov", "Clinic", "14", "Neural speedware adding +2 to Initiative.", "500eb"],
        ]
        conn.execute(
            "INSERT INTO source_tables VALUES (340, 1, 'null', ?)",
            (json.dumps(weapon_table),),
        )
        conn.execute(
            "INSERT INTO source_tables VALUES (340, 2, 'null', ?)",
            (json.dumps(armor_table),),
        )
        conn.execute(
            "INSERT INTO source_tables VALUES (360, 1, 'null', ?)",
            (json.dumps(cyber_table),),
        )
        if materialize:
            library.build_library(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _setup_campaign(tmp_path: Path, rules_db: Path):
    camp_db = tmp_path / "campaign.sqlite"
    svc = GameplayService(camp_db, rules_db)
    camp = svc.execute("create_campaign", {"name": "Watson Run", "operation_id": "op-c1"})["result"]
    return camp_db, svc, camp["id"]


def test_corebook_library_skills_items_and_roles(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)

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
    assert ker["stats"]["humanity_loss"] == 14
    assert ker["stats"]["install"] == "Clinic"
    assert "+2 to Initiative" in ker["description"]

    solo = library.search_library(rules_db, q="Solo", category="role")[0]
    assert solo["category"] == "role"
    assert solo["section_id"] == "solo-142"


def test_unmaterialized_cache_and_one_time_materialize(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules_lazy.sqlite", materialize=False)
    library._MEMORY_CACHE.clear()

    first = library.search_library(rules_db, q="Heavy Pistol")
    assert first[0]["name"] == "Heavy Pistol"
    assert len(library._MEMORY_CACHE) == 1
    second = library.search_library(rules_db, q="Kerenzikov")
    assert second[0]["name"] == "Kerenzikov"
    assert len(library._MEMORY_CACHE) == 1  # cached by file stat + sha

    info = library.materialize_library(rules_db)
    assert info["entries"] >= 7
    conn = sqlite3.connect(rules_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM rule_entries").fetchone()[0]
    finally:
        conn.close()
    assert count == info["entries"]


def test_campaign_homebrew_validation_and_search(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
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
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
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

    rules_db = _create_rules_db(tmp_path / "rules_dup.sqlite", materialize=True)
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
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
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


def test_corebook_curated_catalogs_indexed_for_ai_search(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=False)
    library._MEMORY_CACHE.clear()

    mal = library.search_library(rules_db, q="Malorian Arms 3516", category="weapon")
    assert mal and mal[0]["name"] == "Malorian Arms 3516"

    lace = library.search_library(rules_db, q="Black Lace", category="drug")
    assert any("Black Lace" in x["name"] for x in lace)

    bike = library.search_library(rules_db, q="Superbike", category="vehicle")
    assert any(x["name"] == "Superbike" for x in bike)

    net = library.search_library(rules_db, q="Netrunner", category="role")
    assert net and net[0]["name"] == "Netrunner"


def test_upsert_preserves_existing_fields_and_library_events_idempotency(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
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

    rules_db = _create_rules_db(tmp_path / "rules.sqlite", materialize=True)
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



