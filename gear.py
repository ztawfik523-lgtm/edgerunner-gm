"""Canonical-catalog-backed equipment and inventory transitions."""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

import encounters
import netrunning
import sourcecatalog


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _normalized(value):
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


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
    for header, value in zip(item.get("columns", []), item.get("cells", [])):
        if re.sub(r"[^a-z]", "", header.casefold()) == wanted:
            return value
    return ""


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
            total = price * quantity
            inventory[item_id] = count - quantity
            ch["money"] = money + total
        result = {"item_id": item_id, "quantity": quantity, "eb": total, "action": action}
    elif action == "consume":
        count = _integer(inventory.get(item_id, 0), "inventory count")
        quantity = _integer(args.get("quantity", 1), "quantity", 1)
        if count < quantity: raise ValueError("insufficient owned items")
        inventory[item_id] = count - quantity
        result = {"consumed": quantity, "item_id": item_id}
    elif action == "equip_weapon":
        if item.get("category") != "weapon" or not any(_normalized(item["name"]) == _normalized(x) for x in encounters.WEAPONS):
            raise ValueError("source item is not a supported canonical weapon")
        count = _integer(inventory.get(item_id, 0), "inventory count")
        if count < 1: raise ValueError("weapon is not owned")
        weapon_type = next(x for x in encounters.WEAPONS if _normalized(x) == _normalized(item["name"]))
        inv = ch.setdefault("detail", {}).setdefault("equipment", {}).setdefault("weapons", [])
        index = detail.get("next_weapon_index", 0)
        _integer(index, "next_weapon_index")
        definition = encounters.WEAPONS[weapon_type]
        weapon = {"id": f"weapon-{index}", "type": weapon_type, "loaded": 0,
                  "ammo_kind": definition.get("ammo")}
        inv.append(weapon); detail["next_weapon_index"] = index + 1
        result = {"equipped": copy.deepcopy(weapon)}
    elif action == "equip_armor":
        if item.get("category") != "armor": raise ValueError("item is not canonical armor")
        count = _integer(inventory.get(item_id, 0), "inventory count")
        if count < 1: raise ValueError("armor is not owned")
        sp = _field(item, "sp"); penalty = _field(item, "armorpenalty")
        if not sp.isdigit() or not penalty.isdigit():
            raise ValueError("source armor SP or ArmorPenalty is unavailable for this item")
        location = args.get("location")
        if location not in ("body", "head"): raise ValueError("location must be body or head")
        armor = {"id": f"armor-{len(detail['equipment']['armor'])}", "type": item["name"],
                 "sp": int(sp), "max_sp": int(sp), "location": location, "penalty": int(penalty)}
        detail["equipment"]["armor"].append(armor)
        result = {"equipped": copy.deepcopy(armor)}
    elif action in ("equip_deck", "install_program", "install_hardware"):
        result = {"requires_human_ruling": True, "reason": "Catalog item type/capacity evidence is insufficient to safely validate this operation."}
    elif action in ("install_cyberware", "remove_cyberware"):
        result = {"requires_human_ruling": True, "reason": "Source-derived cyberware prerequisites, slot costs, and humanity evidence are not fully available for this item."}
    else:
        raise ValueError(f"unsupported gear action: {action}")
    ch["inventory"] = inventory
    return {"character": ch, "result": result}
