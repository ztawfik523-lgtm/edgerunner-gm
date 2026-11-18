"""Pure encounter orchestration; combat results use canonical Core Rulebook data."""
from __future__ import annotations

import copy
import secrets
from typing import Callable

from combat import initiative, wound_state, death_save, attack_check, damage_and_armor, critical_injury, brawling_dice
from mechanics import roll_dice

SOURCE = "Cyberpunk RED Core Rulebook, pp. 168–177, 186–188, 221–222"

# Numeric weapon facts (printed pp. 171–174); no descriptive price prose.
WEAPONS = {
    "Medium Pistol": {"range": "pistol", "skill": "Handgun", "damage": (2, 6), "magazine": 12, "ammo": "M Pistol", "rof": 2, "hands": 1},
    "Heavy Pistol": {"range": "pistol", "skill": "Handgun", "damage": (3, 6), "magazine": 8, "ammo": "H Pistol", "rof": 2, "hands": 1},
    "Very Heavy Pistol": {"range": "pistol", "skill": "Handgun", "damage": (4, 6), "magazine": 8, "ammo": "VH Pistol", "rof": 1, "hands": 1},
    "SMG": {"range": "smg", "skill": "Handgun", "damage": (2, 6), "magazine": 30, "ammo": "M Pistol", "rof": 1, "hands": 1, "autofire": 3},
    "Heavy SMG": {"range": "smg", "skill": "Handgun", "damage": (3, 6), "magazine": 40, "ammo": "H Pistol", "rof": 1, "hands": 1, "autofire": 3},
    "Shotgun": {"range": "shotgun", "skill": "Shoulder Arms", "damage": (5, 6), "magazine": 4, "ammo": "Slug", "rof": 1, "hands": 2},
    "Assault Rifle": {"range": "assault_rifle", "skill": "Shoulder Arms", "damage": (5, 6), "magazine": 25, "ammo": "Rifle", "rof": 1, "hands": 2, "autofire": 4},
    "Sniper Rifle": {"range": "sniper_rifle", "skill": "Shoulder Arms", "damage": (5, 6), "magazine": 4, "ammo": "Rifle", "rof": 1, "hands": 2},
    "Bows & Crossbows": {"range": "bow", "skill": "Archery", "damage": (4, 6), "magazine": None, "ammo": "Arrow", "rof": 1, "hands": 2},
    "Grenade Launcher": {"range": "grenade_launcher", "skill": "Heavy Weapons", "damage": (6, 6), "magazine": 2, "ammo": "Grenade", "rof": 1, "hands": 2},
    "Rocket Launcher": {"range": "rocket_launcher", "skill": "Heavy Weapons", "damage": (8, 6), "magazine": 1, "ammo": "Rocket", "rof": 1, "hands": 2},
    "Light Melee Weapon": {"melee": True, "damage": (1, 6), "rof": 2, "hands": None},
    "Medium Melee Weapon": {"melee": True, "damage": (2, 6), "rof": 2, "hands": None},
    "Heavy Melee Weapon": {"melee": True, "damage": (3, 6), "rof": 2, "hands": None},
    "Very Heavy Melee Weapon": {"melee": True, "damage": (4, 6), "rof": 1, "hands": None},
}

