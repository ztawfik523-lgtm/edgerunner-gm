import sqlite3

import pytest

from creation import ROLES, STATS, build_character


@pytest.fixture
def rules(tmp_path):
    path = tmp_path / "rules.sqlite"
    values = [
        (1, 6, 7, 7, 3, 8, 6, 5, 5, 6, 5),
        (2, 7, 8, 6, 3, 6, 6, 7, 5, 6, 6),
        (3, 5, 8, 7, 4, 7, 7, 6, 7, 8, 5),
        (4, 5, 8, 6, 4, 6, 7, 6, 5, 7, 6),
        (5, 6, 6, 7, 5, 7, 6, 7, 6, 8, 4),
        (6, 7, 7, 6, 5, 7, 6, 6, 7, 7, 5),
        (7, 7, 7, 6, 5, 6, 7, 7, 6, 6, 6),
        (8, 7, 8, 7, 5, 6, 6, 5, 6, 8, 4),
        (9, 7, 7, 6, 4, 6, 6, 6, 5, 6, 5),
        (10, 6, 6, 8, 5, 6, 6, 5, 6, 6, 5),
    ]
    text = "▶Solo\nRoll\nINT\nREF\nDEX\nTECH\nCOOL\nWILL\nLUCK\nMOVE\nBODY\nEMP\n" + "\n".join(str(n) for row in values for n in row)
    skills = "| Media |  | Lawman |  | Exec |  | Fixer |  | Nomad |  | Rockerboy |  | Solo |  | Netrunner |  | Tech |  | Medtech |\n"
    skills += "| Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl |\n"
    skills += "\n".join(f"| Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 |" for i in range(20))
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    definitions = "\n".join(f"{name}........INT" for name in basics + [f"Skill {i}" + (" (x2)" if i == 0 else "") for i in range(20)])
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        db.execute("INSERT INTO metadata VALUES('source_sha256','test-digest')")
        db.execute("CREATE TABLE pages(pdf_page INTEGER, printed_page INTEGER, text TEXT)")
        db.execute("INSERT INTO pages VALUES(74, 73, ?)", (text + "\n" + skills,))
        db.execute("INSERT INTO pages VALUES(83, 82, ?)", (definitions,))
    return path


def test_streetrat_uses_source_template_and_records_one_roll(rules):
    result = build_character({"name": "Test", "role": "Solo", "method": "streetrat", "lifepath": {}}, rules, lambda n: 0)
    assert result["stats"] == dict(zip(STATS, [6, 7, 7, 3, 8, 6, 5, 5, 6, 5]))
    assert result["detail"]["creation"]["dice"] == [1]
    assert result["detail"]["creation"]["status"] == "draft"
    assert result["hp"] == 40
    assert result["inventory"] == {} and result["revision"] == 1


def test_edgerunner_rolls_per_stat_column(rules):
    seq = iter(range(10))
    result = build_character({"name": "Test", "role": "Solo", "method": "edgerunner", "skills": {f"Skill {i}": (5 if 1 <= i < 3 else 4) for i in range(20)}, "lifepath": {}}, rules, lambda n: next(seq))
    assert result["detail"]["creation"]["dice"] == list(range(1, 11))
    assert result["stats"] == dict(zip(STATS, [6, 8, 7, 4, 7, 6, 7, 6, 6, 5]))


def test_complete_package_validates_stat_budget_and_keeps_draft(rules):
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    skills = dict.fromkeys(basics, 2)
    skills.update({f"Skill {i}": 5 for i in range(1, 13)})
    stats = dict(zip(STATS, [8, 8, 6, 6, 6, 6, 6, 5, 5, 6]))
    result = build_character({"name": "Test", "role": "Solo", "method": "complete_package", "stats": stats, "skills": skills, "lifepath": {}}, rules)
    assert result["money"] == 2550
    assert result["detail"]["creation"]["status"] == "draft"
    assert result["detail"]["creation"]["dice"] == []


@pytest.mark.parametrize("args", [
    {"name": "Test", "role": "Solo", "method": "streetrat"},
    {"name": "Test", "role": "unknown", "method": "streetrat", "lifepath": {}},
    {"name": "Test", "role": "Solo", "method": "complete_package", "stats": dict.fromkeys(STATS, 6), "skills": {}, "lifepath": {}},
])
def test_rejects_invalid_input(rules, args):
    with pytest.raises(ValueError):
        build_character(args, rules)


