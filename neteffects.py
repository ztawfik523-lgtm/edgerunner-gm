"""Resolve canonical NET program effects into explicit run and character state."""
from __future__ import annotations

import copy
import secrets
from typing import Any

import mechanics


def _has_hardware(run: dict[str, Any], hw_name: str) -> bool:
    items = list(run.get("deck", {}).get("hardware", []) or []) + list(run.get("hardware", []) or [])
    for item in items:
        if item == hw_name or (isinstance(item, dict) and item.get("name") == hw_name):
            return True
    return False


def _is_active_prog(prog: dict[str, Any], name: str | None = None) -> bool:
    return (
        (name is None or prog.get("name") == name)
        and bool(prog.get("active"))
        and int(prog.get("rez", 0) or 0) > 0
        and not bool(prog.get("destroyed"))
    )


def resolve_effect(name: str, run: dict[str, Any], *, target_program_id: str | None = None,
                   randbelow=secrets.randbelow, black_ice: bool = True) -> dict[str, Any]:
    """Resolve a program effect; caller remains responsible for attack/target checks."""
    from netrunning import PROGRAMS  # lazy to avoid netrunning's mechanics dependency cycle

    if name not in PROGRAMS:
        raise ValueError(f"unknown/noncanonical program: {name}")
    if not callable(randbelow):
        raise TypeError("randbelow must be callable")
    result = copy.deepcopy(run)
    effects: list[dict[str, Any]] = []
    dice: list[int] = []
    forced_exit = None
    programs = result.get("deck", {}).get("programs", [])
    conds = result.setdefault("conditions", {})

    def roll(n):
        nonlocal dice
        values = mechanics.roll_dice(n, 6, randbelow)
        dice.extend(values)
        return sum(values)

    def damage(n, brain=True):
        amount = roll(n)
        if brain:
            if not black_ice:
                shield = next((p for p in programs if _is_active_prog(p, "Shield")), None)
                if shield is not None:
                    shield["active"] = False
                    shield["rez"] = 0
                    amount = 0
            if any(_is_active_prog(p, "Armor") for p in programs):
                amount = max(0, amount - 4)
            effects.append({"type": "damage", "amount": amount, "damage_type": "brain"})
        else:
            effects.append({"type": "damage", "amount": amount, "damage_type": "physical"})

    def destroy_or_derez(victim: dict[str, Any], destroy: bool) -> None:
        if destroy:
            if name == "Poison Flatline" and _has_hardware(result, "Hardened Circuitry"):
                victim["active"] = False
                victim["rez"] = 0
            else:
                victim["destroyed"] = True
                victim["active"] = False
                victim["rez"] = 0
        else:
            victim["active"] = False
            victim["rez"] = 0

    def random_program(candidates, destroy):
        if not candidates:
            return
        p = randbelow(len(candidates))
        if isinstance(p, bool):
            raise ValueError("randbelow returned invalid result")
        if not isinstance(p, int) or not 0 <= p < len(candidates):
            raise ValueError("randbelow returned invalid result")
        destroy_or_derez(candidates[p], destroy)

    if name in ("Hellhound", "Hellbolt"):
        damage(2)
        if not _has_hardware(result, "Insulated Wiring"):
            effects.append({"type": "condition", "name": "burning", "value": True, "duration": "until extinguished"})
            effects.append({"type": "damage", "amount": 2, "damage_type": "physical", "timing": "end_of_turn"})
    elif name == "Giant":
        damage(3)
        if not _has_hardware(result, "KRASH Barrier"):
            forced_exit = {"safe": False, "exclude_self": True, "program": name}
    elif name == "Kraken":
        damage(3)
        conds["cannot_move"] = True
        conds["cannot_progress"] = True
        conds["cannot_jack_out"] = True
        conds["cannot_move_turns"] = max(int(conds.get("cannot_move_turns") or 0), 2)
        conds["cannot_jack_out_turns"] = max(int(conds.get("cannot_jack_out_turns") or 0), 2)
        conds["safe_exit_blocked"] = max(int(conds.get("safe_exit_blocked") or 0), 2)
        conds["net_movement_block"] = name
        effects.append({"type": "condition", "name": "net_movement_block", "value": name,
                        "source": next((p.get("id") for p in programs if p.get("name") == name), name),
                        "blocks": ["deeper", "safe_exit"], "duration": "until_end_of_next_turn"})
    elif name in ("Wisp", "Vrizzbolt"):
        damage(1)
        conds["next_turn_action_penalty"] = 1
        effects.append({"type": "condition", "name": "next_turn_action_penalty", "value": 1, "minimum_budget": 2, "duration": "next_turn"})
    elif name == "Asp":
        candidates = [p for p in programs if not p.get("destroyed")]
        if target_program_id is not None:
            victim = next((p for p in candidates if p.get("instance_id") == target_program_id), None)
            if victim is not None:
                destroy_or_derez(victim, True)
            else:
                random_program(candidates, True)
        else:
            random_program(candidates, True)
    elif name == "Poison Flatline":
        random_program([p for p in programs if p.get("type") != "Black ICE" and not p.get("destroyed")], True)
    elif name in ("Liche", "Nervescrub"):
        amount = roll(1)
        effects.extend({"type": "condition", "name": stat, "value": amount, "duration": "1 hour", "minimum": 1} for stat in ("INT", "REF", "DEX"))
    elif name == "Scorpion":
        effects.append({"type": "condition", "name": "MOVE", "value": roll(1), "duration": "1 hour", "minimum": 1})
    elif name == "Skunk":
        conds["slide_penalty"] = -2
        effects.append({"type": "condition", "name": "slide_penalty", "value": -2, "duration": "while_source_rezzed", "source": name})
    elif name == "Raven":
        random_program([p for p in programs if p.get("type") == "Defender" and _is_active_prog(p)], False)
        damage(1)
    elif name == "Superglue":
        rounds = roll(1)
        conds["cannot_move"] = True
        conds["cannot_progress"] = True
        conds["cannot_jack_out"] = True
        conds["cannot_move_turns"] = max(int(conds.get("cannot_move_turns") or 0), rounds)
        conds["cannot_jack_out_turns"] = max(int(conds.get("cannot_jack_out_turns") or 0), rounds)
        conds["safe_exit_blocked"] = max(int(conds.get("safe_exit_blocked") or 0), rounds)
        conds["net_movement_block"] = name
        effects.append({"type": "condition", "name": "net_movement_block", "value": name,
                        "source": next((p.get("id") for p in programs if p.get("name") == name), name),
                        "duration": f"{rounds} rounds", "blocks": ["deeper", "safe_exit"], "once_per_run": True})
    elif name in ("Dragon", "Sabertooth", "Killer", "Banhammer", "Sword"):
        if target_program_id is None:
            if not any(not p.get("destroyed") for p in programs):
                return {"run": result, "character_effects": [], "forced_exit": None, "dice": []}
            return {"run": copy.deepcopy(run), "character_effects": [], "forced_exit": None, "dice": [], "requires_human_ruling": True, "reason": "anti-program effect requires a valid target program"}
        victim = next((p for p in programs if p.get("instance_id") == target_program_id and not p.get("destroyed")), None)
        if victim is None:
            return {"run": copy.deepcopy(run), "character_effects": [], "forced_exit": None, "dice": [], "requires_human_ruling": True, "reason": "target program not found"}
        ice = victim.get("type") == "Black ICE"
        count = {"Dragon": 6, "Sabertooth": 6, "Killer": 4}.get(
            name, 3 if (name == "Banhammer" and not ice) or (name == "Sword" and ice) else 2)
        amount = roll(count)
        if amount >= victim.get("rez", 0):
            if name in ("Dragon", "Sabertooth", "Killer"):
                victim.update(rez=0, destroyed=True, active=False)
            else:
                victim.update(rez=0, active=False)
        else:
            victim["rez"] -= amount
    elif name == "DeckKRASH":
        if not _has_hardware(result, "KRASH Barrier"):
            forced_exit = {"safe": False, "exclude_self": False, "program": name}
    else:
        raise ValueError(f"effect not implemented: {name}")
    return {"run": result, "character_effects": effects, "forced_exit": forced_exit, "dice": dice}
