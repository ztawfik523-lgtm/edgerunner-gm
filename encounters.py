"""Pure encounter orchestration; combat results use canonical Core Rulebook data."""
from __future__ import annotations

import copy
import math
import re
import secrets
from typing import Any, Callable

from combat import initiative, wound_state, attack_check, damage_and_armor, critical_injury, brawling_dice
from mechanics import roll_dice
import rules_eval
import sourcecatalog

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
    "Dartgun": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 8, "ammo": "Arrow", "rof": 1, "hands": 1, "payload_only": True, "no_critical": True},
    "Flamethrower": {"range": "shotgun", "skill": "Heavy Weapons", "damage": (3, 6), "magazine": 4, "ammo": "Slug", "rof": 1, "hands": 2, "no_critical": True, "no_aim": True, "incendiary": True},
    "Helix": {"range": "assault_rifle", "skill": "Autofire", "damage": (2, 6), "magazine": 40, "ammo": "Rifle", "rof": 1, "hands": 2, "autofire": 5, "autofire_only": True, "reload_actions": 2, "min_body": 11},
    "Tsunami Arms Helix": {"range": "assault_rifle", "skill": "Autofire", "damage": (2, 6), "magazine": 40, "ammo": "Rifle", "rof": 1, "hands": 2, "autofire": 5, "autofire_only": True, "reload_actions": 2, "min_body": 11},
    "Kendachi Mono-Three": {"melee": True, "damage": (4, 6), "rof": 1, "hands": 2},
    "Malorian Arms 3516": {"range": "pistol", "skill": "Handgun", "damage": (5, 6), "magazine": 8, "ammo": "VH Pistol", "rof": 1, "hands": 1},
    "Microwaver": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 8, "ammo": "Battery", "rof": 1, "hands": 1, "no_critical": True},
    "Militech \"Cowboy\" U-56 Grenade Launcher": {"range": "grenade_launcher", "skill": "Heavy Weapons", "damage": (6, 6), "magazine": 4, "ammo": "Grenade", "rof": 2, "hands": 2},
    "Militech Cowboy": {"range": "grenade_launcher", "skill": "Heavy Weapons", "damage": (6, 6), "magazine": 4, "ammo": "Grenade", "rof": 2, "hands": 2},
    "Rhinemetall EMG-86 Railgun": {"range": "assault_rifle", "skill": "Heavy Weapons", "damage": (5, 6), "magazine": 4, "ammo": "Rifle", "rof": 1, "hands": 2},
    "Rhinemetall EMG-86": {"range": "assault_rifle", "skill": "Heavy Weapons", "damage": (5, 6), "magazine": 4, "ammo": "Rifle", "rof": 1, "hands": 2},
    "Shrieker": {"range": "pistol", "skill": "Handgun", "damage": (0, 6), "magazine": 8, "ammo": "Battery", "rof": 1, "hands": 1, "no_critical": True},
    "Stun Baton": {"melee": True, "damage": (2, 6), "rof": 2, "hands": 1, "ablation": 0, "non_lethal": True, "no_critical": True},
    "Stun Gun": {"range": "pistol", "skill": "Handgun", "damage": (3, 6), "magazine": 8, "ammo": "Battery", "rof": 2, "hands": 1, "ablation": 0, "non_lethal": True, "no_critical": True},
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

_NPC_REQUIRED_STATS = ("REF", "DEX", "BODY", "WILL", "MOVE")

_AMMO_TYPE_ALIASES = {
    "": "standard",
    "standard": "standard",
    "basic": "standard",
    "ap": "armor_piercing",
    "armor-piercing": "armor_piercing",
    "armor_piercing": "armor_piercing",
    "armor piercing": "armor_piercing",
    "rubber": "rubber",
    "rubber ammunition": "rubber",
    "incendiary": "incendiary",
    "poison": "poison",
    "biotoxin": "biotoxin",
    "sleep": "sleep",
    "sleeping": "sleep",
    "acid": "acid",
}


def _norm_ammo_type(raw: Any) -> str:
    text = str(raw or "").strip().lower().replace("_", " ")
    text = " ".join(text.split())
    if not text:
        return "standard"
    if text in _AMMO_TYPE_ALIASES:
        return _AMMO_TYPE_ALIASES[text]
    underscored = text.replace(" ", "_")
    return _AMMO_TYPE_ALIASES.get(underscored, underscored)


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
    return [
        inj["name"]
        for inj in rules_eval.active_injuries(c)
        if not inj.get("suppressed") and not inj.get("treated") and not inj.get("quick_fixed")
    ]


def _effective_body(c):
    raw_body = _stats(c).get("BODY", 0)
    eval_body = rules_eval.effective_body(c)
    return max(raw_body if type(raw_body) is int else 0, eval_body)


def _injury_move(c):
    names = _active_injuries(c)
    base_move = _stats(c).get("MOVE", 0)
    if type(base_move) is not int or base_move <= 0:
        return 0
    penalty = (4 if "Broken Leg" in names else 0) + (2 if "Collapsed Lung" in names else 0) + (6 if "Dismembered Leg" in names else 0)
    return max(1, base_move - penalty)


def _armor_penalty(c):
    return rules_eval.effective_armor_penalty(c)


def _stat(c, name):
    if name == "BODY":
        return _effective_body(c)
    base = _stats(c).get(name, 0)
    if type(base) is not int:
        base = 0
    if name in ("REF", "DEX", "MOVE"):
        return max(0, base - _armor_penalty(c))
    return max(0, base)


def _is_dead(c) -> bool:
    d = c.get("detail") or {}
    return bool(d.get("dead") or (d.get("conditions") or {}).get("dead"))


def _rand(fn, stop):
    n = fn(stop)
    if type(n) is not int or not 0 <= n < stop:
        raise ValueError(f"randbelow({stop}) must return an integer in [0, {stop-1}]")
    return n


def _initiative_bonus(c) -> int:
    ctx = rules_eval.effective_check_context(c, "REF", None, tags=("initiative",))
    bonus = int(ctx.get("initiative_reaction") or 0)
    conds = (c.get("detail") or {}).get("conditions") or {}
    has_sandevistan = conds.get("sandevistan") is True
    has_kerenzikov = conds.get("kerenzikov") is True
    for label, _ in rules_eval._iter_owned_items(c):
        low = label.casefold()
        if "sandevistan" in low:
            has_sandevistan = True
        elif "kerenzikov" in low:
            has_kerenzikov = True
    # Sandevistan (+3) and Kerenzikov (+2) do not stack.
    if has_sandevistan:
        bonus += 3
    elif has_kerenzikov:
        bonus += 2
    return bonus


def _resolve_tie_group(group: list, rows: dict, randbelow: Callable[[int], int], depth: int = 0) -> list:
    if len(group) <= 1:
        return list(group)
    if depth >= 32:
        raise ValueError("initiative tie unresolved after 32 rerolls")
    tie_rolls = {
        k: initiative(_stat(rows[k], "REF"), bonus=_initiative_bonus(rows[k]), randbelow=randbelow)["total"]
        for k in group
    }
    subgroups: dict[int, list] = {}
    for k in group:
        subgroups.setdefault(tie_rolls[k], []).append(k)
    result = []
    for total in sorted(subgroups, reverse=True):
        sub = subgroups[total]
        if len(sub) > 1:
            result.extend(_resolve_tie_group(sub, rows, randbelow, depth + 1))
        else:
            result.extend(sub)
    return result


def _tie_order(rows, rolls, randbelow):
    ordered_keys = sorted(rows, key=lambda k: (-rolls[k]["total"], str(k)))
    groups: dict[int, list] = {}
    for k in ordered_keys:
        groups.setdefault(rolls[k]["total"], []).append(k)
    order = []
    for total in sorted(groups, reverse=True):
        group = groups[total]
        if len(group) > 1:
            order.extend(_resolve_tie_group(group, rows, randbelow, depth=0))
        else:
            order.extend(group)
    return order


