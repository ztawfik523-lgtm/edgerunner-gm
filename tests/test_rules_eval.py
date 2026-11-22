import copy

import rules_eval


def _fixed_die(die_value: int):
    """Return a randbelow stub producing `die_value` (1..10) on d10."""
    return lambda sides: die_value - 1


def test_effective_initial_emp_precedence_and_derivation():
    assert rules_eval.effective_initial_emp({
        "initial_emp": 4,
        "detail": {"initial_emp": 5, "creation": {"initial_emp": 7}},
    }) == 7
    assert rules_eval.effective_initial_emp({
        "initial_emp": 4,
        "detail": {"initial_emp": 5},
    }) == 5
    assert rules_eval.effective_initial_emp({"initial_emp": 4}) == 4

    # Derive from humanity + cyberware hl / humanity_loss
    derived = {
        "humanity": 40,
        "stats": {"EMP": 4},
        "detail": {"cyberware": [{"name": "Sandevistan", "hl": 14}, {"name": "Skinweave", "humanity_loss": 7}]},
    }
    snap = copy.deepcopy(derived)
    assert rules_eval.effective_initial_emp(derived) == 6
    assert derived == snap

    # Fallback to stats["EMP"] when humanity is missing
    assert rules_eval.effective_initial_emp({"stats": {"EMP": 8}}) == 8


def test_effective_emp_and_sync_emp_from_humanity():
    char = {"humanity": 38, "stats": {"EMP": 7}}
    assert rules_eval.effective_emp(char) == 3
    assert char["stats"]["EMP"] == 7  # pure reader does not mutate

    synced = rules_eval.sync_emp_from_humanity(char)
    assert synced == 3
    assert char["stats"]["EMP"] == 3

    char_neg = {"humanity": -5, "stats": {"EMP": 2}}
    assert rules_eval.sync_emp_from_humanity(char_neg) == 0
    assert char_neg["stats"]["EMP"] == 0

    no_hum = {"humanity": None, "stats": {"EMP": 6}}
    assert rules_eval.effective_emp(no_hum) == 6
    assert rules_eval.sync_emp_from_humanity(no_hum) == 6
    assert no_hum["stats"]["EMP"] == 6


def test_effective_body_with_creation_and_linear_frames():
    assert rules_eval.effective_body({"stats": {"BODY": 6}}) == 6
    assert rules_eval.effective_body({
        "stats": {"BODY": 6},
        "detail": {"creation": {"effective_body": 8}, "effective_body": 10},
    }) == 10

    # Sigma in cyberware -> >= 12
    sigma_char = {
        "stats": {"BODY": 6},
        "detail": {"cyberware": [{"name": "Implanted Linear Frame ∑ (Sigma)", "hl": 14}]},
    }
    assert rules_eval.effective_body(sigma_char) == 12

    # Beta in equipment or inventory -> >= 14
    beta_char = {
        "stats": {"BODY": 8},
        "inventory": {"Implanted Linear Frame ß (Beta)": 1},
    }
    assert rules_eval.effective_body(beta_char) == 14

    # Higher natural/creation BODY is not lowered by Sigma
    strong_sigma = {
        "stats": {"BODY": 14},
        "inventory": {"Linear Frame Sigma": 1},
    }
    assert rules_eval.effective_body(strong_sigma) == 14

    # Zero quantity in inventory or disabled cyberware does not apply
    unowned = {
        "stats": {"BODY": 5},
        "inventory": {"Linear Frame Beta": 0},
        "detail": {"cyberware": [{"name": "Linear Frame Sigma", "disabled": True}]},
    }
    assert rules_eval.effective_body(unowned) == 5


