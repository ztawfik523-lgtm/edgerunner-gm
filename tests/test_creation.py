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
        db.execute("CREATE TABLE source_tables(pdf_page INTEGER, ordinal INTEGER, bbox_json TEXT, cells_json TEXT)")
        import json as _json
        db.execute("INSERT INTO pages VALUES(45, 45, '45\nPersonality\nLifepath')")
        db.execute("INSERT INTO source_tables VALUES(45, 1, NULL, ?)", (_json.dumps([
            ["Region", "Languages"],
            ["North American", "English, Spanish"],
            ["East Asian", "Japanese, Mandarin Chinese"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(45, 2, NULL, ?)", (_json.dumps([
            ["Roll", "Personality"],
            ["1", "Quiet and guarded"],
            ["2", "Steady and grounded"],
        ]),))

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
    assert len(ref["cultural_regions"]) == 2
    assert ref["lifepath_tables"]["personality"] == ["Quiet and guarded", "Steady and grounded"]

    for empty_arg in (None, tmp_path / "does-not-exist.sqlite"):
        missing_ref = build_creation_reference(empty_arg)
        assert missing_ref["rules_indexed"] is False
        assert missing_ref["roles"] == []
        assert missing_ref["methods"] == []
        assert missing_ref["stats"] == {}
        assert missing_ref["skills"] == []
        assert missing_ref["lifepath_tables"] == {}
        assert missing_ref["shop"]["weapon"] == []
        assert missing_ref["shop"]["armor"] == []
        assert missing_ref["shop"]["hardware"] == []
        assert missing_ref["campaign_presets"]["districts"] == []
        assert missing_ref["campaign_presets"]["factions"] == []
        assert missing_ref["campaign_presets"]["caper_styles"] == []


def test_corebook_catalog_builders_and_parsers(tmp_path):
    import json as _json
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

    assert build_corebook_weapons() == []
    assert build_corebook_armor() == []
    assert build_corebook_hardware() == []

    db_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        db.execute("INSERT INTO metadata VALUES('source_sha256', 'cat-digest')")
        db.execute("CREATE TABLE pages(pdf_page INTEGER, printed_page INTEGER, text TEXT)")
        db.execute("INSERT INTO pages VALUES(340, 340, '340\nGear')")
        db.execute("CREATE TABLE source_tables(pdf_page INTEGER, ordinal INTEGER, bbox_json TEXT, cells_json TEXT)")
        db.execute("INSERT INTO source_tables VALUES(340, 1, NULL, ?)", (_json.dumps([
            ["Weapon Type", "Skill", "Damage", "ROF", "Cost"],
            ["Heavy Pistol", "Handgun", "3d6", "2", "100eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(340, 2, NULL, ?)", (_json.dumps([
            ["Armor Type", "SP", "Cost"],
            ["Light Armorjack", "11", "100eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(340, 3, NULL, ?)", (_json.dumps([
            ["Hardware", "Cost"],
            ["Cyberdeck", "500eb"],
        ]),))

    assert build_corebook_weapons(db_path)[0]["name"] == "Heavy Pistol"
    assert build_corebook_armor(db_path)[0]["stats"]["sp"] == 11
    assert build_corebook_hardware(db_path)[0]["name"] == "Cyberdeck"


def test_medtech_creation_applies_initial_benefits_and_reference_includes_vehicles_drugs_presets(rules):
    import json as _json
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

    with sqlite3.connect(rules) as db:
        db.execute("CREATE TABLE IF NOT EXISTS source_tables(pdf_page INTEGER, ordinal INTEGER, bbox_json TEXT, cells_json TEXT)")
        db.execute("INSERT INTO pages VALUES(350, 350, '350\nVehicles & Drugs')")
        db.execute("INSERT INTO source_tables VALUES(350, 1, NULL, ?)", (_json.dumps([
            ["Vehicle", "Cost", "SDP"],
            ["Compact Groundcar", "30000eb", "50"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(350, 2, NULL, ?)", (_json.dumps([
            ["Drug", "Cost", "Primary Effect"],
            ["Synthcoke", "20eb", "+1 REF"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(350, 3, NULL, ?)", (_json.dumps([
            ["District", "Zone Type", "Threat Rating", "Summary"],
            ["Sector 4", "Moderate Zone", "Moderate", "Industrial block."],
        ]),))

    from creation_reference import build_creation_reference

    ref = build_creation_reference(rules)
    assert len(ref["shop"]["vehicle"]) == 1
    assert len(ref["shop"]["drug"]) == 1
    assert len(ref["campaign_presets"]["districts"]) == 1
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


def test_creation_ai_assist_per_textfield_hooks_contacts_and_campaign():
    import asyncio
    import json
    from creation_catalog import _BEAT_KEY_TO_FIELD, generate_creation_ai_assist

    for _, (_, desc) in _BEAT_KEY_TO_FIELD.items():
        assert "p." not in desc.lower() and "corebook" not in desc.lower()

    class _EchoLLM:
        async def complete(self, messages, json_mode=True, temperature=0.7):
            payload = json.loads(messages[1]["content"])
            field = payload.get("target_field")
            if payload.get("target_entry_index") is not None and payload.get("target_sub_field"):
                return json.dumps({"value": f"Updated {field}[{payload['target_entry_index']}].{payload['target_sub_field']}"})
            if field in {"reputation_note", "trauma_hook", "addiction_hook", "debt_hook", "gig_title", "clock_name"}:
                return json.dumps({field: f"Fresh {field}"})
            return json.dumps({})

    r_hook = asyncio.run(
        generate_creation_ai_assist(
            None,
            _EchoLLM(),
            {"target": "bio", "mode": "expand", "field": "debt_hook", "character": {"role": "Fixer"}, "current": {"debt_hook": "Owes 500 eb"}},
        )
    )
    assert r_hook["debt_hook"] == "Fresh debt_hook"

    r_friend_note = asyncio.run(
        generate_creation_ai_assist(
            None,
            _EchoLLM(),
            {
                "target": "contacts",
                "mode": "expand",
                "field": "friends",
                "entry_index": 0,
                "sub_field": "note",
                "character": {"role": "Fixer"},
                "current": {"friends": [{"name": "Marek", "relationship": "Ripperdoc", "note": "Patches you up"}]},
            },
        )
    )
    assert r_friend_note["entry_index"] == 0
    assert r_friend_note["sub_field"] == "note"
    assert r_friend_note["value"] == "Updated friends[0].note"

    r_gig = asyncio.run(
        generate_creation_ai_assist(
            None,
            _EchoLLM(),
            {"target": "campaign", "mode": "scratch", "field": "gig_title", "campaign": {"district": "Watson"}, "current": {}},
        )
    )
    assert r_gig["gig_title"] == "Fresh gig_title"

    r_clock = asyncio.run(
        generate_creation_ai_assist(
            None,
            _EchoLLM(),
            {"target": "campaign", "mode": "scratch", "field": "clock_name", "campaign": {"district": "Watson"}, "current": {}},
        )
    )
    assert r_clock["clock_name"] == "Fresh clock_name"

    r_npc_val = asyncio.run(
        generate_creation_ai_assist(
            None,
            _EchoLLM(),
            {
                "target": "campaign",
                "mode": "expand",
                "field": "npcs",
                "entry_index": 0,
                "sub_field": "val",
                "campaign": {"district": "Watson"},
                "current": {"npcs": {"Marek (Fixer)": "Needs extraction"}},
            },
        )
    )
    assert r_npc_val["value"] == "Updated npcs[0].val"


def test_expanded_character_creation_roles_housing_cyberware_and_reference(rules):
    import json as _json
    import economy
    import roles
    from creation_reference import build_creation_reference

    with sqlite3.connect(rules) as db:
        db.execute("CREATE TABLE IF NOT EXISTS source_tables(pdf_page INTEGER, ordinal INTEGER, bbox_json TEXT, cells_json TEXT)")
        db.execute("INSERT INTO pages VALUES(355, 355, '355\nExpanded Market')")
        db.execute("INSERT INTO source_tables VALUES(355, 1, NULL, ?)", (_json.dumps([
            ["Ammo", "Cost"],
            ["Basic Ammunition", "10eb"],
            ["Armor-Piercing Ammunition", "100eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(355, 2, NULL, ?)", (_json.dumps([
            ["Attachment", "Cost"],
            ["Sniping Scope", "500eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(355, 3, NULL, ?)", (_json.dumps([
            ["Service", "Cost"],
            ["Lifestyle: Kibble", "100eb"],
            ["Trauma Team Silver", "500eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(355, 4, NULL, ?)", (_json.dumps([
            ["Housing", "Rent (eb/mo)", "Summary"],
            ["Cargo Container", "1000", "Standard container."],
            ["Corporate Conapt", "0", "Exec corporate housing perk."],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(355, 5, NULL, ?)", (_json.dumps([
            ["Name", "Style", "Garment", "Cost"],
            ["Generic Chic Jacket", "Generic Chic", "Jacket", "50eb"],
            ["High Fashion Jacket", "High Fashion", "Jacket", "1000eb"],
        ]),))
        db.execute("INSERT INTO source_tables VALUES(355, 6, NULL, ?)", (_json.dumps([
            ["Cyberware Name", "Install", "HL", "Cost"],
            ["Implanted Linear Frame ∑ (Sigma)", "Hospital", "14", "1000eb"],
        ]),))

    # 1. Creation Reference includes extracted ammo, attachments, services, housing, fashion_matrix, housing_tiers, lifestyles
    ref = build_creation_reference(rules)
    assert len(ref["shop"]["ammo"]) >= 2
    assert len(ref["shop"]["attachment"]) >= 1
    assert len(ref["shop"]["service"]) >= 2
    assert len(ref["shop"]["housing"]) >= 2
    assert len(ref["fashion_matrix"]) >= 1
    assert any("corporate" in h["id"] and h.get("exec_only") for h in ref["housing_tiers"])
    assert any(l["id"] == "Kibble" for l in ref["lifestyles"])

    basics = [
        "Athletics", "Brawling", "Concentration", "Conversation", "Education",
        "Evasion", "First Aid", "Human Perception", "Language (Streetslang)",
        "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth",
    ]
    base_skills = dict.fromkeys(basics, 2)
    base_skills.update({f"Skill {i}": 5 for i in range(1, 13)})
    stats = dict(zip(STATS, [6, 7, 6, 8, 6, 6, 6, 6, 5, 6]))

    # 2. Tech maker_ranks persisted & usable by roles.tech_project_begin; Head Armor auto-equipped; Reputation & hooks stored
    tech = build_character(
        {
            "name": "Wrench",
            "method": "complete_package",
            "role": "Tech",
            "stats": stats,
            "skills": base_skills,
            "lifepath": {"cultural_origin": "North American"},
            "role_choices": {
                "maker": [
                    "Field Expertise", "Upgrade Expertise",
                    "Upgrade Expertise", "Fabrication Expertise",
                    "Fabrication Expertise", "Invention Expertise",
                    "Field Expertise", "Upgrade Expertise",
                ],
            },
            "housing": "cube",
            "lifestyle": "Generic Prepak",
            "reputation": 3,
            "reputation_note": "Known in Kabuki salvage yards",
            "starting_hooks": {"debt": "Owes 500 eb to Fixer Mara"},
            "starting_gear": {
                "inventory": {
                    "Heavy Pistol": 1,
                    "Light Armorjack Body (SP 11)": 1,
                    "Light Armorjack Head Armor (SP 11)": 1,
                },
                "cyberware": [
                    {"name": "Linear Frame Sigma", "hl": 14, "cost_eb": 1000},
                    {"name": "Skinweave", "hl": 7, "cost_eb": 500},
                ],
                "equipped_weapon": "Heavy Pistol",
                "equipped_armor": {"name": "Light Armorjack Body (SP 11)", "sp": 11},
                "money_spent_eb": 1700,
                "fashion": [{"name": "Urban Flash Outfit", "cost_eb": 320, "style": "Urban Flash"}],
            },
        },
        rules,
        lambda s: 0,
    )
    assert tech["detail"]["roles"][0]["choices"]["maker_ranks"]["Upgrade Expertise"] == 3
    assert tech["detail"]["equipped_head_armor"] == {"name": "Light Armorjack Head Armor (SP 11)", "sp": 11}
    assert tech["detail"]["housing"] == "cube"
    assert tech["detail"]["lifestyle"] == "Generic Prepak"
    assert tech["detail"]["reputation"] == 3
    assert tech["detail"]["reputation_note"] == "Known in Kabuki salvage yards"
    assert tech["detail"]["backstory"]["starting_hooks"]["debt"] == "Owes 500 eb to Fixer Mara"
    # Linear Frame Sigma raises effective BODY from 5 -> 12 => HP = 10 + 5 * ceil((12+6)/2) = 55, death_save = 12
    assert tech["stats"]["BODY"] == 5
    assert tech["max_hp"] == 55
    assert tech["death_save"] == 12
    assert tech["detail"]["creation"]["cyberware_modifiers"]["subdermal_sp"] == 7

    # Tech project invention works immediately using persisted maker_ranks
    proj = roles.apply_action(
        tech,
        "tech_project_begin",
        {
            "project_kind": "invent",
            "project_id": "custom-optic",
            "gm_approved": True,
            "category": "Expensive",
            "gm_repair_skill": "Skill 1",
        },
        lambda s: 0,
    )
    assert proj["result"]["project_id"] == "custom-optic"

    # Economy pay_month works immediately with persisted housing & lifestyle
    paid = economy.apply_action(tech, "pay_month", {"month": 2}, lambda s: 0)
    assert paid["result"]["paid"] == 800

    # 3. Fashion budget > 800 eb rejected on complete_package
    with pytest.raises(ValueError, match="fashion spending exceeds 800 eb"):
        build_character(
            {
                "name": "Overdressed",
                "method": "complete_package",
                "role": "Rockerboy",
                "stats": stats,
                "skills": base_skills,
                "lifepath": {"cultural_origin": "North American"},
                "starting_gear": {
                    "inventory": {"Heavy Pistol": 1},
                    "fashion": [{"name": "High Fashion Contact Lenses", "cost_eb": 1000}],
                    "money_spent_eb": 100,
                },
            },
            rules,
            lambda s: 0,
        )

    # 4. Exec, Nomad & Fixer role parity
    exec_char = build_character(
        {
            "name": "Director Vance",
            "method": "complete_package",
            "role": "Exec",
            "stats": stats,
            "skills": base_skills,
            "role_choices": {"team_member": {"name": "Kaito Reyes", "role": "Bodyguard", "loyalty": 5}},
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {"inventory": {"Very Heavy Pistol": 1}},
        },
        rules,
        lambda s: 0,
    )
    assert exec_char["detail"]["creation"]["status"] == "validated"
    assert exec_char["detail"]["housing"] == "corporate"
    assert exec_char["detail"]["trauma_team"] == "Silver"
    assert exec_char["detail"]["team"][0]["loyalty"] == 5

    nomad_char = build_character(
        {
            "name": "Dusty",
            "method": "complete_package",
            "role": "Nomad",
            "stats": stats,
            "skills": base_skills,
            "role_choices": {"moto": ["Compact Groundcar", "Superbike", "Armored Chassis", "NOS (Nitrous Boost)"]},
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {"inventory": {"Heavy Pistol": 1}},
        },
        rules,
        lambda s: 0,
    )
    assert nomad_char["detail"]["creation"]["status"] == "validated"
    assert nomad_char["detail"]["active_vehicle"] == "compact-groundcar"
    swapped = roles.apply_action(
        nomad_char,
        "nomad_vehicle",
        {"mode": "swap", "vehicle_id": "superbike", "family_close": True, "now_minutes": 100},
        lambda s: 0,
    )
    assert swapped["result"]["pending_vehicle"] == "superbike"

    fixer_char = build_character(
        {
            "name": "Broker",
            "method": "complete_package",
            "role": "Fixer",
            "stats": stats,
            "skills": base_skills,
            "role_choices": {"culture": "Kabuki Night Market", "language": "Japanese"},
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {"inventory": {"Heavy Pistol": 1}},
        },
        rules,
        lambda s: 0,
    )
    assert fixer_char["skills"].get("Language (Japanese)") == 4

    # 5. Reviewer hardening: Skin Weave (with space), Bodyweight Suit dual coverage, Communications Center, budget bypass guards
    skin_bw = build_character(
        {
            "name": "Mesh",
            "method": "complete_package",
            "role": "Nomad",
            "stats": stats,
            "skills": base_skills,
            "role_choices": {"moto": ["Compact Groundcar", "Communications Center", "Armored Chassis", "Smuggling Compartment"]},
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {
                "inventory": {"Heavy Pistol": 1, "Bodyweight Suit (Head & Body SP 11)": 1},
                "cyberware": [{"name": "Skin Weave", "hl": 7, "cost_eb": 500}],
            },
        },
        rules,
        lambda s: 0,
    )
    assert skin_bw["detail"]["creation"]["cyberware_modifiers"]["subdermal_sp"] == 7
    assert "Bodyweight Suit" in skin_bw["detail"]["equipped_armor"]["name"]
    assert skin_bw["detail"]["equipped_armor"]["sp"] == 11
    assert "Bodyweight Suit" in skin_bw["detail"]["equipped_head_armor"]["name"]
    assert skin_bw["detail"]["equipped_head_armor"]["sp"] == 11
    assert "Communications Center" in skin_bw["detail"]["family_motorpool"][0]["upgrades"]
    assert len(skin_bw["detail"]["family_motorpool"]) == 1

    skin_only = build_character(
        {
            "name": "Derm",
            "method": "complete_package",
            "role": "Solo",
            "stats": stats,
            "skills": base_skills,
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {
                "inventory": {"Heavy Pistol": 1},
                "cyberware": [{"name": "Skin Weave", "hl": 7, "cost_eb": 500}],
            },
        },
        rules,
        lambda s: 0,
    )
    assert skin_only["detail"]["equipped_armor"] == {"name": "Skinweave", "sp": 7}
    assert skin_only["detail"]["equipped_head_armor"] == {"name": "Skinweave", "sp": 7}

    # Omitted money_spent_eb still enforces 2550 eb catalog gear cap
    with pytest.raises(ValueError, match="exceeds 2550 eb budget"):
        build_character(
            {
                "name": "Heavyspender",
                "method": "complete_package",
                "role": "Solo",
                "stats": stats,
                "skills": base_skills,
                "lifepath": {"cultural_origin": "North American"},
                "starting_gear": {
                    "cyberware": [
                        {"name": "Implanted Linear Frame ∑ (Sigma)"},
                        {"name": "Implanted Linear Frame ∑ (Sigma)"},
                        {"name": "Implanted Linear Frame ∑ (Sigma)"},
                    ],
                },
            },
            rules,
            lambda s: 0,
        )

    # Spoofed cost_eb=0 on catalog fashion still resolves real catalog price against 800 eb fashion cap
    with pytest.raises(ValueError, match="fashion spending exceeds 800 eb budget"):
        build_character(
            {
                "name": "Spoofer",
                "method": "complete_package",
                "role": "Rockerboy",
                "stats": stats,
                "skills": base_skills,
                "lifepath": {"cultural_origin": "North American"},
                "starting_gear": {
                    "inventory": {"Heavy Pistol": 1},
                    "fashion": [{"name": "High Fashion Jacket", "cost_eb": 0}],
                },
            },
            rules,
            lambda s: 0,
        )



