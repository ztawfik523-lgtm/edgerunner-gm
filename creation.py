"""Pure character-generation draft builder backed by an indexed rules source."""
from __future__ import annotations

import re
import secrets
import sqlite3
from pathlib import Path
from typing import Callable, Any
from sourcecatalog import skills as source_skills_catalog, lookup_skill, _normalize as _catalog_normalize
from roles import validate_role_choices

STATS = ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")
ROLES = ("Rockerboy", "Solo", "Netrunner", "Tech", "Medtech", "Media", "Lawman", "Exec", "Fixer", "Nomad")


def _pages(path: str | Path) -> list[tuple[int, str]]:
    try:
        with sqlite3.connect(Path(path).expanduser().resolve().as_uri() + "?mode=ro", uri=True) as db:
            return [(int(p), str(t)) for p, t in db.execute("SELECT pdf_page,text FROM pages ORDER BY pdf_page")]
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(f"Cannot read rules pages: {exc}") from exc


def _template(pages: list[tuple[int, str]], role: str) -> list[list[int]]:
    # The extracted page presents each cell as its own line, with a plain ▶Role heading.
    for page, text in pages:
        if not 74 <= page <= 78:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not re.fullmatch(rf"\s*▶\s*{re.escape(role)}\s*", line, re.I):
                continue
            tokens: list[int] = []
            for candidate in lines[i + 1:]:
                if re.search(r"▶\s*(?:Method|Rockerboy|Solo|Netrunner|Tech|Medtech|Media|Lawman|Exec|Fixer|Nomad)", candidate, re.I):
                    break
                stripped = candidate.strip()
                if re.fullmatch(r"\d+", stripped):
                    tokens.append(int(stripped))
                elif stripped and not re.fullmatch(r"(?:Roll|INT|REF|DEX|TECH|COOL|WILL|LUCK|MOVE|BODY|EMP)", stripped, re.I):
                    # Non-numeric table captions are allowed, but never harvest unrelated numbers.
                    continue
                if len(tokens) == 110:
                    break
            if len(tokens) == 110:
                rows = [tokens[n:n + 11] for n in range(0, 110, 11)]
                if [r[0] for r in rows] == list(range(1, 11)) and all(2 <= n <= 8 for r in rows for n in r[1:]):
                    return [r[1:] for r in rows]
    raise ValueError(f"No validated ten-row STAT template found for role {role!r}")


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


def _role_skills(pages: list[tuple[int, str]], role: str, catalog: dict[str, dict[str, Any]]) -> dict[str, int]:
    # Indexed table extraction preserves column order as pipe-delimited cells.
    for _, text in pages:
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 10 or not any(_norm_skill(c) == _norm_skill(role) for c in cells):
                continue
            role_col = next(i for i, c in enumerate(cells) if _norm_skill(c) == _norm_skill(role))
            lvl_col = role_col + 1
            start_row = idx + 1
            if start_row < len(lines) and "|" in lines[start_row]:
                sub = [c.strip() for c in lines[start_row].split("|")]
                for j in range(role_col + 1, min(len(sub), role_col + 4)):
                    if _norm_skill(sub[j]) in ("lvl", "level"):
                        lvl_col = j
                        start_row += 1
                        break
            result: dict[str, int] = {}
            for row_line in lines[start_row:]:
                if "|" not in row_line:
                    if result:
                        break
                    continue
                row_cells = [c.strip() for c in row_line.split("|")]
                if max(role_col, lvl_col) >= len(row_cells):
                    if result:
                        break
                    continue
                skill_cell = row_cells[role_col]
                lvl_cell = row_cells[lvl_col]
                norm = _norm_skill(skill_cell)
                if norm in ("skill", "lvl", "level", ""):
                    continue
                if not re.fullmatch(r"[0-6]", lvl_cell):
                    if result:
                        break
                    continue
                canonical = _canonical_skill_name(catalog, skill_cell)
                if canonical is not None:
                    result[canonical] = int(lvl_cell)
                if len(result) == 20:
                    return result
    raise ValueError(f"Could not validate exactly 20 source skills for {role}")


BASIC = {_norm_skill(x) for x in ("Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth")}
def build_character(args: dict[str, Any], rules_path: str | Path, randbelow: Callable[[int], int] = secrets.randbelow) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    role = args.get("role")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    method = args.get("method")
    if method not in ("streetrat", "edgerunner", "complete_package"):
        raise ValueError("method must be streetrat, edgerunner, or complete_package")
    pages = _pages(rules_path)
    dice: list[int] = []
    supplied_rolls = args.get("template_rolls")
    if method in ("streetrat", "edgerunner"):
        templates = _template(pages, role)
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
    source_skills = _role_skills(pages, role, catalog) if method in ("streetrat", "edgerunner") else {}
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
        if isinstance(starting_gear.get("equipped_armor"), dict):
            equipment_detail["equipped_armor"] = dict(starting_gear["equipped_armor"])
        if isinstance(starting_gear.get("fashion"), list):
            fashion_items = [x for x in starting_gear["fashion"] if isinstance(x, (str, dict))]
        spent_eb = starting_gear.get("money_spent_eb")
        if method == "complete_package" and type(spent_eb) is int:
            if not 0 <= spent_eb <= 2550:
                raise ValueError("complete_package money_spent_eb must be between 0 and 2550")
            starting_money = 2550 - spent_eb
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
    hp = 10 + 5 * ((stats["BODY"] + stats["WILL"] + 1) // 2)
    initial_humanity = stats["EMP"] * 10
    starting_humanity = max(0, initial_humanity - humanity_loss)
    seriously_wounded = (hp + 1) // 2
    death_save = stats["BODY"]
    active_emp = max(0, starting_humanity // 10)
    detail: dict[str, Any] = {
        "roles": [{"role": role, "rank": 4, "choices": choices}],
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
            "seriously_wounded": seriously_wounded,
            "death_save": death_save,
            "fashion_budget": 800 if method == "complete_package" else 0,
        },
        "lifepath": lifepath,
    }
    if cyberware_list:
        detail["cyberware"] = cyberware_list
    if "equipped_weapon" in equipment_detail:
        detail["equipped_weapon"] = equipment_detail["equipped_weapon"]
    if "equipped_armor" in equipment_detail:
        detail["equipped_armor"] = equipment_detail["equipped_armor"]
    if fashion_items:
        detail["fashion"] = fashion_items
    backstory = args.get("backstory")
    if isinstance(backstory, dict):
        detail["backstory"] = dict(backstory)
    if handle:
        detail["handle"] = handle
    if real_name:
        detail["real_name"] = real_name
    if isinstance(args.get("real_name_hidden"), bool):
        detail["real_name_hidden"] = args["real_name_hidden"]
    elif handle and real_name:
        detail["real_name_hidden"] = True
    for str_key in ("portrait_url", "color", "owner_username"):
        val = args.get(str_key)
        if isinstance(val, str) and val.strip():
            detail[str_key] = val.strip()
    return {
        "name": name.strip(), "role": role, "stats": stats, "skills": skills,
        "hp": hp, "max_hp": hp, "humanity": starting_humanity,
        "seriously_wounded": seriously_wounded, "death_save": death_save,
        "luck_remaining": stats["LUCK"], "money": starting_money,
        "inventory": inventory, "revision": 1,
        "detail": detail,
    }
