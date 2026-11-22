import copy

from health import apply_action


def test_stabilize_and_daily_healing_without_input_mutation():
    chars = {
        "med": {"stats": {"TECH": 8}, "skills": {"First Aid": 6}},
        "pc": {"stats": {"BODY": 5}, "hp": 8, "max_hp": 30,
               "detail": {"wound": "serious", "mortality_penalty": 0}},
    }
    original = copy.deepcopy(chars)
    stabilized = apply_action(chars, "med", "stabilize", {"target_id": "pc"}, lambda n: 9)
    assert stabilized["result"]["success"]
    assert stabilized["characters"]["pc"]["detail"]["stabilized"]
    healed = apply_action(stabilized["characters"], "pc", "rest",
                          {"days": 2, "light_activity": True}, lambda n: 0)
    assert healed["characters"]["pc"]["hp"] == 18
    assert chars == original


def test_unstabilized_rest_does_not_heal():
    chars = {"p": {"stats": {"BODY": 5}, "hp": 4, "max_hp": 20}}
    out = apply_action(chars, "p", "rest", {"days": 3, "light_activity": True})
    assert out["characters"]["p"]["hp"] == 4


def test_actor_cannot_self_treat_injuries_and_drugs_need_catalog():
    chars = {"p": {"stats": {}, "skills": {}, "inventory": [], "detail": {}}}
    for action in ("quick_fix", "treat_injury", "street_drug"):
        out = apply_action(chars, "p", action, {})
        assert out["result"]["requires_human_ruling"]
        assert out["characters"] == chars


def test_standard_therapy_caps_humanity_and_spends_patient_funds():
    chars = {
        "doc": {"stats": {"TECH": 8}, "skills": {"Medical Tech": 6},
                "detail": {"roles": [{"role": "Medtech", "rank": 4}]}},
        "pc": {"stats": {"EMP": 3}, "humanity": 30, "money": 500,
               "detail": {"initial_emp": 4, "cyberware": [
                   {"humanity_loss": 2}, {"humanity_loss": 1, "borgware": True},
                   {"humanity_loss": 0}]}}
    }
    out = apply_action(chars, "doc", "therapy", {"target_id": "pc", "therapy": "standard"},
                       lambda n: 5)
    assert out["result"]["success"]
    assert out["characters"]["pc"]["humanity"] == 34  # cap: 40 - 2 - 4
    assert out["characters"]["pc"]["stats"]["EMP"] == 3
    assert out["characters"]["pc"]["money"] == 0
    assert out["characters"]["doc"]["detail"]["clock_minutes"] == 10080
    assert out["characters"]["pc"]["detail"]["clock_minutes"] == 10080
    assert chars["pc"]["money"] == 500


def test_therapy_hl_key_addiction_validation_before_charge_and_wound_penalty():
    import pytest

    chars = {
        "doc": {
            "stats": {"TECH": 8, "MOVE": 6},
            "skills": {"Medical Tech": 6},
            "hp": 10,
            "max_hp": 30,  # Seriously Wounded (-2)
            "detail": {"roles": [{"role": "Medtech", "rank": 4}]},
        },
        "pc": {
            "stats": {"EMP": 3},
            "humanity": 20,
            "money": 1000,
            "detail": {
                "creation": {"initial_emp": 5},
                "cyberware": [{"name": "Skinweave", "hl": 7}],
                "addictions": ["Boost"],
            },
        },
    }
    # Addiction therapy for non-existent addiction raises BEFORE charging 1,000 eb
    with pytest.raises(ValueError, match="existing addiction"):
        apply_action(chars, "doc", "therapy", {"target_id": "pc", "therapy": "addiction", "addiction": "Smash"})
    assert chars["pc"]["money"] == 1000

    # Valid addiction therapy succeeds when total (8+6+die-2) > 15; die=5 -> 8+6+5-2 = 17 > 15
    cured = apply_action(chars, "doc", "therapy", {"target_id": "pc", "therapy": "addiction", "addiction": "Boost"}, lambda n: 4)
    assert cured["result"]["success"] is True
    assert cured["characters"]["pc"]["money"] == 0
    assert cured["characters"]["pc"]["detail"]["addictions"] == []

    # Standard therapy uses "hl" key on cyberware (max humanity = 50 - 2 = 48) and syncs EMP
    # Doc seriously wounded (-2): 8 + 6 + 5 - 2 = 17 > 15 -> succeeds
    std = apply_action(chars, "doc", "therapy", {"target_id": "pc", "therapy": "standard"}, lambda n: 4)
    assert std["result"]["max_humanity"] == 48
    assert std["characters"]["pc"]["humanity"] == 30
    assert std["characters"]["pc"]["stats"]["EMP"] == 3


