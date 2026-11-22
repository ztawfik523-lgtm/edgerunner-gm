"""Canonical-catalog-backed equipment and inventory transitions."""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

import encounters
import netrunning
import rules_eval
import sourcecatalog


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _normalized(value):
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _alnum_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _header_key(header: str) -> str:
    return re.sub(r"[^a-z]", "", str(header).casefold())


def _item(catalog, item_id):
    if not isinstance(item_id, str) or item_id not in catalog:
        raise ValueError("item_id must identify an exact source-catalog item")
    return catalog[item_id]


def _detail(ch):
    detail = ch.setdefault("detail", {})
    detail.setdefault("equipment", {}).setdefault("weapons", [])
    detail["equipment"].setdefault("armor", [])
    detail.setdefault("catalog_items", {})
    return detail


def _field(item, wanted):
    wanted_tuple = (wanted,) if isinstance(wanted, str) else tuple(wanted)
    columns = item.get("columns", [])
    cells = item.get("cells", [])
    for target in wanted_tuple:
        for header, value in zip(columns, cells):
            if _header_key(header) == target:
                return value
    return ""


def _has_header(item, wanted_tuple: tuple[str, ...]) -> bool:
    return any(_header_key(header) in wanted_tuple for header in item.get("columns", []))


def _parse_sp(item: dict[str, Any]) -> int | None:
    raw = _field(item, ("sp", "stoppingpower", "stoppingpowersp", "damagestoppingpowersp", "damagestoppingpower"))
    if not raw:
        for header, value in zip(item.get("columns", []), item.get("cells", [])):
            hk = _header_key(header)
            if hk.startswith(("stoppingpower", "damagestoppingpower")):
                raw = value
                break
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            low = text.casefold()
            if "hp" in low and "sp" not in low:
                return 0
            m = re.search(r"(\d+)", text)
            if m:
                return int(m.group(1))
    stats = item.get("stats")
    if isinstance(stats, dict):
        for k in ("sp", "stopping_power", "damage_stopping_power_sp"):
            val = stats.get(k)
            if isinstance(val, int) and not isinstance(val, bool):
                return max(0, val)
            if isinstance(val, str) and val.strip():
                if "hp" in val.casefold() and "sp" not in val.casefold():
                    return 0
                m = re.search(r"(\d+)", val)
                if m:
                    return int(m.group(1))
    for text_src in (item.get("description"), item.get("summary"), item.get("name")):
        if isinstance(text_src, str) and text_src.strip():
            m = re.search(r"\bSP\s*[:=]?\s*(\d+)\b|\b(\d+)\s*SP\b", text_src, re.I)
            if m:
                return int(m.group(1) or m.group(2))
    return None