def test_role_list_is_fixed_and_rng_is_checked(rules):
    assert len(ROLES) == 10
    with pytest.raises(ValueError, match="randbelow"):
        build_character({"name": "Test", "role": "Solo", "method": "streetrat", "lifepath": {}}, rules, lambda n: 10)


def test_rejects_unknown_paid_skill(rules):
    with pytest.raises(ValueError, match="Unknown skill"):
        build_character({"name": "Test", "role": "Solo", "method": "complete_package",
                         "stats": dict(zip(STATS, [8, 8, 6, 6, 6, 6, 6, 5, 5, 6])),
                         "skills": {"Not a source skill": 2}, "lifepath": {}}, rules)


def test_starting_gear_cyberware_hl_backstory_and_template_rolls(rules):
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    skills = dict.fromkeys(basics, 2)
    skills.update({f"Skill {i}": 5 for i in range(1, 13)})
    stats = dict(zip(STATS, [8, 8, 6, 6, 6, 6, 6, 5, 5, 6]))
    result = build_character(
        {
            "name": "Chrome Vee",
            "role": "Solo",
            "method": "complete_package",
            "stats": stats,
            "skills": skills,
            "lifepath": {"cultural_region": "North American"},
            "backstory": {
                "concept": "Watson street merc",
                "summary": "Walked away from Arasaka security.",
                "established_history": "Owes Ripperdoc Viktor 300 eb.",
            },
            "starting_gear": {
                "inventory": {"Very Heavy Pistol": 1, "Agent": 1},
                "cyberware": [{"name": "Neural Link", "hl": 7, "cost_eb": 500}],
                "equipped_weapon": "Very Heavy Pistol",
                "equipped_armor": {"name": "Light Armorjack", "sp": 11},
                "fashion": [{"name": "Bag Lady Chic Jacket", "cost_eb": 100}],
                "money_spent_eb": 700,
            },
        },
        rules,
    )
    assert result["money"] == 1850
    assert result["humanity"] == 53
    assert result["inventory"] == {"Very Heavy Pistol": 1, "Agent": 1}
    assert result["detail"]["creation"]["status"] == "validated"
    assert result["detail"]["creation"]["starting_humanity_loss"] == 7
    assert result["detail"]["equipped_weapon"] == "Very Heavy Pistol"
    assert result["detail"]["equipped_armor"]["sp"] == 11
    assert result["detail"]["backstory"]["established_history"] == "Owes Ripperdoc Viktor 300 eb."

    edgerunner = build_character(
        {
            "name": "Roller",
            "role": "Solo",
            "method": "edgerunner",
            "template_rolls": [1] * 10,
            "skills": {f"Skill {i}": (5 if 1 <= i < 3 else 4) for i in range(20)},
            "lifepath": {},
            "starting_gear": {"inventory": {"Agent": 1}},
        },
        rules,
    )
    assert edgerunner["detail"]["creation"]["dice"] == [1] * 10
    assert edgerunner["detail"]["creation"]["status"] == "validated"


