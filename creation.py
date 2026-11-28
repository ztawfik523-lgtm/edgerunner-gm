"""Pure character-generation draft builder backed by an indexed rules source."""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Callable, Any
import rules_eval
from sourcecatalog import entries as source_entries, items as source_items, roles as source_roles, skills as source_skills_catalog, lookup_skill, _normalize as _catalog_normalize
from economy import housing_costs
from roles import validate_role_choices

STATS = ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")
ROLES = ("Rockerboy", "Solo", "Netrunner", "Tech", "Medtech", "Media", "Lawman", "Exec", "Fixer", "Nomad")


def _role_stats(rules_path: str | Path, role: str) -> dict[str, Any]:
    entry = source_roles(rules_path).get(role)
    if entry is None:
        raise ValueError(f"Role {role!r} is not in the indexed Corebook")
    return entry["stats"]


def _template(rules_path: str | Path, role: str) -> list[list[int]]:
    rows = _role_stats(rules_path, role).get("stat_templates") or []
    if len(rows) != 10 or any(len(r) != 10 or not all(type(n) is int and 2 <= n <= 8 for n in r) for r in rows):
        raise ValueError(f"No validated ten-row STAT template found for role {role!r}")
    return rows


def _norm_skill(value: str) -> str:
    value = re.sub(r"\s*\(choose\s*1\)\s*", "", value, flags=re.I)
    value = re.sub(r"\s*\(x\s*2\)\s*", "", value, flags=re.I)
    value = re.sub(r"\s*/\s*", "/", value)
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _canonical_skill_name(catalog: dict[str, dict[str, Any]], raw_name: str) -> str | None:
    definition = lookup_skill(catalog, raw_name)
    if definition is None:
        return None
    norm_raw = _catalog_normalize(raw_name)
    for canonical in catalog:
        if _catalog_normalize(canonical) == norm_raw:
            return canonical
    # Specializable form such as "Language (Streetslang)" or "Science (Biology)".
    match = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", re.sub(r"\s*\(choose\s*1\)\s*|\s*\(x\s*2\)\s*", " ", raw_name, flags=re.I).strip())
    if match:
        base_norm = _catalog_normalize(match.group(1))
        spec = re.sub(r"\s+", " ", match.group(2).strip())
        canonical_base = next((k for k in catalog if _catalog_normalize(k) == base_norm), match.group(1).strip())
        return f"{canonical_base} ({spec})"
    return raw_name.strip()


