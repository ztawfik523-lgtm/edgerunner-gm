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
