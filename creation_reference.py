"""Beginner-friendly character creation and campaign setup data, read from the indexed Corebook."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import economy
import sourcecatalog
from creation import BASIC, ROLES, STATS, _norm_skill, _role_skills, _template

CREATION_METHODS: list[dict[str, Any]] = [
    {
        "id": "streetrat",
        "name": "Streetrat (Templates)",
        "badge": "Best for Beginners",
        "summary": "Fastest official Cyberpunk RED build: pick a Role, roll 1d10 (or pick a row) for STATs, get pre-tuned skills and a ready-to-run starting kit + 500 eb.",
        "rules": "1d10 selects one balanced STAT template row for your Role, 20 pre-set Role Skills (weighted 86 pts), +4 free Cultural Language, starting Role weapons/armor/cyberware, and 500 eb.",
    },
    {
        "id": "edgerunner",
        "name": "Edgerunner (Fast & Dirty)",
        "badge": "Balanced Control",
        "summary": "Keep your Role's starter gear & cyberware kit, roll/pick each STAT column individually from your Role's templates, and customize your 86 skill points across your Role's 20 skills.",
        "rules": "Roll 1d10 per STAT column, allocate 86 weighted points across your Role's 20 skills (each rank 2–6; x2 skills cost double), +4 Cultural Language, starting Role gear + 500 eb.",
    },
    {
        "id": "complete_package",
        "name": "Complete Package (Calculated)",
        "badge": "Full Point-Buy",
        "summary": "Build from scratch with 62 STAT points (2–8 each), 86 Skill points across every Corebook skill, 2,550 eb to buy your own weapons/armor/cyberware, plus 800 eb for fashion.",
        "rules": "62 STAT pts (2..8), 86 weighted Skill pts (all 13 Basic Skills min 2, max 6; Surgery/Medical Tech are Medtech-only), 2,550 eb gear/cyberware + 800 eb fashion.",
    },
]

_BASIC_DEFAULT_SPECS = {
    "language": "Language (Streetslang)",
    "local expert": "Local Expert (Your Home)",
}
_SHOP_CATEGORIES = ("weapon", "armor", "cyberware", "gear", "program", "hardware", "vehicle", "drug", "ammo",
                    "attachment", "service", "housing")
# Lifepath section (outline slug) -> keys for its roll-table columns, in table order.
_LIFEPATH_SECTIONS = {
    "your-personality": ("personality",),
    "dress-and-personal-style": ("clothing_style", "hairstyle", "affectation"),
    "your-motivations-and-relationships": ("value_most", "feelings_about_people"),
    "things-you-value-the-most": ("valued_possession", "valued_person"),
    "your-original-family-background": ("family_background",),
    "your-environment": ("childhood_environment",),
    "your-family-crisis": ("family_crisis",),
    "your-friends": ("friend_relationship",),
    "your-enemies": ("enemy_who", "enemy_cause", "enemy_backup"),
    "sweet-revenge": ("sweet_revenge",),
    "your-tragic-love-affair": ("tragic_love",),
    "your-life-goals": ("life_goal",),
}


def _tables(path: Path, kind: str) -> list[dict[str, Any]]:
    tables = sourcecatalog.rule_tables(path, kind)
    if not tables:
        raise ValueError(f"The rules index has no {kind} table")
    return tables


def _entries(path: Path, category: str) -> list[dict[str, Any]]:
    entries = sourcecatalog.entries(path, category)
    if not entries:
        raise ValueError(f"The rules index has no {category} entries")
    return entries


def lifepath(path: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """(cultural regions, lifepath key -> options) from the Corebook roll tables."""
    sections: dict[str, list[dict[str, Any]]] = {}
    for table in _tables(path, "roll_table"):
        slug = re.sub(r"-\d+$", "", table["section_id"] or "")
        sections.setdefault(slug, []).append(table)
    missing = sorted({"cultural-origins", *_LIFEPATH_SECTIONS} - set(sections))
    if missing:
        raise ValueError(f"The rules index has no lifepath tables for: {', '.join(missing)}")
    regions = [
        {"region": row[1], "languages": [name.strip() for name in row[2].split(",") if name.strip()]}
        for row in sections["cultural-origins"][0]["rows"]
    ]
    options: dict[str, list[str]] = {}
    for slug, keys in _LIFEPATH_SECTIONS.items():
        columns: list[list[str]] = []
        for table in sections[slug]:
            rows = [[*row[1:-1], f"{row[-1]} {note}".strip()] for row, note in zip(table["rows"], table["notes"])]
            if slug == "your-original-family-background":
                columns.append([" — ".join(row) for row in rows])
            else:
                columns.extend([list(column) for column in zip(*rows)])
        if len(columns) != len(keys):
            raise ValueError(f"Unexpected lifepath table layout for {slug}")
        options.update({key: [value for value in column if value] for key, column in zip(keys, columns)})
    return regions, options


def campaign_presets(rules_path: str | Path) -> dict[str, Any]:
    """Campaign Creator choices the Corebook provides: districts, corporations, zones, threats and headlines."""
    path = Path(rules_path)

    def named_rows(kind: str) -> list[dict[str, Any]]:
        return [{"name": row[0], "summary": row[1], "printed_page": table["printed_page"]}
                for table in _tables(path, kind) for row in table["rows"]]

    def places(category: str) -> list[dict[str, Any]]:
        # District prose opens with a numbered key-place list; drop the leading map number.
        return [{"name": e["name"], "summary": sourcecatalog._summarize(re.sub(r"^\d+\.\s*", "", e["description"])),
                 "printed_page": e["printed_page"]} for e in _entries(path, category)]

    headlines = _tables(path, "screamsheet_headlines")[0]["rows"]
    return {
        "districts": places("location"),
        "factions": [{**faction, "type": "Corporation"} for faction in places("faction")],
        "zone_types": named_rows("zone_type"),
        "threat_ratings": named_rows("threat_rating"),
        # One list per headline column; a headline takes one word from each.
        "screamsheet_headlines": [[value for value in column if value] for column in list(zip(*headlines))[1:]],
    }


def _kit(entries: list[dict[str, Any]], cyberware: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    def option(raw: dict[str, Any]) -> dict[str, Any]:
        name = re.sub(r"^Program:\s*", "", raw["item"])
        out: dict[str, Any] = {"item": name, "qty": raw["qty"]}
        if cyberware is not None:
            entry = cyberware.get(re.sub(r"[^a-z0-9]", "", name.casefold()))
            stats = entry["stats"] if entry else {}
            out.update(hl=stats.get("hl", 0), install=stats.get("install", ""), notes=entry["summary"] if entry else "")
        return out

    return [
        {"type": "choice", "options": [option(o) for o in e["options"]]} if e["type"] == "choice"
        else {"type": "fixed", **option(e)}
        for e in entries
    ]


def _roles(path: Path) -> list[dict[str, Any]]:
    indexed = sourcecatalog.roles(path)
    catalog = sourcecatalog.skills(path)
    paths = sourcecatalog.role_lifepaths(path)
    cyberware = {re.sub(r"[^a-z0-9]", "", e["name"].casefold()): e for e in _entries(path, "cyberware")}
    result = []
    for role in ROLES:
        templates = _template(path, role)
        entry = indexed[role]
        stats = entry["stats"]
        missing = [key for key in ("ability", "starter_weapons_armor", "starter_outfit", "starter_cyberware",
                                   "starter_humanity_loss") if key not in stats]
        if missing:
            raise ValueError(f"The indexed {role} role is missing: {', '.join(missing)}")
        is_armor = [e["type"] == "fixed" and bool(re.search(r"\(SP\s*\d+\)", e["item"]))
                    for e in stats["starter_weapons_armor"]]
        result.append({
            "name": role,
            "ability": stats["ability"],
            "summary": entry["summary"],
            "description": entry["description"],
            "printed_page": entry["printed_page"],
            "templates": templates,
            "skills": _role_skills(path, role, catalog),
            "starting_weapons": _kit([e for e, armor in zip(stats["starter_weapons_armor"], is_armor) if not armor]),
            "starting_armor": [e["item"] for e, armor in zip(stats["starter_weapons_armor"], is_armor) if armor],
            "starting_outfit": _kit(stats["starter_outfit"]),
            "starting_cyberware": _kit(stats["starter_cyberware"], cyberware),
            "starting_hl": stats["starter_humanity_loss"],
            "role_lifepath": [
                {"key": re.sub(r"[^a-z0-9]+", "_", table["title"].casefold()).strip("_"),
                 "label": table["title"], "options": table["options"]}
                for table in paths[role]
            ],
        })
    return result


def build_creation_reference(rules_path: str | Path) -> dict[str, Any]:
    """Assemble Corebook creation data, templates, lifepath, and shop items; the index is required."""
    path = Path(rules_path).expanduser()
    if not path.is_file():
        raise ValueError("Character creation needs your indexed Cyberpunk RED Corebook PDF")

    catalog = sourcecatalog.skills(path)
    groups = sourcecatalog.skill_groups(path)
    skill_entries = {e["name"]: e for e in _entries(path, "skill")}
    skills = []
    for name, meta in sorted(catalog.items(), key=lambda kv: kv[0].casefold()):
        norm = _norm_skill(name)
        skills.append({
            "name": name,
            "stat": meta["stat"],
            "cost": meta["cost"],
            "basic": norm in BASIC or norm in _BASIC_DEFAULT_SPECS,
            "basic_skill_name": _BASIC_DEFAULT_SPECS.get(norm, name),
            "specializable": skill_entries[name]["stats"]["specializable"],
            "group": groups[name],
            "printed_page": meta["printed_page"],
            "summary": skill_entries[name]["summary"],
            "description": skill_entries[name]["description"],
        })

    shop = {
        category: sorted(
            ({"id": e["id"], "name": e["name"], "category": category, "cost_eb": e["stats"]["cost_eb"],
              "summary": e["summary"], "description": e["description"], "printed_page": e["printed_page"],
              "stats": e["stats"]}
             for e in _entries(path, category) if type(e["stats"].get("cost_eb")) is int),
            key=lambda item: (item["cost_eb"], item["name"].casefold()),
        )
        for category in _SHOP_CATEGORIES
    }
    fashion = [
        {"id": e["id"], "name": e["name"], "cost_eb": e["stats"]["cost_eb"], "style": e["stats"]["style"],
         "garment": e["stats"]["garment"], "summary": e["summary"]}
        for e in _entries(path, "fashion")
    ]
    housing, lifestyles = economy.housing_costs(path)
    housing_text = {e["name"]: e["description"] for e in _entries(path, "housing")}
    regions, lifepath_tables = lifepath(path)
    drugs = _entries(path, "drug")
    return {
        "stat_names": list(STATS),
        "methods": CREATION_METHODS,
        "roles": _roles(path),
        "skills": skills,
        "cultural_regions": regions,
        "lifepath_tables": lifepath_tables,
        "shop": shop,
        "fashion": fashion,
        "housing_tiers": [
            {"id": name, "name": name, "monthly_eb": cost, "summary": housing_text[name],
             "exec_only": name.startswith("Corporate")}
            for name, cost in sorted(housing.items(), key=lambda kv: (kv[1], kv[0]))
        ],
        "lifestyles": [
            {"id": name, "name": name, "monthly_eb": cost, "summary": housing_text[name]}
            for name, cost in sorted(lifestyles.items(), key=lambda kv: kv[1])
        ],
        "pharmaceuticals": [e["name"] for e in drugs if e["stats"].get("kind") == "pharmaceutical"],
        "martial_arts_forms": [
            e["name"] for e in sourcecatalog.entries(path, "rule")
            if "martial art" in e["tags"] and e["name"] != "Shared Special Moves"
        ],
        "nomad_vehicles": [item["name"] for item in shop["vehicle"]],
        "nomad_upgrades": [
            {"name": row[1].split(":", 1)[0].strip(), "rank": int(row[0])}
            for table in _tables(path, "vehicle_upgrade") for row in table["rows"]
        ],
        "campaign_presets": campaign_presets(path),
    }