def test_active_injuries_normalizes_enriches_dedups_and_preserves_flags():
    char = {
        "injuries": [
            "Brain Injury",
            "Foreign Object",
            {"id": "body:aimed_leg", "name": "Broken Leg"},
        ],
        "detail": {
            "clock_minutes": 100,
            "injuries": [
                {"id": "head:3", "name": "Brain Injury", "suppressed": True, "quick_fixed": True},
                {"id": "head:7", "name": "Foreign Object"},
                {"id": "body:5", "name": "Broken Ribs", "effect_suppressed_until": 500},
                {"id": "head:5", "name": "Concussion", "effect_removed": True},
                {"id": "head:6", "name": "Broken Jaw", "treated": True},
            ],
        },
    }
    snap = copy.deepcopy(char)
    res = rules_eval.active_injuries(char)
    assert char == snap

    by_id = {x["id"]: x for x in res}
    assert set(by_id) == {"head:3", "head:7", "body:5", "body:8", "head:6"}
    assert by_id["head:3"]["suppressed"] is True
    assert by_id["head:3"]["quick_fixed"] is True
    assert by_id["head:3"]["treated"] is False
    assert by_id["head:3"]["death_save_penalty"] == 1
    assert by_id["body:5"]["suppressed"] is True
    assert by_id["body:8"]["name"] == "Broken Leg"
    assert by_id["body:8"]["death_save_penalty"] == 0
    assert by_id["head:6"]["treated"] is True


def test_effective_armor_penalty_variants():
    assert rules_eval.effective_armor_penalty({}) == 0
    assert rules_eval.effective_armor_penalty({"armor_penalty": "None"}) == 0
    assert rules_eval.effective_armor_penalty({"armor_penalty": -2}) == 2
    assert rules_eval.effective_armor_penalty({"detail": {"armor_penalty": "-4 REF, DEX, and MOVE"}}) == 4
    assert rules_eval.effective_armor_penalty({
        "detail": {
            "equipped_armor": {"name": "Medium Armorjack Body Armor (SP 12)", "sp": 12},
            "equipped_head_armor": {"name": "Flak Head Armor / Helmet (SP 15)", "sp": 15},
            "equipment": {
                "armor": [
                    {"id": "armor-0", "type": "Bulletproof Shield", "sp": 0, "armor_penalty_minimum_0": "Requires 1 arm"},
                    {"id": "armor-1", "type": "Heavy Armorjack", "sp": 13, "penalty": 2},
                ]
            },
        }
    }) == 4
    assert rules_eval.effective_armor_penalty({"armor": {"name": "Bulletproof Shield", "armor_penalty_minimum_0": "Requires 1 arm"}}) == 0


def test_effective_wound_penalty_and_suppression():
    serious = {"hp": 15, "max_hp": 40, "stats": {"MOVE": 6}}
    mortal = {"hp": 0, "max_hp": 40, "stats": {"MOVE": 6}}
    healthy = {"hp": 40, "max_hp": 40, "stats": {"MOVE": 6}}

    assert rules_eval.effective_wound_penalty(healthy) == 0
    assert rules_eval.effective_wound_penalty(serious) == -2
    assert rules_eval.effective_wound_penalty(mortal) == -4

    # BlackLace suppresses Serious, not Mortal
    blacklace_serious = {
        **serious,
        "detail": {"clock_minutes": 100, "drugs": {"BlackLace": {"expires_at": 500}}},
    }
    blacklace_mortal = {**mortal, "detail": blacklace_serious["detail"]}
    assert rules_eval.effective_wound_penalty(blacklace_serious) == 0
    assert rules_eval.effective_wound_penalty(blacklace_mortal) == -4

    # Stim suppresses Serious, not Mortal
    stim_serious = {
        **serious,
        "detail": {"clock_minutes": 10, "pharmaceutical_effects": {"Stim": {"expires_at": 70, "ignore_serious_wounded": True}}},
    }
    stim_expired = {
        **serious,
        "detail": {"clock_minutes": 70, "pharmaceutical_effects": {"Stim": {"expires_at": 70, "ignore_serious_wounded": True}}},
    }
    assert rules_eval.effective_wound_penalty(stim_serious) == 0
    assert rules_eval.effective_wound_penalty(stim_expired) == -2

    # Pain Editor suppresses BOTH Serious and Mortal
    pain_editor_mortal = {**mortal, "detail": {"cyberware": [{"name": "Pain Editor"}]}}
    pain_editor_inv = {**mortal, "inventory": {"Pain Editor": 1}}
    assert rules_eval.effective_wound_penalty(pain_editor_mortal) == 0
    assert rules_eval.effective_wound_penalty(pain_editor_inv) == 0