def _parse_penalty_value(raw: Any) -> int | None:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return abs(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        low = text.casefold()
        if low in {"none", "no penalty", "n/a", "-", "—", "–", "0"}:
            return 0
        if re.fullmatch(r"[+-]?\s*\d+", text):
            return abs(int(text.replace(" ", "")))
        m = re.match(r"^[+-]?\s*(\d+)\b", text)
        if m:
            return int(m.group(1))
        m = re.search(r"(?:^|[\s(:])-\s*(\d+)\b", text)
        if m:
            return int(m.group(1))
        if "requires" in low or "arm" in low or "see" in low:
            return 0
    return None


def _parse_armor_penalty(item: dict[str, Any]) -> int | None:
    penalty_headers = ("armorpenalty", "armorpenaltyminimum", "armorpenaltyminimum0", "penalty", "armorpen")
    raw = _field(item, penalty_headers)
    if not raw:
        for header, value in zip(item.get("columns", []), item.get("cells", [])):
            if _header_key(header).startswith("armorpenalty"):
                raw = value
                break
    parsed = _parse_penalty_value(raw)
    if parsed is not None:
        return parsed
    stats = item.get("stats")
    if isinstance(stats, dict):
        for k in ("penalty", "armor_penalty", "armor_penalty_minimum_0"):
            if k in stats and stats[k] is not None:
                parsed = _parse_penalty_value(stats[k])
                if parsed is not None:
                    return parsed
    for text_src in (item.get("description"), item.get("summary")):
        if isinstance(text_src, str) and text_src.strip():
            m = re.search(r"armor\s*penalty\s*:\s*([^\n.;]+)", text_src, re.I)
            if m:
                parsed = _parse_penalty_value(m.group(1))
                if parsed is not None:
                    return parsed
            if "no penalty" in text_src.casefold():
                return 0
    return None


_PROGRAM_ALIASES = {"speedygonzalez": "Speedy Gonzalvez"}
_PROGRAM_BY_KEY = {_alnum_key(k): k for k in netrunning.PROGRAMS}
_PROGRAM_BY_KEY.update(_PROGRAM_ALIASES)
_HARDWARE_BY_KEY = {_alnum_key(k): k for k in netrunning.HARDWARE}


def _resolve_program(item: dict[str, Any]) -> tuple[str, int, int] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    for candidate in (name, stripped):
        key = _alnum_key(candidate)
        if key in _PROGRAM_BY_KEY:
            canon_name = _PROGRAM_BY_KEY[key]
            defn = netrunning.PROGRAMS[canon_name]
            max_rez = int(defn["rez"])
            slot_cost = 2 if defn["type"] == "Black ICE" else 1
            return canon_name, max_rez, slot_cost
    cat = str(item.get("category") or "").casefold()
    if cat == "program" or (_has_header(item, ("rez", "program", "programname")) and cat not in {"weapon", "armor", "cyberware", "fashion"}):
        rez_raw = _field(item, ("rez",))
        m_rez = re.search(r"(\d+)", str(rez_raw))
        max_rez = int(m_rez.group(1)) if m_rez else 0
        slots_raw = _field(item, ("slots", "slot", "slotcost"))
        m_slots = re.search(r"(\d+)", str(slots_raw))
        if m_slots:
            slot_cost = max(1, int(m_slots.group(1)))
        else:
            combined = f"{name} {' '.join(str(c) for c in item.get('cells', []))} {item.get('description') or ''}".casefold()
            slot_cost = 2 if "black ice" in combined else 1
        return name, max_rez, slot_cost
    return None


def _resolve_hardware(item: dict[str, Any]) -> tuple[str, int] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    stripped = re.sub(r"\s*\(Cyberdeck[^)]*\)", "", name, flags=re.I).strip()
    stripped_any = re.sub(r"\s*\([^)]*\)\s*$", "", stripped).strip()
    for candidate in (name, stripped, stripped_any):
        key = _alnum_key(candidate)
        if key in _HARDWARE_BY_KEY:
            canon_name = _HARDWARE_BY_KEY[key]
            return canon_name, int(netrunning.HARDWARE[canon_name])
    cat = str(item.get("category") or "").casefold()
    combined = f"{name} {' '.join(str(c) for c in item.get('columns', []))} {' '.join(str(c) for c in item.get('cells', []))} {item.get('description') or ''}".casefold()
    if cat == "hardware" and ("cyberdeck" in combined or "slot" in combined) and "emplaced" not in combined and "turret" not in name.casefold():
        if "cyberdeck" in _alnum_key(name) and "(cyberdeck" not in name.casefold():
            return None
        slots_raw = _field(item, ("slots", "slot", "slotcost"))
        m_slots = re.search(r"(\d+)", str(slots_raw)) or re.search(r"(\d+)\s*slots?", combined, re.I)
        slot_cost = max(1, int(m_slots.group(1))) if m_slots else 1
        return stripped or name, slot_cost
    return None


def _resolve_cyberdeck(item: dict[str, Any]) -> int | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    cat = str(item.get("category") or "").casefold()
    low_name = name.casefold()
    if cat in {"weapon", "armor", "cyberware", "program", "fashion"}:
        return None
    if "(cyberdeck" in low_name or _resolve_program(item) is not None or _resolve_hardware(item) is not None:
        return None
    is_deck = (
        "cyberdeck" in low_name
        or cat in {"cyberdeck", "deck"}
        or ("deck" in low_name and any(_header_key(h) in {"slots", "capacity", "totalslots", "deckslots", "programslots"} for h in item.get("columns", [])))
    )
    if not is_deck:
        return None
    slots_raw = _field(item, ("slots", "capacity", "totalslots", "deckslots", "programslots"))
    m_col = re.search(r"(\d+)", str(slots_raw))
    if m_col:
        return max(1, int(m_col.group(1)))
    stats = item.get("stats")
    if isinstance(stats, dict):
        for k in ("slots", "capacity"):
            val = stats.get(k)
            if type(val) is int and val > 0:
                return val
    combined = f"{name} {' '.join(str(c) for c in item.get('cells', []))} {item.get('description') or ''} {item.get('summary') or ''}"
    m_text = re.search(r"(\d+)\s*slots?", combined, re.I)
    if m_text:
        return max(1, int(m_text.group(1)))
    low_combined = combined.casefold()
    if "poor" in low_combined:
        return 5
    if "excellent" in low_combined:
        return 9
    if "standard" in low_combined:
        return 7
    return 7


def _is_valid_deck(deck: Any) -> bool:
    if not isinstance(deck, dict):
        return False
    slots = deck.get("slots") if type(deck.get("slots")) is int else deck.get("capacity")
    return type(slots) is int and slots > 0


def _used_deck_slots(deck: dict[str, Any]) -> int:
    prog_slots = sum(
        int(p.get("slots", 1))
        for p in deck.get("programs", [])
        if isinstance(p, dict)
    )
    hw_slots = sum(
        int(h.get("slots", 1))
        for h in deck.get("hardware", [])
        if isinstance(h, dict)
    )
    return prog_slots + hw_slots


def _equipped_count(detail: dict[str, Any], item_id: str) -> int:
    equipment = detail.get("equipment") if isinstance(detail.get("equipment"), dict) else {}
    weapons = equipment.get("weapons") if isinstance(equipment.get("weapons"), list) else []
    armor = equipment.get("armor") if isinstance(equipment.get("armor"), list) else []
    weapon_c = sum(
        1 for w in weapons
        if isinstance(w, dict) and w.get("equipped") is not False and w.get("item_id") == item_id
    )
    body_c = sum(
        1 for a in armor
        if isinstance(a, dict) and a.get("equipped") is not False and a.get("item_id") == item_id
        and str(a.get("location") or "body").strip().casefold() == "body"
    )
    head_c = sum(
        1 for a in armor
        if isinstance(a, dict) and a.get("equipped") is not False and a.get("item_id") == item_id
        and str(a.get("location") or "").strip().casefold() == "head"
    )
    both_c = sum(
        1 for a in armor
        if isinstance(a, dict) and a.get("equipped") is not False and a.get("item_id") == item_id
        and str(a.get("location") or "").strip().casefold() == "body & head"
    )
    armor_c = max(body_c, head_c) + both_c
    deck = detail.get("deck")
    deck_c = 1 if isinstance(deck, dict) and deck.get("item_id") == item_id else 0
    prog_c = sum(
        1 for p in deck.get("programs", [])
        if isinstance(p, dict) and p.get("item_id") == item_id
    ) if isinstance(deck, dict) else 0
    hw_c = sum(
        1 for h in deck.get("hardware", [])
        if isinstance(h, dict) and h.get("item_id") == item_id
    ) if isinstance(deck, dict) else 0
    return weapon_c + armor_c + deck_c + prog_c + hw_c


def apply_action(character: dict, action: str, args: dict, rules_path,
                 randbelow: Callable[[int], int]) -> dict:
    if not isinstance(character, dict) or not isinstance(args, dict):
        raise TypeError("character and args must be objects")
    if not callable(randbelow):
        raise TypeError("randbelow must be callable")
    ch = copy.deepcopy(character)
    catalog = sourcecatalog.items(rules_path)
    detail = _detail(ch)
    inventory = ch.setdefault("inventory", {})
    if not isinstance(inventory, dict):
        raise ValueError("inventory must be an object")
    money = _integer(ch.get("money", 0), "money")
    if action in {"buy", "sell", "consume", "equip_weapon", "equip_armor", "equip_deck", "install_program", "install_hardware"}:
        item_id = args.get("item_id")
        item = _item(catalog, item_id)
    if action in ("buy", "sell"):
        quantity = _integer(args.get("quantity", 1), "quantity", 1)
        price = item["cost"]
        if action == "buy":
            total = price * quantity
            if money < total: raise ValueError("insufficient money")
            ch["money"] = money - total
            inventory[item_id] = _integer(inventory.get(item_id, 0), "inventory count") + quantity
            detail["catalog_items"][item_id] = copy.deepcopy(item)
        else:
            count = _integer(inventory.get(item_id, 0), "inventory count")
            if count < quantity: raise ValueError("insufficient owned items")
            eq_count = _equipped_count(detail, item_id)
            if count - quantity < eq_count:
                raise ValueError("cannot sell currently equipped item")
            total = price * quantity
            inventory[item_id] = count - quantity
            ch["money"] = money + total
        result = {"item_id": item_id, "quantity": quantity, "eb": total, "action": action}
    elif action == "consume":
        count = _integer(inventory.get(item_id, 0), "inventory count")
        quantity = _integer(args.get("quantity", 1), "quantity", 1)
        if count < quantity: raise ValueError("insufficient owned items")
        eq_count = _equipped_count(detail, item_id)
        if count - quantity < eq_count:
            raise ValueError("cannot consume currently equipped item")
        inventory[item_id] = count - quantity
        result = {"consumed": quantity, "item_id": item_id}
    elif action == "equip_weapon":
        if item.get("category") != "weapon" or not any(_normalized(item["name"]) == _normalized(x) for x in encounters.WEAPONS):
            raise ValueError("source item is not a supported canonical weapon")
        count = _integer(inventory.get(item_id, 0), "inventory count")
        if count < 1: raise ValueError("weapon is not owned")
        weapon_type = next(x for x in encounters.WEAPONS if _normalized(x) == _normalized(item["name"]))
        inv = detail["equipment"]["weapons"]
        equipped_copies = sum(
            1 for w in inv
            if isinstance(w, dict) and w.get("equipped") is not False and w.get("item_id") == item_id
        )
        if equipped_copies >= count:
            raise ValueError("cannot equip more copies of weapon than owned")
        index = detail.get("next_weapon_index", len(inv))
        _integer(index, "next_weapon_index")
        if index < len(inv):
            index = len(inv)
        definition = encounters.WEAPONS[weapon_type]
        weapon = {"id": f"weapon-{index}", "item_id": item_id, "type": weapon_type, "loaded": 0,
                  "ammo_kind": definition.get("ammo")}
        inv.append(weapon)
        detail["next_weapon_index"] = index + 1
        result = {"equipped": copy.deepcopy(weapon)}
    elif action == "equip_armor":
        if item.get("category") != "armor": raise ValueError("item is not canonical armor")
        count = _integer(inventory.get(item_id, 0), "inventory count")
        if count < 1: raise ValueError("armor is not owned")
        sp_val = _parse_sp(item)
        penalty_val = _parse_armor_penalty(item)
        if sp_val is None or penalty_val is None:
            raise ValueError("source armor SP or ArmorPenalty is unavailable for this item")
        location = args.get("location")
        if location not in ("body", "head"): raise ValueError("location must be body or head")
        armor_list = detail["equipment"]["armor"]
        equipped_at_loc = sum(
            1 for a in armor_list
            if isinstance(a, dict) and a.get("equipped") is not False and a.get("item_id") == item_id
            and str(a.get("location") or "body").strip().casefold() in {location, "body & head"}
        )
        if equipped_at_loc >= count:
            raise ValueError("cannot equip more copies of armor than owned")
        index = detail.get("next_armor_index", len(armor_list))
        _integer(index, "next_armor_index")
        if index < len(armor_list):
            index = len(armor_list)
        armor = {"id": f"armor-{index}", "item_id": item_id, "type": item["name"],
                 "sp": sp_val, "max_sp": sp_val, "location": location, "penalty": penalty_val}
        armor_list.append(armor)
        detail["next_armor_index"] = index + 1
        result = {"equipped": copy.deepcopy(armor)}
    elif action == "equip_deck":
        slots = _resolve_cyberdeck(item)
        if slots is None:
            result = {"requires_human_ruling": True, "reason": "Catalog item is not an identifiable cyberdeck."}
        else:
            count = _integer(inventory.get(item_id, 0), "inventory count")
            if count < 1: raise ValueError("cyberdeck is not owned")
            existing = detail.get("deck")
            if isinstance(existing, dict) and existing.get("item_id") == item_id and count <= 1:
                raise ValueError("cannot equip more copies of cyberdeck than owned")
            deck_obj = {
                "item_id": item_id,
                "name": item["name"],
                "slots": slots,
                "capacity": slots,
                "programs": [],
                "hardware": [],
            }
            detail["deck"] = deck_obj
            result = {"equipped_deck": copy.deepcopy(deck_obj)}
    elif action == "install_program":
        prog = _resolve_program(item)
        if prog is None:
            result = {"requires_human_ruling": True, "reason": "Catalog item is not an identifiable cyberdeck program."}
        else:
            canon_name, max_rez, slot_cost = prog
            deck = detail.get("deck")
            if not _is_valid_deck(deck):
                raise ValueError("no cyberdeck is equipped")
            count = _integer(inventory.get(item_id, 0), "inventory count")
            if count < 1: raise ValueError("program is not owned")
            progs = deck.setdefault("programs", [])
            installed_copies = sum(
                1 for p in progs if isinstance(p, dict) and p.get("item_id") == item_id
            )
            if installed_copies >= count:
                raise ValueError("cannot install more copies of program than owned")
            deck_slots = deck.get("slots") if type(deck.get("slots")) is int else deck.get("capacity")
            if _used_deck_slots(deck) + slot_cost > deck_slots:
                raise ValueError("insufficient cyberdeck slots")
            index = detail.get("next_program_index", len(progs))
            _integer(index, "next_program_index")
            if index < len(progs):
                index = len(progs)
            entry = {
                "id": f"prog-{index}",
                "item_id": item_id,
                "name": canon_name,
                "rez": max_rez,
                "max_rez": max_rez,
                "slots": slot_cost,
                "active": False,
            }
            progs.append(entry)
            detail["next_program_index"] = index + 1
            result = {"installed_program": copy.deepcopy(entry)}
    elif action == "install_hardware":
        hw = _resolve_hardware(item)
        if hw is None:
            result = {"requires_human_ruling": True, "reason": "Catalog item is not identifiable cyberdeck hardware."}
        else:
            canon_name, slot_cost = hw
            deck = detail.get("deck")
            if not _is_valid_deck(deck):
                raise ValueError("no cyberdeck is equipped")
            count = _integer(inventory.get(item_id, 0), "inventory count")
            if count < 1: raise ValueError("hardware is not owned")
            hws = deck.setdefault("hardware", [])
            installed_copies = sum(
                1 for h in hws if isinstance(h, dict) and h.get("item_id") == item_id
            )
            if installed_copies >= count:
                raise ValueError("cannot install more copies of hardware than owned")
            deck_slots = deck.get("slots") if type(deck.get("slots")) is int else deck.get("capacity")
            if _used_deck_slots(deck) + slot_cost > deck_slots:
                raise ValueError("insufficient cyberdeck slots")
            index = detail.get("next_hardware_index", len(hws))
            _integer(index, "next_hardware_index")
            if index < len(hws):
                index = len(hws)
            entry = {
                "id": f"hw-{index}",
                "item_id": item_id,
                "name": canon_name,
                "slots": slot_cost,
            }
            hws.append(entry)
            detail["next_hardware_index"] = index + 1
            result = {"installed_hardware": copy.deepcopy(entry)}
    elif action in ("install_cyberware", "remove_cyberware"):
        result = {"requires_human_ruling": True, "reason": "Source-derived cyberware prerequisites, slot costs, and humanity evidence are not fully available for this item."}
    else:
        raise ValueError(f"unsupported gear action: {action}")
    ch["inventory"] = inventory
    rules_eval.sync_equipment_views(ch)
    return {"character": ch, "result": result}