def test_exec_empty_separator_and_creation_reference(tmp_path):
    from creation_reference import build_creation_reference

    path = tmp_path / "exec_rules.sqlite"
    values = [
        (i + 1, 6, 7, 7, 3, 8, 6, 5, 5, 6, 5)
        for i in range(10)
    ]
    text = "▶Exec\nRoll\nINT\nREF\nDEX\nTECH\nCOOL\nWILL\nLUCK\nMOVE\nBODY\nEMP\n" + "\n".join(str(n) for row in values for n in row)
    # Mimics real PDF page 88 where Exec has a blank column between Skill and Lvl
    skills = "| Media |  | Lawman |  | Exec |  |  | Fixer |  | Nomad |  | Rockerboy |  | Solo |  | Netrunner |  | Tech |  | Medtech |\n"
    skills += "| Skill | Lvl | Skill | Lvl | Skill |  | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl |\n"
    exec_names = ["Accounting", "Bureaucracy", "Business"] + [f"Skill {i}" for i in range(3, 20)]
    for i in range(20):
        skills += (
            f"| Skill {i} | 4 | Skill {i} | 4 | {exec_names[i]} |  | 4 | "
            + " | ".join(f"Skill {i} | 4" for _ in range(7))
            + " |\n"
        )
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    defs = "\n".join(f"{name}........INT" for name in basics + exec_names)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        db.execute("INSERT INTO metadata VALUES('source_sha256','exec-digest')")
        db.execute("CREATE TABLE pages(pdf_page INTEGER, printed_page INTEGER, text TEXT)")
        db.execute("INSERT INTO pages VALUES(78, 77, ?)", (text,))
        db.execute("INSERT INTO pages VALUES(83, 82, ?)", (defs,))
        db.execute("INSERT INTO pages VALUES(88, 87, ?)", (skills,))

    ref = build_creation_reference(path)
    assert ref["rules_indexed"] is True
    assert len(ref["roles"]) == 10
    exec_role = next(r for r in ref["roles"] if r["name"] == "Exec")
    assert len(exec_role["templates"]) == 10
    assert exec_role["skills"]["Accounting"] == 4
    assert exec_role["skills"]["Bureaucracy"] == 4
    assert exec_role["skills"]["Business"] == 4
    assert len(exec_role["skills"]) == 20
    assert len(ref["stats"]) == 10
    assert len(ref["cultural_regions"]) >= 10
    assert len(ref["lifepath_tables"]) >= 5

    missing_ref = build_creation_reference(tmp_path / "does-not-exist.sqlite")
    assert missing_ref["rules_indexed"] is False
    assert len(missing_ref["roles"]) == 10
    assert any(item["name"] == "Malorian Arms 3516" for item in missing_ref["shop"]["weapon"])
    assert any(item["name"] == 'Militech "Ronin" (Assault Rifle)' for item in missing_ref["shop"]["weapon"])
    assert any(item["stats"].get("sp") == 18 and item["stats"].get("location") == "Body" for item in missing_ref["shop"]["armor"])
    assert any(item["name"] == "Heavy Armorjack Head Armor / Helmet (SP 13)" for item in missing_ref["shop"]["armor"])
    assert any("Cyberdeck" in item["name"] or "KRASH" in item["name"] for item in missing_ref["shop"]["hardware"])


def test_corebook_catalog_builders_and_parsers():
    from creation_catalog import (
        build_corebook_armor,
        build_corebook_hardware,
        build_corebook_weapons,
        parse_hl_int,
        parse_sp_int,
    )

    assert parse_hl_int("2 (1d6/2 Round up)") == 2
    assert parse_hl_int("7 (2d6)") == 7
    assert parse_hl_int(14) == 14
    assert parse_hl_int("N/A") == 0
    assert parse_sp_int("13") == 13
    assert parse_sp_int("SP 18") == 18

    weapons = build_corebook_weapons()
    names = {w["name"] for w in weapons}
    for exotic in (
        "Malorian Arms 3516",
        "Kendachi Mono-Three",
        "Tsunami Arms Helix",
        "Rhinemetall EMG-86 Railgun",
        "Battleglove (Exotic Cyberarm Gauntlet)",
        "Dartgun (Exotic)",
    ):
        assert exotic in names
    assert any("Poor" in str(w["stats"].get("quality")) for w in weapons)
    assert any("Standard" in str(w["stats"].get("quality")) for w in weapons)
    assert any("Excellent" in str(w["stats"].get("quality")) for w in weapons)
    assert any(w["stats"].get("subtype") == "Attachment" for w in weapons)
    assert any(w["stats"].get("subtype") == "Ammo" for w in weapons)

    armor = build_corebook_armor()
    assert any(a["name"] == "Kevlar® Body Armor (SP 7)" and a["stats"]["sp"] == 7 for a in armor)
    assert any(a["name"] == "Metalgear® Head Armor / Helmet (SP 18)" and a["stats"]["location"] == "Head" for a in armor)
    assert any(a["name"] == "Bulletproof Shield (10 HP)" and a["stats"]["location"] == "Shield" for a in armor)

    hardware = build_corebook_hardware()
    assert any("Cyberdeck" in h["name"] for h in hardware)
    assert any("KRASH" in h["name"] for h in hardware)


def test_medtech_creation_applies_initial_benefits_and_reference_includes_vehicles_drugs_presets(rules):
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    skills = dict.fromkeys(basics, 2)
    skills.update({f"Skill {i}": 5 for i in range(1, 13)})
    stats = dict(zip(STATS, [8, 8, 6, 6, 6, 6, 6, 5, 5, 6]))
    med = build_character(
        {
            "name": "Doc Kurosawa",
            "method": "complete_package",
            "role": "Medtech",
            "stats": stats,
            "skills": skills,
            "lifepath": {"cultural_origin": "East Asian"},
            "role_choices": {
                "medicine": {"Surgery": 2, "Pharmaceuticals": 1, "Cryosystem Operation": 1},
                "recipes": ["Speedheal"],
            },
            "starting_gear": {
                "inventory": {"Heavy Pistol": 1, "Light Armorjack": 1},
                "equipped_weapon": "Heavy Pistol",
            },
        },
        rules,
        lambda s: 0,
    )
    assert med["skills"]["Surgery"] == 4
    assert med["skills"]["Medical Tech"] == 2

    from creation_reference import build_creation_reference

    ref = build_creation_reference(rules)
    assert len(ref["shop"]["vehicle"]) >= 8
    assert len(ref["shop"]["drug"]) >= 10
    assert "districts" in ref["campaign_presets"]
    assert "caper_styles" in ref["campaign_presets"]