def test_effective_check_context_stats_skills_roles_and_armor_gating():
    char = {
        "humanity": 25,
        "hp": 40,
        "max_hp": 40,
        "stats": {"INT": 6, "REF": 7, "DEX": 6, "TECH": 8, "COOL": 5, "WILL": 6, "EMP": 7, "MOVE": 6, "BODY": 5},
        "skills": {"Handgun": 6, "Persuasion": 4, "Resist Torture/Drugs": 5},
        "detail": {
            "clock_minutes": 50,
            "armor_penalty": "-2 REF, DEX, and MOVE",
            "cyberware": [{"name": "Implanted Linear Frame ∑ (Sigma)"}],
            "drugs": {"Boost": {"expires_at": 500}, "Smash": {"expires_at": 500}},
            "net_debuffs": {"Liche": 3},
            "conditions": {"MOVE": 2},
            "maker_ranks": {"field_expertise": 3},
            "medtech": {"cryosystem_operation": 2},
            "roles": [
                {"role": "Tech", "rank": 4, "choices": {"maker_ranks": {"Upgrade Expertise": 4}}},
                {"role": "Netrunner", "rank": 5},
            ],
        },
    }

    # REF gets armor penalty (-2) and Liche (-3) -> 7 - 3 = 4 stat, -2 armor, Handgun=6 -> 8
    ranged = rules_eval.effective_check_context(char, "REF", "  handgun ")
    assert ranged["base_stat_value"] == 7
    assert ranged["net_debuff"] == -3
    assert ranged["stat_value"] == 4
    assert ranged["skill"] == "Handgun"
    assert ranged["skill_value"] == 6
    assert ranged["armor_penalty"] == -2
    assert ranged["effective_base"] == 8

    # WILL does NOT get armor penalty; case/space insensitive skill lookup
    resist = rules_eval.effective_check_context(char, "WILL", "resist   torture / drugs")
    assert resist["armor_penalty"] == 0
    assert resist["skill"] == "Resist Torture/Drugs"
    assert resist["skill_value"] == 5
    assert resist["effective_base"] == 11

    # EMP uses humanity // 10 = 2 (not stats["EMP"]=7), no armor penalty
    emp_ctx = rules_eval.effective_check_context(char, "EMP", None)
    assert emp_ctx["stat_value"] == 2
    assert emp_ctx["armor_penalty"] == 0

    # BODY uses Sigma Linear Frame = 12
    body_ctx = rules_eval.effective_check_context(char, "BODY", None)
    assert body_ctx["stat_value"] == 12

    # INT gets Boost (+2) and Liche (-3) -> 6 + 2 - 3 = 5
    int_ctx = rules_eval.effective_check_context(char, "INT", "Field Expertise")
    assert int_ctx["stat_value"] == 5
    assert int_ctx["skill_value"] == 3
    assert int_ctx["substance_modifier"] == 2
    assert int_ctx["net_debuff"] == -3

    # Smash (+2 Persuasion)
    pers = rules_eval.effective_check_context(char, "COOL", "Persuasion")
    assert pers["substance_modifier"] == 2
    assert pers["total_modifier"] == 2
    assert pers["effective_base"] == 5 + 4 + 2

    # Tech Maker specialty & Medtech specialty & Role Ability
    assert rules_eval.effective_check_context(char, "TECH", "upgrade_expertise")["skill_value"] == 4
    assert rules_eval.effective_check_context(char, "TECH", "Cryosystem Operation")["skill_value"] == 2
    assert rules_eval.effective_check_context(char, "ROLE", "Interface")["effective_base"] == 5

    # Clamped >= 0 on heavy debuff
    heavy_debuff = {"stats": {"INT": 2}, "detail": {"net_debuffs": {"INT": 5}}}
    assert rules_eval.effective_check_context(heavy_debuff, "INT", None)["stat_value"] == 0


