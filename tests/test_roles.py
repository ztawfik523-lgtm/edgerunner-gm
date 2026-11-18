import pytest

import roles


def character(role, rank=4, ip=0):
    return {"stats": {}, "skills": {}, "hp": 20, "max_hp": 20, "humanity": 40,
            "money": 0, "inventory": [], "detail": {"roles": [{"role": role, "rank": rank, "choices": {}}], "ip": ip}}


def fixed(n):
    return lambda sides: n - 1


def test_role_choice_helper_is_explicit_about_unresolved_choice_catalog():
    result = roles.validate_role_choices("Tech", 4, {"maker": []})
    assert result["valid"] and result["requires_human_ruling"]
    with pytest.raises(ValueError): roles.validate_role_choices("Unknown", 4, {})
    with pytest.raises(ValueError): roles.validate_role_choices("Solo", 11, {})


def test_solo_allocation_is_bounded_and_pure():
    original = character("Solo")
    changed = roles.apply_action(original, "solo_allocate", {"allocation": {"initiative_reaction": 4}}, fixed(1))
    assert changed["character"]["detail"]["solo_allocation"] == {"initiative_reaction": 4}
    assert "solo_allocation" not in original["detail"]
    with pytest.raises(ValueError): roles.apply_action(original, "solo_allocate", {"allocation": {"initiative_reaction": 5}})


def test_rocker_check_strict_dv_success_and_failure_lock():
    c = character("Rockerboy")
    success = roles.apply_action(c, "rocker_convert", {"target_eligible": True, "group_size": "single"}, fixed(4))
    assert success["result"]["total"] == 9 and success["result"]["success"]
    failure = roles.apply_action(c, "rocker_favor", {"scope_approved": True, "group_size": "small", "group_id": "x", "now_minutes": 0}, fixed(3))
    assert not failure["result"]["success"]
    assert failure["character"]["detail"]["favor_locks"]["x"] == 10080


def test_ip_costs_ties_and_multiclass_gate():
    c = character("Solo", 4, 540)
    promoted = roles.apply_action(c, "spend_ip_role", {"role": "Solo"})
    assert promoted["result"]["rank"] == 5 and promoted["result"]["cost"] == 300
    # Rank 4 permits multiclassing; rank 1 costs 60 IP.
    c["detail"]["ip"] = 60
    multi = roles.apply_action(c, "spend_ip_role", {"role": "Nomad", "choices": {"moto": ["vehicle"]}})
    assert multi["character"]["detail"]["roles"][-1]["role"] == "Nomad"
    assert multi["result"]["rank"] == 1 and multi["result"]["cost"] == 60


def test_skill_ip_pricing_and_human_ruling_no_mutation():
    c = character("Tech", 4, 80)
    c["skills"]["Athletics"] = 3
    spent = roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 3})
    assert spent["result"]["cost"] == 80 and spent["character"]["detail"]["ip"] == 0
    result = roles.apply_action(c, "lawman_backup", {})
    assert result["result"]["requires_human_ruling"] and result["character"] == c


def test_solo_precision_cost_and_fumble_boolean_allocation():
    c = character("Solo")
    assert roles.apply_action(c, "solo_allocate", {"allocation": {"precision_attack": 1}})["result"]["spent"] == 3
    with pytest.raises(ValueError): roles.apply_action(c, "solo_allocate", {"allocation": {"fumble_recovery": 2}})


def test_lawman_backup_exact_roll_and_rounds():
    c = character("Lawman", 4)
    result = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: 5 if sides == 10 else 5)
    assert result["result"]["success"] and result["result"]["arrival_rounds"] == 6
    assert result["result"]["tier"] == 5


def test_stored_skill_rank_controls_ip_upgrade():
    c = character("Solo", ip=80)
    c["skills"]["Athletics"] = 3
    with pytest.raises(ValueError): roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 2})
    spent = roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 3})
    assert spent["result"]["rank"] == 4


def test_lawman_backup_failure_and_tier_10_two_groups():
    c = character("Lawman", 4)
    fail = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: 9)
    assert fail["result"]["success"] is False
    c = character("Lawman", 10)
    success = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: 0 if sides == 10 else 5)
    assert success["result"]["arrival_rounds"] == 6
    assert success["result"]["groups"] == 2 and success["result"]["tier"] == 10


def test_media_passive_rumor_limited_twice_weekly():
    c = character("Media")
    one = roles.apply_action(c, "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))
    assert one["result"]["total"] == 12 and one["result"]["rumor"] == "Vague"
    two = roles.apply_action(one["character"], "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))
    with pytest.raises(ValueError): roles.apply_action(two["character"], "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))


def test_fix_haggle_failure_does_not_grant_terms():
    c = character("Fixer", 10)
    c["stats"]["COOL"] = 2
    c["skills"]["Trading"] = 2
    # First d10 is 1 for the Fixer and 10 for the opponent.
    seq = iter([0, 9, 9])
    result = roles.apply_action(c, "fixer_haggle", {"transaction_id": "t1", "opponent_gm_approved": True,
        "opponent": {"COOL": 10, "Trading": 10}, "deal": "discount_10"}, lambda sides: next(seq))
    assert result["result"]["success"] is False and result["result"]["terms"] is None
