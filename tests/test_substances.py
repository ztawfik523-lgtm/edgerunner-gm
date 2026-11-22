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


def test_black_lace_initial_emp_fallback_and_rapidetox_restores_humanity():
    c = chars()
    # Remove detail.initial_emp; rely on creation.initial_emp + cyberware hl
    del c["p"]["detail"]["initial_emp"]
    c["p"]["detail"]["creation"] = {"initial_emp": 5}
    c["p"]["detail"]["cyberware"] = [{"name": "Skinweave", "hl": 7}]
    c["p"]["humanity"] = 43
    c["p"]["stats"]["EMP"] = 4
    c["doc"] = {"stats": {"TECH": 8}, "skills": {}, "inventory": {"pharma:Rapidetox": 2}, "detail": {"roles": [{"role": "Medtech", "rank": 2}]}}

    drugged = apply_action(c, "p", "street_drug", {"drug": "BlackLace"}, lambda n: 0)  # -2 humanity -> 41
    assert drugged["characters"]["p"]["humanity"] == 41
    assert effective_values(drugged["characters"]["p"])[2]["ignore_serious_wounded"] is True

    # Rapidetox before expiration purges BlackLace, prevents secondary check, and restores Humanity
    detoxed = apply_action(drugged["characters"], "doc", "pharmaceutical", {"name": "Rapidetox", "target_id": "p", "willing": True})
    assert detoxed["characters"]["p"]["humanity"] == 43
    assert detoxed["characters"]["p"]["stats"]["EMP"] == 4
    assert "drugs" not in detoxed["characters"]["p"]["detail"]


def test_speedheal_effective_body_stim_condition_clamping_and_dose_sources():
    c = chars()
    c["p"]["stats"]["INT"] = 1
    c["p"]["stats"]["REF"] = 1
    c["p"]["skills"]["Dance"] = 1
    c["p"]["detail"]["addictions"] = ["Boost", "Smash"]
    # Clamping prevents negative stats or skills
    eff_stats, eff_skills, _ = effective_values(c["p"])
    assert eff_stats["INT"] == 0
    assert eff_skills["Dance"] == 0

    # Speedheal uses effective_body (Linear Frame Sigma = 12) + WILL (6) = +18 HP
    c["p"]["detail"]["cyberware"] = [{"name": "Implanted Linear Frame Sigma"}]
    c["p"]["detail"]["roles"] = [{"role": "Medtech", "rank": 2}]
    c["p"]["detail"]["pharmaceuticals"] = {"Speedheal": 1}
    c["p"]["inventory"]["Stim"] = 1
    healed = apply_action(c, "p", "pharmaceutical", {"name": "Speedheal"})
    assert healed["characters"]["p"]["hp"] == 28  # 10 + 18
    assert healed["characters"]["p"]["detail"]["pharmaceuticals"]["Speedheal"] == 0

    # Stim consumes from inventory[name] and exposes ignore_serious_wounded in effective_values
    stimmed = apply_action(healed["characters"], "p", "pharmaceutical", {"name": "Stim"})
    assert stimmed["characters"]["p"]["inventory"]["Stim"] == 0
    assert stimmed["characters"]["p"]["detail"]["pharmaceutical_effects"]["Stim"]["ignore_serious_wounded"] is True
    assert effective_values(stimmed["characters"]["p"])[2]["ignore_serious_wounded"] is True


def test_wound_penalty_on_secondary_addiction_check_and_lifecycle_clock_hooks(tmp_path):
    from gameplay import GameplayService
    from campaign import STAT_NAMES

    # Direct substance check with wound penalty: WILL=6, Resist=4 -> base 10. Seriously Wounded (-2) -> 8.
    # Die=9 -> 8+9=17 NOT > 17 (tie fails DV17!). Without wound penalty 10+9=19 would pass.
    c = chars()
    c = apply_action(c, "p", "street_drug", {"drug": "BlackLace"}, lambda n: 0)["characters"]
    out = apply_action(c, "p", "advance_time", {"minutes": 1440}, lambda n: 8)
    assert out["result"]["expired_drug_checks"][0]["success"] is False
    assert "BlackLace" in out["characters"]["p"]["detail"]["addictions"]

    # SoloService advance_campaign_clock fires expirations across advance_time, health_action, economy_action, substance_action
    svc = GameplayService(tmp_path / "camp.sqlite")
    camp = svc.execute("create_campaign", {"name": "Drugs", "operation_id": "c1"})["result"]
    pc = svc.execute("create_character", {
        "name": "Runner",
        "stats": dict.fromkeys(STAT_NAMES, 6),
        "skills": {"Resist Torture/Drugs": 4},
        "inventory": {"drug:Boost": 3, "drug:Smash": 3},
        "detail": {"roles": [{"role": "Solo", "rank": 4}], "stabilized": True},
        "operation_id": "ch1",
    })["result"]
    pc = svc.store.update_character(pc["id"], pc["revision"], {"hp": 10}, "hurt", "hurt1")
    svc.execute("attach_character", {"campaign_id": camp["id"], "character_id": pc["id"], "expected_revision": camp["revision"], "reason": "join", "operation_id": "att1"})
    rev = svc.campaign_context(camp["id"])["solo"]["revision"]

    # 1. Take Boost (duration 1440m) then advance time via health_action (rest 1 day = 1440m) -> expires Boost!
    r1 = svc.execute("substance_action", {"actor_id": pc["id"], "action": "street_drug", "arguments": {"drug": "Boost"}, "expected_revision": rev, "reason": "boost", "operation_id": "op1"}, campaign_id=camp["id"])["result"]
    r2 = svc.execute("health_action", {"actor_id": pc["id"], "action": "rest", "arguments": {"days": 1, "light_activity": True}, "expected_revision": r1["revision"], "reason": "rest", "operation_id": "op2"}, campaign_id=camp["id"])["result"]
    assert r2["result"]["expired_drug_checks"][0]["drug"] == "Boost"
    assert svc.campaign_context(camp["id"])["solo"]["runtime"]["clock_minutes"] == 1440

    # 2. Take Smash (duration 240m) then advance via economy_action (hustle = 10080m) -> expires Smash & syncs runtime clock!
    r3 = svc.execute("substance_action", {"actor_id": pc["id"], "action": "street_drug", "arguments": {"drug": "Smash"}, "expected_revision": r2["revision"], "reason": "smash", "operation_id": "op3"}, campaign_id=camp["id"])["result"]
    r4 = svc.execute("economy_action", {"character_id": pc["id"], "action": "hustle", "arguments": {"role": "Solo", "free_days": 7}, "expected_revision": r3["revision"], "reason": "hustle", "operation_id": "op4"}, campaign_id=camp["id"])["result"]
    assert r4["result"]["expired_drug_checks"][0]["drug"] == "Smash"
    assert svc.campaign_context(camp["id"])["solo"]["runtime"]["clock_minutes"] == 1440 + 10080