def test_stabilize_rejects_full_hp_and_sets_mortal_unconscious_and_resets_penalty():
    import pytest

    chars = {
        "med": {
            "stats": {"TECH": 8, "MOVE": 6},
            "skills": {"Paramedic": 6},
            "hp": 30,
            "max_hp": 30,
            "detail": {"injuries": [{"id": "body:11", "name": "Crushed Fingers"}]},  # -4 hand skill
        },
        "healthy": {"stats": {"BODY": 6}, "hp": 30, "max_hp": 30, "detail": {}},
        "dying": {
            "stats": {"BODY": 6},
            "hp": 0,
            "max_hp": 30,
            "detail": {"death_save_base_penalty": 2, "death_save_penalty": 3},
        },
    }
    with pytest.raises(ValueError, match="full HP"):
        apply_action(chars, "med", "stabilize", {"target_id": "healthy"}, lambda n: 9)

    # Actor has Crushed Fingers (-4): base 8 + 6 - 4 = 10; die=5 -> 15 == DV15 -> FAILS!
    fail = apply_action(chars, "med", "stabilize", {"target_id": "dying", "skill": "Paramedic"}, lambda n: 4)
    assert fail["result"]["success"] is False

    # Die=6 -> 10 + 6 = 16 > 15 -> SUCCEEDS!
    ok = apply_action(chars, "med", "stabilize", {"target_id": "dying", "skill": "Paramedic"}, lambda n: 5)
    assert ok["result"]["success"] is True
    dying_after = ok["characters"]["dying"]
    assert dying_after["hp"] == 1
    assert dying_after["detail"]["stabilized"] is True
    assert dying_after["detail"]["conditions"]["unconscious"] is True
    assert dying_after["detail"]["death_save_penalty"] == 0