def test_effective_check_context_injuries_and_solo_allocations():
    char = {
        "hp": 40,
        "max_hp": 40,
        "stats": {"INT": 6, "REF": 8, "DEX": 7, "COOL": 6, "TECH": 6, "MOVE": 6},
        "skills": {
            "Perception": 5,
            "Handgun": 6,
            "Melee Weapon": 5,
            "Persuasion": 4,
            "Pick Lock": 4,
            "Athletics": 4,
        },
        "detail": {
            "injuries": [
                {"id": "head:2", "name": "Lost Eye"},
                {"id": "head:10", "name": "Damaged Ear"},
                {"id": "body:9", "name": "Torn Muscle"},
                {"id": "head:6", "name": "Broken Jaw"},
                {"id": "body:11", "name": "Crushed Fingers"},
                {"id": "body:8", "name": "Broken Leg"},
                {"id": "head:5", "name": "Concussion", "suppressed": True},
            ],
            "solo_allocation": {
                "threat_detection": 2,
                "precision_attack": 4,
                "fumble_recovery": 4,
                "spot_weakness": 1,
                "damage_deflection": 2,
                "initiative_reaction": 1,
            },
        },
    }

    # Vision perception: Lost Eye (-4), Threat Detection (+2), Concussion is suppressed (0)
    vis = rules_eval.effective_check_context(char, "INT", "Perception", tags=("vision",))
    assert vis["injury_penalty"] == -4
    assert vis["solo_bonus"] == 2
    assert vis["fumble_recovery"] is True
    assert vis["spot_weakness"] == 1
    assert vis["damage_deflection"] == 2
    assert vis["initiative_reaction"] == 1
    assert vis["effective_base"] == 6 + 5 - 4 + 2

    # Hearing perception: Damaged Ear (-2), Threat Detection (+2)
    hear = rules_eval.effective_check_context(char, "INT", "Perception", tags=("hearing",))
    assert hear["injury_penalty"] == -2
    assert hear["solo_bonus"] == 2

    # Ranged attack: Lost Eye (-4), Precision Attack (+1 from 4 // 3)
    rng = rules_eval.effective_check_context(char, "REF", "Handgun", tags=("attack", "ranged"))
    assert rng["injury_penalty"] == -4
    assert rng["solo_bonus"] == 1
    assert rng["effective_base"] == 8 + 6 - 4 + 1

    # Melee attack: Torn Muscle (-2), Precision Attack (+1)
    mel = rules_eval.effective_check_context(char, "DEX", "Melee Weapon", tags=("attack", "melee"))
    assert mel["injury_penalty"] == -2
    assert mel["solo_bonus"] == 1

    # Speech check: Broken Jaw (-4)
    sp = rules_eval.effective_check_context(char, "COOL", "Persuasion", tags=("speech",))
    assert sp["injury_penalty"] == -4

    # Hand check: Crushed Fingers (-4)
    hand = rules_eval.effective_check_context(char, "TECH", "Pick Lock", tags=("hand",))
    assert hand["injury_penalty"] == -4

    # MOVE check: Broken Leg (-4) only on stat == "MOVE"
    mv = rules_eval.effective_check_context(char, "MOVE", "Athletics")
    assert mv["injury_penalty"] == -4
    ath = rules_eval.effective_check_context(char, "DEX", "Athletics")
    assert ath["injury_penalty"] == 0


