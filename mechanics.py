"""Deterministic, evidence-based Cyberpunk RED skill-check mechanics.

Rules reference: Cyberpunk RED Core Rulebook, pp. 129–130.
"""

import secrets
from collections.abc import Callable
from typing import Any


def _integer(name: str, value: Any, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ValueError(f"{name} must be {bound}")
    return value


def _die(sides: int, randbelow: Callable[[int], int]) -> int:
    result = randbelow(sides)
    _integer("randbelow result", result, 0, sides - 1)
    return result + 1


def roll_dice(count: int, sides: int, randbelow: Callable[[int], int] = secrets.randbelow) -> list[int]:
    """Roll bounded dice using an injectable randbelow(stop) source."""
    _integer("count", count, 1, 100)
    _integer("sides", sides, 2, 1000)
    if not callable(randbelow):
        raise TypeError("randbelow must be callable")
    return [_die(sides, randbelow) for _ in range(count)]


def _check_inputs(stat: int, skill: int | None, dv: int, modifier: int,
                  luck: int, complementary: bool, extra_time: bool) -> int:
    _integer("stat", stat, 0, 100)
    _integer("skill", 0 if skill is None else skill, 0, 100)
    _integer("dv", dv, 0)
    _integer("modifier", modifier, -100, 100)
    _integer("luck", luck, 0, 100)
    if not isinstance(complementary, bool):
        raise TypeError("complementary must be a bool")
    if not isinstance(extra_time, bool):
        raise TypeError("extra_time must be a bool")
    return 0 if skill is None else skill


def skill_check(stat: int, skill: int | None, dv: int, modifier: int = 0,
                luck: int = 0, complementary: bool = False,
                extra_time: bool = False,
                randbelow: Callable[[int], int] = secrets.randbelow) -> dict[str, Any]:
    """Resolve a check. Caller must validate and atomically deduct LUCK pool."""
    skill_value = _check_inputs(stat, skill, dv, modifier, luck, complementary, extra_time)
    initial = roll_dice(1, 10, randbelow)[0]
    dice = [initial]
    critical_adjustment = 0
    if initial == 10:
        further = roll_dice(1, 10, randbelow)[0]
        dice.append(further)
        critical_adjustment = further
    elif initial == 1:
        further = roll_dice(1, 10, randbelow)[0]
        dice.append(further)
        critical_adjustment = -further
    complementary_bonus = int(complementary)
    extra_time_bonus = int(extra_time)
    base = stat + skill_value
    total = base + initial + critical_adjustment + modifier + complementary_bonus + extra_time_bonus + luck
    return {
        "dice": dice,
        "base": base,
        "critical_adjustment": critical_adjustment,
        "modifier": modifier,
        "luck_bonus": luck,
        "complementary_bonus": complementary_bonus,
        "extra_time_bonus": extra_time_bonus,
        "total": total,
        "dv": dv,
        "success": total > dv,
        "source": "Cyberpunk RED Core Rulebook, pp. 129–130",
    }


def opposed_check(attacker: dict[str, Any], defender: dict[str, Any],
                  randbelow: Callable[[int], int] = secrets.randbelow) -> dict[str, Any]:
    """Resolve two standard checks; defender wins a tie."""
    attacker_result = skill_check(**attacker, randbelow=randbelow)
    defender_result = skill_check(**defender, randbelow=randbelow)
    return {
        "attacker": attacker_result,
        "defender": defender_result,
        "attacker_wins": attacker_result["total"] > defender_result["total"],
        "source": "Cyberpunk RED Core Rulebook, p. 129",
    }
