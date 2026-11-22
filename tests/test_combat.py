import pytest

from combat import (
    attack_check, brawling_dice, critical_injury, daily_heal, damage_and_armor,
    death_save, initiative, stabilize_check, wound_state,
)


def fixed(*values):
    it = iter(values)
    return lambda stop: next(it)


def test_initiative_plain_d10_and_validation():
    assert initiative(8, randbelow=fixed(9))["total"] == 18
    with pytest.raises(TypeError):
        initiative(True, randbelow=fixed(0))


def test_wound_thresholds():
    # Per Corebook p. 221: Light at >= 1/2 max HP, Serious at < 1/2 max HP
    assert wound_state(5, 10, 6)["name"] == "light"   # exactly half = light
    assert wound_state(4, 10, 6)["name"] == "serious"  # below half = serious
    assert wound_state(0, 10, 6) == {
        "name": "mortal", "action_penalty": -4, "move": 1,
        "source": "Cyberpunk RED Core Rulebook, p. 221",
    }


def test_attack_check_uses_standard_skill_check():
    result = attack_check(8, 6, 15, randbelow=fixed(1))
    assert result["total"] == 16 and result["success"]


def test_melee_armor_rounds_sp_down_and_does_not_mutate():
    armor = [{"id": "vest", "sp": 11}]
    out = damage_and_armor([6], armor, melee=True)
    assert out["effective_sp"] == 5
    assert out["penetration"] == 1 and out["armor_after"][0]["sp"] == 10
    assert armor[0]["sp"] == 11


def test_highest_armor_only_head_and_critical_bonus():
    out = damage_and_armor([6, 6], [{"id": "a", "sp": 4}, {"id": "b", "sp": 8}], location="head")
    # Head shot: penetration (12-8=4) * 2 = 8, critical bonus +5 = 13
    assert out["critical_trigger"] and out["hp_damage"] == 13
    assert out["armor_after"] == [{"id": "a", "sp": 4}, {"id": "b", "sp": 7}]


def test_autofire_raw_damage_and_brawling_dice():
    # Autofire: 2 dice, margin 4, cap 3 -> min(4,3)=3 hits, raw = (3+4)*3 = 21
    out = damage_and_armor([3, 4], [], autofire_margin=4, autofire_cap=3)
    assert out["raw"] == 21
    # Brawling dice by BODY
    assert brawling_dice(4, cyberarm=True) == 2
    assert brawling_dice(11, martial_arts=True) == 4


def test_death_save_natural_ten_fails_and_penalty_increments():
    result = death_save(body=2, penalty=2, randbelow=fixed(9))
    assert result["dead"] and result["next_penalty"] == 3


def test_stabilization_dv_and_rest_healing():
    # skill_check rolls 1d10, then on 1 or 10 rolls again for critical adjustment.
    # fixed(0, 0) provides two values: initial=0->roll=1, further=0->adjustment=-1
    assert stabilize_check(10, 2, "serious", randbelow=fixed(0, 0))["dv"] == 13
    assert daily_heal(5, 20, 4, True, True)["new_hp"] == 9
    assert daily_heal(5, 20, 4, False, True)["new_hp"] == 5


def test_body_critical_table_outcome_and_existing_injury_reroll():
    result = critical_injury("body", [], randbelow=fixed(0))
    assert result["name"] == "Dismembered Arm"
    assert result["dice"] == [1, 1] and result["bonus_damage"] == 5
    rerolled = critical_injury("body", ["Dismembered Arm"], randbelow=fixed(0))
    assert rerolled["name"] == "Dismembered Hand"
    assert rerolled["dice"] == [1, 2]


def test_head_critical_table_metadata_and_exhaustion():
    result = critical_injury("head", [], randbelow=fixed(0))
    assert result["name"] == "Lost Eye"
    assert result["quick_fix"] == "N/A" and result["treatment"] == "Surgery DV17"
    all_head = [
        "Lost Eye", "Brain Injury", "Damaged Eye", "Concussion", "Broken Jaw",
        "Foreign Object", "Whiplash", "Cracked Skull", "Damaged Ear",
        "Crushed Windpipe", "Lost Ear",
    ]
    assert critical_injury("head", all_head)["requires_human_ruling"]