def test_sync_equipment_views_bidirectional_and_idempotent():
    char = {
        "inventory": {"ammo: m pistol": "24", "ammo:Rifle": 10},
        "detail": {
            "cyberware": [{"name": "Standard Cyberarm", "hl": 7}],
            "equipped_weapon": "Heavy Pistol",
            "equipped_armor": {"name": "Medium Armorjack Body Armor (SP 12)", "sp": 12},
            "equipped_head_armor": {"name": "Light Armorjack Head Armor (SP 11)", "sp": 11},
        },
    }
    rules_eval.sync_equipment_views(char)
    d = char["detail"]
    assert d["free_hands"] == 2
    assert d["cyberarm"] is True
    assert char["inventory"] == {"ammo:M Pistol": 24, "ammo:Rifle": 10}
    assert len(d["equipment"]["weapons"]) == 1
    assert d["equipment"]["weapons"][0]["type"] == "Heavy Pistol"
    assert len(d["equipment"]["armor"]) == 2
    assert d["equipment"]["armor"][0]["penalty"] == 2
    assert d["equipment"]["armor"][1]["location"] == "head"
    assert d["equipment"]["armor"][1]["penalty"] == 0

    # Idempotent on repeated calls
    once = copy.deepcopy(char)
    rules_eval.sync_equipment_views(char)
    assert char == once

    # Cyberarm option alone should NOT set cyberarm=True
    opt_only = {"detail": {"cyberware": [{"name": "Rippers", "slot": "Cyberarm Option / Meat Arm Cyberware"}]}}
    rules_eval.sync_equipment_views(opt_only)
    assert opt_only["detail"]["cyberarm"] is False


def test_recompute_death_save_base_penalty_and_apply_death_save():
    char = {
        "hp": 0,
        "max_hp": 35,
        "stats": {"BODY": 6},
        "detail": {
            "cyberware": [{"name": "Implanted Linear Frame ∑ (Sigma)"}],
            "injuries": [
                {"id": "head:3", "name": "Brain Injury"},           # +1
                {"id": "head:8", "name": "Whiplash"},               # +1
                {"id": "body:8", "name": "Broken Leg"},             # 0
                {"id": "body:2", "name": "Dismembered Arm", "suppressed": True},  # suppressed -> 0
                {"id": "body:4", "name": "Collapsed Lung", "death_save_penalty": 0},  # explicit 0
            ],
            "death_save_penalty": 0,
        },
    }
    assert rules_eval.recompute_death_save_base_penalty(char) == 2
    assert char["detail"]["death_save_base_penalty"] == 2

    # Effective BODY is 12 (Sigma). Base=2, Escalation=0 -> total=2. Die=5 -> 5+2=7 < 12 -> survived!
    first = rules_eval.apply_death_save(char, _fixed_die(5))
    assert first["survived"] is True
    assert first["dead"] is False
    assert first["base_penalty"] == 2
    assert first["escalation_penalty"] == 0
    assert first["total_penalty"] == 2
    assert first["next_escalation_penalty"] == 1
    # Crucial invariant: detail["death_save_penalty"] stores ONLY escalation counter (1), NOT base+esc+1 (3)!
    assert char["detail"]["death_save_penalty"] == 1

    # Second save: Base=2, Escalation=1 -> total=3. Die=9 -> 9+3=12 >= 12 -> dead!
    second = rules_eval.apply_death_save(char, _fixed_die(9))
    assert second["survived"] is False
    assert second["dead"] is True
    assert second["total_penalty"] == 3
    assert second["next_escalation_penalty"] == 2
    assert char["detail"]["death_save_penalty"] == 2
    assert char["detail"]["conditions"]["dead"] is True
    assert char["detail"]["dead"] is True