def npc_stat_blocks(rules_path: Any) -> list[dict[str, Any]]:
    """The `npc` entries of the rules index that carry a combat stat block."""
    return [e for e in sourcecatalog.entries(rules_path, "npc") if e["stats"].get("kind") == "stat_block"]


def _weapon_type(name: str, rules_path: Any) -> str:
    """The engine weapon profile behind a stat block's weapon name."""
    clean = re.sub(r"^(?:(?:Poor|Standard|Excellent) Quality|Popup)\s+", "", name, flags=re.I)
    clean = re.sub(r"\bVH\b", "Very Heavy", clean)
    singular = lambda text: text.casefold().rstrip("s")  # noqa: E731
    for key in WEAPONS:
        if clean.casefold() == key.casefold() or singular(clean) in map(singular, key.split(" & ")):
            return key
    # Cyberweapons state their melee class in the Corebook description.
    for entry in sourcecatalog.entries(rules_path, "cyberware"):
        if entry["name"].casefold() == clean.casefold():
            match = re.search(r"\b(?:Very Heavy|Heavy|Medium|Light) Melee Weapon\b", entry["description"])
            if match:
                return match.group(0)
    raise ValueError(f"Stat block weapon {name!r} has no weapon profile; supply the NPC's weapons explicitly")


def _listed_ammo(equipment: str, weapons: list[str]) -> dict[str, int]:
    """Spare ammunition counts a stat block lists for the weapons it carries."""
    text = equipment
    for long, short in (("Very Heavy Pistol", "VH Pistol"), ("Heavy Pistol", "H Pistol"), ("Medium Pistol", "M Pistol")):
        text = text.replace(long, short)
    found = {}
    for kind in {WEAPONS[w].get("ammo") for w in weapons} - {None}:
        match = re.search(rf"(?<![A-Za-z]){re.escape(kind)}(?: Ammo)? x(\d+)", text)
        if match:
            found[f"ammo:{kind}"] = int(match.group(1))
    return found


def _book_injuries(spec: Any, rules_path: Any) -> Any:
    """A spec's injuries, named or identified, completed with their Critical Injury table rows."""
    if not (isinstance(spec, dict) and isinstance(spec.get("injuries"), list) and spec["injuries"]):
        return spec
    rows = [row for table in sourcecatalog.critical_injuries(rules_path).values() for row in table.values()]
    injuries = []
    for item in spec["injuries"]:
        given = {"name": item} if isinstance(item, str) else item
        if isinstance(given, dict):
            key, value = ("id", given["id"]) if given.get("id") else ("name", given.get("name"))
            row = next((r for r in rows if r[key].casefold() == str(value).strip().casefold()), None)
            if row:
                given = {**row, **given, "name": row["name"]}
        injuries.append(given)
    return {**spec, "injuries": injuries}


def expand_npc_specs(specs: list[Any], rules_path: Any) -> list[Any]:
    """Fill NPC specs from the index: stat blocks named by {"entry": name or id} (explicit fields win)
    and the book's rows for the Critical Injuries a spec lists."""
    specs = [_book_injuries(spec, rules_path) for spec in specs]
    if not any(isinstance(spec, dict) and spec.get("entry") for spec in specs):
        return specs
    if not rules_path:
        raise ValueError("NPC stat block entries need your indexed Corebook")
    blocks = npc_stat_blocks(rules_path)
    if not blocks:
        raise ValueError("The rules index has no NPC stat blocks; rebuild it from your Corebook PDF")
    known = {key.casefold(): e for e in blocks for key in (e["id"], e["name"])}
    result = []
    for spec in specs:
        if not (isinstance(spec, dict) and spec.get("entry")):
            result.append(spec)
            continue
        overrides = {k: v for k, v in spec.items() if k != "entry"}
        entry = known.get(str(spec["entry"]).strip().casefold())
        if entry is None:
            raise ValueError(f"Unknown NPC stat block {spec['entry']!r}; the index has: {', '.join(e['name'] for e in blocks)}")
        block = entry["stats"]
        base = {"name": entry["name"], "stats": block["npc_stats"], "skills": block["skills"],
                "max_hp": block["hit_points"], "sp_body": block.get("sp_body", 0), "sp_head": block.get("sp_head", 0),
                "armor_penalty": block["armor_penalty"]}
        if "weapons" not in overrides:
            base["weapons"] = [_weapon_type(w["name"], rules_path) for w in block.get("weapons", [])]
            base["inventory"] = _listed_ammo(block.get("equipment", ""), base["weapons"])
        merged = {**base, **overrides}
        for key in ("stats", "skills", "inventory"):
            if isinstance(base.get(key), dict) and isinstance(overrides.get(key), dict):
                merged[key] = {**base[key], **overrides[key]}
        result.append(merged)
    return result


def build_npc_combatant(spec: dict[str, Any], existing_ids: set[str] | None = None) -> dict[str, Any]:
    """Build a valid ephemeral NPC combatant sheet from a stat block.

    Required: name, stats (REF, DEX, BODY, WILL, MOVE), hp or max_hp, and weapons.
    Omitted skills are untrained and omitted armor is no armor. Specs naming a
    Corebook entry go through `expand_npc_specs` first.
    """
    existing = set(existing_ids or ())
    if not isinstance(spec, dict):
        raise ValueError("NPC entry must be an object")
    spec_dict = dict(spec)
    name = str(spec_dict.get("name") or spec_dict.get("handle") or "").strip()
    if not name:
        raise ValueError("NPC name is required")
    raw_stats = spec_dict.get("stats")
    if not isinstance(raw_stats, dict):
        raise ValueError(f"NPC {name} requires a stats object")
    stats: dict[str, int] = {}
    for k, v in raw_stats.items():
        if type(v) is not int:
            raise ValueError(f"NPC stat {k} must be an integer")
        stats[str(k).upper()] = v
    missing = [k for k in _NPC_REQUIRED_STATS if k not in stats]
    if missing:
        raise ValueError(f"NPC {name} is missing stats: {', '.join(missing)}")

    skills: dict[str, int] = {}
    for k, v in (spec_dict.get("skills") or {}).items():
        if type(v) is not int:
            raise ValueError(f"NPC skill {k} must be an integer")
        skills[str(k)] = v

    raw_max_hp = spec_dict.get("max_hp")
    raw_hp = spec_dict.get("hp")
    if raw_max_hp is None and raw_hp is None:
        raise ValueError(f"NPC {name} requires hp or max_hp")
    if raw_max_hp is not None and (type(raw_max_hp) is not int or raw_max_hp < 1):
        raise ValueError("NPC max_hp must be a positive integer")
    if raw_hp is not None and type(raw_hp) is not int:
        raise ValueError("NPC hp must be an integer")
    max_hp = raw_max_hp if raw_max_hp is not None else max(1, raw_hp)
    hp = raw_hp if raw_hp is not None else max_hp

    sp_body = spec_dict.get("sp_body", 0)
    sp_head = spec_dict.get("sp_head", 0)
    armor_penalty = spec_dict.get("armor_penalty", 0)
    for label, val in (("sp_body", sp_body), ("sp_head", sp_head), ("armor_penalty", armor_penalty)):
        if type(val) is not int or val < 0:
            raise ValueError(f"NPC {label} must be a non-negative integer")

    explicit_id = spec_dict.get("id")
    if explicit_id is not None:
        if not isinstance(explicit_id, str) or not explicit_id.strip():
            raise ValueError("NPC id must be a non-empty string")
        npc_id = explicit_id.strip()
        if npc_id in existing:
            raise ValueError(f"duplicate combatant id: {npc_id}")
    else:
        idx = 0
        while f"npc-{idx}" in existing:
            idx += 1
        npc_id = f"npc-{idx}"

    armor_list: list[dict[str, Any]] = []
    if sp_body > 0:
        armor_list.append({
            "id": f"{npc_id}-armor-body",
            "type": "NPC Body Armor",
            "sp": sp_body,
            "max_sp": sp_body,
            "location": "body",
            "penalty": armor_penalty,
        })
    if sp_head > 0:
        armor_list.append({
            "id": f"{npc_id}-armor-head",
            "type": "NPC Head Armor",
            "sp": sp_head,
            "max_sp": sp_head,
            "location": "head",
            "penalty": armor_penalty,
        })

    raw_weapons = spec_dict.get("weapons")
    if not isinstance(raw_weapons, list):
        raise ValueError("NPC weapons must be a list")
    weapons_list: list[dict[str, Any]] = []
    inventory: dict[str, int] = dict(spec_dict.get("inventory") or {}) if isinstance(spec_dict.get("inventory"), dict) else {}
    for w_idx, entry in enumerate(raw_weapons):
        if isinstance(entry, str):
            w_type = entry.strip()
            if w_type not in WEAPONS:
                raise ValueError(f"unknown canonical weapon type: {w_type}")
            defn = WEAPONS[w_type]
            w_obj = {
                "id": f"{npc_id}-w-{w_idx}",
                "type": w_type,
                "loaded": defn.get("magazine"),
                "ammo_kind": defn.get("ammo"),
                "ammo_type": "standard" if defn.get("ammo") else None,
            }
        elif isinstance(entry, dict):
            w_type = str(entry.get("type") or entry.get("name") or "").strip()
            if w_type not in WEAPONS:
                raise ValueError(f"unknown canonical weapon type: {w_type}")
            defn = WEAPONS[w_type]
            w_obj = {
                "id": str(entry.get("id") or f"{npc_id}-w-{w_idx}"),
                "type": w_type,
                "loaded": entry.get("loaded", defn.get("magazine")),
                "ammo_kind": entry.get("ammo_kind", defn.get("ammo")),
                "ammo_type": _norm_ammo_type(entry.get("ammo_type") or "standard") if defn.get("ammo") else None,
            }
        else:
            raise ValueError("NPC weapon entry must be a string or object")
        weapons_list.append(w_obj)
        if w_obj.get("ammo_kind") and defn.get("magazine"):
            akey = f"ammo:{w_obj['ammo_kind']}"
            inventory.setdefault(akey, int(defn["magazine"]) * 2)

    free_hands = spec_dict.get("free_hands", 2)
    if type(free_hands) is not int or free_hands < 0:
        raise ValueError("NPC free_hands must be a non-negative integer")

    raw_injuries = copy.deepcopy(spec_dict.get("injuries") or [])
    if not isinstance(raw_injuries, list):
        raise ValueError("NPC injuries must be a list")
    raw_conditions = copy.deepcopy(spec_dict.get("conditions") or {})
    if not isinstance(raw_conditions, dict):
        raise ValueError("NPC conditions must be a dict")

    sheet: dict[str, Any] = {
        "id": npc_id,
        "name": name,
        "is_npc": True,
        "stats": stats,
        "skills": skills,
        "hp": hp,
        "max_hp": max_hp,
        "luck_remaining": max(0, int(stats.get("LUCK", 0))),
        "inventory": inventory,
        "injuries": raw_injuries,
        "detail": {
            "handle": name,
            "free_hands": free_hands,
            "equipment": {
                "weapons": weapons_list,
                "armor": armor_list,
            },
            "equipped_weapon": weapons_list[0]["type"] if weapons_list else None,
            "conditions": raw_conditions,
            "injuries": copy.deepcopy(raw_injuries),
        },
    }
    rules_eval.sync_equipment_views(sheet)
    rules_eval.recompute_death_save_base_penalty(sheet)
    return sheet


