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
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    definitions = "\n".join(f"{name}........INT" for name in basics + [f"Skill {i}" + (" (x2)" if i == 0 else "") for i in range(20)])
    from tests import rules_fixture as rf
    rf.build(path, [
        rf.page(83, 82, [rf.block(line, 60 + 20 * i) for i, line in enumerate(definitions.splitlines())]),
    ], digest="test-digest")
    rf.add_role(path, "Solo", [list(row[1:]) for row in values], {f"Skill {i}": 4 for i in range(20)})
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
    exec_names = ["Accounting", "Bureaucracy", "Business"] + [f"Skill {i}" for i in range(3, 20)]
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    defs = "\n".join(f"{name}........INT" for name in basics + exec_names)
    from tests import rules_fixture as rf
    rf.build(path, [
        rf.page(83, 82, [rf.block(line, 60 + 20 * i) for i, line in enumerate(defs.splitlines())]),
    ], digest="exec-digest")
    rf.add_role(path, "Exec", [list(row[1:]) for row in values], dict.fromkeys(exec_names, 4))

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


def test_expanded_character_creation_roles_housing_cyberware_and_reference(rules):
    import economy
    import roles
    from creation_reference import build_creation_reference

    # 1. Creation Reference includes full ammo, attachments, services, housing, 90-item fashion_matrix, housing_tiers, lifestyles
    ref = build_creation_reference(rules)
    assert len(ref["shop"]["ammo"]) >= 3
    assert len(ref["shop"]["attachment"]) >= 3
    assert len(ref["shop"]["service"]) >= 5
    assert len(ref["shop"]["housing"]) >= 4
    assert len(ref["fashion_matrix"]) == 90
    assert any(h["id"] == "corporate" and h.get("exec_only") for h in ref["housing_tiers"])
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
    assert tech["detail"]["equipped_head_armor"] == {"name": "Light Armorjack Head Armor (SP 11)", "sp": 11, "penalty": 0}
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
    assert skin_only["detail"]["equipped_armor"] == {"name": "Skinweave", "sp": 7, "penalty": 0}
    assert skin_only["detail"]["equipped_head_armor"] == {"name": "Skinweave", "sp": 7, "penalty": 0}

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


def test_build_character_synchronizes_equipment_views(rules):
    basics = [
        "Athletics", "Brawling", "Concentration", "Conversation", "Education",
        "Evasion", "First Aid", "Human Perception", "Language (Streetslang)",
        "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth",
    ]
    base_skills = dict.fromkeys(basics, 2)
    base_skills.update({f"Skill {i}": 5 for i in range(1, 13)})
    stats = dict(zip(STATS, [6, 7, 6, 7, 6, 6, 6, 6, 6, 6]))

    char = build_character(
        {
            "name": "Chrome",
            "method": "complete_package",
            "role": "Solo",
            "stats": stats,
            "skills": base_skills,
            "lifepath": {"cultural_origin": "North American"},
            "starting_gear": {
                "inventory": {
                    "Heavy Pistol": 1,
                    "ammo: h pistol": 24,
                    "Medium Armorjack Body Armor (SP 12)": 1,
                },
                "cyberware": [{"name": "Standard Cyberarm", "hl": 7}],
                "equipped_weapon": "Heavy Pistol",
                "equipped_armor": {"name": "Medium Armorjack Body Armor (SP 12)", "sp": 12},
                "money_spent_eb": 700,
            },
        },
        rules,
        lambda s: 0,
    )
    detail = char["detail"]
    assert detail["free_hands"] == 2
    assert detail["cyberarm"] is True
    assert char["inventory"]["ammo:H Pistol"] == 24
    assert "ammo: h pistol" not in char["inventory"]
    assert detail["equipment"]["weapons"][0]["type"] == "Heavy Pistol"
    assert detail["equipment"]["armor"][0]["sp"] == 12
    assert detail["equipment"]["armor"][0]["penalty"] == 2
    assert detail["equipped_armor"] == {"name": "Medium Armorjack Body Armor (SP 12)", "sp": 12, "penalty": 2}