def _role_skills(rules_path: str | Path, role: str, catalog: dict[str, dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, rank in (_role_stats(rules_path, role).get("streetrat_skills") or {}).items():
        canonical = _canonical_skill_name(catalog, name)
        if canonical is not None and type(rank) is int and 0 <= rank <= 6:
            result[canonical] = rank
    if len(result) != 20:
        raise ValueError(f"Could not validate exactly 20 source skills for {role}")
    return result


BASIC = {_norm_skill(x) for x in ("Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth")}
def _norm_item(value: str) -> str:
    return _norm_skill(re.sub(r"[®™]", "", value))


def _armor_sp(rules_path: str | Path) -> dict[str, int]:
    """Armor name -> SP for every Corebook armor that has Stopping Power."""
    return {_norm_item(e["name"]): e["stats"]["sp"] for e in source_entries(rules_path, "armor") if e["stats"].get("sp")}


def _worn_armor(name: str, armor_sp: dict[str, int]) -> dict[str, Any] | None:
    """The armor piece an item name describes; an explicit "SP n" in the name wins over the book value."""
    norm = _norm_item(name)
    match = max((key for key in armor_sp if key in norm), key=len, default=None)
    if match is None:
        return None
    explicit = re.search(r"SP\s*(\d+)", name, re.I)
    return {"name": name, "sp": int(explicit.group(1)) if explicit else armor_sp[match]}


def _infer_armor_from_inventory(inventory: dict[str, int], armor_sp: dict[str, int], location: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for item_name in inventory:
        low = item_name.lower()
        head = any(word in low for word in ("head", "helmet", "cowl"))
        covers_both = "bodyweight" in low or "body" in low and head
        if location == "head" and not (head or covers_both):
            continue
        if location == "body" and head and not covers_both:
            continue
        piece = _worn_armor(item_name, armor_sp)
        if piece and (best is None or piece["sp"] > best["sp"]):
            best = piece
    return best


def _catalog_lookups(catalog: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """(item name -> id, cyberware name -> id). Shared names resolve to the non-cyberware item first."""
    by_name: dict[str, str] = {}
    cyberware: dict[str, str] = {}
    for item_id, meta in sorted(catalog.items(), key=lambda kv: kv[1]["category"] == "cyberware"):
        norm = _norm_item(meta["name"])
        for key in (norm, norm.replace(" ", "")):
            by_name.setdefault(key, item_id)
            if meta["category"] == "cyberware":
                cyberware.setdefault(key, item_id)
    return by_name, cyberware


def _lookup_id(lookup: dict[str, str], raw_name: str) -> str | None:
    norm = _norm_item(re.sub(r"\s+—\s+[^—]+$", "", raw_name.strip()))
    return lookup.get(norm) or lookup.get(norm.replace(" ", ""))


def build_character(args: dict[str, Any], rules_path: str | Path, randbelow: Callable[[int], int] = secrets.randbelow) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    role = args.get("role")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    method = args.get("method")
    if method not in ("streetrat", "edgerunner", "complete_package"):
        raise ValueError("method must be streetrat, edgerunner, or complete_package")
    dice: list[int] = []
    supplied_rolls = args.get("template_rolls")
    if method in ("streetrat", "edgerunner"):
        templates = _template(rules_path, role)
        count = 1 if method == "streetrat" else 10
        if supplied_rolls is not None:
            if not isinstance(supplied_rolls, list) or len(supplied_rolls) != count or any(type(r) is not int or not 1 <= r <= 10 for r in supplied_rolls):
                raise ValueError(f"template_rolls must be a list of {count} integers from 1 to 10")
            dice = list(supplied_rolls)
        else:
            for _ in range(count):
                roll = randbelow(10) + 1
                if not 1 <= roll <= 10:
                    raise ValueError("randbelow must return an integer in [0, 9]")
                dice.append(roll)
        row = templates[dice[0] - 1] if method == "streetrat" else [templates[dice[i] - 1][i] for i in range(10)]
        stats = dict(zip(STATS, row))
    else:
        raw = args.get("stats")
        if not isinstance(raw, dict) or set(raw) != set(STATS) or any(type(v) is not int or not 2 <= v <= 8 for v in raw.values()) or sum(raw.values()) != 62:
            raise ValueError("complete_package requires all ten STATs from 2 to 8 totaling 62")
        stats = dict(raw)
    catalog = source_skills_catalog(rules_path)
    source_skills = _role_skills(rules_path, role, catalog) if method in ("streetrat", "edgerunner") else {}
    supplied = args.get("skills", {})
    if not isinstance(supplied, dict) or any(not isinstance(k, str) or type(v) is not int or not 0 <= v <= 6 for k, v in supplied.items()):
        raise ValueError("skills must map skill names to integer ranks 0..6")
    skills = dict(source_skills) if method == "streetrat" else {}
    if method != "streetrat":
        for name, rank in supplied.items():
            canonical = _canonical_skill_name(catalog, name)
            if canonical is None:
                raise ValueError(f"Unknown skill: {name}")
            if canonical in skills:
                raise ValueError(f"Duplicate normalized skill: {name}")
            skills[canonical] = rank
    if method == "edgerunner":
        allowed = set(map(_norm_skill, source_skills))
        if set(map(_norm_skill, skills)) != allowed or any(v < 2 for v in skills.values()) or sum(v * lookup_skill(catalog, k)["cost"] for k, v in skills.items()) != 86:
            raise ValueError("edgerunner skills must use the source role list, ranks 2..6, and weighted total 86")
    if method == "complete_package":
        if len(set(map(_norm_skill, skills)) & BASIC) != 13 or any(next((v for k, v in skills.items() if _norm_skill(k) == basic), 0) < 2 for basic in BASIC):
            raise ValueError("complete_package requires all 13 named Basic Skills at rank 2 or higher")
        if any(re.search(r"\b(Surgery|Medical Tech)\b", k, re.I) and v for k, v in skills.items()):
            raise ValueError("Surgery and Medical Tech cannot be purchased")
        if sum(rank * lookup_skill(catalog, name)["cost"] for name, rank in skills.items()) != 86:
            raise ValueError("complete_package weighted skill cost must total 86 points")
    specializations = args.get("specializations")
    if isinstance(specializations, dict):
        for base_name, chosen in specializations.items():
            if not isinstance(base_name, str) or not isinstance(chosen, str) or not chosen.strip():
                continue
            base_norm = _norm_skill(base_name)
            for existing in list(skills):
                if _norm_skill(existing) == base_norm:
                    spec_name = f"{existing} ({chosen.strip()})"
                    if lookup_skill(catalog, spec_name) is not None:
                        skills[spec_name] = skills.pop(existing)
                    break
    lifepath = args.get("lifepath")
    if not isinstance(lifepath, dict):
        raise ValueError("lifepath is required as a structured, editable GM-authored object")
    raw_handle = args.get("handle")
    handle = raw_handle.strip() if isinstance(raw_handle, str) and raw_handle.strip() else ""
    raw_real_name = args.get("real_name")
    real_name = raw_real_name.strip() if isinstance(raw_real_name, str) and raw_real_name.strip() else ""
    name = args.get("name")
    if (not isinstance(name, str) or not name.strip()) and (handle or real_name):
        name = handle or real_name
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required and must be nonempty")
    choices = args.get("role_choices", {})
    role_validation = validate_role_choices(role, 4, choices)
    initial_benefits = role_validation.get("initial_benefits") if isinstance(role_validation, dict) else None
    if isinstance(initial_benefits, dict):
        for benefit_name, benefit_rank in initial_benefits.items():
            if benefit_name in {"Surgery", "Medical Tech"} and type(benefit_rank) is int and benefit_rank > 0:
                skills[benefit_name] = max(int(skills.get(benefit_name, 0)), benefit_rank)
    starting_gear = args.get("starting_gear")
    unresolved: list[str] = []
    inventory: dict[str, int] = {}
    cyberware_list: list[dict[str, Any]] = []
    equipment_detail: dict[str, Any] = {}
    fashion_items: list[dict[str, Any]] = []
    humanity_loss = 0
    starting_money = 2550 if method == "complete_package" else 500
    if isinstance(starting_gear, dict):
        raw_inv = starting_gear.get("inventory")
        if isinstance(raw_inv, dict):
            for item_name, qty in raw_inv.items():
                if isinstance(item_name, str) and item_name.strip() and type(qty) is int and qty > 0:
                    inventory[item_name.strip()] = qty
        raw_cw = starting_gear.get("cyberware")
        if isinstance(raw_cw, list):
            for entry in raw_cw:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip():
                    hl = entry.get("hl", 0)
                    hl_val = int(hl) if isinstance(hl, int) and hl >= 0 else 0
                    humanity_loss += hl_val
                    cyberware_list.append({
                        "name": entry["name"].strip(),
                        "hl": hl_val,
                        "install": str(entry.get("install") or ""),
                        "cost_eb": int(entry["cost_eb"]) if isinstance(entry.get("cost_eb"), int) else 0,
                        "notes": str(entry.get("notes") or ""),
                    })
                elif isinstance(entry, str) and entry.strip():
                    cyberware_list.append({"name": entry.strip(), "hl": 0})
        raw_hl = starting_gear.get("humanity_loss")
        if type(raw_hl) is int and raw_hl >= 0 and raw_hl > humanity_loss:
            humanity_loss = raw_hl
        if isinstance(starting_gear.get("equipped_weapon"), str) and starting_gear["equipped_weapon"].strip():
            equipment_detail["equipped_weapon"] = starting_gear["equipped_weapon"].strip()
        armor_sp = _armor_sp(rules_path)
        if isinstance(starting_gear.get("equipped_armor"), dict) and str(starting_gear["equipped_armor"].get("name") or "").strip():
            equipment_detail["equipped_armor"] = dict(starting_gear["equipped_armor"])
        elif inventory:
            inferred_body = _infer_armor_from_inventory(inventory, armor_sp, "body")
            if inferred_body is not None:
                equipment_detail["equipped_armor"] = inferred_body
        head_in = starting_gear.get("equipped_head_armor")
        if isinstance(head_in, str):
            head_in = {"name": head_in}
        if isinstance(head_in, dict) and str(head_in.get("name") or "").strip():
            head_name = str(head_in["name"]).strip()
            piece = {"sp": head_in["sp"]} if head_in.get("sp") else _worn_armor(head_name, armor_sp)
            if piece is None:
                raise ValueError(f"Unknown head armor without an SP value: {head_name}")
            equipment_detail["equipped_head_armor"] = {"name": head_name, "sp": int(piece["sp"])}
        elif inventory:
            inferred_head = _infer_armor_from_inventory(inventory, armor_sp, "head")
            if inferred_head is not None:
                equipment_detail["equipped_head_armor"] = inferred_head
        if isinstance(starting_gear.get("fashion"), list):
            fashion_items = [x for x in starting_gear["fashion"] if isinstance(x, (str, dict))]
        item_catalog = source_items(rules_path)
        by_name, cyberware_names = _catalog_lookups(item_catalog)
        fashion_names_norm: set[str] = set()
        fashion_total = 0
        for f_entry in fashion_items:
            fname = str(f_entry.get("name") or "").strip() if isinstance(f_entry, dict) else f_entry.strip()
            if not fname:
                continue
            fashion_names_norm.add(_norm_item(fname))
            item_id = _lookup_id(by_name, fname)
            if item_id:
                fashion_total += item_catalog[item_id]["cost"]
            elif isinstance(f_entry, dict) and type(f_entry.get("cost_eb")) is int and f_entry["cost_eb"] >= 0:
                fashion_total += f_entry["cost_eb"]

        known_cw_hl = 0
        known_gear_eb = 0
        for cw_item in cyberware_list:
            item_id = _lookup_id(cyberware_names, cw_item["name"]) or _lookup_id(by_name, cw_item["name"])
            if item_id:
                known_cw_hl += item_catalog[item_id]["stats"].get("hl") or 0
                known_gear_eb += item_catalog[item_id]["cost"]
            elif isinstance(cw_item.get("cost_eb"), int) and cw_item["cost_eb"] > 0:
                known_gear_eb += cw_item["cost_eb"]
        if known_cw_hl > humanity_loss:
            humanity_loss = known_cw_hl
        for inv_name, inv_qty in inventory.items():
            if _norm_item(inv_name) in fashion_names_norm:
                continue
            item_id = _lookup_id(by_name, inv_name)
            if not item_id:
                continue
            if item_catalog[item_id]["category"] == "fashion":
                fashion_total += item_catalog[item_id]["cost"] * inv_qty
            else:
                known_gear_eb += item_catalog[item_id]["cost"] * inv_qty
        if method == "complete_package" and fashion_total > 800:
            raise ValueError("complete_package fashion spending exceeds 800 eb budget")

        spent_eb = starting_gear.get("money_spent_eb")
        if method == "complete_package":
            if known_gear_eb > 2550:
                raise ValueError("complete_package catalog equipment cost exceeds 2550 eb budget")
            if spent_eb is not None:
                if type(spent_eb) is not int or not 0 <= spent_eb <= 2550:
                    raise ValueError("complete_package money_spent_eb must be between 0 and 2550")
                if spent_eb < known_gear_eb:
                    raise ValueError("complete_package money_spent_eb cannot be less than catalog equipment cost")
                effective_spent = max(spent_eb, known_gear_eb)
            else:
                effective_spent = known_gear_eb
            starting_money = 2550 - effective_spent
        if not inventory and not cyberware_list and not equipment_detail:
            unresolved.append("source-derived starting equipment package not validated")
    else:
        unresolved.append("source-derived starting equipment package not validated")
    if role_validation.get("requires_human_ruling"):
        unresolved.append(role_validation.get("reason", "role choice requires human ruling"))
    language = args.get("cultural_language")
    if language:
        free_name = f"Language ({language})"
        if any(_norm_skill(k) == _norm_skill(free_name) for k in skills):
            unresolved.append("cultural language overlaps paid skill; stacking requires human ruling")
        else:
            definition = lookup_skill(catalog, free_name)
            if definition is None:
                raise ValueError(f"Unknown cultural language skill: {free_name}")
            skills[free_name] = 4
    if role == "Fixer" and isinstance(choices, dict):
        fixer_lang = str(choices.get("language") or "").strip()
        if fixer_lang and fixer_lang.lower() != "streetslang":
            fixer_lang_skill = f"Language ({fixer_lang})"
            if not any(_norm_skill(k) == _norm_skill(fixer_lang_skill) for k in skills):
                if lookup_skill(catalog, fixer_lang_skill) is not None or lookup_skill(catalog, "Language (Streetslang)") is not None:
                    skills[fixer_lang_skill] = 4

    housing_eb, lifestyle_eb = housing_costs(rules_path)
    housing_in = args.get("housing")
    default_housing = "Corporate Conapt" if role == "Exec" else "Cargo Container"
    housing = str(housing_in).strip() if isinstance(housing_in, str) and housing_in.strip() else default_housing
    if housing not in housing_eb:
        raise ValueError(f"Unknown housing tier: {housing}")
    if housing.startswith("Corporate") and role != "Exec":
        raise ValueError("Corporate housing requires Exec role")

    lifestyle_in = args.get("lifestyle")
    lifestyle = str(lifestyle_in).strip() if isinstance(lifestyle_in, str) and lifestyle_in.strip() else "Kibble"
    if lifestyle not in lifestyle_eb:
        raise ValueError(f"Unknown lifestyle tier: {lifestyle}")

    trauma_in = args.get("trauma_team")
    default_trauma = "Silver" if role == "Exec" else "None"
    trauma_team = str(trauma_in).strip() if isinstance(trauma_in, str) and trauma_in.strip() else default_trauma
    if trauma_team not in ("None", "Silver", "Executive"):
        raise ValueError("trauma_team must be None, Silver, or Executive")

    base_body = stats["BODY"]
    grafted_count = sum(1 for cw in cyberware_list if "grafted muscle" in cw["name"].lower())
    effective_body = min(10, base_body + 2 * grafted_count) if grafted_count > 0 else base_body
    subdermal_sp = 0
    subdermal_name = ""
    for cw in cyberware_list:
        low_cw = cw["name"].lower()
        if "linear frame" in low_cw and ("beta" in low_cw or "β" in low_cw):
            effective_body = max(effective_body, 14)
        elif "linear frame" in low_cw and ("sigma" in low_cw or "σ" in low_cw or "Σ" in cw["name"]):
            effective_body = max(effective_body, 12)
        if "subdermal armor" in low_cw and subdermal_sp < 11:
            subdermal_sp = 11
            subdermal_name = "Subdermal Armor"
        elif re.search(r"skin\s*weave", low_cw) and subdermal_sp < 7:
            subdermal_sp = 7
            subdermal_name = "Skinweave"

    if subdermal_sp > 0:
        cur_body_sp = int((equipment_detail.get("equipped_armor") or {}).get("sp") or 0)
        if cur_body_sp < subdermal_sp:
            equipment_detail["equipped_armor"] = {"name": subdermal_name, "sp": subdermal_sp}
        cur_head_sp = int((equipment_detail.get("equipped_head_armor") or {}).get("sp") or 0)
        if cur_head_sp < subdermal_sp:
            equipment_detail["equipped_head_armor"] = {"name": subdermal_name, "sp": subdermal_sp}

    hp = 10 + 5 * ((effective_body + stats["WILL"] + 1) // 2)
    initial_humanity = stats["EMP"] * 10
    starting_humanity = max(0, initial_humanity - humanity_loss)
    seriously_wounded = (hp + 1) // 2
    death_save = effective_body
    active_emp = max(0, starting_humanity // 10)
    stored_choices = dict(choices) if isinstance(choices, dict) else choices
    if role == "Tech" and isinstance(stored_choices, dict) and isinstance(role_validation.get("maker_ranks"), dict):
        stored_choices["maker_ranks"] = dict(role_validation["maker_ranks"])

    raw_rep = args.get("reputation", 0)
    if raw_rep is None:
        reputation = 0
    elif type(raw_rep) is int and 0 <= raw_rep <= 10:
        reputation = raw_rep
    else:
        raise ValueError("reputation must be an integer between 0 and 10")
    reputation_note = str(args.get("reputation_note") or "").strip()

    raw_hooks = args.get("starting_hooks")
    starting_hooks: dict[str, str] = {}
    if isinstance(raw_hooks, dict):
        for hk in ("trauma", "addiction", "debt"):
            hv = str(raw_hooks.get(hk) or "").strip()
            if hv:
                starting_hooks[hk] = hv

    detail: dict[str, Any] = {
        "roles": [{"role": role, "rank": 4, "choices": stored_choices}],
        "housing": housing,
        "lifestyle": lifestyle,
        "reputation": reputation,
        "creation": {
            "status": "draft" if unresolved else "validated",
            "unresolved": unresolved,
            "method": method,
            "dice": dice,
            "source": str(rules_path),
            "initial_emp": stats["EMP"],
            "initial_humanity": initial_humanity,
            "starting_humanity_loss": humanity_loss,
            "active_emp": active_emp,
            "base_body": base_body,
            "effective_body": effective_body,
            "cyberware_modifiers": {
                "effective_body": effective_body,
                "subdermal_sp": subdermal_sp,
            },
            "seriously_wounded": seriously_wounded,
            "death_save": death_save,
            "fashion_budget": 800 if method == "complete_package" else 0,
            **({"starting_hooks": starting_hooks} if starting_hooks else {}),
        },
        "lifepath": lifepath,
    }
    if reputation_note:
        detail["reputation_note"] = reputation_note
    if trauma_team != "None":
        detail["trauma_team"] = trauma_team
    if role == "Exec" and isinstance(role_validation.get("initial_team"), list):
        detail["team"] = list(role_validation["initial_team"])
    if role == "Nomad" and isinstance(role_validation.get("initial_motorpool"), list):
        detail["family_motorpool"] = list(role_validation["initial_motorpool"])
        if role_validation.get("active_vehicle"):
            detail["active_vehicle"] = str(role_validation["active_vehicle"])
    catalog_items: dict[str, dict[str, Any]] = {}
    for item_name in inventory:
        item_id = _lookup_id(by_name, item_name)
        if item_id:
            catalog_items[item_id] = dict(item_catalog[item_id])
    if catalog_items:
        detail["catalog_items"] = catalog_items
    if cyberware_list:
        detail["cyberware"] = cyberware_list
    if "equipped_weapon" in equipment_detail:
        detail["equipped_weapon"] = equipment_detail["equipped_weapon"]
    if "equipped_armor" in equipment_detail:
        detail["equipped_armor"] = equipment_detail["equipped_armor"]
    if "equipped_head_armor" in equipment_detail:
        detail["equipped_head_armor"] = equipment_detail["equipped_head_armor"]
    if fashion_items:
        detail["fashion"] = fashion_items
    backstory = args.get("backstory")
    if isinstance(backstory, dict):
        detail["backstory"] = dict(backstory)
    if starting_hooks:
        detail.setdefault("backstory", {})["starting_hooks"] = dict(starting_hooks)
    if handle:
        detail["handle"] = handle
    if real_name:
        detail["real_name"] = real_name
    if isinstance(args.get("real_name_hidden"), bool):
        detail["real_name_hidden"] = args["real_name_hidden"]
    elif handle and real_name:
        detail["real_name_hidden"] = True
    for str_key in ("gender", "pronouns", "portrait_url", "color", "owner_username"):
        val = args.get(str_key)
        if isinstance(val, str) and val.strip():
            detail[str_key] = val.strip()
    char = {
        "name": name.strip(), "role": role, "stats": stats, "skills": skills,
        "hp": hp, "max_hp": hp, "humanity": starting_humanity,
        "seriously_wounded": seriously_wounded, "death_save": death_save,
        "luck_remaining": stats["LUCK"], "money": starting_money,
        "inventory": inventory, "revision": 1,
        "detail": detail,
    }
    return rules_eval.sync_equipment_views(char)
