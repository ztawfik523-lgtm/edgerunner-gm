"""Tests for canonical Cyberpunk RED Corebook GM Data and Catalogs."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import corebook_gm_data as cgd
import creation_catalog as cc
import economy
import library


def test_corebook_net_catalog_completeness():
    catalog = cgd.build_corebook_net_catalog()
    assert len(catalog) >= 44

    by_name = {item["name"]: item for item in catalog}

    # Booster Programs
    for prog in ["Eraser", "See Ya", "Speedygonzalez", "Worm"]:
        assert prog in by_name
        assert by_name[prog]["category"] == "program"
        assert by_name[prog]["stats"]["class"] == "Booster"
        assert by_name[prog]["stats"]["rez"] == 7

    # Defender Programs
    for prog in ["Armor", "Flak", "Shield"]:
        assert prog in by_name
        assert by_name[prog]["category"] == "program"
        assert by_name[prog]["stats"]["class"] == "Defender"
        assert by_name[prog]["stats"]["rez"] == 7

    # Attackers
    for prog in ["Banhammer", "Sword", "DeckKRASH", "Hellbolt", "Nervescrub", "Poison Flatline", "Superglue", "Vrizzbolt"]:
        assert prog in by_name
        assert by_name[prog]["category"] == "program"

    # All 9 Corebook Anti-Personnel Black ICE + 3 Anti-Program Black ICE
    ice_names = ["Asp", "Giant", "Hellhound", "Kraken", "Liche", "Raven", "Scorpion", "Skunk", "Wisp", "Dragon", "Killer", "Sabertooth"]
    for ice in ice_names:
        assert ice in by_name
        assert by_name[ice]["category"] == "program"
        assert "Black ICE" in by_name[ice]["stats"]["class"]
        assert by_name[ice]["stats"]["rez"] > 0
        assert by_name[ice]["stats"]["slots"] == 2

    # All 3 Demons
    demons = {
        "Imp": {"rez": 15, "interface": 3, "net_actions": 2, "cost_eb": 1000},
        "Efreet": {"rez": 25, "interface": 4, "net_actions": 3, "cost_eb": 5000},
        "Balron": {"rez": 30, "interface": 7, "net_actions": 4, "cost_eb": 10000},
    }
    for dname, expected in demons.items():
        assert dname in by_name
        dem = by_name[dname]
        assert dem["category"] == "program"
        assert dem["stats"]["class"] == "Demon"
        assert dem["stats"]["rez"] == expected["rez"]
        assert dem["stats"]["interface"] == expected["interface"]
        assert dem["stats"]["net_actions"] == expected["net_actions"]
        assert dem["stats"]["combat_number"] == 14
        assert dem["stats"]["cost_eb"] == expected["cost_eb"]

    # Hardware & Emplaced Defenses
    hw_names = ["Backup Drive", "Hardened Circuitry", "Insulated Wiring", "KRASH Barrier", "Range Upgrade", "DNA Lock", "Automated Turret", "Laser Grid", "Mines", "Poison Gas Trap", "Electrified Floor", "Control Node", "File", "Password"]
    for hw in hw_names:
        assert hw in by_name
        assert by_name[hw]["category"] == "hardware"
        assert by_name[hw]["stats"]["cost_eb"] > 0


def test_corebook_cyberware_additions():
    cw = cgd.build_corebook_cyberware_additions()
    assert len(cw) >= 98

    by_name = {item["name"]: item for item in cw}

    # Fashionware
    fashionware = ["Biomonitor", "Chemskin", "EMP Threading", "Light Tattoo", "Shift Tacts", "Skinwatch", "Techhair"]
    for item_name in fashionware:
        assert item_name in by_name
        item = by_name[item_name]
        assert item["category"] == "cyberware"
        assert item["stats"]["install"] == "Mall"
        assert item["stats"]["humanity_loss"] == "0"
        assert item["stats"]["hl"] == 0
        assert item["stats"]["cost_eb"] in (10, 100)

    # Core items with exact HL & install checks
    assert by_name["Kerenzikov"]["stats"]["cost_eb"] == 500
    assert by_name["Kerenzikov"]["stats"]["hl"] == 14
    assert by_name["Kerenzikov"]["stats"]["install"] == "Clinic"

    assert by_name["Pain Editor"]["stats"]["cost_eb"] == 1000
    assert by_name["Pain Editor"]["stats"]["hl"] == 14
    assert by_name["Pain Editor"]["stats"]["install"] == "N/A"

    assert by_name["Skill Chip"]["stats"]["cost_eb"] == 500
    assert by_name["Skill Chip"]["stats"]["hl"] == 7
    assert by_name["Skill Chip"]["stats"]["install"] == "N/A"

    assert by_name["Sandevistan"]["stats"]["cost_eb"] == 500
    assert by_name["Sandevistan"]["stats"]["hl"] == 7
    assert by_name["Sandevistan"]["stats"]["install"] == "Clinic"

    assert by_name["Subdermal Armor"]["stats"]["cost_eb"] == 1000
    assert by_name["Subdermal Armor"]["stats"]["hl"] == 14
    assert by_name["Subdermal Armor"]["stats"]["install"] == "Hospital"

    # Schema integrity across all cyberware items
    for item in cw:
        assert item["id"].startswith("corebook-cw-")
        assert item["category"] == "cyberware"
        assert isinstance(item["printed_page"], int)
        assert isinstance(item["stats"]["cost_eb"], int)
        assert isinstance(item["stats"]["hl"], int)
        assert item["stats"]["install"] in ("Mall", "Clinic", "Hospital", "N/A")
        assert item["stats"]["slots_required"] in (1, 2, 3)


def test_corebook_ammo_attachments_exotics():
    items = cgd.build_corebook_ammo_attachments_exotics()
    assert len(items) >= 35

    by_cat = {}
    for item in items:
        by_cat.setdefault(item["category"], []).append(item)

    assert len(by_cat["ammo"]) == 13
    assert len(by_cat["attachment"]) == 8
    assert len(by_cat["weapon"]) == 14

    # Ammo checks
    ammo_by_name = {a["name"]: a for a in by_cat["ammo"]}
    assert ammo_by_name["Basic Ammunition"]["stats"]["cost_eb"] == 10
    assert ammo_by_name["Armor-Piercing Ammunition"]["stats"]["cost_eb"] == 100
    assert ammo_by_name["Armor-Piercing Ammunition"]["stats"]["ablation"] == 2
    assert ammo_by_name["Biotoxin Ammunition"]["stats"]["cost_eb"] == 500
    assert ammo_by_name["Biotoxin Ammunition"]["stats"]["resist_dv"] == 15
    assert ammo_by_name["Rubber Ammunition"]["stats"]["lethal"] is False

    # Attachments checks (must not be concealable)
    for att in by_cat["attachment"]:
        assert att["stats"]["concealable"] is False
        assert att["stats"]["cost_eb"] in (100, 500)

    # Exotics checks
    weap_by_name = {w["name"]: w for w in by_cat["weapon"]}
    assert "Malorian Arms 3516" in weap_by_name
    assert weap_by_name["Malorian Arms 3516"]["stats"]["cost_eb"] == 10000
    assert weap_by_name["Malorian Arms 3516"]["stats"]["body_req"] == 11
    assert weap_by_name["Kendachi Mono-Three"]["stats"]["cost_eb"] == 5000
    assert weap_by_name["Constitution Arms Hurricane Assault Weapon"]["stats"]["cost_eb"] == 5000


def test_corebook_services_housing_fashion():
    items = cgd.build_corebook_services_housing_fashion()
    assert len(items) >= 119

    by_cat = {}
    for item in items:
        by_cat.setdefault(item["category"], []).append(item)

    assert len(by_cat["service"]) == 19
    assert len(by_cat["housing"]) == 10
    assert len(by_cat["fashion"]) == 90

    # Services
    srv_by_name = {s["name"]: s for s in by_cat["service"]}
    assert srv_by_name["Trauma Team Silver"]["stats"]["cost_eb"] == 500
    assert srv_by_name["Trauma Team Executive"]["stats"]["cost_eb"] == 1000
    assert srv_by_name["Standard Humanity Loss Therapy"]["stats"]["cost_eb"] == 500
    assert srv_by_name["Extreme Humanity Loss Therapy"]["stats"]["cost_eb"] == 1000
    assert srv_by_name["Lifestyle: Kibble"]["stats"]["cost_eb"] == 100
    assert srv_by_name["Lifestyle: Generic Prepak"]["stats"]["cost_eb"] == 300
    assert srv_by_name["Lifestyle: Good Prepak"]["stats"]["cost_eb"] == 600
    assert srv_by_name["Lifestyle: Fresh Food"]["stats"]["cost_eb"] == 1500

    # Housing (10 tiers)
    house_by_name = {h["name"]: h for h in by_cat["housing"]}
    assert house_by_name["Living on the Street"]["stats"]["cost_eb"] == 0
    assert house_by_name["Cube Hotel"]["stats"]["cost_eb"] == 500
    assert house_by_name["Cargo Container"]["stats"]["rent_eb_mo"] == 1000
    assert house_by_name["Cargo Container"]["stats"]["buy_eb"] == 15000
    assert house_by_name["Studio Apartment"]["stats"]["rent_eb_mo"] == 1500
    assert house_by_name["Studio Apartment"]["stats"]["buy_eb"] == 25000
    assert house_by_name["Two-Bedroom Apartment"]["stats"]["rent_eb_mo"] == 2500
    assert house_by_name["Two-Bedroom Apartment"]["stats"]["buy_eb"] == 35000
    assert house_by_name["Upscale Conapt"]["stats"]["rent_eb_mo"] == 7500
    assert house_by_name["Upscale Conapt"]["stats"]["buy_eb"] == 85000
    assert house_by_name["Luxury Penthouse"]["stats"]["rent_eb_mo"] == 15000
    assert house_by_name["Luxury Penthouse"]["stats"]["buy_eb"] == 500000
    assert house_by_name["Corporate Beaverville House"]["stats"]["buy_eb"] == 200000
    assert house_by_name["Corporate Beaverville McMansion"]["stats"]["buy_eb"] == 500000

    # Fashion (10 styles x 9 garments = 90)
    assert len(by_cat["fashion"]) == 90
    for f in by_cat["fashion"]:
        assert f["stats"]["cost_eb"] in (10, 20, 50, 100, 500, 1000, 5000, 50000)


def test_corebook_mooks_and_encounters():
    assert cgd.build_corebook_mooks_and_encounters() == []
    assert cgd.build_corebook_opponents() == []
    assert cgd.build_corebook_encounters() == []
    assert cc.build_corebook_locations() == []
    assert cc.build_corebook_factions() == []

    presets = cc.build_campaign_presets()
    assert len(presets["zone_types"]) >= 7
    assert len(presets["threat_ratings"]) >= 5
    assert len(presets["screamsheets"]) >= 5


def test_corebook_rules_reference():
    rules = cgd.build_corebook_rules_reference()
    assert len(rules) == 9

    by_id = {r["id"]: r for r in rules}
    assert "corebook-rule-dv-scale" in by_id
    assert "corebook-rule-negative-modifiers" in by_id
    assert "corebook-rule-facedowns-reputation" in by_id
    assert "corebook-rule-cover-hp" in by_id
    assert "corebook-rule-martial-arts-moves" in by_id
    assert "corebook-rule-critical-injuries" in by_id
    assert "corebook-rule-repair-table" in by_id
    assert "corebook-rule-beat-chart-63" in by_id
    assert "corebook-rule-playstyle-ip-table" in by_id


def test_role_hustles_60_and_economy_integration():
    hustles = cgd.ROLE_HUSTLES_60
    assert len(hustles) == 10
    expected_roles = {"Rockerboy", "Solo", "Netrunner", "Tech", "Medtech", "Media", "Lawman", "Exec", "Fixer", "Nomad"}
    assert set(hustles.keys()) == expected_roles

    for role, rows in hustles.items():
        assert len(rows) == 6
        for idx, row in enumerate(rows, 1):
            assert row["roll"] == idx
            assert len(row["label"]) > 0
            assert row["low_eb"] in (0, 100, 200, 300)
            assert row["typical_eb"] in (100, 200, 300, 500)
            assert row["high_eb"] in (300, 500, 600, 800)

    # Economy.py integration check
    char = {"money": 500, "detail": {"roles": [{"role": "Rockerboy", "rank": 4}]}}
    out = economy.apply_action(char, "hustle", {"role": "Rockerboy", "free_days": 7}, randbelow=lambda n: 0)
    assert out["result"]["earned"] == 200
    assert out["result"]["label"] == "Played an underground club set for door cash."
    assert out["character"]["money"] == 700


def test_exported_canonical_constants():
    # Martial Arts Moves
    ma = cgd.MARTIAL_ARTS_MOVES
    assert set(ma.keys()) == {"Aikido", "Karate", "Judo", "Taekwondo"}
    for style, moves in ma.items():
        assert len(moves) == 2

    # DV Table
    dv = cgd.DV_TABLE
    assert dv == {"Simple": 9, "Everyday": 13, "Difficult": 15, "Professional": 17, "Heroic": 21, "Incredible": 24, "Legendary": 29}

    # Repair Table
    rep = cgd.REPAIR_TABLE
    assert "vehicles" in rep
    assert "items" in rep
    assert rep["vehicles"]["Minor Damage"]["dv"] == 9
    assert rep["items"]["Cheap / Everyday (<=20eb)"]["dv"] == 9

    # Critical Injuries Table
    crit = cgd.CRITICAL_INJURIES_TABLE
    assert crit["bonus_damage"] == 5
    assert len(crit["body"]) == 11
    assert len(crit["head"]) == 11
    assert crit["body"][0]["roll"] == 2
    assert crit["body"][-1]["roll"] == 12

    # Beat Chart (63 unique beats)
    beats = cgd.BEAT_CHART_63
    assert set(beats.keys()) == {"Hook", "Cliffhanger", "Development", "Climax", "Resolution"}
    assert len(beats["Hook"]) == 10
    assert len(beats["Cliffhanger"]) == 13
    assert len(beats["Development"]) == 29
    assert len(beats["Climax"]) == 3
    assert len(beats["Resolution"]) == 9
    unique_beats = set(b for b_list in beats.values() for b in b_list)
    assert len(unique_beats) == 63

    # Playstyle IP Table
    ip_table = cgd.PLAYSTYLE_IP_TABLE
    assert len(ip_table) == 8
    assert [row["ip"] for row in ip_table] == [10, 20, 30, 40, 50, 60, 70, 80]
    for row in ip_table:
        for col in ["Group", "Warrior", "Socializer", "Explorer", "Roleplayer"]:
            assert col in row and len(row[col]) > 0


def test_creation_catalog_reexports():
    assert hasattr(cc, "build_corebook_net_catalog")
    assert hasattr(cc, "build_corebook_cyberware_additions")
    assert hasattr(cc, "build_corebook_ammo_attachments_exotics")
    assert hasattr(cc, "build_corebook_services_housing_fashion")
    assert hasattr(cc, "build_corebook_mooks_and_encounters")
    assert hasattr(cc, "build_corebook_opponents")
    assert hasattr(cc, "build_corebook_encounters")
    assert hasattr(cc, "build_corebook_rules_reference")
    assert hasattr(cc, "ROLE_HUSTLES_60")
    assert hasattr(cc, "MARTIAL_ARTS_MOVES")
    assert hasattr(cc, "DV_TABLE")
    assert hasattr(cc, "REPAIR_TABLE")
    assert hasattr(cc, "CRITICAL_INJURIES_TABLE")
    assert hasattr(cc, "BEAT_CHART_63")
    assert hasattr(cc, "PLAYSTYLE_IP_TABLE")
