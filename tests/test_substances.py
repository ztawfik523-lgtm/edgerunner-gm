import copy

import pytest

from substances import apply_action, effective_values


def chars():
    return {"p": {"stats": {"INT": 5, "REF": 6, "WILL": 6, "BODY": 5, "EMP": 5},
                  "skills": {"Resist Torture/Drugs": 4, "Dance": 2}, "humanity": 50,
                  "max_hp": 30, "hp": 10, "inventory": {
                      "drug:BlackLace": 4, "drug:Boost": 4, "drug:Smash": 4,
                      "drug:BlueGlass": 4, "drug:Synthcoke": 4},
                  "detail": {"initial_emp": 5, "clock_minutes": 0}}}


def test_primary_effects_and_repeated_doses_extend_without_mutating_base():
    original = chars()
    one = apply_action(original, "p", "street_drug", {"drug": "Boost"}, lambda n: 0)
    assert effective_values(one["characters"]["p"])[0]["INT"] == 7
    two = apply_action(one["characters"], "p", "street_drug", {"drug": "Boost"}, lambda n: 0)
    assert two["characters"]["p"]["detail"]["drugs"]["Boost"]["expires_at"] == 2880
    assert two["characters"]["p"]["stats"]["INT"] == 5
    smash = apply_action(original, "p", "street_drug", {"drug": "Smash"}, lambda n: 0)
    assert effective_values(smash["characters"]["p"])[1]["Dance"] == 4
    assert original["p"]["inventory"]["drug:Boost"] == 4


def test_secondary_addiction_and_rehab_automatic_failure():
    c = chars()
    c["p"]["detail"]["rehab_auto_fail_until"] = {"Boost": 1000}
    c = apply_action(c, "p", "street_drug", {"drug": "Boost"}, lambda n: 0)["characters"]
    out = apply_action(c, "p", "advance_time", {"minutes": 1440}, lambda n: 0)
    check = out["result"]["expired_drug_checks"][0]
    assert check["automatic_failure"]
    assert "Boost" in out["characters"]["p"]["detail"]["addictions"]
    assert effective_values(out["characters"]["p"])[0]["INT"] == 3


def test_black_lace_humanity_loss_is_returned_only_on_secondary_pass():
    c = chars()
    # 2d6 totals 2; secondary check is 10 + 4 + 1 and passes DV17.
    c = apply_action(c, "p", "street_drug", {"drug": "BlackLace"}, lambda n: 0)["characters"]
    assert c["p"]["humanity"] == 48
    out = apply_action(c, "p", "advance_time", {"minutes": 1440}, lambda n: 9)
    assert out["characters"]["p"]["humanity"] == 50
    assert not out["characters"]["p"]["detail"]["addictions"]


def test_unwilling_and_pharma_role_and_target_consent_restrictions():
    c = chars()
    with pytest.raises(ValueError): apply_action(c, "p", "street_drug", {"drug": "Boost", "target_id": "p", "willing": False})
    c["p"]["inventory"]["pharma:Speedheal"] = 1
    with pytest.raises(ValueError): apply_action(c, "p", "pharmaceutical", {"name": "Speedheal"})
    c["doc"] = {"stats": {"TECH": 8}, "skills": {}, "inventory": {}, "detail": {"roles": [{"role": "Medtech", "rank": 1}]}}
    c["p"]["inventory"]["pharma:Stim"] = 1
    with pytest.raises(ValueError): apply_action(c, "doc", "pharmaceutical", {"name": "Stim", "target_id": "p"})
    assert c["p"]["inventory"]["pharma:Stim"] == 1
