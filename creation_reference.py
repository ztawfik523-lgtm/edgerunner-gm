"""Structured character creation reference data backed strictly by rules.sqlite."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import corebook_gm_data as cgd
from creation import BASIC, ROLES, STATS, _norm_skill, _pages, _role_skills, _template
from creation_catalog import parse_hl_int
from library import (
    load_corebook_entries,
    query_campaign_presets,
    query_lifepath_data,
    query_roles_data,
    search_library,
)
from sourcecatalog import items as source_items_catalog, skills as source_skills_catalog

STAT_INFO: dict[str, dict[str, Any]] = {
    "INT": {"name": "Intelligence", "short": "Awareness, deduction, and education.", "mechanics": "Governs INT-based skills."},
    "REF": {"name": "Reflexes", "short": "Reaction speed, initiative, and ranged aiming.", "mechanics": "Adds to Initiative + 1d10 and Ranged Weapon skills."},
    "DEX": {"name": "Dexterity", "short": "Agility, dodging, stealth, and melee.", "mechanics": "Governs Evasion, Stealth, Athletics, and Melee skills."},
    "TECH": {"name": "Technique", "short": "Working with tools, cyberware, locks, and medical stabilization.", "mechanics": "Governs TECH-based skills."},
    "COOL": {"name": "Cool", "short": "Composure under pressure and social presence.", "mechanics": "Governs COOL-based social skills."},
    "WILL": {"name": "Willpower", "short": "Mental grit, stamina, and Hit Points.", "mechanics": "Combines with BODY to determine Hit Points: 10 + 5 * ceil((BODY + WILL)/2)."},
    "LUCK": {"name": "Luck", "short": "Spendable pool of points to boost rolls.", "mechanics": "Declare before rolling a d10 to add +1 per LUCK point spent."},
    "MOVE": {"name": "Movement", "short": "Movement speed per action.", "mechanics": "Move Action distance is MOVE * 2 meters (or yards) per turn."},
    "BODY": {"name": "Body", "short": "Physical toughness, Hit Points, and Death Saves.", "mechanics": "Combines with WILL for HP and sets the Death Save target."},
    "EMP": {"name": "Empathy", "short": "Social reading and cyberware tolerance.", "mechanics": "Max Humanity = EMP * 10; every 10 Humanity lost reduces current EMP by 1."},
}

CREATION_METHODS: list[dict[str, Any]] = [
    {
        "id": "streetrat",
        "name": "Streetrat (Templates)",
        "badge": "Template Build",
        "summary": "Select a Role, roll 1d10 (or pick a row) for STAT templates, use preset Role skills, and start with 500 eb.",
        "rules": "1d10 selects a STAT template row for your Role, 20 preset Role skills (86 pts), +4 Cultural Language, and 500 eb.",
    },
    {
        "id": "edgerunner",
        "name": "Edgerunner (Fast & Dirty)",
        "badge": "Balanced Control",
        "summary": "Roll 1d10 per STAT column from your Role's template table and allocate 86 weighted points across your Role's 20 skills.",
        "rules": "Roll 1d10 per STAT column, allocate 86 weighted points across your Role's 20 skills (ranks 2–6; x2 skills cost double), +4 Cultural Language, and 500 eb.",
    },
    {
        "id": "complete_package",
        "name": "Complete Package (Calculated)",
        "badge": "Full Point-Buy",
        "summary": "Allocate 62 STAT points (2–8 each), 86 Skill points across all skills, 2,550 eb for gear/cyberware, and 800 eb for fashion.",
        "rules": "62 STAT pts (2–8), 86 weighted Skill pts (Basic Skills min 2, max 6), 2,550 eb gear/cyberware + 800 eb fashion.",
    },
]

_SKILL_GROUPS = {
    "Awareness": {"Concentration", "Conceal/Reveal Object", "Lip Reading", "Perception", "Tracking"},
    "Body": {"Athletics", "Contortionist", "Dance", "Endurance", "Resist Torture/Drugs", "Stealth"},
    "Control": {"Drive Land Vehicle", "Pilot Air Vehicle", "Pilot Sea Vehicle", "Riding"},
    "Education": {"Accounting", "Animal Handling", "Bureaucracy", "Business", "Composition", "Criminology", "Cryptography", "Deduction", "Education", "Gamble", "Language", "Library Search", "Local Expert", "Science", "Tactics", "Wilderness Survival"},
    "Fighting": {"Brawling", "Evasion", "Martial Arts", "Melee Weapon"},
    "Performance": {"Acting", "Play Instrument"},
    "Ranged": {"Archery", "Autofire", "Handgun", "Heavy Weapons", "Shoulder Arms"},
    "Social": {"Bribery", "Conversation", "Human Perception", "Interrogation", "Persuasion", "Personal Grooming", "Streetwise", "Trading", "Wardrobe & Style"},
    "Technique": {"Air Vehicle Tech", "Basic Tech", "Cybertech", "Demolitions", "Electronics/Security Tech", "First Aid", "Forgery", "Land Vehicle Tech", "Paint/Draw/Sculpt", "Paramedic", "Photography/Film", "Pick Lock", "Pick Pocket", "Sea Vehicle Tech", "Weaponstech"},
}

_BASIC_BASES = {
    "athletics",
    "brawling",
    "concentration",
    "conversation",
    "education",
    "evasion",
    "first aid",
    "human perception",
    "language",
    "local expert",
    "perception",
    "persuasion",
    "stealth",
}

_BASIC_DEFAULT_SPECS = {
    "language": "Language (Streetslang)",
    "local expert": "Local Expert (Your Home)",
}

_SHOP_CATEGORIES = (
    "weapon",
    "armor",
    "cyberware",
    "gear",
    "program",
    "hardware",
    "vehicle",
    "drug",
    "ammo",
    "attachment",
    "service",
    "housing",
)


def _skill_group(skill_name: str) -> str:
    base = skill_name.split("(", 1)[0].strip()
    for group, names in _SKILL_GROUPS.items():
        if base in names or skill_name in names:
            return group
    return "Other"


def _slug_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_") or "item"


def build_creation_reference(rules_path: str | Path | None) -> dict[str, Any]:
    """Assemble structured creation data, templates, lifepath, and shop items from rules.sqlite."""
    path = Path(rules_path).expanduser() if rules_path else None
    rules_indexed = bool(path and path.is_file())
    empty_shop = {cat: [] for cat in _SHOP_CATEGORIES}
    empty_presets = {
        "districts": [],
        "factions": [],
        "caper_styles": [],
        "screamsheet_hooks": [],
        "zone_types": [],
        "threat_ratings": [],
        "screamsheets": [],
    }
    if not rules_indexed or path is None:
        return {
            "rules_indexed": False,
            "stat_names": [],
            "stats": {},
            "methods": [],
            "roles": [],
            "skills": [],
            "cultural_regions": [],
            "lifepath_tables": {},
            "shop": empty_shop,
            "fashion": [],
            "fashion_matrix": [],
            "housing_tiers": [],
            "lifestyles": [],
            "campaign_presets": empty_presets,
            "difficult_skills": [],
            "threat_ratings": [],
            "zone_types": [],
            "screamsheets": [],
            "difficulty_values": {},
        }

    templates: dict[str, list[list[int]]] = {}
    role_skills: dict[str, dict[str, int]] = {}
    skills_list: list[dict[str, Any]] = []
    shop_items: dict[str, list[dict[str, Any]]] = {cat: [] for cat in _SHOP_CATEGORIES}
    fashion_items: list[dict[str, Any]] = []
    fashion_matrix: list[dict[str, Any]] = []

    pages = _pages(path)
    catalog = source_skills_catalog(path)
    lib_skills = {
        entry["name"].casefold(): entry
        for entry in search_library(path, category="skill", limit=200)
    }
    for role in ROLES:
        try:
            templates[role] = _template(pages, role)
        except ValueError:
            pass
        try:
            role_skills[role] = _role_skills(pages, role, catalog)
        except ValueError:
            pass

    for name, meta in sorted(catalog.items(), key=lambda kv: kv[0].casefold()):
        lib_entry = lib_skills.get(name.casefold())
        norm_key = _norm_skill(name)
        skills_list.append({
            "name": name,
            "stat": meta["stat"],
            "cost": meta["cost"],
            "basic": norm_key in BASIC or norm_key in _BASIC_BASES,
            "basic_skill_name": _BASIC_DEFAULT_SPECS.get(norm_key, name),
            "specializable": name.casefold() in {"language", "local expert", "science", "play instrument", "martial arts"},
            "group": _skill_group(name),
            "printed_page": meta.get("printed_page"),
            "summary": (lib_entry or {}).get("summary") or f"{name} ({meta['stat']})",
            "description": (lib_entry or {}).get("description") or f"{name} ({meta['stat']}, x{meta['cost']}).",
        })

    # Populate shop & fashion directly from rules.sqlite (rule_entries + sourcecatalog.items)
    seen_shop: dict[str, set[str]] = {cat: set() for cat in (*_SHOP_CATEGORIES, "fashion")}
    for entry in load_corebook_entries(path):
        cat = str(entry.get("category") or "")
        if cat not in seen_shop:
            continue
        stats = dict(entry.get("stats") or {})
        cost_eb = stats.get("cost_eb")
        if not isinstance(cost_eb, int):
            continue
        key = str(entry.get("name") or "").casefold()
        if not key or key in seen_shop[cat]:
            continue
        seen_shop[cat].add(key)
        if cat == "cyberware" and "hl" not in stats:
            stats["hl"] = parse_hl_int(stats.get("humanity_loss"))
        if cat == "fashion":
            item_row = {
                "id": entry["id"],
                "name": entry["name"],
                "cost_eb": cost_eb,
                "style": str(stats.get("style") or ""),
                "garment": str(stats.get("garment") or ""),
                "summary": entry.get("summary") or "",
            }
            fashion_matrix.append(item_row)
            fashion_items.append(item_row)
        else:
            shop_items[cat].append({
                "id": entry["id"],
                "name": entry["name"],
                "category": cat,
                "cost_eb": cost_eb,
                "summary": entry.get("summary") or "",
                "description": entry.get("description") or "",
                "printed_page": entry.get("printed_page"),
                "stats": stats,
            })

    try:
        raw_src_items = source_items_catalog(path)
    except ValueError:
        raw_src_items = {}
    for item_id, meta in raw_src_items.items():
        cat = str(meta.get("category") or "gear")
        if cat not in seen_shop:
            continue
        name = str(meta.get("name") or "").strip()
        cost_eb = meta.get("cost")
        if not name or not isinstance(cost_eb, int):
            continue
        key = name.casefold()
        if key in seen_shop[cat]:
            continue
        seen_shop[cat].add(key)
        if cat == "fashion":
            item_row = {
                "id": item_id,
                "name": name,
                "cost_eb": cost_eb,
                "style": "",
                "garment": "",
                "summary": f"{name} ({cost_eb}eb).",
            }
            fashion_matrix.append(item_row)
            fashion_items.append(item_row)
        else:
            shop_items[cat].append({
                "id": item_id,
                "name": name,
                "category": cat,
                "cost_eb": cost_eb,
                "summary": f"{name} ({cost_eb}eb).",
                "description": f"{name}: {cat} ({cost_eb}eb).",
                "printed_page": meta.get("printed_page"),
                "stats": {"cost_eb": cost_eb},
            })

    for cat in _SHOP_CATEGORIES:
        shop_items[cat].sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))
    fashion_matrix.sort(key=lambda item: (item["style"].casefold(), item["cost_eb"], item["name"].casefold()))
    fashion_items.sort(key=lambda item: (item["cost_eb"], item["name"].casefold()))

    # Housing tiers & lifestyles derived from extracted housing/service entries
    housing_tiers: list[dict[str, Any]] = []
    for h in shop_items["housing"]:
        hstats = h.get("stats") or {}
        monthly = hstats.get("rent_eb_mo") if isinstance(hstats.get("rent_eb_mo"), int) else h["cost_eb"]
        hid = _slug_id(h["name"])
        row: dict[str, Any] = {
            "id": hid,
            "name": h["name"],
            "monthly_eb": monthly,
            "summary": h.get("summary") or "",
        }
        if "corporate" in hid or "exec" in h.get("summary", "").casefold():
            row["exec_only"] = True
        housing_tiers.append(row)

    lifestyles: list[dict[str, Any]] = []
    for svc in shop_items["service"]:
        sname = svc["name"]
        if sname.casefold().startswith("lifestyle:") or "lifestyle" in (svc.get("summary") or "").casefold():
            clean_name = re.sub(r"^lifestyle\s*:\s*", "", sname, flags=re.I).strip()
            lifestyles.append({
                "id": clean_name,
                "name": clean_name,
                "monthly_eb": svc["cost_eb"],
                "summary": svc.get("summary") or "",
            })

    roles_db = query_roles_data(path)
    roles_payload = []
    for role in ROLES:
        db_role = roles_db.get(role, {})
        roles_payload.append({
            "name": role,
            "ability": db_role.get("ability") or "",
            "ability_summary": db_role.get("ability_summary") or "",
            "description": db_role.get("description") or "",
            "key_stats": db_role.get("key_stats") or [],
            "printed_page": db_role.get("printed_page"),
            "templates": templates.get(role, []),
            "skills": role_skills.get(role, {}),
        })

    cultural_regions, lifepath_tables = query_lifepath_data(path)
    campaign_presets = query_campaign_presets(path)

    return {
        "rules_indexed": rules_indexed,
        "stat_names": list(STATS),
        "stats": STAT_INFO,
        "methods": CREATION_METHODS,
        "roles": roles_payload,
        "skills": skills_list,
        "cultural_regions": cultural_regions,
        "lifepath_tables": lifepath_tables,
        "shop": shop_items,
        "fashion": fashion_items,
        "fashion_matrix": fashion_matrix,
        "housing_tiers": housing_tiers,
        "lifestyles": lifestyles,
        "campaign_presets": campaign_presets,
        "difficult_skills": [s["name"] for s in skills_list if s.get("cost") == 2],
        "threat_ratings": campaign_presets.get("threat_ratings", []),
        "zone_types": campaign_presets.get("zone_types", []),
        "screamsheets": campaign_presets.get("screamsheets", []),
        "difficulty_values": cgd.DV_TABLE,
    }