def test_injury_care_removes_quick_fix_permanent_and_scopes_cybertech():
    import pytest
    import rules_eval

    chars = {
        "med": {"stats": {"TECH": 8}, "skills": {"Paramedic": 6, "First Aid": 6, "Cybertech": 6}},
        "pc": {
            "stats": {"BODY": 6},
            "hp": 20,
            "max_hp": 30,
            "detail": {
                "clock_minutes": 100,
                "cyberware": [{"name": "Standard Cyberarm", "hl": 7}],
                "injuries": [
                    {"id": "body:7", "name": "Foreign Object"},  # Quick Fix permanently removes
                    {"id": "body:6", "name": "Broken Arm"},
                    {"id": "body:8", "name": "Broken Leg"},
                    {"id": "head:3", "name": "Brain Injury"},  # base death-save penalty +1
                    {"id": "body:4", "name": "Collapsed Lung"},  # base death-save penalty +1
                ],
            },
        },
    }
    # Cyberarm does NOT permit Cybertech on Broken Leg, Collapsed Lung, or Brain Injury
    for bad_id in ("body:8", "body:4"):
        with pytest.raises(ValueError, match="not permitted"):
            apply_action(chars, "med", "quick_fix", {"target_id": "pc", "injury_id": bad_id, "skill": "Cybertech"}, lambda n: 7)
    for bad_id in ("body:8", "head:3", "body:4"):
        with pytest.raises(ValueError, match="not permitted"):
            apply_action(chars, "med", "treat_injury", {"target_id": "pc", "injury_id": bad_id, "skill": "Cybertech"}, lambda n: 7)

    # Cyberarm DOES permit Cybertech on Broken Arm
    arm_fix = apply_action(chars, "med", "quick_fix", {"target_id": "pc", "injury_id": "body:6", "skill": "Cybertech"}, lambda n: 7)
    assert arm_fix["result"]["success"] is True

    # Quick Fix on Foreign Object permanently removes it from injuries list
    fo_fix = apply_action(chars, "med", "quick_fix", {"target_id": "pc", "injury_id": "body:7", "skill": "First Aid"}, lambda n: 7)
    assert fo_fix["result"]["success"] is True
    remaining_ids = [i["id"] for i in fo_fix["characters"]["pc"]["detail"]["injuries"]]
    assert "body:7" not in remaining_ids

    # Quick Fix on Collapsed Lung suppresses it for 1440m and updates death_save_base_penalty (from 2 to 1)
    lung_fix = apply_action(fo_fix["characters"], "med", "quick_fix", {"target_id": "pc", "injury_id": "body:4", "skill": "Paramedic"}, lambda n: 7)
    assert lung_fix["result"]["success"] is True
    assert lung_fix["characters"]["pc"]["detail"]["death_save_base_penalty"] == 1

    # Once clock advances past effect_suppressed_until, recompute restores the +1 penalty even if quick_fixed=True
    pc_expired = copy.deepcopy(lung_fix["characters"]["pc"])
    for inj in pc_expired["detail"]["injuries"]:
        if inj["id"] == "body:4":
            inj["quick_fixed"] = True
    pc_expired["detail"]["clock_minutes"] = 2000
    assert rules_eval.recompute_death_save_base_penalty(pc_expired) == 2


def test_rest_honors_effective_body_enhanced_antibodies_antibiotic_and_zero_days():
    chars = {
        "pc": {
            "stats": {"BODY": 5},
            "hp": 5,
            "max_hp": 60,
            "detail": {
                "stabilized": True,
                "clock_minutes": 0,
                "cyberware": [
                    {"name": "Implanted Linear Frame Sigma", "installed": True},
                    {"name": "Enhanced Antibodies", "installed": True},
                ],
                "pharmaceutical_effects": {
                    "Antibiotic": {"expires_at": 10080, "daily_hp": 2},
                },
            },
        }
    }
    # Effective BODY=12 * 2 (Enhanced Antibodies) + 2 (Antibiotic) = 26 HP/day -> 2 days = +52 -> 57 HP
    rested = apply_action(chars, "pc", "rest", {"days": 2, "light_activity": True})
    assert rested["characters"]["pc"]["hp"] == 57

    # Zero days with light_activity=False preserves stabilized=True
    zero = apply_action(chars, "pc", "rest", {"days": 0, "light_activity": False})
    assert zero["characters"]["pc"]["detail"]["stabilized"] is True


def test_death_save_delegates_to_rules_eval_with_base_and_escalation():
    chars = {
        "pc": {
            "stats": {"BODY": 6},
            "hp": 0,
            "max_hp": 35,
            "detail": {
                "cyberware": [{"name": "Implanted Linear Frame Sigma"}],
                "injuries": [{"id": "head:3", "name": "Brain Injury"}],
                "death_save_penalty": 1,
            },
        }
    }
    # Effective BODY=12; base=1, escalation=1 -> total=2. Die=9 -> 9+2=11 < 12 -> survives; escalation -> 2
    res = apply_action(chars, "pc", "death_save", {}, lambda n: 8)
    assert res["result"]["survived"] is True
    assert res["result"]["base_penalty"] == 1
    assert res["result"]["escalation_penalty"] == 1
    assert res["characters"]["pc"]["detail"]["death_save_penalty"] == 2
