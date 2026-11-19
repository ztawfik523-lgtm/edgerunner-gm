"""Tests for BYOC-driven catalogs, stripped Corebook lore, and mechanical schemas."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import corebook_gm_data as cgd
import creation_catalog as cc
import creation_reference as cr
import economy
import library


def _build_synthetic_rules_db(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
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
        conn.execute("INSERT INTO metadata VALUES ('source_sha256', 'synthetic-digest')")
        skill_txt = "82\nHandgun........REF\nBasic ranged pistol skill."
        role_txt = "144\nRockerboy\nRole Ability: Charismatic Impact\nKey STATs: COOL, EMP, DEX\nPerformer and rebel."
        shop_txt = "340\nGear & Market\nSynthetic equipment tables."
        conn.execute("INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES (82, 82, 'Skills', ?, ?)", (skill_txt, len(skill_txt)))
        conn.execute("INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES (144, 144, 'Rockerboy', ?, ?)", (role_txt, len(role_txt)))
        conn.execute("INSERT INTO pages(pdf_page, printed_page, header, text, chars) VALUES (340, 340, 'Market', ?, ?)", (shop_txt, len(shop_txt)))
        conn.execute("INSERT INTO source_sections VALUES ('rockerboy-144', 'Rockerboy', 144, 144, 144)")

        tables = [
            (340, 1, [["Program", "Class", "ATK", "DEF", "REZ", "Cost"], ["Sword", "Attacker", "1", "0", "0", "50eb"]]),
            (340, 2, [["Cyberware Name", "Install", "HL", "Cost"], ["Kerenzikov", "Clinic", "14", "500eb"]]),
            (340, 3, [["Ammo", "Cost", "Ablation"], ["Armor-Piercing Ammunition", "100eb", "2"]]),
            (340, 4, [["Attachment", "Cost"], ["Sniping Scope", "500eb"]]),
            (340, 5, [["Weapon Type", "Skill", "Damage", "ROF", "Cost"], ["Heavy Pistol", "Handgun", "3d6", "2", "100eb"]]),
            (340, 6, [["Armor Type", "SP", "Cost"], ["Light Armorjack", "11", "100eb"]]),
            (340, 7, [["Hardware", "Cost"], ["Backup Drive", "100eb"]]),
            (340, 8, [["Vehicle", "Cost", "SDP", "Seats"], ["Compact Groundcar", "30000eb", "50", "4"]]),
            (340, 9, [["Drug", "Cost", "Primary Effect"], ["Synthcoke", "20eb", "+1 REF"]]),
            (340, 10, [["Service", "Cost"], ["Lifestyle: Kibble", "100eb"], ["Trauma Team Silver", "500eb"]]),
            (340, 11, [["Housing", "Rent (eb/mo)", "Buy (eb)"], ["Cargo Container", "1000", "15000eb"]]),
            (340, 12, [["Name", "Style", "Garment", "Cost"], ["Generic Chic Jacket", "Generic Chic", "Jacket", "50eb"]]),
        ]
        for pg, ordinal, rows in tables:
            conn.execute("INSERT INTO source_tables VALUES (?, ?, 'null', ?)", (pg, ordinal, json.dumps(rows)))
        library.build_library(conn)
        conn.commit()
    return path


def test_hardcoded_corebook_prose_and_lore_stripped():
    assert cgd.build_corebook_net_catalog() == []
    assert cgd.build_corebook_cyberware_additions() == []
    assert cgd.build_corebook_ammo_attachments_exotics() == []
    assert cgd.build_corebook_services_housing_fashion() == []
    assert cgd.build_corebook_mooks_and_encounters() == []
    assert cgd.build_corebook_opponents() == []
    assert cgd.build_corebook_encounters() == []
    assert cgd.build_corebook_rules_reference() == []

    assert cc.build_corebook_weapons() == []
    assert cc.build_corebook_armor() == []
    assert cc.build_corebook_hardware() == []
    assert cc.build_corebook_vehicles() == []
    assert cc.build_corebook_drugs() == []
    assert cc.build_corebook_gear() == []
    assert cc.build_corebook_roles() == []
    assert cc.build_corebook_locations() == []
    assert cc.build_corebook_factions() == []
    assert cc.build_corebook_rules_highlights() == []
    assert cc.build_library_corebook_entries("digest") == []

    presets = cc.build_campaign_presets()
    assert presets["districts"] == []
    assert presets["factions"] == []
    assert presets["caper_styles"] == []
    assert presets["screamsheets"] == []

    for method in cr.CREATION_METHODS:
        assert "Corebook pp." not in method["rules"]
        assert "pp." not in method["rules"]


def test_synthetic_rules_db_populates_catalog_builders(tmp_path: Path):
    rules_db = _build_synthetic_rules_db(tmp_path / "rules.sqlite")

    net = cgd.build_corebook_net_catalog(rules_db)
    assert any(x["name"] == "Sword" and x["category"] == "program" for x in net)
    assert any(x["name"] == "Backup Drive" and x["category"] == "hardware" for x in net)

    cw = cgd.build_corebook_cyberware_additions(rules_db)
    assert len(cw) == 1 and cw[0]["name"] == "Kerenzikov"
    assert cw[0]["stats"]["hl"] == 14

    ammo_att = cgd.build_corebook_ammo_attachments_exotics(rules_db)
    assert any(x["name"] == "Armor-Piercing Ammunition" and x["category"] == "ammo" for x in ammo_att)
    assert any(x["name"] == "Sniping Scope" and x["category"] == "attachment" for x in ammo_att)

    shf = cgd.build_corebook_services_housing_fashion(rules_db)
    assert any(x["name"] == "Cargo Container" and x["category"] == "housing" for x in shf)
    assert any(x["name"] == "Generic Chic Jacket" and x["category"] == "fashion" for x in shf)

    assert cc.build_corebook_vehicles(rules_db)[0]["name"] == "Compact Groundcar"
    assert cc.build_corebook_drugs(rules_db)[0]["name"] == "Synthcoke"
    assert cc.build_corebook_roles(rules_db)[0]["name"] == "Rockerboy"


def test_role_hustles_60_and_economy_integration():
    hustles = cgd.ROLE_HUSTLES_60
    assert len(hustles) == 10
    expected_roles = {"Rockerboy", "Solo", "Netrunner", "Tech", "Medtech", "Media", "Lawman", "Exec", "Fixer", "Nomad"}
    assert set(hustles.keys()) == expected_roles

    for _role, rows in hustles.items():
        assert len(rows) == 6
        for idx, row in enumerate(rows, 1):
            assert row["roll"] == idx
            assert row["label"] == ""
            assert row["low_eb"] in (0, 100, 200, 300)
            assert row["typical_eb"] in (100, 200, 300, 500)
            assert row["high_eb"] in (300, 500, 600, 800)

    char = {"money": 500, "detail": {"roles": [{"role": "Rockerboy", "rank": 4}]}}
    out = economy.apply_action(char, "hustle", {"role": "Rockerboy", "free_days": 7}, randbelow=lambda n: 0)
    assert out["result"]["earned"] == 200
    assert out["result"]["label"] == ""
    assert out["character"]["money"] == 700


def test_exported_canonical_constants():
    assert cgd.DV_TABLE == {"Simple": 9, "Everyday": 13, "Difficult": 15, "Professional": 17, "Heroic": 21, "Incredible": 24, "Legendary": 29}
    assert cgd.REPAIR_TABLE["vehicles"]["Minor Damage"]["dv"] == 9
    assert cgd.REPAIR_TABLE["items"]["Cheap / Everyday (<=20eb)"]["dv"] == 9
    assert cgd.CRITICAL_INJURIES_TABLE["bonus_damage"] == 5
    assert set(cgd.BEAT_CHART_63.keys()) == {"Hook", "Cliffhanger", "Development", "Climax", "Resolution"}
    assert [row["ip"] for row in cgd.PLAYSTYLE_IP_TABLE] == [10, 20, 30, 40, 50, 60, 70, 80]


def test_creation_catalog_reexports():
    for attr in (
        "build_corebook_net_catalog",
        "build_corebook_cyberware_additions",
        "build_corebook_ammo_attachments_exotics",
        "build_corebook_services_housing_fashion",
        "build_corebook_mooks_and_encounters",
        "build_corebook_opponents",
        "build_corebook_encounters",
        "build_corebook_rules_reference",
        "ROLE_HUSTLES_60",
        "MARTIAL_ARTS_MOVES",
        "DV_TABLE",
        "REPAIR_TABLE",
        "CRITICAL_INJURIES_TABLE",
        "BEAT_CHART_63",
        "PLAYSTYLE_IP_TABLE",
    ):
        assert hasattr(cc, attr)