# Exotic Weapon profiles (Corebook pp. 347–350)
EXOTIC_WEAPONS = {
    "Air Pistol": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 12, "ammo": "M Pistol", "rof": 2, "hands": 1},
    "Battleglove": {"melee": True, "damage": (2, 6), "rof": 2, "hands": 1},
    "Constitution Arms Hurricane": {"range": "shotgun", "skill": "Shoulder Arms", "damage": (5, 6), "magazine": 16, "ammo": "Slug", "rof": 2, "hands": 2},
    "Constitution Arms Hurricane Assault Weapon": {"range": "shotgun", "skill": "Shoulder Arms", "damage": (5, 6), "magazine": 16, "ammo": "Slug", "rof": 2, "hands": 2},
    "Dartgun": {"range": "pistol", "skill": "Handgun", "damage": (4, 6), "magazine": 8, "ammo": "Arrow", "rof": 1, "hands": 1},
    "Flamethrower": {"range": "shotgun", "skill": "Heavy Weapons", "damage": (5, 6), "magazine": 4, "ammo": "Slug", "rof": 1, "hands": 2},
    "Helix": {"range": "assault_rifle", "skill": "Autofire", "damage": (2, 6), "magazine": 40, "ammo": "Rifle", "rof": 1, "hands": 2, "autofire": 5},
    "Tsunami Arms Helix": {"range": "assault_rifle", "skill": "Autofire", "damage": (2, 6), "magazine": 40, "ammo": "Rifle", "rof": 1, "hands": 2, "autofire": 5},
    "Kendachi Mono-Three": {"melee": True, "damage": (4, 6), "rof": 1, "hands": 2},
    "Malorian Arms 3516": {"range": "pistol", "skill": "Handgun", "damage": (5, 6), "magazine": 8, "ammo": "VH Pistol", "rof": 1, "hands": 1},
    "Microwaver": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 8, "ammo": "Battery", "rof": 1, "hands": 1},
    "Militech \"Cowboy\" U-56 Grenade Launcher": {"range": "grenade_launcher", "skill": "Heavy Weapons", "damage": (6, 6), "magazine": 4, "ammo": "Grenade", "rof": 2, "hands": 2},
    "Militech Cowboy": {"range": "grenade_launcher", "skill": "Heavy Weapons", "damage": (6, 6), "magazine": 4, "ammo": "Grenade", "rof": 2, "hands": 2},
    "Rhinemetall EMG-86 Railgun": {"range": "assault_rifle", "skill": "Heavy Weapons", "damage": (5, 6), "magazine": 4, "ammo": "Rifle", "rof": 1, "hands": 2},
    "Rhinemetall EMG-86": {"range": "assault_rifle", "skill": "Heavy Weapons", "damage": (5, 6), "magazine": 4, "ammo": "Rifle", "rof": 1, "hands": 2},
    "Shrieker": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 8, "ammo": "Battery", "rof": 1, "hands": 1},
    "Stun Baton": {"melee": True, "damage": (2, 6), "rof": 2, "hands": 1, "ablation": 0},
    "Stun Gun": {"range": "pistol", "skill": "Handgun", "damage": (3, 6), "magazine": 8, "ammo": "Battery", "rof": 2, "hands": 1, "ablation": 0},
}
WEAPONS.update({k: v for k, v in EXOTIC_WEAPONS.items() if k not in WEAPONS})
RANGE_DVS = {
    "pistol": (13, 15, 20, 25, 30, 30, None, None),
    "smg": (15, 13, 15, 20, 25, 25, 30, None),
    "shotgun": (13, 15, 20, 25, 30, 35, None, None),
    "assault_rifle": (17, 16, 15, 13, 15, 20, 25, 30),
    "sniper_rifle": (30, 25, 25, 20, 15, 16, 17, 20),
    "bow": (15, 13, 15, 17, 20, 22, None, None),
    "grenade_launcher": (16, 15, 15, 17, 20, 22, 25, None),
    "rocket_launcher": (17, 16, 15, 15, 20, 20, 25, 30),
}
AUTOFIRE_DVS = {"smg": (15, 13, 15, 20, 25), "assault_rifle": (17, 16, 15, 13, 15)}
_RANGE_MAX = (6, 12, 25, 50, 100, 200, 400, 800)


def _detail(c):
    d = c.setdefault("detail", {})
    d.setdefault("equipment", {}).setdefault("weapons", [])
    d["equipment"].setdefault("armor", [])
    d.setdefault("conditions", {})
    d.setdefault("injuries", [])
    return d


def _stats(c): return c.get("stats", c)
def _skill(c, name): return c.get("skills", {}).get(name, 0)
def c_inventory_count(c, kind): return c.get("inventory", {}).get(f"ammo:{kind}", 0)
def _active_injuries(c):
    d = c.get("detail", {}); now = d.get("clock_minutes", 0)
    return [i.get("name") for i in d.get("injuries", []) if isinstance(i, dict) and not i.get("effect_removed") and not (isinstance(i.get("effect_suppressed_until"), int) and i["effect_suppressed_until"] > now)]
def _injury_move(c):
    names = _active_injuries(c)
    penalty = (4 if "Broken Leg" in names else 0) + (2 if "Collapsed Lung" in names else 0) + (6 if "Dismembered Leg" in names else 0)
    return max(1, _stats(c).get("MOVE", 0) - penalty)
def _armor_penalty(c):
    penalties = {"Medium Armorjack": 2, "Heavy Armorjack": 2, "Flak": 4, "Metalgear®": 4, "Metalgear": 4}
    return max((penalties.get(a.get("type"), 0) for a in c.get("detail", {}).get("equipment", {}).get("armor", [])), default=0)