def start_encounter(characters: list[dict], randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    if not isinstance(characters, list) or not characters:
        raise ValueError("characters must be a non-empty list")
    rows = {}
    for c in characters:
        if not isinstance(c, dict) or not isinstance(c.get("id"), (str, int)):
            raise ValueError("each character requires an id")
        if c["id"] in rows:
            raise ValueError("character ids must be unique")
        if type(_stats(c).get("REF")) is not int:
            raise ValueError(f"{c['id']} requires integer REF")
        rows[c["id"]] = copy.deepcopy(c)
    rolls = {k: initiative(_stat(c, "REF"), bonus=_initiative_bonus(c), randbelow=randbelow) for k, c in rows.items()}
    order = _tie_order(rows, rolls, randbelow)
    turn_index = next((idx for idx, k in enumerate(order) if not _is_dead(rows[k])), 0)
    initial_mortal = [k for k in order if rows[k].get("hp", 1) <= 0 and not _is_dead(rows[k])]
    return {
        "active": True,
        "round": 1,
        "queue": order,
        "turn_index": turn_index,
        "initiative": rolls,
        "requires_initial_turn_resolution": initial_mortal,
        "source": SOURCE,
    }


def _current(e):
    q, i = e.get("queue", []), e.get("turn_index", 0)
    if not q or type(i) is not int or not 0 <= i < len(q):
        raise ValueError("invalid encounter queue")
    return q[i]


def _turn(c):
    t = _detail(c).setdefault(
        "encounter_turn",
        {
            "move_initialized": False,
            "move_used": False,
            "move_remaining": 0,
            "action_used": False,
            "attacks_used": 0,
            "rof2_used": 0,
            "rof1_used": False,
            "grappled": False,
        },
    )
    return t


def _begin_turn(c):
    d = _detail(c)
    d["encounter_turn"] = {
        "move_initialized": False,
        "move_used": False,
        "move_remaining": 0,
        "action_used": False,
        "attacks_used": 0,
        "rof2_used": 0,
        "rof1_used": False,
        "grappled": False,
    }


def resolve_end_of_turn(char: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve end-of-turn injury/condition effects (movement injuries, burning, flash_out)."""
    d = _detail(char)
    t = _turn(char)
    names = _active_injuries(char)
    effects: list[dict[str, Any]] = []

    if t.get("moved_this_turn", 0) > 4:
        move_injs = [n for n in names if n in ("Broken Ribs", "Foreign Object")]
        if move_injs:
            dmg = 5 * len(move_injs)
            char["hp"] = char.get("hp", 0) - dmg
            d["stabilized"] = False
            effects.append({"type": "movement_injury_damage", "damage": dmg, "injuries": move_injs})
        ear_injs = [n for n in names if n in ("Damaged Ear", "Lost Ear")]
        if ear_injs:
            d["conditions"]["lose_next_move"] = True
            effects.append({"type": "lose_next_move", "injuries": ear_injs})

    if d["conditions"].get("burning") and not _is_dead(char):
        char["hp"] = char.get("hp", 0) - 2
        d["stabilized"] = False
        effects.append({"type": "burning", "damage": 2})

    if d["conditions"].pop("flash_out", None):
        effects.append({"type": "flash_out_cleared"})

    return effects


def resolve_start_of_turn(
    char: dict[str, Any],
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> dict[str, Any]:
    """Resolve start-of-turn Death Save, move loss, Spinal Injury, and turn budget reset."""
    d = _detail(char)
    ds = None
    if char.get("hp", 1) <= 0 and not _is_dead(char):
        ds = rules_eval.apply_death_save(char, randbelow=randbelow)
        d["last_death_save"] = ds

    loses_move = bool(d["conditions"].pop("lose_next_move", False))
    _begin_turn(char)
    if loses_move:
        d["encounter_turn"]["move_lost"] = True

    injuries = _active_injuries(char)
    if "Spinal Injury" in injuries:
        d["conditions"]["spinal_no_action"] = True
    else:
        d["conditions"].pop("spinal_no_action", None)

    return {
        "death_save": ds,
        "move_lost": loses_move,
        "spinal_no_action": bool(d["conditions"].get("spinal_no_action")),
        "dead": _is_dead(char),
    }


def _clear_grapple_between(cs: dict, target_id: str) -> None:
    """Remove any grapple/choke_tracker references to target_id across all combatants."""
    for cid, char in cs.items():
        if cid == target_id:
            continue
        cd = _detail(char)
        g = cd["conditions"].get("grapple")
        if isinstance(g, dict) and g.get("target_id") == target_id:
            cd["conditions"].pop("grapple", None)
            cd["conditions"].pop("choke_tracker", None)
            if g.get("hand_committed") and cd.get("free_hands") is not None:
                cd["free_hands"] += 1


def add_npc_specs(args: dict) -> list[Any]:
    """The NPC specs of an add_npc call: `npcs`, a single `npc`/`spec`, or the arguments themselves."""
    raw_specs = args.get("npcs")
    if raw_specs is None:
        raw_single = args.get("npc", args.get("spec"))
        if raw_single is not None:
            raw_specs = [raw_single]
        elif args:
            raw_specs = [args]
        else:
            raise ValueError("add_npc requires npc specification")
    if not isinstance(raw_specs, list) or not raw_specs:
        raise ValueError("npcs must be a non-empty list")
    return raw_specs


def _add_npc(e: dict, cs: dict, args: dict, randbelow: Callable[[int], int]) -> dict:
    raw_specs = add_npc_specs(args)

    cur_id = _current(e) if e.get("queue") else None
    existing_ids = set(str(k) for k in cs) | set(str(k) for k in (e.get("npcs") or {}))
    enc_npcs = e.setdefault("npcs", {})
    init_map = e.setdefault("initiative", {})
    added_ids: list[str] = []
    added_sheets: list[dict[str, Any]] = []

    for spec in raw_specs:
        npc = build_npc_combatant(spec, existing_ids=existing_ids)
        nid = npc["id"]
        existing_ids.add(nid)
        roll = initiative(_stat(npc, "REF"), bonus=_initiative_bonus(npc), randbelow=randbelow)
        init_map[nid] = roll
        enc_npcs[nid] = copy.deepcopy(npc)
        cs[nid] = npc
        added_ids.append(nid)
        added_sheets.append(copy.deepcopy(npc))

        q = e.setdefault("queue", [])
        inserted = False
        for idx, qid in enumerate(q):
            q_roll = init_map.get(qid)
            if isinstance(q_roll, dict) and roll["total"] > q_roll.get("total", -999):
                q.insert(idx, nid)
                inserted = True
                break
        if not inserted:
            q.append(nid)

    if cur_id is not None and cur_id in e["queue"]:
        e["turn_index"] = e["queue"].index(cur_id)

    res: dict[str, Any] = {"added": added_ids, "npcs": added_sheets}
    if len(added_sheets) == 1:
        res["npc"] = added_sheets[0]
    return {"encounter": e, "characters": cs, "result": res}


def _remove_npc(e: dict, cs: dict, args: dict) -> dict:
    enc_npcs = e.get("npcs") or {}
    hint = args.get("npc_id") or args.get("target_id") or args.get("id") or args.get("name")
    if not isinstance(hint, str) or not hint.strip():
        raise ValueError("remove_npc requires npc_id or name")
    needle = hint.strip()
    nid = None
    if needle in enc_npcs:
        nid = needle
    else:
        low = needle.casefold()
        matches = [
            k for k, v in enc_npcs.items()
            if isinstance(v, dict)
            and (
                str(v.get("name") or "").strip().casefold() == low
                or str((v.get("detail") or {}).get("handle") or "").strip().casefold() == low
            )
        ]
        if len(matches) == 1:
            nid = matches[0]
    if nid is None:
        raise ValueError(f"unknown encounter NPC: {hint}")

    removed_sheet = enc_npcs.pop(nid, None)
    cs.pop(nid, None)
    if isinstance(e.get("initiative"), dict):
        e["initiative"].pop(nid, None)
    _clear_grapple_between(cs, nid)
    for other_npc in enc_npcs.values():
        if isinstance(other_npc, dict):
            d = _detail(other_npc)
            g = d["conditions"].get("grapple")
            if isinstance(g, dict) and g.get("target_id") == nid:
                d["conditions"].pop("grapple", None)
                d["conditions"].pop("choke_tracker", None)

    q = e.get("queue", [])
    old_idx = e.get("turn_index", 0)
    cur_id = q[old_idx] if q and 0 <= old_idx < len(q) else None
    if nid in q:
        q.remove(nid)
    if not q:
        e["active"] = False
        e["turn_index"] = 0
    elif nid == cur_id:
        if old_idx >= len(q):
            e["round"] = e.get("round", 1) + 1
            e["turn_index"] = 0
        else:
            e["turn_index"] = old_idx
    elif cur_id in q:
        e["turn_index"] = q.index(cur_id)

    removed_name = (removed_sheet or {}).get("name", nid) if isinstance(removed_sheet, dict) else nid
    return {"encounter": e, "characters": cs, "result": {"removed": nid, "name": removed_name}}


def apply_action(
    encounter: dict,
    characters: dict,
    actor_id,
    action: str,
    args: dict | None = None,
    randbelow: Callable[[int], int] = secrets.randbelow,
    rules_path: Any = None,
) -> dict:
    if not isinstance(encounter, dict) or not isinstance(characters, dict):
        raise TypeError("encounter and characters must be objects")
    e, cs, args = copy.deepcopy(encounter), copy.deepcopy(characters), copy.deepcopy(args or {})

    if action == "add_npc":
        return _add_npc(e, cs, args, randbelow)
    if action == "remove_npc":
        return _remove_npc(e, cs, args)

    if actor_id not in cs:
        raise ValueError("unknown actor")

    out_of_turn_allowed = action in ("release", "release_hold")
    if not out_of_turn_allowed and actor_id != _current(e):
        raise ValueError("actor is not current in the initiative queue")

    actor_detail = _detail(cs[actor_id])
    if actor_detail.get("dead") or actor_detail["conditions"].get("unconscious"):
        if action != "next_turn":
            raise ValueError("dead or unconscious character cannot act")

    if action == "next_turn":
        outgoing_id = _current(e)
        outgoing = cs[outgoing_id]
        end_effects = resolve_end_of_turn(outgoing)
        q = e["queue"]
        i = e["turn_index"]
        next_id = None
        for _ in range(len(q)):
            i = (i + 1) % len(q)
            if i == 0:
                e["round"] += 1
            cand = q[i]
            if cand in cs and not _is_dead(cs[cand]):
                next_id = cand
                break
        if next_id is None:
            e["active"] = False
            return {"encounter": e, "characters": cs, "result": {"ended": True, "reason": "No living participants remain", "end_of_turn_effects": end_effects}}
        e["turn_index"] = i
        start_res = resolve_start_of_turn(cs[next_id], randbelow=randbelow)
        return {
            "encounter": e,
            "characters": cs,
            "result": {
                "actor_id": next_id,
                "round": e["round"],
                "death_save": start_res["death_save"],
                "end_of_turn_effects": end_effects,
            },
        }

    c = cs[actor_id]
    d = _detail(c)
    t = _turn(c)

    if d["conditions"].get("flash_out") and action not in ("move", "release", "release_hold"):
        raise ValueError("flash_out prevents an Action this Turn")
    if d["conditions"].get("forced_cover") and action not in ("move", "run", "get_up", "release", "release_hold"):
        raise ValueError("forced_cover requires moving into cover")
    if d["conditions"].get("spinal_no_action") and action not in ("move", "release", "release_hold"):
        raise ValueError("Spinal Injury prevents an Action this Turn")

    state = wound_state(max(0, c.get("hp", c.get("max_hp", 1))), c.get("max_hp", 1), max(0, _injury_move(c) - _armor_penalty(c)))

    if action in ("move", "run"):
        if t.get("move_lost"):
            raise ValueError("injury removed this Turn's Move Action")
        if d["conditions"].get("prone"):
            raise ValueError("prone characters must get_up before moving")
        if d["conditions"].get("grapple", {}).get("role") == "defender":
            raise ValueError("grappled defender cannot move independently")
        if action == "run" and not t["move_used"]:
            raise ValueError("Run requires a prior Move Action this Turn")
        if not t["move_initialized"]:
            t["move_initialized"] = True
            t["move_remaining"] = state["move"] * 2
        if action == "move":
            t["move_used"] = True
        if action == "run":
            if t["action_used"]:
                raise ValueError("Run requires the unused other Action")
            t["action_used"] = True
            t["move_remaining"] += state["move"] * 2
        distance = args.get("meters", t["move_remaining"])
        if type(distance) is not int or distance < 0 or distance > t["move_remaining"]:
            raise ValueError("meters exceeds movement budget")
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
        if t["action_used"] or d["conditions"].get("spinal_no_action"):
            raise ValueError("Action unavailable")
        if not d["conditions"].get("prone"):
            raise ValueError("Get Up requires the Prone condition")
        d["conditions"].pop("prone", None)
        t["action_used"] = True
        return {"encounter": e, "characters": cs, "result": {"stood": True}}

    if action == "extinguish":
        _consume_action(t)
        target_id = args.get("target_id", actor_id)
        if target_id not in cs:
            raise ValueError("valid target_id required")
        if target_id != actor_id and "range_m" in args:
            dist = args["range_m"]
            if type(dist) not in (int, float) or not math.isfinite(dist) or not 0 <= dist <= 2:
                raise ValueError("target must be within 2m")
        td = _detail(cs[target_id])
        extinguished = bool(td["conditions"].pop("burning", None))
        return {"encounter": e, "characters": cs, "result": {"extinguished": extinguished, "target_id": target_id}}

    if action == "reload":
        return _reload_weapon(e, cs, actor_id, args)

    if action == "release" and "trigger" in args:
        return _release_hold(e, cs, actor_id, args)
    if action in ("grab", "choke", "throw", "release", "escape"):
        return _grapple_action(e, cs, actor_id, action, args, randbelow)
    if action == "suppressive_fire":
        return _suppressive_fire(e, cs, actor_id, args, randbelow)
    if action == "hold":
        return _hold_action(e, cs, actor_id, args)
    if action == "release_hold":
        return _release_hold(e, cs, actor_id, args)
    if action != "attack":
        raise ValueError(f"unsupported encounter action: {action}")
    return _attack(e, cs, actor_id, args, randbelow, rules_path)


def _find_ammo_inventory_key(inventory: dict[str, Any], kind: str, ammo_type: str) -> str | None:
    if not isinstance(inventory, dict):
        return None
    if ammo_type == "standard":
        k = f"ammo:{kind}"
        val = inventory.get(k, 0)
        return k if (type(val) is int and val > 0) else None

    candidates = [
        f"ammo:{kind}:{ammo_type}",
        f"ammo:{kind} ({ammo_type})",
        f"ammo:{ammo_type}",
        ammo_type,
    ]
    for cand in candidates:
        val = inventory.get(cand)
        if type(val) is int and val > 0:
            return cand

    # Case-insensitive fallback matching ammo:<type> or <type>
    wanted_norms = {
        f"ammo:{kind}:{ammo_type}".casefold(),
        f"ammo:{kind} ({ammo_type})".casefold(),
        f"ammo:{ammo_type}".casefold(),
        ammo_type.casefold(),
    }
    if ammo_type == "armor_piercing":
        wanted_norms.update({"ammo:ap", "ap", f"ammo:{kind}:ap".casefold(), "ammo:armor-piercing", "armor-piercing"})
    for k, val in inventory.items():
        if isinstance(k, str) and k.strip().casefold() in wanted_norms and type(val) is int and val > 0:
            return k
    return None


def _credit_ammo_inventory(inventory: dict[str, Any], kind: str, ammo_type: str, amount: int) -> None:
    if amount <= 0:
        return
    if ammo_type == "standard":
        key = f"ammo:{kind}"
    else:
        key = _find_ammo_inventory_key(inventory, kind, ammo_type) or f"ammo:{kind}:{ammo_type}"
    cur = inventory.get(key, 0)
    inventory[key] = (cur if type(cur) is int else 0) + amount


def _reload_weapon(e: dict, cs: dict, actor_id: str, args: dict) -> dict:
    c = cs[actor_id]
    d = _detail(c)
    t = _turn(c)
    if d["conditions"].get("spinal_no_action"):
        raise ValueError("Action unavailable")

    weapon = _weapon(d, args.get("weapon_id"))
    definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
    if definition.get("melee") or definition["magazine"] is None:
        raise ValueError("weapon cannot be reloaded")

    kind = args.get("ammo_kind", definition["ammo"])
    if kind != definition["ammo"]:
        raise ValueError("wrong ammunition type")

    ammo_type = _norm_ammo_type(args.get("ammo_type") or "standard")
    mag = int(definition["magazine"])
    old_type = _norm_ammo_type(weapon.get("ammo_type") or "standard")
    current_loaded = weapon.get("loaded") or 0
    if type(current_loaded) is not int or current_loaded < 0:
        current_loaded = 0

    inventory = c.setdefault("inventory", {})
    ammo_key = _find_ammo_inventory_key(inventory, kind, ammo_type)
    count = inventory.get(ammo_key, 0) if ammo_key else 0
    if type(count) is not int or count <= 0:
        raise ValueError("insufficient ammunition to reload")

    effective_loaded = 0 if ammo_type != old_type else current_loaded
    space = mag - effective_loaded
    if space <= 0:
        raise ValueError("magazine is already full")

    requested = args.get("rounds", args.get("count", space))
    if type(requested) is not int or requested < 1 or requested > space:
        raise ValueError("requested reload rounds out of range")

    reload_actions = int(definition.get("reload_actions") or 1)
    _consume_action(t)

    if reload_actions > 1:
        prog = weapon.get("reload_progress")
        if isinstance(prog, dict) and prog.get("ammo_type") == ammo_type:
            done = int(prog.get("actions_done", 0)) + 1
        else:
            done = 1
        if done < reload_actions:
            weapon["reload_progress"] = {
                "actions_done": done,
                "actions_required": reload_actions,
                "ammo_type": ammo_type,
            }
            return {
                "encounter": e,
                "characters": cs,
                "result": {
                    "reloading": weapon["id"],
                    "actions_done": done,
                    "actions_required": reload_actions,
                    "completed": False,
                },
            }
        weapon.pop("reload_progress", None)

    if ammo_type != old_type and current_loaded > 0:
        _credit_ammo_inventory(inventory, kind, old_type, current_loaded)

    to_load = min(requested, space, count)
    inventory[ammo_key] = count - to_load
    weapon.update(loaded=effective_loaded + to_load, ammo_kind=kind, ammo_type=ammo_type)
    c["inventory"] = inventory
    return {
        "encounter": e,
        "characters": cs,
        "result": {
            "reloaded": weapon["id"],
            "loaded": weapon["loaded"],
            "ammo_type": ammo_type,
            "rounds_loaded": to_load,
            "completed": True,
        },
    }


def _consume_action(t):
    if t["action_used"]:
        raise ValueError("Action already used")
    t["action_used"] = True


def _weapon(d, weapon_id):
    matches = [w for w in d["equipment"]["weapons"] if w.get("id") == weapon_id]
    if len(matches) != 1:
        raise ValueError("unknown or ambiguous weapon id")
    w = matches[0]
    if w.get("type") not in WEAPONS and w.get("type") not in EXOTIC_WEAPONS:
        raise ValueError("unknown canonical weapon type")
    return w


def _range_index(distance, count):
    if type(distance) not in (float, int) or not math.isfinite(distance) or distance < 0:
        raise ValueError("range_m must be nonnegative")
    for i, end in enumerate(_RANGE_MAX[:count]):
        if distance <= end:
            return i
    return None


def _cannot_evade(target: dict) -> bool:
    td = _detail(target)
    return bool(
        _is_dead(target)
        or td["conditions"].get("unconscious")
        or "Dismembered Leg" in _active_injuries(target)
    )


def _resolve_non_damage_exotic_hit(
    weapon: dict | None,
    target: dict,
    td: dict,
    armor: list[dict],
    args: dict,
    raw_ammo_type: str,
    randbelow: Callable[[int], int],
    rules_path: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Handle dice_count == 0 exotic weapons (Microwaver, Shrieker, Dartgun, Air Pistol/Acid)."""
    acid_ablation = args.get("acid_ablation") is True or raw_ammo_type == "acid"
    if acid_ablation:
        for a in armor:
            if a.get("sp", 0) > 0:
                a["sp"] = max(0, a["sp"] - 1)

    wtype = weapon.get("type") if isinstance(weapon, dict) else ""
    extra: dict[str, Any] = {}
    direct_dmg = 0

    if wtype == "Microwaver":
        mw_check = attack_check(
            _stat(target, "TECH"),
            _skill(target, "Cybertech"),
            15,
            modifier=_wound_penalty(target),
            randbelow=randbelow,
        )
        disabled = not mw_check["success"]
        if disabled:
            td["conditions"]["cyberware_disabled"] = True
        extra["microwaver_check"] = mw_check
        extra["cyberware_disabled"] = disabled

    elif wtype == "Shrieker":
        has_level_dampers = any(
            "level damper" in label.casefold()
            for label, _ in rules_eval._iter_owned_items(target)
        )
        if has_level_dampers:
            extra["shrieker_immune"] = True
        else:
            sh_check = attack_check(
                _stat(target, "WILL"),
                _skill(target, "Resist Torture/Drugs"),
                15,
                modifier=_wound_penalty(target),
                randbelow=randbelow,
            )
            extra["shrieker_check"] = sh_check
            if not sh_check["success"] and not any(n in _active_injuries(target) for n in ("Damaged Ear", "Lost Ear")):
                crit = {**sourcecatalog.critical_injuries(rules_path)["head"][10], "bonus_damage": 0, "source": SOURCE}
                td["injuries"].append(crit)
                extra["critical_injury"] = crit
                extra["critical_injuries"] = [crit]

    elif wtype == "Dartgun":
        payload = _norm_ammo_type(args.get("payload") or (raw_ammo_type if raw_ammo_type not in ("", "standard") else "poison"))
        if payload not in ("poison", "biotoxin", "sleep"):
            payload = "poison"
        dv = 15 if payload == "biotoxin" else 13
        p_check = attack_check(
            _stat(target, "WILL"),
            _skill(target, "Resist Torture/Drugs"),
            dv,
            modifier=_wound_penalty(target),
            randbelow=randbelow,
        )
        extra["payload"] = payload
        extra["payload_check"] = p_check
        extra["payload_resisted"] = p_check["success"]
        if not p_check["success"]:
            if payload == "sleep":
                td["conditions"]["unconscious"] = True
            elif payload == "biotoxin":
                dice = roll_dice(3, 6, randbelow)
                direct_dmg = sum(dice)
                extra["payload_dice"] = dice
            else:  # poison
                dice = roll_dice(2, 6, randbelow)
                direct_dmg = sum(dice)
                extra["payload_dice"] = dice

            if direct_dmg > 0:
                old_hp = target.get("hp", 0)
                target["hp"] = old_hp - direct_dmg
                td["stabilized"] = False
                if old_hp > 0 >= target["hp"]:
                    td["crossed_mortal_wound_this_attack"] = {
                        "requires_human_ruling": True,
                        "reason": "Whether crossing to Mortally Wounded causes an immediate additional critical injury is unresolved.",
                    }

    damage = {
        "hp_damage": direct_dmg,
        "sp_ablation": 1 if (acid_ablation and armor) else 0,
        "penetration": 0,
        "critical_trigger": False,
        "armor_after": armor,
    }
    return damage, extra


def _attack(e, cs, actor_id, args, randbelow, rules_path):
    attacker = cs[actor_id]
    ad = _detail(attacker)
    turn = _turn(attacker)
    mode = args.get("mode", "ranged")
    target_id = args.get("target_id")
    if target_id not in cs or target_id == actor_id:
        raise ValueError("valid target_id required")
    target = cs[target_id]
    td = _detail(target)

    location = args.get("location", "body")
    if location not in ("body", "head", "leg", "held_item"):
        raise ValueError("invalid hit location")
    aim = location != "body"
    if aim and args.get("aimed", True) is not True:
        raise ValueError("special locations require an aimed attack")
    if aim and mode == "autofire":
        raise ValueError("autofire cannot make aimed shots")

    luck = args.get("luck", 0)
    if type(luck) is not int or luck < 0 or luck > attacker.get("luck_remaining", 0):
        raise ValueError("invalid LUCK spend")

    defender_dodge = args.get("dodge", False)
    if type(defender_dodge) is not bool:
        raise ValueError("dodge must be boolean")

    weapon = None
    definition = None
    if mode in ("brawling", "martial_arts"):
        skill_name = "Brawling" if mode == "brawling" else f"Martial Arts ({args.get('form', '')})"
        if mode == "martial_arts" and (not args.get("form") or _skill(attacker, skill_name) < 1):
            raise ValueError("Martial Arts requires a trained, explicitly named form")
        rof = 2
        dice_count = brawling_dice(_effective_body(attacker), bool(ad.get("cyberarm")) if mode == "brawling" else False, mode == "martial_arts")
        damage_flag = mode
        melee = True
    else:
        weapon = _weapon(ad, args.get("weapon_id"))
        definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
        melee = bool(definition.get("melee"))
        skill_name = "Melee Weapon" if melee else definition["skill"]
        rof = definition["rof"]
        dice_count = definition["damage"][0]
        damage_flag = "melee" if melee else None
        if melee and mode == "ranged":
            mode = "melee"
        if melee and mode != "melee":
            raise ValueError("melee weapons cannot use a ranged fire mode")
        if not melee and mode == "melee":
            raise ValueError("ranged weapon cannot use melee mode")
        if not melee and mode not in ("ranged", "autofire"):
            raise ValueError("mode must be ranged or autofire")
        if definition.get("autofire_only") and mode != "autofire":
            raise ValueError("weapon only fires in autofire mode")
        if definition.get("no_aim") and aim:
            raise ValueError("weapon cannot make aimed shots")
        min_body = definition.get("min_body")
        if min_body and _effective_body(attacker) < min_body:
            raise ValueError(f"weapon requires BODY {min_body}+")
        if definition.get("range") in ("grenade_launcher", "rocket_launcher"):
            raise ValueError("explosive attacks require area placement and blast resolution; ordinary single-target attack is prohibited")
        if ad["conditions"].get("grapple") and (definition.get("hands") or 0) >= 2:
            raise ValueError("cannot use a two-handed weapon while grappled")
        if not melee:
            if weapon["type"] == "Bows & Crossbows":
                bow_ammo_type = _norm_ammo_type(args.get("ammo_type") or "standard")
                if bow_ammo_type == "standard":
                    if c_inventory_count(attacker, "Arrow") < 1:
                        raise ValueError("no arrows in inventory")
                else:
                    if not _find_ammo_inventory_key(attacker.get("inventory", {}), "Arrow", bow_ammo_type):
                        raise ValueError(f"no {bow_ammo_type} arrows in inventory")
            elif weapon.get("loaded", 0) <= (19 if weapon.get("type") in ("Helix", "Tsunami Arms Helix") and mode == "autofire" else (9 if mode == "autofire" else 0)):
                raise ValueError("insufficient loaded ammunition")
            if weapon.get("ammo_kind") != definition["ammo"]:
                raise ValueError("loaded ammo does not match canonical weapon")
            if "ammo_type" in weapon and weapon["ammo_type"] is not None and args.get("ammo_type") is not None:
                if _norm_ammo_type(args["ammo_type"]) != _norm_ammo_type(weapon["ammo_type"]):
                    raise ValueError("requested ammo_type does not match loaded weapon ammo_type")

    if aim:
        _consume_action(turn)
        count = 1
    elif rof == 1:
        if turn["rof2_used"]:
            raise ValueError("cannot combine ROF 1 with ROF 2 attacks")
        if turn["rof1_used"]:
            raise ValueError("ROF 1 attack already made")
        _consume_action(turn)
        turn["rof1_used"] = True
        count = 1
    else:
        if (turn["action_used"] and turn["rof2_used"] == 0) or turn["rof1_used"] or turn["rof2_used"] >= 2:
            raise ValueError("attack allowance exhausted")
        if turn["rof2_used"] == 0:
            turn["action_used"] = True
        turn["rof2_used"] += 1
        count = 1

    distance = args.get("range_m")
    if melee:
        if type(distance) not in (int, float) or not math.isfinite(distance) or not 0 <= distance <= 2:
            raise ValueError("melee target must be within 2m")
        dv = None
    else:
        if type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0:
            raise ValueError("range_m required")
        key = definition["range"]
        if mode == "autofire":
            vals = AUTOFIRE_DVS.get(key)
            if vals is None:
                raise ValueError("weapon has no canonical Autofire mode")
            idx = _range_index(distance, 5)
            if idx is None:
                raise ValueError("target out of Autofire range")
            dv = vals[idx]
        else:
            idx = _range_index(distance, 8)
            dv = None if idx is None else RANGE_DVS[key][idx]
            if dv is None:
                raise ValueError("target out of weapon range")

    raw_ammo_type = _norm_ammo_type(
        weapon.get("ammo_type") if (weapon and weapon.get("ammo_type") is not None) else args.get("ammo_type")
    )

    if mode == "autofire":
        weapon["loaded"] -= (20 if weapon and weapon.get("type") in ("Helix", "Tsunami Arms Helix") else 10)
        weapon.pop("reload_progress", None)
    elif weapon and not melee:
        if weapon["type"] == "Bows & Crossbows":
            inv = attacker.setdefault("inventory", {})
            akey = _find_ammo_inventory_key(inv, "Arrow", raw_ammo_type) or "ammo:Arrow"
            inv[akey] -= 1
        else:
            weapon["loaded"] -= 1
            weapon.pop("reload_progress", None)

    attacker["luck_remaining"] = attacker.get("luck_remaining", 0) - luck
    cannot_evade = _cannot_evade(target)
    results = []

    for _ in range(count):
        if melee:
            check = attack_check(
                _stat(attacker, "DEX"),
                _skill(attacker, skill_name),
                0,
                modifier=(-8 if aim else 0) + _wound_penalty(attacker) + (-2 if "Torn Muscle" in _active_injuries(attacker) else 0),
                luck=luck,
                randbelow=randbelow,
            )
            if cannot_evade:
                hit = True
            else:
                defense = attack_check(
                    _stat(target, "DEX"),
                    _skill(target, "Evasion"),
                    0,
                    modifier=_wound_penalty(target),
                    randbelow=randbelow,
                )
                check["defense"] = defense
                hit = check["total"] > defense["total"]
        else:
            atk_skill = "Autofire" if mode == "autofire" else skill_name
            atk_mod = (-8 if aim else 0) + _wound_penalty(attacker) + _ranged_injury_penalty(attacker)
            if defender_dodge and not cannot_evade and _stat(target, "REF") >= 8:
                check = attack_check(_stat(attacker, "REF"), _skill(attacker, atk_skill), 0, modifier=atk_mod, luck=luck, randbelow=randbelow)
                defense = attack_check(_stat(target, "DEX"), _skill(target, "Evasion"), 0, modifier=_wound_penalty(target), randbelow=randbelow)
                check["defense"] = defense
                hit = check["total"] > defense["total"]
            else:
                check = attack_check(_stat(attacker, "REF"), _skill(attacker, atk_skill), dv, modifier=atk_mod, luck=luck, randbelow=randbelow)
                hit = check["success"]

        item: dict[str, Any] = {"check": check, "hit": hit}
        if hit:
            is_rubber = raw_ammo_type == "rubber"
            is_non_lethal = bool(definition and definition.get("non_lethal"))
            no_critical = is_rubber or is_non_lethal or bool(definition and definition.get("no_critical"))
            is_incendiary = bool(definition and definition.get("incendiary")) or raw_ammo_type == "incendiary"

            ablation = 1
            if raw_ammo_type == "armor_piercing":
                ablation = 2
            elif is_rubber:
                ablation = 0
            elif definition and definition.get("ablation") is not None:
                ablation = definition["ablation"]

            loc = "head" if location == "head" else "body"
            armor = [a for a in td["equipment"]["armor"] if a.get("location") == loc]

            if dice_count == 0:
                damage, extra = _resolve_non_damage_exotic_hit(weapon, target, td, armor, args, raw_ammo_type, randbelow, rules_path)
                item["damage"] = damage
                item.setdefault("critical_injury", None)
                item.setdefault("critical_injuries", [])
                item.update(extra)
            else:
                if mode == "autofire":
                    dice = roll_dice(2, 6, randbelow)
                    margin = max(1, check["total"] - (check["defense"]["total"] if "defense" in check else dv))
                else:
                    dice = roll_dice(dice_count, 6, randbelow)
                    margin = None

                damage = damage_and_armor(
                    dice,
                    armor,
                    location=loc,
                    melee=damage_flag == "melee",
                    martial_arts=damage_flag == "martial_arts",
                    brawling=damage_flag == "brawling",
                    autofire_margin=margin,
                    autofire_cap=definition.get("autofire") if mode == "autofire" else None,
                    cracked_skull="Cracked Skull" in _active_injuries(target),
                    ablation=ablation,
                )
                if no_critical and damage["critical_trigger"]:
                    damage["hp_damage"] = max(0, damage["hp_damage"] - 5)
                    damage["critical_trigger"] = False

                td["equipment"]["armor"] = [
                    next((p for p in damage["armor_after"] if p["id"] == a["id"]), a) if a.get("location") == loc else a
                    for a in td["equipment"]["armor"]
                ]

                was_mortal = target.get("hp", 0) <= 0
                old_hp = target.get("hp", 0)
                hp_dmg = damage["hp_damage"]

                if is_non_lethal:
                    # Stun Baton / Stun Gun: clamp hp >= 1 and set unconscious if damage would drop HP < 1
                    if old_hp >= 1:
                        new_hp = old_hp - hp_dmg
                        if new_hp < 1:
                            target["hp"] = 1
                            td["conditions"]["unconscious"] = True
                        else:
                            target["hp"] = new_hp
                    else:
                        td["conditions"]["unconscious"] = True
                elif is_rubber:
                    # Rubber Ammunition: clamp hp >= 1 when old_hp >= 1
                    if old_hp >= 1:
                        new_hp = old_hp - hp_dmg
                        target["hp"] = 1 if new_hp < 1 else new_hp
                else:
                    target["hp"] = old_hp - hp_dmg
                    if old_hp > 0 >= target["hp"]:
                        td["crossed_mortal_wound_this_attack"] = {
                            "requires_human_ruling": True,
                            "reason": "Whether crossing to Mortally Wounded causes an immediate additional critical injury is unresolved.",
                        }

                if hp_dmg > 0 and target["hp"] < old_hp:
                    td["stabilized"] = False

                if is_incendiary and damage["penetration"] > 0:
                    td["conditions"]["burning"] = True

                mortal_hit = was_mortal and hp_dmg > 0 and not is_non_lethal and not is_rubber
                if mortal_hit:
                    td["death_save_penalty"] = td.get("death_save_penalty", 0) + 1

                criticals = []
                if not no_critical:
                    for is_mortal_trigger in ([False] if damage["critical_trigger"] else []) + ([True] if mortal_hit else []):
                        critical = critical_injury(loc, [x.get("name", "") for x in td["injuries"]], rules_path, randbelow)
                        criticals.append(critical)
                        if not critical.get("requires_human_ruling"):
                            td["injuries"].append(critical)
                            rules_eval.recompute_death_save_base_penalty(target)
                            if is_mortal_trigger:
                                target["hp"] -= critical.get("bonus_damage", 5)
                                td["stabilized"] = False

                item.update(damage=damage, critical_injury=criticals[0] if criticals else None, critical_injuries=criticals)

                if (
                    location == "leg"
                    and not no_critical
                    and damage["penetration"] > 0
                    and not any(n in _active_injuries(target) for n in ("Broken Leg", "Dismembered Leg"))
                ):
                    broken_leg = sourcecatalog.critical_injuries(rules_path)["body"][8]
                    td["injuries"].append({**broken_leg, "bonus_damage": 5, "source": SOURCE})
                    target["hp"] -= 5
                    td["stabilized"] = False

                if location == "held_item" and damage["penetration"] > 0:
                    wanted = args.get("held_item_id")
                    held_items = td["equipment"].get("held_items", [])
                    found = next((x for x in held_items if x.get("id") == wanted), None)
                    if found is None:
                        raise ValueError("held_item_id must identify a held item")
                    held_items.remove(found)
                    td.setdefault("dropped_items", []).append(found)
        results.append(item)
    return {"encounter": e, "characters": cs, "result": {"attacks": results}}


def _opposed_brawl(a, b, randbelow, modifier_a=0):
    ca = attack_check(_stat(a, "DEX"), _skill(a, "Brawling"), 0, modifier=modifier_a + _wound_penalty(a), randbelow=randbelow)
    cb = attack_check(_stat(b, "DEX"), _skill(b, "Brawling"), 0, modifier=_wound_penalty(b), randbelow=randbelow)
    return ca, cb, ca["total"] > cb["total"]


def _grapple_action(e, cs, actor_id, action, args, randbelow):
    a = cs[actor_id]
    ad = _detail(a)
    turn = _turn(a)
    target_id = args.get("target_id")
    if action == "release":
        g = ad["conditions"].pop("grapple", None)
        if not g or g.get("role") != "attacker":
            raise ValueError("only the attacker may end a Grapple without an Action")
        other = _detail(cs[g["target_id"]])
        other["conditions"].pop("grapple", None)
        other["conditions"].pop("choke_tracker", None)
        ad["conditions"].pop("choke_tracker", None)
        if ad.get("free_hands") is not None:
            ad["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"released": g["target_id"]}}
    if target_id not in cs or target_id == actor_id:
        raise ValueError("valid target_id required")
    b = cs[target_id]
    bd = _detail(b)
    if action == "grab":
        if turn["action_used"]:
            raise ValueError("Action already used")
        if ad["conditions"].get("grapple"):
            raise ValueError("already grappling")
        if type(ad.get("free_hands")) is not int or ad["free_hands"] < 1:
            raise ValueError("Grab requires explicit free-hand inventory in detail.free_hands")
        grab_dist = args.get("range_m", 99)
        if type(grab_dist) not in (int, float) or not math.isfinite(grab_dist) or grab_dist < 0 or grab_dist > 2:
            raise ValueError("target is outside 2m reach")
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
        if not grapple or grapple.get("target_id") != actor_id or grapple.get("role") != "attacker":
            raise ValueError("target is not grappling actor")
        check_a, check_b, won = _opposed_brawl(a, b, randbelow, 0)
        _consume_action(turn)
        if won:
            ad["conditions"].pop("grapple", None)
            bd["conditions"].pop("grapple", None)
            ad["conditions"].pop("choke_tracker", None)
            bd["conditions"].pop("choke_tracker", None)
            if bd.get("free_hands") is not None:
                bd["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"escaped": won, "attacker": check_a, "defender": check_b}}
    if not grapple or grapple.get("target_id") != target_id or grapple.get("role") != "attacker":
        raise ValueError("actor is not grappling target")
    if action == "choke":
        _consume_action(turn)
        direct = _effective_body(a)
        old = b.get("hp", 0)
        new = old - direct
        if old > 1 and new < 1:
            new = 1
            bd["conditions"]["unconscious"] = True
        b["hp"] = new
        dealt = old - b["hp"]
        if dealt > 0:
            bd["stabilized"] = False
        prior = bd["conditions"].get("choke_tracker", {})
        rounds = prior.get("count", 0) + 1 if prior.get("last_round") == e["round"] - 1 else 1
        bd["conditions"]["choke_tracker"] = {"count": rounds, "last_round": e["round"]}
        if rounds >= 3:
            bd["conditions"]["unconscious"] = True
        return {"encounter": e, "characters": cs, "result": {"direct_damage": dealt, "unconscious": bool(bd["conditions"].get("unconscious"))}}
    if action == "throw":
        _consume_action(turn)
        direct = _effective_body(a)
        b["hp"] = b.get("hp", 0) - direct
        if direct > 0:
            bd["stabilized"] = False
        bd["conditions"]["prone"] = True
        ad["conditions"].pop("grapple", None)
        bd["conditions"].pop("grapple", None)
        ad["conditions"].pop("choke_tracker", None)
        bd["conditions"].pop("choke_tracker", None)
        if ad.get("free_hands") is not None:
            ad["free_hands"] += 1
        return {"encounter": e, "characters": cs, "result": {"direct_damage": direct, "thrown_prone": True}}
    raise ValueError("unsupported grapple action")


def _suppressive_fire(e, cs, actor_id, args, randbelow):
    a = cs[actor_id]
    ad = _detail(a)
    t = _turn(a)
    weapon = _weapon(ad, args.get("weapon_id"))
    definition = WEAPONS.get(weapon["type"]) or EXOTIC_WEAPONS[weapon["type"]]
    if definition.get("autofire") is None:
        raise ValueError("weapon does not support suppressive fire")
    if weapon.get("loaded", 0) < 10 or weapon.get("ammo_kind") != definition["ammo"]:
        raise ValueError("requires 10 correctly loaded bullets")
    for row in args.get("targets", []):
        distance = row.get("range_m")
        if type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0:
            raise ValueError("range_m must be nonnegative")
    _consume_action(t)
    weapon["loaded"] -= 10
    roll = attack_check(_stat(a, "REF"), _skill(a, "Autofire"), 0, modifier=_wound_penalty(a), randbelow=randbelow)
    forced = []
    for row in args.get("targets", []):
        tid = row.get("target_id")
        distance = row.get("range_m")
        if tid not in cs or tid == actor_id:
            raise ValueError("invalid suppressive-fire target")
        if distance > 25 or row.get("covered") or not row.get("line_of_sight") or not row.get("on_foot"):
            continue
        target = cs[tid]
        defense = attack_check(_stat(target, "WILL"), _skill(target, "Concentration"), 0, modifier=_wound_penalty(target), randbelow=randbelow)
        panic = defense["total"] < roll["total"]
        if panic:
            _detail(target)["conditions"]["forced_cover"] = {"by": actor_id, "move": True, "run_if_needed": True}
        forced.append({"target_id": tid, "check": defense, "forced_to_cover": panic})
    return {"encounter": e, "characters": cs, "result": {"attack_check": roll, "targets": forced}}


def _hold_action(e, cs, actor_id, args):
    c = cs[actor_id]
    d = _detail(c)
    t = _turn(c)
    held = args.get("held_action")
    target = args.get("target_id")
    trigger = args.get("trigger")
    if not isinstance(held, str) or not held or not isinstance(trigger, str) or not trigger or target not in cs:
        raise ValueError("Hold requires declared action, trigger, and target")
    _consume_action(t)
    d["held_action"] = {"action": held, "target_id": target, "trigger": trigger, "owner": actor_id}
    return {"encounter": e, "characters": cs, "result": {"held": copy.deepcopy(d["held_action"])}}


def _release_hold(e, cs, actor_id, args):
    held = _detail(cs[actor_id]).get("held_action")
    if not held or args.get("trigger") != held["trigger"]:
        raise ValueError("held action trigger does not match")
    del _detail(cs[actor_id])["held_action"]
    return {"encounter": e, "characters": cs, "result": {"released_action": held["action"], "target_id": held["target_id"], "trigger": held["trigger"]}}


def _wound_penalty(c):
    names = _active_injuries(c)
    grapple = c.get("detail", {}).get("conditions", {}).get("grapple")
    wound_pen = rules_eval.effective_wound_penalty(c)
    inj_pen = -2 * sum(n in names for n in ("Brain Injury", "Concussion"))
    return wound_pen + inj_pen - (2 if grapple else 0)


def _ranged_injury_penalty(c):
    names = _active_injuries(c)
    return -4 if "Lost Eye" in names else -2 if "Damaged Eye" in names else 0


def _dv_evasion(c):
    return _stat(c, "DEX") + _skill(c, "Evasion") + 10