def test_creation_ai_assist_imports_search_pages(tmp_path):
    import asyncio
    import sqlite3
    from creation_catalog import generate_creation_ai_assist

    rules_db = tmp_path / "rules.sqlite"
    with sqlite3.connect(rules_db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS pages(pdf_page INTEGER PRIMARY KEY, printed_page INTEGER, text TEXT)")
        conn.commit()

    class _FakeLLM:
        async def complete(self, messages, **_kwargs):
            return '{"concept": "Netrunner from Kabuki"}'

    res = asyncio.run(
        generate_creation_ai_assist(
            rules_db,
            _FakeLLM(),
            {"target": "bio", "mode": "scratch", "character": {"role": "Netrunner"}},
        )
    )
    assert res["concept"] == "Netrunner from Kabuki"


def test_creation_ai_assist_per_field_and_creative_variety(tmp_path):
    import asyncio
    import json
    from creation_catalog import generate_creation_ai_assist

    seen_prompts: list[dict] = []

    class _InspectLLM:
        async def complete(self, messages, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            seen_prompts.append(payload)
            if payload.get("target_field") == "established_history":
                return json.dumps({"established_history": "Owes a Night Market stall owner 150 eb."})
            if payload.get("target_field") == "enemies":
                return json.dumps({"enemies": [{"who": "Fixer", "name": "Rafa", "wronged": "They wronged me", "cause": "Skimmed pay", "backup": "2 solo bodyguards", "revenge": "Expose his ledger"}]})
            if payload.get("target_field") == "beat_cliffhanger":
                return json.dumps({"beat_chart": {"cliffhanger": "The freight barge lifts off early."}})
            return json.dumps({"concept": "Rancho Coronado grease-monkey", "summary": "Fixes Nomad rigs."})

    # Per-field bio expand returns only that field
    r_bio = asyncio.run(
        generate_creation_ai_assist(
            None,
            _InspectLLM(),
            {
                "target": "bio",
                "mode": "expand",
                "field": "established_history",
                "character": {"role": "Tech"},
                "current": {"summary": "Grew up in Santo Domingo.", "established_history": "Owes 150 eb."},
            },
        )
    )
    assert r_bio["field"] == "established_history"
    assert "established_history" in r_bio
    assert "summary" not in r_bio
    assert list(seen_prompts[-1]["required_json_schema"].keys()) == ["established_history"]

    # Per-field contacts expand returns only enemies
    r_contacts = asyncio.run(
        generate_creation_ai_assist(
            None,
            _InspectLLM(),
            {
                "target": "contacts",
                "mode": "expand",
                "field": "enemies",
                "character": {"role": "Solo"},
                "current": {"enemies": [{"name": "Rafa", "who": "Fixer"}]},
            },
        )
    )
    assert r_contacts["field"] == "enemies"
    assert r_contacts["enemies"][0]["name"] == "Rafa"
    assert "friends" not in r_contacts

    # Per-field campaign beat expand returns only that beat
    r_beat = asyncio.run(
        generate_creation_ai_assist(
            None,
            _InspectLLM(),
            {
                "target": "campaign",
                "mode": "expand",
                "field": "beat_cliffhanger",
                "campaign": {"district": "Watson Development"},
                "current": {},
            },
        )
    )
    assert r_beat["beat_chart"] == {"cliffhanger": "The freight barge lifts off early."}

    # Scratch includes creative_seed and avoid_repeating when prior draft exists
    asyncio.run(
        generate_creation_ai_assist(
            None,
            _InspectLLM(),
            {
                "target": "bio",
                "mode": "scratch",
                "character": {"role": "Nomad"},
                "current": {"summary": "Old repetitive Trauma Team story."},
            },
        )
    )
    assert "creative_seed" in seen_prompts[-1]
    assert "Old repetitive Trauma Team story." in seen_prompts[-1]["avoid_repeating"]