def _stat(c, name): return max(0, _stats(c).get(name, 0) - _armor_penalty(c))
def _rand(fn, stop):
    n = fn(stop)
    if type(n) is not int or not 0 <= n < stop: raise ValueError(f"randbelow({stop}) must return an integer in [0, {stop-1}]")
    return n


def _tie_order(rows, rolls, randbelow):
    for _ in range(32):
        order = sorted(rows, key=lambda k: (-rolls[k]["total"], str(k)))
        groups = {}
        for k in order: groups.setdefault(rolls[k]["total"], []).append(k)
        ties = [group for group in groups.values() if len(group) > 1]
        if not ties: return order
        for group in ties:
            for k in group: rolls[k] = initiative(_stat(rows[k], "REF"), randbelow=randbelow)
    raise ValueError("initiative tie unresolved after 32 rerolls")


def start_encounter(characters: list[dict], randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    if not isinstance(characters, list) or not characters: raise ValueError("characters must be a non-empty list")
    rows = {}
    for c in characters:
        if not isinstance(c, dict) or not isinstance(c.get("id"), (str, int)): raise ValueError("each character requires an id")
        if c["id"] in rows: raise ValueError("character ids must be unique")
        if type(_stats(c).get("REF")) is not int: raise ValueError(f"{c['id']} requires integer REF")
        rows[c["id"]] = copy.deepcopy(c)
    rolls = {k: initiative(_stat(c, "REF"), randbelow=randbelow) for k, c in rows.items()}
    order = _tie_order(rows, rolls, randbelow)
    initial_mortal = [k for k in order if rows[k].get("hp", 1) <= 0]
    return {"active": True, "round": 1, "queue": order, "turn_index": 0, "initiative": rolls,
            "requires_initial_turn_resolution": initial_mortal, "source": SOURCE}


def _current(e):
    q, i = e.get("queue", []), e.get("turn_index", 0)
    if not q or type(i) is not int or not 0 <= i < len(q): raise ValueError("invalid encounter queue")
    return q[i]


def _turn(c):
    t = _detail(c).setdefault("encounter_turn", {"move_initialized": False, "move_used": False, "move_remaining": 0, "action_used": False, "attacks_used": 0, "rof2_used": 0, "rof1_used": False, "grappled": False})
    return t


def _begin_turn(c):
    d = _detail(c); d["encounter_turn"] = {"move_initialized": False, "move_used": False, "move_remaining": 0, "action_used": False, "attacks_used": 0, "rof2_used": 0, "rof1_used": False, "grappled": False}


def apply_action(encounter: dict, characters: dict, actor_id, action: str, args: dict | None = None,
                 randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    if not isinstance(encounter, dict) or not isinstance(characters, dict): raise TypeError("encounter and characters must be objects")
    e, cs, args = copy.deepcopy(encounter), copy.deepcopy(characters), copy.deepcopy(args or {})
    if actor_id not in cs: raise ValueError("unknown actor")
    if actor_id != _current(e): raise ValueError("actor is not current in the initiative queue")
    actor_detail = _detail(cs[actor_id])
    if actor_detail.get("dead") or actor_detail["conditions"].get("unconscious"):
        if action != "next_turn": raise ValueError("dead or unconscious character cannot act")
    if action == "next_turn":
        outgoing_id = _current(e)
        outgoing = cs[outgoing_id]; od = _detail(outgoing); ot = _turn(outgoing)
        names = _active_injuries(outgoing)
        if ot.get("moved_this_turn", 0) > 4:
            outgoing["hp"] -= 5 * sum(n in names for n in ("Broken Ribs", "Foreign Object"))
            if any(n in names for n in ("Damaged Ear", "Lost Ear")): od["conditions"]["lose_next_move"] = True
        i = (e["turn_index"] + 1) % len(e["queue"])
        if i == 0: e["round"] += 1
        e["turn_index"] = i; actor_id = e["queue"][i]; c = cs[actor_id]; d = _detail(c)
        ds = None
        if c.get("hp", 1) <= 0 and not d.get("dead"):
            base = d.get("death_save_base_penalty", 0)
            ds = death_save(_stats(c).get("BODY", 0), base + d.get("death_save_penalty", 0), randbelow)
            d["death_save_penalty"] = ds["next_penalty"] - base
            if ds["dead"]: d["dead"] = True
        loses_move = d["conditions"].pop("lose_next_move", False)
        _begin_turn(c)
        if loses_move: d["encounter_turn"]["move_lost"] = True
        injuries = _active_injuries(c)
        if "Spinal Injury" in injuries: _detail(c)["conditions"]["spinal_no_action"] = True
        else: _detail(c)["conditions"].pop("spinal_no_action", None)
        return {"encounter": e, "characters": cs, "result": {"actor_id": actor_id, "death_save": ds}}
    c = cs[actor_id]; d = _detail(c); t = _turn(c); stats = _stats(c)
    if d["conditions"].get("spinal_no_action") and action != "move":
        raise ValueError("Spinal Injury prevents an Action this Turn")
    state = wound_state(max(0, c.get("hp", c.get("max_hp", 1))), c.get("max_hp", 1), max(0, _injury_move(c) - _armor_penalty(c)))
    if action in ("move", "run"):
        if t.get("move_lost"): raise ValueError("injury removed this Turn's Move Action")
        if d["conditions"].get("prone"): raise ValueError("prone characters must get_up before moving")
        if d["conditions"].get("grapple", {}).get("role") == "defender": raise ValueError("grappled defender cannot move independently")
        if action == "run" and not t["move_used"]: raise ValueError("Run requires a prior Move Action this Turn")
        if not t["move_initialized"]:
            t["move_initialized"] = True
            t["move_remaining"] = state["move"] * 2
        if action == "move": t["move_used"] = True
        if action == "run":
            if t["action_used"]: raise ValueError("Run requires the unused other Action")
            t["action_used"] = True
            t["move_remaining"] += state["move"] * 2
        distance = args.get("meters", t["move_remaining"])
        if type(distance) is not int or distance < 0 or distance > t["move_remaining"]: raise ValueError("meters exceeds movement budget")
        t["move_remaining"] -= distance
        d["position_m"] = d.get("position_m", 0) + distance
        t["moved_this_turn"] = t.get("moved_this_turn", 0) + distance
        grapple = d["conditions"].get("grapple")
        if grapple and grapple.get("role") == "attacker":
            dragged = _detail(cs[grapple["target_id"]])
            dragged["position_m"] = dragged.get("position_m", 0) + distance
        if d["conditions"].get("forced_cover") and args.get("into_cover"):
            d["conditions"].pop("forced_cover", None)
        return {"encounter": e, "characters": cs, "result": {"moved_m": distance, "remaining_m": t["move_remaining"]}}
    if action == "get_up":
        if t["action_used"] or d["conditions"].get("spinal_no_action"): raise ValueError("Action unavailable")
        if not d["conditions"].get("prone"): raise ValueError("Get Up requires the Prone condition")
        d["conditions"].pop("prone", None); t["action_used"] = True
        return {"encounter": e, "characters": cs, "result": {"stood": True}}
    if action == "reload":
        if d["conditions"].get("spinal_no_action"): raise ValueError("Action unavailable")
        _consume_action(t)
        weapon = _weapon(d, args.get("weapon_id")); definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
        if definition.get("melee") or definition["magazine"] is None: raise ValueError("weapon cannot be reloaded")
        kind = args.get("ammo_kind", definition["ammo"])
        if kind != definition["ammo"]: raise ValueError("wrong ammunition type")
        inventory = c.get("inventory", {}); ammo_key = f"ammo:{kind}"
        count = inventory.get(ammo_key, 0)
        if type(count) is not int or count < definition["magazine"]: raise ValueError("insufficient ammunition for a full reload")
        inventory[ammo_key] = count - definition["magazine"]
        weapon.update(loaded=definition["magazine"], ammo_kind=kind)
        c["inventory"] = inventory
        return {"encounter": e, "characters": cs, "result": {"reloaded": weapon["id"], "loaded": weapon["loaded"]}}
    if action == "release" and "trigger" in args: return _release_hold(e, cs, actor_id, args)
    if action in ("grab", "choke", "throw", "release", "escape"):
        return _grapple_action(e, cs, actor_id, action, args, randbelow)
    if action == "suppressive_fire": return _suppressive_fire(e, cs, actor_id, args, randbelow)
    if action == "hold": return _hold_action(e, cs, actor_id, args)
    if action == "release_hold": return _release_hold(e, cs, actor_id, args)
    if action != "attack": raise ValueError(f"unsupported encounter action: {action}")
    return _attack(e, cs, actor_id, args, randbelow)


def _consume_action(t):
    if t["action_used"]: raise ValueError("Action already used")
    t["action_used"] = True


def _weapon(d, weapon_id):
    matches = [w for w in d["equipment"]["weapons"] if w.get("id") == weapon_id]
    if len(matches) != 1: raise ValueError("unknown or ambiguous weapon id")
    w = matches[0]
    if w.get("type") not in WEAPONS and w.get("type") not in EXOTIC_WEAPONS: raise ValueError("unknown canonical weapon type")
    return w


def _range_index(distance, count):
    if type(distance) not in (float, int) or distance < 0: raise ValueError("range_m must be nonnegative")
    for i, end in enumerate(_RANGE_MAX[:count]):
        if distance <= end: return i
    return None


def _attack(e, cs, actor_id, args, randbelow):
    attacker = cs[actor_id]; ad = _detail(attacker); turn = _turn(attacker); mode = args.get("mode", "ranged")
    target_id = args.get("target_id")
    if target_id not in cs or target_id == actor_id: raise ValueError("valid target_id required")
    target = cs[target_id]; td = _detail(target); ts = _stats(target); ast = _stats(attacker)
    location = args.get("location", "body")
    if location not in ("body", "head", "leg", "held_item"): raise ValueError("invalid hit location")
    aim = location != "body"
    if aim and args.get("aimed", True) is not True: raise ValueError("special locations require an aimed attack")
    if aim and mode == "autofire": raise ValueError("autofire cannot make aimed shots")
    luck = args.get("luck", 0)
    if type(luck) is not int or luck < 0 or luck > attacker.get("luck_remaining", 0): raise ValueError("invalid LUCK spend")
    defender_dodge = args.get("dodge", False)
    if type(defender_dodge) is not bool: raise ValueError("dodge must be boolean")
    weapon = None; definition = None
    if mode in ("brawling", "martial_arts"):
        skill_name = "Brawling" if mode == "brawling" else f"Martial Arts ({args.get('form', '')})"
        if mode == "martial_arts" and (not args.get("form") or _skill(attacker, skill_name) < 1): raise ValueError("Martial Arts requires a trained, explicitly named form")
        rof, dice_count, damage_flag = 2, brawling_dice(ast.get("BODY", 0), bool(ad.get("cyberarm")) if mode == "brawling" else False, mode == "martial_arts"), mode
        melee = True
    else:
        weapon = _weapon(ad, args.get("weapon_id")); definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
        melee = bool(definition.get("melee")); skill_name = "Melee Weapon" if melee else definition["skill"]
        rof = definition["rof"]; dice_count = definition["damage"][0]; damage_flag = "melee" if melee else None
        if melee and mode == "ranged": mode = "melee"
        if melee and mode != "melee": raise ValueError("melee weapons cannot use a ranged fire mode")
        if not melee and mode == "melee": raise ValueError("ranged weapon cannot use melee mode")
        if not melee and mode not in ("ranged", "autofire"): raise ValueError("mode must be ranged or autofire")
        if definition.get("range") in ("grenade_launcher", "rocket_launcher"):
            raise ValueError("explosive attacks require area placement and blast resolution; ordinary single-target attack is prohibited")
        if ad["conditions"].get("grapple") and (definition.get("hands") or 0) >= 2: raise ValueError("cannot use a two-handed weapon while grappled")
        if not melee:
            if weapon["type"] == "Bows & Crossbows":
                if c_inventory_count(attacker, "Arrow") < 1: raise ValueError("no arrows in inventory")
            elif weapon.get("loaded", 0) <= (19 if weapon.get("type") in ("Helix", "Tsunami Arms Helix") and mode == "autofire" else (9 if mode == "autofire" else 0)): raise ValueError("insufficient loaded ammunition")
            if weapon.get("ammo_kind") != definition["ammo"]: raise ValueError("loaded ammo does not match canonical weapon")
    if aim: _consume_action(turn); count = 1
    elif rof == 1:
        if turn["rof2_used"]: raise ValueError("cannot combine ROF 1 with ROF 2 attacks")
        if turn["rof1_used"]: raise ValueError("ROF 1 attack already made")
        _consume_action(turn)
        turn["rof1_used"] = True; count = 1
    else:
        if (turn["action_used"] and turn["rof2_used"] == 0) or turn["rof1_used"] or turn["rof2_used"] >= 2: raise ValueError("attack allowance exhausted")
        if turn["rof2_used"] == 0: turn["action_used"] = True
        turn["rof2_used"] += 1; count = 1
    distance = args.get("range_m")
    if melee:
        if type(distance) not in (int, float) or not 0 <= distance <= 2: raise ValueError("melee target must be within 2m")
        dv = None
    else:
        if type(distance) not in (int, float) or distance < 0: raise ValueError("range_m required")
        key = definition["range"]
        if mode == "autofire":
            vals = AUTOFIRE_DVS.get(key)
            if vals is None: raise ValueError("weapon has no canonical Autofire mode")
            idx = _range_index(distance, 5)
            if idx is None: raise ValueError("target out of Autofire range")
            dv = vals[idx]
        else:
            idx = _range_index(distance, 8); dv = None if idx is None else RANGE_DVS[key][idx]
            if dv is None: raise ValueError("target out of weapon range")
    if mode == "autofire":
        weapon["loaded"] -= (20 if weapon and weapon.get("type") in ("Helix", "Tsunami Arms Helix") else 10)
    elif weapon and not melee:
        if weapon["type"] == "Bows & Crossbows":
            inv = attacker.setdefault("inventory", {}); inv["ammo:Arrow"] -= 1
        else: weapon["loaded"] -= 1
    attacker["luck_remaining"] = attacker.get("luck_remaining", 0) - luck
    nchecks = count
    results = []
    for _ in range(nchecks):
        if melee:
            check = attack_check(_stat(attacker, "DEX"), _skill(attacker, skill_name), 0,
                                 modifier=(-8 if aim else 0) + _wound_penalty(attacker) + (-2 if "Torn Muscle" in _active_injuries(attacker) else 0), luck=luck, randbelow=randbelow)
            defense = attack_check(_stat(target, "DEX"), _skill(target, "Evasion"), 0,
                                   modifier=_wound_penalty(target), randbelow=randbelow)
            check["defense"] = defense
            hit = check["total"] > defense["total"]
        else:
            if defender_dodge and _stat(target, "REF") >= 8 and "Dismembered Leg" not in _active_injuries(target):
                check = attack_check(_stat(attacker, "REF"), _skill(attacker, "Autofire" if mode == "autofire" else skill_name), 0, modifier=(-8 if aim else 0) + _wound_penalty(attacker) + _ranged_injury_penalty(attacker), luck=luck, randbelow=randbelow)
                defense = attack_check(_stat(target, "DEX"), _skill(target, "Evasion"), 0, modifier=_wound_penalty(target), randbelow=randbelow)
                check["defense"] = defense
                hit = check["total"] > defense["total"]
            else:
                check = attack_check(_stat(attacker, "REF"), _skill(attacker, "Autofire" if mode == "autofire" else skill_name), dv, modifier=(-8 if aim else 0) + _wound_penalty(attacker) + _ranged_injury_penalty(attacker), luck=luck, randbelow=randbelow)
                hit = check["success"]
        item = {"check": check, "hit": hit}
        if hit:
            ablation = 1
            raw_ammo_type = str(args.get("ammo_type") or "").strip().lower()
            if "armor-piercing" in raw_ammo_type or "armor_piercing" in raw_ammo_type or raw_ammo_type == "ap":
                ablation = 2
            elif "rubber" in raw_ammo_type:
                ablation = 0
            elif isinstance(args.get("ablation"), int):
                ablation = max(0, args["ablation"])
            elif definition and definition.get("ablation") is not None:
                ablation = definition["ablation"]

            loc = "head" if location == "head" else "body"
            armor = [a for a in td["equipment"]["armor"] if a.get("location") == loc]

            if dice_count == 0:
                for a in armor:
                    if a.get("sp", 0) > 0:
                        a["sp"] = max(0, a["sp"] - 1)
                damage = {"hp_damage": 0, "sp_ablation": 1 if armor else 0, "penetration": 0, "critical_trigger": False, "armor_after": armor}
                item.update(damage=damage, critical_injury=None, critical_injuries=[])
            else:
                if mode == "autofire": dice = roll_dice(2, 6, randbelow); margin = max(1, check["total"] - (check["defense"]["total"] if "defense" in check else dv))
                else: dice = roll_dice(dice_count, 6, randbelow); margin = None
                damage = damage_and_armor(dice, armor, location=loc, melee=damage_flag == "melee", martial_arts=damage_flag == "martial_arts", brawling=damage_flag == "brawling", autofire_margin=margin, autofire_cap=definition.get("autofire") if mode == "autofire" else None, cracked_skull="Cracked Skull" in [x.get("name") for x in td["injuries"]], ablation=ablation)
                td["equipment"]["armor"] = [next((p for p in damage["armor_after"] if p["id"] == a["id"]), a) if a.get("location") == loc else a for a in td["equipment"]["armor"]]
                was_mortal = target.get("hp", 0) <= 0
                old_hp = target.get("hp", 0)
                target["hp"] = old_hp - damage["hp_damage"]
                if old_hp > 0 >= target["hp"]:
                    td["crossed_mortal_wound_this_attack"] = {"requires_human_ruling": True, "reason": "Whether crossing to Mortally Wounded causes an immediate additional critical injury is unresolved."}
                if was_mortal: td["death_save_penalty"] = td.get("death_save_penalty", 0) + 1
                criticals = []
                for is_mortal_trigger in ([False] if damage["critical_trigger"] else []) + ([True] if was_mortal else []):
                    critical = critical_injury(loc, [x.get("name", "") for x in td["injuries"]], randbelow)
                    criticals.append(critical)
                    if not critical.get("requires_human_ruling"):
                        td["injuries"].append(critical)
                        if "base death-save penalty +1" in critical.get("effects", ""):
                            td["death_save_base_penalty"] = td.get("death_save_base_penalty", 0) + 1
                        if is_mortal_trigger: target["hp"] -= critical.get("bonus_damage", 5)
                item.update(damage=damage, critical_injury=criticals[0] if criticals else None, critical_injuries=criticals)
                if location == "leg" and damage["penetration"] > 0 and not any(n in _active_injuries(target) for n in ("Broken Leg", "Dismembered Leg")):
                    td["injuries"].append({"id": "body:aimed_leg", "name": "Broken Leg", "effects": "MOVE -4", "bonus_damage": 5, "source": SOURCE})
                    target["hp"] -= 5
                if location == "held_item" and damage["penetration"] > 0:
                    wanted = args.get("held_item_id")
                    held_items = td["equipment"].get("held_items", [])
                    found = next((x for x in held_items if x.get("id") == wanted), None)
                    if found is None: raise ValueError("held_item_id must identify a held item")
                    held_items.remove(found); td.setdefault("dropped_items", []).append(found)
        results.append(item)
    return {"encounter": e, "characters": cs, "result": {"attacks": results}}


def _opposed_brawl(a, b, randbelow, modifier_a=0):
    ca = attack_check(_stat(a, "DEX"), _skill(a, "Brawling"), 0,
                      modifier=modifier_a + _wound_penalty(a), randbelow=randbelow)
    cb = attack_check(_stat(b, "DEX"), _skill(b, "Brawling"), 0,
                      modifier=_wound_penalty(b), randbelow=randbelow)
    return ca, cb, ca["total"] > cb["total"]


def _grapple_action(e, cs, actor_id, action, args, randbelow):
    a = cs[actor_id]; ad = _detail(a); turn = _turn(a); target_id = args.get("target_id")
    if action == "release":
        g = ad["conditions"].pop("grapple", None)
        if not g or g.get("role") != "attacker": raise ValueError("only the attacker may end a Grapple without an Action")
        other = _detail(cs[g["target_id"]]); other["conditions"].pop("grapple", None)
        if ad.get("free_hands") is not None: ad["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"released": g["target_id"]}}
    if target_id not in cs or target_id == actor_id: raise ValueError("valid target_id required")
    b = cs[target_id]; bd = _detail(b); bt = _turn(b)
    if action == "grab":
        if turn["action_used"]: raise ValueError("Action already used")
        if ad["conditions"].get("grapple"): raise ValueError("already grappling")
        if type(ad.get("free_hands")) is not int or ad["free_hands"] < 1: raise ValueError("Grab requires explicit free-hand inventory in detail.free_hands")
        if args.get("range_m", 99) > 2: raise ValueError("target is outside 2m reach")
        check_a, check_b, won = _opposed_brawl(a, b, randbelow)
        turn["action_used"] = True
        if won:
            ad["free_hands"] -= 1
            ad["conditions"]["grapple"] = {"role": "attacker", "target_id": target_id, "hand_committed": True}
            bd["conditions"]["grapple"] = {"role": "defender", "target_id": actor_id, "hand_committed": False}
        return {"encounter": e, "characters": cs, "result": {"won": won, "attacker": check_a, "defender": check_b}}
    grapple = ad["conditions"].get("grapple")
    if action == "escape":
        grapple = bd["conditions"].get("grapple")
        if not grapple or grapple.get("target_id") != actor_id or grapple.get("role") != "attacker": raise ValueError("target is not grappling actor")
        check_a, check_b, won = _opposed_brawl(a, b, randbelow, -2)
        _consume_action(turn)
        if won:
            ad["conditions"].pop("grapple", None); bd["conditions"].pop("grapple", None)
            if bd.get("free_hands") is not None: bd["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"escaped": won, "attacker": check_a, "defender": check_b}}
    if not grapple or grapple.get("target_id") != target_id or grapple.get("role") != "attacker": raise ValueError("actor is not grappling target")
    if action == "choke":
        _consume_action(turn)
        direct = _stats(a).get("BODY", 0)
        old = b.get("hp", 0); new = old - direct
        if old > 1 and new < 1:
            new = 1; bd["conditions"]["unconscious"] = True
        b["hp"] = new
        prior = bd["conditions"].get("choke_tracker", {})
        rounds = prior.get("count", 0) + 1 if prior.get("last_round") == e["round"] - 1 else 1
        bd["conditions"]["choke_tracker"] = {"count": rounds, "last_round": e["round"]}
        if rounds >= 3: bd["conditions"]["unconscious"] = True
        return {"encounter": e, "characters": cs, "result": {"direct_damage": old-b["hp"], "unconscious": bool(bd["conditions"].get("unconscious"))}}
    if action == "throw":
        _consume_action(turn); direct = _stats(a).get("BODY", 0)
        b["hp"] = b.get("hp", 0) - direct
        bd["conditions"]["prone"] = True
        ad["conditions"].pop("grapple", None); bd["conditions"].pop("grapple", None)
        if ad.get("free_hands") is not None: ad["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"direct_damage": direct, "thrown_prone": True}}
    raise ValueError("unsupported grapple action")


def _suppressive_fire(e, cs, actor_id, args, randbelow):
    a = cs[actor_id]; ad = _detail(a); t = _turn(a); weapon = _weapon(ad, args.get("weapon_id")); definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
    if definition.get("autofire") is None: raise ValueError("weapon does not support suppressive fire")
    if weapon.get("loaded", 0) < 10 or weapon.get("ammo_kind") != definition["ammo"]: raise ValueError("requires 10 correctly loaded bullets")
    _consume_action(t); weapon["loaded"] -= 10
    roll = attack_check(_stat(a, "REF"), _skill(a, "Autofire"), 0, modifier=_wound_penalty(a), randbelow=randbelow)
    forced = []
    for row in args.get("targets", []):
        tid = row.get("target_id"); distance = row.get("range_m")
        if tid not in cs or tid == actor_id: raise ValueError("invalid suppressive-fire target")
        if type(distance) not in (int, float) or distance > 25 or row.get("covered") or not row.get("line_of_sight") or not row.get("on_foot"): continue
        target = cs[tid]
        defense = attack_check(_stat(target, "WILL"), _skill(target, "Concentration"), 0, modifier=_wound_penalty(target), randbelow=randbelow)
        panic = defense["total"] < roll["total"]
        if panic: _detail(target)["conditions"]["forced_cover"] = {"by": actor_id, "move": True, "run_if_needed": True}
        forced.append({"target_id": tid, "check": defense, "forced_to_cover": panic})
    return {"encounter": e, "characters": cs, "result": {"attack_check": roll, "targets": forced}}


def _hold_action(e, cs, actor_id, args):
    c = cs[actor_id]; d = _detail(c); t = _turn(c)
    held = args.get("held_action"); target = args.get("target_id"); trigger = args.get("trigger")
    if not isinstance(held, str) or not held or not isinstance(trigger, str) or not trigger or target not in cs: raise ValueError("Hold requires declared action, trigger, and target")
    _consume_action(t); d["held_action"] = {"action": held, "target_id": target, "trigger": trigger, "owner": actor_id}
    return {"encounter": e, "characters": cs, "result": {"held": copy.deepcopy(d["held_action"])}}


def _release_hold(e, cs, actor_id, args):
    held = _detail(cs[actor_id]).get("held_action")
    if not held or args.get("trigger") != held["trigger"]: raise ValueError("held action trigger does not match")
    del _detail(cs[actor_id])["held_action"]
    return {"encounter": e, "characters": cs, "result": {"released_action": held["action"], "target_id": held["target_id"], "trigger": held["trigger"]}}


def _wound_penalty(c):
    names = _active_injuries(c)
    grapple = c.get("detail", {}).get("conditions", {}).get("grapple")
    return wound_state(max(0, c.get("hp", c.get("max_hp", 1))), c.get("max_hp", 1), _stats(c).get("MOVE", 0))["action_penalty"] - 2 * sum(n in names for n in ("Brain Injury", "Concussion")) - (2 if grapple else 0)


def _ranged_injury_penalty(c):
    names = _active_injuries(c)
    return -4 if "Lost Eye" in names else -2 if "Damaged Eye" in names else 0


def _dv_evasion(c):
    return _stats(c).get("DEX", 0) + _skill(c, "Evasion") + 10