def test_effective_check_context_addictions_combat_awareness_and_edge_cases():
    # Empty character does not crash
    empty_ctx = rules_eval.effective_check_context({}, None, None)
    assert empty_ctx["stat_value"] == 0
    assert empty_ctx["skill_value"] == 0
    assert empty_ctx["effective_base"] == 0
    assert empty_ctx["reasons"] == []

    # BlackLace addiction (-2 REF when inactive) + Synthcoke (+1 REF) -> net -1 REF
    # Scorpion debuff (-3 MOVE), combat_awareness alias, top-level role_rank
    char = {
        "role": "Solo",
        "role_rank": 5,
        "stats": {"REF": 6, "MOVE": 4, "INT": 5},
        "skills": {"Martial Arts (Karate)": 4},
        "detail": {
            "clock_minutes": 300,
            "addictions": ["BlackLace"],
            "drugs": {"Synthcoke": {"expires_at": 600}},
            "conditions": {"Scorpion": 3},
            "combat_awareness": {"precision_attack": 6, "fumble_recovery": 3},
            "injuries": [
                {"name": "Damaged Eye"},
                {"name": "Lost Ear"},
                {"name": "Sprained Ankle"},
                {"name": "Collapsed Lung"},
            ],
        },
    }

    ma = rules_eval.effective_check_context(char, "REF", "Martial Arts (Karate)")
    assert ma["base_stat_value"] == 6
    assert ma["substance_modifier"] == -1
    assert ma["stat_value"] == 5
    assert ma["solo_bonus"] == 2  # 6 // 3
    assert ma["fumble_recovery"] is False  # 3 < 4
    assert ma["injury_penalty"] == 0  # Damaged Eye doesn't hit melee
    assert ma["effective_base"] == 5 + 4 + 2

    mv = rules_eval.effective_check_context(char, "MOVE", None)
    assert mv["net_debuff"] == -3
    assert mv["stat_value"] == 1
    assert mv["injury_penalty"] == -4  # Sprained Ankle (-2) + Collapsed Lung (-2)

    # Hearing vs vision Perception with Damaged Eye + Lost Ear
    hear = rules_eval.effective_check_context(char, "INT", "Perception", tags=("hearing",))
    assert hear["injury_penalty"] == -4
    vis = rules_eval.effective_check_context(char, "INT", "Perception", tags=("vision",))
    assert vis["injury_penalty"] == -2

    # Role ability via top-level role + role_rank, and Maker/Medtech choice lists
    assert rules_eval.effective_check_context(char, "ROLE", "Combat Awareness")["effective_base"] == 5
    tech_choices = {
        "detail": {
            "roles": [{
                "role": "Tech",
                "rank": 2,
                "choices": {"maker": [["Field Expertise", "Upgrade Expertise"], ["Field Expertise", "Invention Expertise"]]},
            }, {
                "role": "Medtech",
                "rank": 2,
                "choices": {"medicine": {"Pharmaceuticals": 2}},
            }]
        }
    }
    assert rules_eval.effective_check_context(tech_choices, "TECH", "Field Expertise")["skill_value"] == 2
    assert rules_eval.effective_check_context(tech_choices, "TECH", "Pharmaceuticals")["skill_value"] == 2


def test_sync_equipment_views_updates_stale_ui_summaries_and_die_10_death_save():
    char = {
        "hp": 0,
        "max_hp": 30,
        "stats": {"BODY": 10},
        "detail": {
            "free_hands": 1,
            "equipped_weapon": "Medium Pistol",
            "equipped_armor": {"name": "Kevlar", "sp": 7},
            "equipment": {
                "weapons": [{"id": "weapon-0", "type": "Assault Rifle", "loaded": 25, "ammo_kind": "Rifle"}],
                "armor": [{"id": "armor-0", "type": "Heavy Armorjack", "sp": 11, "max_sp": 13, "location": "body", "penalty": 2}],
            },
        },
    }
    rules_eval.sync_equipment_views(char)
    assert char["detail"]["free_hands"] == 1
    assert char["detail"]["equipped_weapon"] == "Assault Rifle"
    assert char["detail"]["equipped_armor"] == {"name": "Heavy Armorjack", "sp": 11, "penalty": 2}

    # Die=10 always kills even when 10 + 0 < BODY? Wait: 10 is automatic failure in CPR!
    res = rules_eval.apply_death_save(char, _fixed_die(10))
    assert res["dead"] is True
    assert res["survived"] is False
    assert char["detail"]["conditions"]["dead"] is True
    assert char["detail"]["death_save_penalty"] == 1
