import pytest

from mechanics import opposed_check, roll_dice, skill_check


def fixed(*values):
    values = iter(values)
    return lambda stop: next(values)


def test_skill_check_strictly_exceeds_dv_and_has_bonus_breakdown():
    result = skill_check(5, None, 9, modifier=-1, luck=2, complementary=True,
                         extra_time=True, randbelow=fixed(1))
    assert result == {
        "dice": [2], "base": 5, "critical_adjustment": 0, "modifier": -1,
        "luck_bonus": 2, "complementary_bonus": 1, "extra_time_bonus": 1,
        "total": 10, "dv": 9, "success": True,
        "source": "Cyberpunk RED Core Rulebook, pp. 129–130",
    }
    assert not skill_check(0, 0, 2, randbelow=fixed(1))["success"]


def test_critical_10_adds_one_nonrecursive_die():
    result = skill_check(0, 0, 19, randbelow=fixed(9, 9))
    assert result["dice"] == [10, 10]
    assert result["critical_adjustment"] == 10
    assert result["success"]


def test_critical_1_subtracts_one_nonrecursive_die_and_not_automatic_failure():
    result = skill_check(100, 100, 1, randbelow=fixed(0, 9))
    assert result["dice"] == [1, 10]
    assert result["critical_adjustment"] == -10
    assert result["success"]


def test_opposed_tie_is_defender_win():
    result = opposed_check({"stat": 4, "skill": 2, "dv": 0},
                           {"stat": 5, "skill": 1, "dv": 0}, fixed(4, 4))
    assert result["attacker"]["total"] == result["defender"]["total"]
    assert not result["attacker_wins"]


@pytest.mark.parametrize("args", [(-1, 1, 2), (101, 0, 2), (0, 0, -1),
                                   (True, 0, 2), (0, True, 2)])
def test_invalid_check_inputs(args):
    with pytest.raises((TypeError, ValueError)):
        skill_check(*args, randbelow=fixed(0))


@pytest.mark.parametrize("value", [True, -1, 101])
def test_invalid_roll_arguments(value):
    with pytest.raises((TypeError, ValueError)):
        roll_dice(value, 10, fixed(0))


@pytest.mark.parametrize("result", [-1, 10, True, 1.5])
def test_invalid_random_source_values(result):
    with pytest.raises((TypeError, ValueError)):
        roll_dice(1, 10, lambda stop: result)


def test_rolls_bounded_dice():
    assert roll_dice(3, 6, fixed(0, 2, 5)) == [1, 3, 6]
