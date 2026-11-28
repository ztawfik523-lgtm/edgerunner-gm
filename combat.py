"""Pure Cyberpunk RED combat and recovery primitives (Core Rulebook pp. 168, 186–188, 221–223)."""
import secrets
from collections.abc import Callable
from typing import Any

from mechanics import skill_check
import sourcecatalog

SOURCE = "Cyberpunk RED Core Rulebook, pp. 168, 176–177, 186–188, 221–223"


def _int(name, value, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < low or (high is not None and value > high):
        raise ValueError(f"{name} out of range")
    return value


def _bool(name, value):
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")


def _die(randbelow):
    if not callable(randbelow):
        raise TypeError("randbelow must be callable")
    n = randbelow(10)
    _int("randbelow result", n, 0, 9)
    return n + 1


def initiative(ref, bonus=0, randbelow=secrets.randbelow):
    _int("ref", ref); _int("bonus", bonus, low=-100)
    dice = [_die(randbelow)]
    return {"dice": dice, "total": ref + bonus + dice[0], "source": "Cyberpunk RED Core Rulebook, p. 168"}


def wound_state(hp, max_hp, move):
    _int("max_hp", max_hp, 1); _int("hp", hp, -1_000_000); _int("move", move)
    if hp < 1:
        name, penalty, movement = "mortal", -4, (0 if move == 0 else max(1, move - 6))
    elif hp < (max_hp + 1) // 2:
        name, penalty, movement = "serious", -2, move
    elif hp < max_hp:
        name, penalty, movement = "light", 0, move
    else:
        name, penalty, movement = "healthy", 0, move
    return {"name": name, "action_penalty": penalty, "move": movement, "source": "Cyberpunk RED Core Rulebook, p. 221"}


def attack_check(stat, skill, dv, modifier=0, luck=0, randbelow=secrets.randbelow):
    result = skill_check(stat, skill, dv, modifier=modifier, luck=luck, randbelow=randbelow)
    result["source"] = "Cyberpunk RED Core Rulebook, pp. 129–130, 172"
    return result


def damage_and_armor(dice: list, armor: list, location="body", melee=False, martial_arts=False,
                     brawling=False, autofire_margin=None, autofire_cap=None, cracked_skull=False,
                     ablation: int = 1):
    for name, flag in (("melee", melee), ("martial_arts", martial_arts), ("brawling", brawling), ("cracked_skull", cracked_skull)):
        _bool(name, flag)
    _int("ablation", ablation, 0)
    if not isinstance(dice, list) or not dice: raise ValueError("dice must be a non-empty list")
    for d in dice: _int("damage die", d, 1, 6)
    if not isinstance(armor, list): raise TypeError("armor must be a list")
    if location not in ("body", "head"): raise ValueError("location must be body or head")
    if sum((melee, martial_arts, brawling)) > 1: raise ValueError("incompatible attack flags")
    if (autofire_margin is None) != (autofire_cap is None): raise ValueError("autofire margin and cap must be supplied together")
    if autofire_margin is not None:
        _int("autofire_margin", autofire_margin, 1)
        if autofire_cap not in (3, 4, 5): raise ValueError("autofire cap must be 3, 4, or 5")
        if melee or martial_arts or brawling or location == "head": raise ValueError("autofire cannot be melee or aimed")
        if len(dice) != 2: raise ValueError("autofire requires exactly two dice")
    ids, pieces = set(), []
    for item in armor:
        if not isinstance(item, dict) or "id" not in item or "sp" not in item: raise ValueError("armor items require id and sp")
        if item["id"] in ids: raise ValueError("armor ids must be unique")
        ids.add(item["id"]); _int("armor sp", item["sp"]); pieces.append(item)
    selected = max(pieces, key=lambda p: p["sp"], default=None)
    sp = selected["sp"] if selected else 0
    raw = sum(dice)
    if autofire_margin is not None: raw *= min(autofire_margin, autofire_cap)
    effective = sp if brawling else ((sp + 1) // 2 if melee or martial_arts else sp)
    penetration = max(0, raw - effective)
    multiplier = (3 if cracked_skull else 2) if location == "head" else 1
    hp_damage = penetration * multiplier + (5 if sum(d == 6 for d in dice) >= 2 else 0)
    # Corebook p. 184: highest SP protects, but all worn armor layers in the hit location ablate together.
    armor_after = [
        dict(piece, sp=max(0, piece["sp"] - ablation) if penetration > 0 else piece["sp"])
        for piece in armor
    ]
    return {"raw": raw, "effective_sp": effective, "penetration": penetration, "hp_damage": hp_damage,
            "critical_trigger": sum(d == 6 for d in dice) >= 2, "armor_after": armor_after, "source": "Cyberpunk RED Core Rulebook, pp. 174, 176–177, 186–188"}


def critical_injury(location, existing, rules_path, randbelow=secrets.randbelow):
    if location not in ("body", "head"): raise ValueError("location must be body or head")
    if not isinstance(existing, list) or any(not isinstance(x, str) for x in existing): raise TypeError("existing must be a list of names")
    table = sourcecatalog.critical_injuries(rules_path)[location]
    available = [roll for roll, injury in table.items() if injury["name"] not in existing]
    if not available:
        return {"requires_human_ruling": True, "location": location, "reason": "Every injury on this location's table is already present; the rules say to reroll until a new injury, so no eligible outcome remains.", "source": "Cyberpunk RED Core Rulebook, pp. 187–188"}
    if not callable(randbelow): raise TypeError("randbelow must be callable")
    # Uniformly choose among the 36 equally likely ordered 2d6 outcomes, conditioned
    # on not selecting an already-present injury. This is equivalent to rerolling
    # duplicates but always terminates.
    allowed = [pair for pair in ((a, b) for a in range(1, 7) for b in range(1, 7)) if pair[0] + pair[1] in available]
    n = randbelow(len(allowed))
    _int("randbelow result", n, 0, len(allowed) - 1)
    dice = list(allowed[n])
    roll = sum(dice)
    return {**table[roll], "dice": dice, "bonus_damage": 5,
            "source": "Cyberpunk RED Core Rulebook, pp. 187–188, 223"}


def death_save(body, penalty=0, randbelow=secrets.randbelow):
    _int("body", body); _int("penalty", penalty)
    die = _die(randbelow)
    survived = die != 10 and die + penalty < body
    return {"survived": survived, "dead": not survived, "dice": [die], "next_penalty": penalty + 1, "source": "Cyberpunk RED Core Rulebook, p. 222"}


def stabilize_check(tech, skill, wound, modifier=0, randbelow=secrets.randbelow):
    dvs = {"light": 10, "serious": 13, "mortal": 15}
    if wound not in dvs: raise ValueError("wound must be light, serious, or mortal")
    return skill_check(tech, skill, dvs[wound], modifier=modifier, randbelow=randbelow)


def daily_heal(hp, max_hp, body, stabilized, rested):
    _int("hp", hp, -1_000_000); _int("max_hp", max_hp, 1); _int("body", body); _bool("stabilized", stabilized); _bool("rested", rested)
    if hp > max_hp: raise ValueError("hp cannot exceed max_hp")
    if not stabilized or not rested: return {"new_hp": hp, "stabilized": stabilized and rested, "source": "Cyberpunk RED Core Rulebook, pp. 222–223"}
    if hp < 1: raise ValueError("mortal stabilization is an explicit stabilization check, not daily healing")
    return {"new_hp": min(max_hp, hp + body), "stabilized": True, "source": "Cyberpunk RED Core Rulebook, pp. 222–223"}


def brawling_dice(body, cyberarm=False, martial_arts=False):
    _int("body", body); _bool("cyberarm", cyberarm); _bool("martial_arts", martial_arts)
    if cyberarm and martial_arts: raise ValueError("cyberarm applies to brawling, not martial arts")
    return 4 if body >= 11 else 3 if body >= 7 else 2 if body >= 5 or cyberarm else 1
