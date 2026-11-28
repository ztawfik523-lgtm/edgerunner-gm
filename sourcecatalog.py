"""Source-derived Corebook catalogs: table registry, normalized tables and rule entries.

Tables are recognized by their column-header signatures (never by page
numbers). Everything here runs once at index build time; request-time readers
(`skills`, `items`, `entries`, `rule_table`) only read the materialized
`rule_entries` / `rule_tables` rows.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable

from layout import cell_lines, cell_text, flat, norm_key

STATS = frozenset("INT REF DEX TECH COOL WILL LUCK MOVE BODY EMP".split())
_HEADER = re.compile(r"^(.+?)\.{2,}\s*(INT|REF|DEX|TECH|COOL|WILL|LUCK|MOVE|BODY|EMP)\s*$", re.I)
_SPECIALIZABLE = {"language", "local expert", "science", "play instrument", "martial arts"}
# A page defines skills when it carries at least this many dot-leader skill headers.
_SKILL_PAGE_MIN_HEADERS = 3


def _normalize(value: str) -> str:
    value = re.sub(r"\s*\(choose\s*1\)\s*", " ", value, flags=re.I)
    value = re.sub(r"\s*\(x\s*2\)\s*", " ", value, flags=re.I)
    value = re.sub(r"\s*/\s*", "/", value)
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _slug(value: str) -> str:
    import unicodedata
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "entry"


def _summarize(text: str, limit: int = 180) -> str:
    cleaned = flat(text)
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    chosen = sentence if len(sentence) <= limit else cleaned
    return chosen if len(chosen) <= limit else chosen[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Field parsers
# --------------------------------------------------------------------------

_PRICE = re.compile(r"(\d[\d,]*)\s*eb\b", re.I)
_LABEL = re.compile(r"^(?:[A-Z][a-z]*\.?)(?:\s+[A-Z][a-z]*\.?){0,2}$")


def _price_label(label: str) -> str:
    words = label.replace(".", ". ").split()
    return " ".join("Very" if w.casefold() in {"v.", "v"} else w for w in words)


def parse_cost(cell: str) -> dict[str, Any]:
    """'1,000eb (V. Expensive)' or 'Premium (100eb)' -> cost_eb plus price category."""
    text = flat(cell)
    prices = [int(p.replace(",", "")) for p in _PRICE.findall(text)]
    result: dict[str, Any] = {}
    if not prices:
        return result
    result["cost_eb"] = prices[0]
    if len(prices) > 1:
        result["cost_options_eb"] = prices
    rest = _PRICE.sub(" ", text)
    for group in re.findall(r"\(([^()]*)\)", rest):
        if _LABEL.fullmatch(group.strip()):
            result.setdefault("price_category", _price_label(group.strip()))
            rest = rest.replace(f"({group})", " ", 1)
    rest = re.sub(r"\(\s*\)", " ", rest)
    rest = flat(rest).strip(" ,;")
    if rest and "price_category" not in result and _LABEL.fullmatch(rest):
        result["price_category"] = _price_label(rest)
    elif rest and rest.casefold() != "or" and not re.fullmatch(r"(?:or\s*)+", rest, re.I):
        result["cost_note"] = rest
    return result


def parse_humanity_loss(cell: str) -> dict[str, Any]:
    """'7 (2d6)' -> humanity_loss '2d6', average 7; '0 (N/A)' -> 0."""
    text = flat(cell)
    match = re.match(r"(\d+)\s*(?:\((.*)\))?", text)
    if not match:
        return {"humanity_loss": text} if text else {}
    avg = int(match.group(1))
    dice = (match.group(2) or "").strip()
    out: dict[str, Any] = {"hl": avg, "humanity_loss_avg": avg}
    out["humanity_loss"] = avg if not dice or dice.upper() == "N/A" else dice
    return out


def _int(cell: str) -> int | None:
    text = flat(cell)
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def _yes_no(cell: str) -> bool | None:
    text = flat(cell).casefold()
    if text.startswith("yes"):
        return True
    if text.startswith("no"):
        return False
    return None


def _magazine(cell: str) -> dict[str, Any]:
    match = re.match(r"\s*(\d+|N/A)\s*(?:\((.*?)\))?", flat(cell), re.I)
    if not match:
        return {}
    out: dict[str, Any] = {}
    if match.group(1).isdigit():
        out["magazine"] = int(match.group(1))
    if match.group(2):
        out["ammo_type"] = match.group(2).strip()
    return out


def _armor_penalty(cell: str) -> int | str:
    text = flat(cell)
    if not text or text.casefold().startswith("none"):
        return 0
    match = re.match(r"\s*(-\d+)", text)
    return int(match.group(1)) if match else text


# --------------------------------------------------------------------------
# Table registry keyed on column-header signatures
# --------------------------------------------------------------------------

def _has(*keys: str) -> Callable[[list[str]], bool]:
    wanted = set(keys)
    return lambda header: wanted <= set(header)


def _exact(*keys: str) -> Callable[[list[str]], bool]:
    wanted = list(keys)
    return lambda header: [h for h in header if h] == wanted


def _role_columns(suffix: str) -> Callable[[list[str]], bool]:
    return lambda header: len([h for h in header if h]) >= 3 and all(h.endswith(suffix) and len(h) > len(suffix) for h in header if h)


# (kind, matcher, name column key or None)
REGISTRY: list[tuple[str, Callable[[list[str]], bool], str | None]] = [
    ("ranged_weapon", _has("weapontype", "weaponskill", "singleshotdamage", "cost"), "weapontype"),
    ("melee_weapon", _has("meleeweapontype", "damage", "cost"), "meleeweapontype"),
    ("weapon_quality_cost", _has("standardqualityweaponcost", "poorqualityweaponcost", "excellentqualityweaponcost"), None),
    ("weapon_quality_examples", _has("rangedweapontype", "poorweaponqualityexample", "standardweaponqualityexample"), "rangedweapontype"),
    ("exotic_weapon", lambda h: [x for x in h if x] in (["weapon", "cost"], ["weapon", "descriptionanddata", "cost"]), "weapon"),
    ("attachment", _exact("attachment", "cost"), "attachment"),
    ("magazine_size", _exact("type", "standard", "extended", "drum"), "type"),
    ("ammo", _exact("ammunitiontype", "cost"), "ammunitiontype"),
    ("armor", _has("armortype", "damagestoppingpowersp", "cost"), "armortype"),
    ("shield", _has("shieldtype", "hitpointshp", "cost"), "shieldtype"),
    ("cyberware", _has("name", "install", "descriptiondata", "cost", "hl"), "name"),
    ("gear", lambda h: [x for x in h if x] in (["item", "cost"], ["item", "description", "cost"], ["item", "descriptiondata", "cost"]), "item"),
    ("fashion", lambda h: bool(h) and not h[0] and {"bottoms", "top", "jacket", "footwear"} <= set(h), None),
    ("drug", _has("drug", "primaryeffectduration", "secondaryeffectdv", "costperdose"), "drug"),
    ("pharmaceutical", _exact("pharmaceutical", "effect"), "pharmaceutical"),
    ("vehicle", _has("vehicle", "description", "sdp", "seats", "cost"), "vehicle"),
    ("vehicle_upgrade", _exact("rankrequired", "upgrade"), None),
    ("cyberdeck", _exact("type", "cost", "slots"), "type"),
    ("hardware", _exact("name", "data", "cost"), "name"),
    ("black_ice", _has("name", "class", "per", "spd", "atk", "def", "rez", "cost"), "name"),
    ("program", _has("name", "class", "atk", "def", "rez", "effect", "cost"), "name"),
    ("demon", _has("name", "rez", "interface", "netactions", "combatnumber", "cost"), "name"),
    ("service", _exact("serviceentertainment", "cost"), "serviceentertainment"),
    ("lifestyle", _has("lifestyle", "whatitentails", "monthlycost"), "lifestyle"),
    ("housing", _has("realestate", "costtorentpermonth", "costtobuy"), "realestate"),
    ("stat_template", _exact("roll", "int", "ref", "dex", "tech", "cool", "will", "luck", "move", "body", "emp"), None),
    ("npc_stat_template", _exact("roll", "int", "ref", "dex", "tech", "cool", "will", "move", "body", "emp"), None),
    ("role_skill_list", _role_columns("skills"), None),
    ("starter_weapons_armor", _role_columns("weaponsarmor"), None),
    ("starter_outfit", _role_columns("outfit"), None),
    ("starter_cyberware", _role_columns("cyberware"), None),
    ("critical_injury", _has("roll2d6", "injury", "injuryeffect", "quickfix", "treatment"), "injury"),
    ("hustle", _has("roll", "whatyoudidtomakebankthatweek"), None),
    ("night_market", lambda h: bool(h) and h[0].startswith("roll") and "foodanddrugs" in h, None),
    ("difficulty_value", _has("difficulty", "description", "dv"), "difficulty"),
    ("wound_state", _has("woundstate", "threshold", "woundeffect"), "woundstate"),
    ("cover", _has("typeofcover", "thickhp", "thinhp"), "typeofcover"),
    ("zone_type", _exact("zonetype", "description"), "zonetype"),
    ("threat_rating", _exact("threatrating", "description"), "threatrating"),
    ("fashion_trend", lambda h: [x for x in h if x][:1] == ["fashiontrend"], "fashiontrend"),
    ("screamsheet_headlines", lambda h: bool(h) and h[0].startswith("screamsheetheadlines"), None),
    ("therapy", _has("therapy", "description", "cost", "effect"), "therapy"),
    ("job_pay", _has("jobtype", "payforjobperperson"), "jobtype"),
    ("price_category", _exact("pricecategory", "marketprice"), "pricecategory"),
    ("interface_ability", _exact("ability", "data"), "ability"),
    ("roll_table", lambda h: bool(h) and h[0] in {"roll", "1d10", "1d6", "roll2d6", "roll3d6", "rolld100", "roll"}, None),
]


def classify(header_keys: list[str]) -> tuple[str, str | None]:
    for kind, matcher, name_col in REGISTRY:
        if matcher(header_keys):
            return kind, name_col
    return "table", None


def normalize_table(raw_rows: list[list[str]]) -> dict[str, Any] | None:
    """Find the header row, drop empty spacer columns and fold continuation rows.

    Continuation rows (empty name cell, or a single populated cell under a
    wider header) are attached to the preceding row as notes.
    """
    rows = [[cell or "" for cell in row] for row in raw_rows]
    header_index, kind, name_col = None, "table", None
    for i, row in enumerate(rows[:4]):
        keys = [norm_key(cell_text(c)) for c in row]
        k, n = classify(keys)
        if k != "table":
            header_index, kind, name_col = i, k, n
            break
    groups: list[str] = []
    if header_index is None:
        # Paired "Skill | Lvl" sub-headers under a row of group (role) names.
        for i, row in enumerate(rows[1:5], 1):
            keys = [norm_key(cell_text(c)) for c in row if cell_text(c)]
            if keys and len(keys) % 2 == 0 and keys == ["skill", "lvl"] * (len(keys) // 2):
                header_index, kind = i, "role_skill_levels"
                groups = [cell_text(c) for c in rows[i - 1] if cell_text(c)]
                break
    if header_index is None:
        header_index = next((i for i, row in enumerate(rows[:4])
                             if sum(bool(cell_text(c)) for c in row) >= 2 and all(len(cell_text(c)) <= 80 for c in row)), None)
        if header_index is None:
            return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[header_index]
    body = rows[header_index + 1:]
    keep = [j for j in range(width) if cell_text(header[j]) or any(cell_text(r[j]) for r in body)]
    # A column with an empty header whose only content is continuation text
    # (Icon:/Alt. Fire Modes) belongs to the row notes, not a real column.
    columns = [cell_text(header[j]) for j in keep]
    keys = [norm_key(c) for c in columns]
    name_idx = keys.index(name_col) if name_col in keys else 0
    data: list[list[str]] = []
    raw_cells: list[list[str]] = []
    notes: list[str] = []
    for row in body:
        cells = [row[j] for j in keep]
        texts = [cell_text(c) for c in cells]
        populated = [t for t in texts if t]
        if not populated:
            continue
        if [norm_key(t) for t in texts] == keys:
            continue
        continuation = (not texts[name_idx] and kind != "fashion") or (len(populated) == 1 and len(keys) >= 3 and kind not in {"roll_table"})
        if continuation and data:
            notes[-1] = (notes[-1] + " " + " ".join(populated)).strip()
            continue
        data.append(texts)
        raw_cells.append(cells)
        notes.append("")
    if not data:
        return None
    return {"kind": kind, "columns": columns, "keys": keys, "rows": data, "raw_cells": raw_cells, "notes": notes,
            "name_index": name_idx, "groups": groups}


def load_tables(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Normalize and classify every stored source table."""
    printed = dict(conn.execute("SELECT pdf_page, printed_page FROM pages"))
    sections = conn.execute(
        "SELECT id, start_pdf, anchor_ordinal, title FROM source_sections WHERE kind='section' ORDER BY start_pdf, anchor_ordinal"
    ).fetchall()
    result = []
    last_title: dict[str, tuple[int, str]] = {}
    for pdf_page, ordinal, cells_json, title, first_block in conn.execute(
            "SELECT pdf_page, ordinal, cells_json, title, first_block FROM source_tables ORDER BY pdf_page, ordinal"):
        table = normalize_table(json.loads(cells_json))
        if table is None:
            continue
        position = (pdf_page, first_block or 0)
        section_id = section_title = None
        for sid, start, anchor, stitle in sections:
            if (start, anchor or 0) <= position:
                section_id, section_title = sid, stitle
            else:
                break
        # A grid that starts at the page top (continued listing) has no caption
        # of its own; it continues the previous table of the same kind.
        previous = last_title.get(table["kind"])
        if not title and table["kind"] != "table" and previous and pdf_page - previous[0] <= 1:
            title = previous[1]
        if title:
            last_title[table["kind"]] = (pdf_page, title)
        table.update({"id": f"p{pdf_page}-t{ordinal}", "pdf_page": pdf_page, "ordinal": ordinal,
                      "printed_page": printed.get(pdf_page), "title": title, "section_id": section_id,
                      "section_title": section_title})
        result.append(table)
    return result


def write_rule_tables(conn: sqlite3.Connection, tables: list[dict[str, Any]]) -> None:
    conn.executescript("""
        DROP TABLE IF EXISTS rule_tables;
        CREATE TABLE rule_tables (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, signature TEXT NOT NULL,
            pdf_page INTEGER NOT NULL, printed_page INTEGER, section_id TEXT,
            columns_json TEXT NOT NULL, rows_json TEXT NOT NULL, notes_json TEXT NOT NULL);
        CREATE INDEX rule_tables_kind_idx ON rule_tables(kind);
    """)
    for t in tables:
        conn.execute("INSERT INTO rule_tables VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (t["id"], t["kind"], t["title"], "|".join(k for k in t["keys"] if k), t["pdf_page"],
                      t["printed_page"], t["section_id"], json.dumps(t["columns"], ensure_ascii=False),
                      json.dumps(t["rows"], ensure_ascii=False), json.dumps(t["notes"], ensure_ascii=False)))


# --------------------------------------------------------------------------
# Prose evidence: heading blocks and the body text that follows them
# --------------------------------------------------------------------------

def heading_index(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every heading block with the body text up to the next heading."""
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for pdf_page, ordinal, text, role in conn.execute(
            "SELECT pdf_page, ordinal, text, role FROM source_blocks ORDER BY pdf_page, ordinal"):
        if role == "heading":
            current = {"pdf_page": pdf_page, "ordinal": ordinal, "title": flat(text).lstrip("▶ ").strip(), "parts": []}
            out.append(current)
        elif role == "body" and current is not None and pdf_page - current["pdf_page"] <= 1:
            current["parts"].append(text)
    for item in out:
        item["text"] = " ".join(flat(p) for p in item.pop("parts"))
    return out


def _prose_for(name: str, headings: list[dict[str, Any]], near: int, span: int = 8) -> dict[str, Any] | None:
    key = norm_key(name)
    if not key:
        return None
    best = None
    for h in headings:
        if abs(h["pdf_page"] - near) > span or not h["text"]:
            continue
        hk = norm_key(h["title"])
        if hk == key or (len(key) >= 5 and (hk.startswith(key) or key.startswith(hk) and len(hk) >= 5)):
            score = (hk == key, -abs(h["pdf_page"] - near), h["pdf_page"] >= near)
            if best is None or score > best[0]:
                best = (score, h)
    return best[1] if best else None


# --------------------------------------------------------------------------
# Entry construction
# --------------------------------------------------------------------------

def _entry(category: str, name: str, description: str, stats: dict[str, Any], table: dict[str, Any] | None,
           digest: str, *, pdf_page: int | None = None, printed_page: int | None = None,
           section_id: str | None = None, tags: Iterable[str] = (), source: dict[str, Any] | None = None) -> dict[str, Any]:
    generated = isinstance(description, _Facts)
    description = flat(description)
    page = pdf_page if pdf_page is not None else (table["pdf_page"] if table else None)
    return {
        "id": f"corebook:{category}:{_slug(name)}",
        "name": name,
        "norm_name": _normalize(name),
        "category": category,
        "source": "corebook",
        "summary": _summarize(description),
        "description": description,
        "stats": {k: v for k, v in stats.items() if v is not None and v != ""},
        "tags": [category, *tags],
        "pdf_page": page,
        "printed_page": printed_page if printed_page is not None else (table["printed_page"] if table else None),
        "section_id": section_id if section_id is not None else (table["section_id"] if table else None),
        "source_sha256": digest,
        "source_ref": source or {},
        "generated_description": generated,
    }


def _row(table: dict[str, Any], i: int) -> dict[str, str]:
    return dict(zip(table["keys"], table["rows"][i]))


def _source(table: dict[str, Any], i: int) -> dict[str, Any]:
    return {"table": table["id"], "columns": table["columns"], "cells": table["rows"][i]}


class _Facts(str):
    """A description composed from table stats (no prose column exists)."""


def _fact_line(parts: list[str]) -> str:
    return _Facts(" · ".join(p for p in parts if p) + ".")


def _weapon_stats(row: dict[str, str], note: str) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    stats.update(parse_cost(row.get("cost", "")))
    if row.get("weaponskill"):
        stats["skill"] = row["weaponskill"]
    dmg = row.get("singleshotdamage") or row.get("damage")
    if dmg:
        stats["damage"] = dmg
    stats.update(_magazine(row.get("standardmagazine", "")))
    rof = row.get("rateoffirerof") or row.get("rof")
    if rof:
        stats["rof"] = _int(rof) if _int(rof) is not None else rof
    hands = row.get("handsrequired") or row.get("ofhandsrequired")
    if hands:
        stats["hands"] = _int(hands) if _int(hands) is not None else hands
    concealed = row.get("canbeconcealed")
    if concealed:
        stats["concealable"] = _yes_no(concealed)
    if row.get("examplemeleeweapons"):
        stats["examples"] = [x.strip() for x in row["examplemeleeweapons"].split(",") if x.strip()]
    if note:
        special = re.sub(r"^alt\.?\s*fire modes\s*&\s*special features\s*:\s*", "", note, flags=re.I).strip()
        if special:
            stats["special_features"] = special
    return stats


def _weapon_facts(name: str, kind: str, stats: dict[str, Any]) -> str:
    return _fact_line([
        f"{name}: {kind}",
        f"{stats['skill']} skill" if stats.get("skill") else "",
        f"{stats['damage']} damage" if stats.get("damage") else "",
        f"ROF {stats['rof']}" if stats.get("rof") is not None else "",
        f"magazine {stats.get('magazine', 'N/A')} ({stats['ammo_type']})" if stats.get("ammo_type") else "",
        f"{stats['hands']}-handed" if isinstance(stats.get("hands"), int) else "",
        ("concealable" if stats["concealable"] else "not concealable") if isinstance(stats.get("concealable"), bool) else "",
        f"special: {stats['special_features']}" if stats.get("special_features") else "",
        f"examples: {', '.join(stats['examples'])}" if stats.get("examples") else "",
        f"{stats['cost_eb']}eb" if stats.get("cost_eb") is not None else "",
    ])


def _quality_maps(tables: list[dict[str, Any]]) -> tuple[dict[int, dict[str, int]], dict[str, dict[str, str]]]:
    """Standard cost -> {poor, excellent} costs, and weapon type -> {quality: brand example}."""
    cost_map: dict[int, dict[str, int]] = {}
    examples: dict[str, dict[str, str]] = {}
    for t in tables:
        if t["kind"] == "weapon_quality_cost":
            for i in range(len(t["rows"])):
                r = _row(t, i)
                std = parse_cost(r.get("standardqualityweaponcost", "")).get("cost_eb")
                if std is None:
                    continue
                cost_map[std] = {"standard": std,
                                 "poor": parse_cost(r.get("poorqualityweaponcost", "")).get("cost_eb"),
                                 "excellent": parse_cost(r.get("excellentqualityweaponcost", "")).get("cost_eb")}
        elif t["kind"] == "weapon_quality_examples":
            for i in range(len(t["rows"])):
                r = _row(t, i)
                examples[r.get("rangedweapontype", "")] = {
                    "poor": r.get("poorweaponqualityexample", ""),
                    "standard": r.get("standardweaponqualityexample", ""),
                    "excellent": r.get("excellentweaponqualityexample", ""),
                }
    return cost_map, examples


def _base_for(type_name: str, bases: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = norm_key(type_name)
    if key in bases:
        return bases[key]
    # "Bow" / "Crossbow" rows refer to the shared "Bows & Crossbows" weapon row.
    for base_key, base in bases.items():
        if key and (base_key.startswith(key) or key.rstrip("s") in base_key):
            return base
    return None


def _build_weapons(tables, headings, digest) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    bases: dict[str, dict[str, Any]] = {}
    for t in tables:
        if t["kind"] not in {"ranged_weapon", "melee_weapon"}:
            continue
        kind_label = "ranged weapon" if t["kind"] == "ranged_weapon" else "melee weapon"
        for i in range(len(t["rows"])):
            r = _row(t, i)
            name = r.get("weapontype") or r.get("meleeweapontype")
            if not name:
                continue
            stats = _weapon_stats(r, t["notes"][i])
            stats["weapon_class"] = "melee" if t["kind"] == "melee_weapon" else "ranged"
            stats["weapon_type"] = name
            entry = _entry("weapon", name, _weapon_facts(name, kind_label, stats), stats, t, digest,
                           tags=[stats["weapon_class"]], source=_source(t, i))
            entries.append(entry)
            bases.setdefault(norm_key(name), entry)
            # Melee rows list example weapons of the type; each becomes a buyable entry of that type.
            for example in stats.get("examples", []):
                ex_stats = {**stats, "weapon_type": name, "example_of": name}
                ex_stats.pop("examples", None)
                entries.append(_entry("weapon", f"{example} ({name})", f"{example}: an example of a {name}. " + entry["description"],
                                      ex_stats, t, digest, tags=[stats["weapon_class"], "example"],
                                      source={"base": entry["id"], **_source(t, i)}))
    cost_map, examples = _quality_maps(tables)
    for type_name, by_quality in examples.items():
        base = _base_for(type_name, bases)
        if base is None:
            continue
        std_cost = base["stats"].get("cost_eb")
        for quality in ("poor", "standard", "excellent"):
            brand = by_quality.get(quality)
            if not brand:
                continue
            stats = {k: v for k, v in base["stats"].items() if k not in {"cost_eb", "price_category"}}
            cost = cost_map.get(std_cost, {}).get(quality) if std_cost is not None else None
            stats.update({"quality": quality, "weapon_type": type_name, "cost_eb": cost if cost is not None else std_cost})
            name = f"{brand} ({type_name})"
            description = (f"{brand} is a {quality.capitalize()} Quality {type_name}. " + base["description"])
            entries.append(_entry("weapon", name, description, stats, None, digest, pdf_page=base["pdf_page"],
                                  printed_page=base["printed_page"], section_id=base["section_id"],
                                  tags=["ranged", "brand", quality],
                                  source={"base": base["id"], "quality_table": True}))
    for t in tables:
        if t["kind"] != "exotic_weapon":
            continue
        for i in range(len(t["rows"])):
            r = _row(t, i)
            name = r.get("weapon")
            if not name:
                continue
            stats = parse_cost(r.get("cost", ""))
            stats["weapon_class"] = "exotic"
            prose = _prose_for(name, headings, t["pdf_page"])
            description = r.get("descriptionanddata") or (prose["text"] if prose else "")
            entries.append(_entry("weapon", name, description or _fact_line([f"{name}: exotic weapon", f"{stats.get('cost_eb')}eb"]),
                                  stats, t, digest, tags=["exotic"], source=_source(t, i)))
    return entries


def _priced_simple(t, i, category, name, description, digest, extra=None, tags=()):
    r = _row(t, i)
    stats = parse_cost(r.get("cost", "") or r.get("costperdose", "") or r.get("monthlycost", ""))
    stats.update(extra or {})
    return _entry(category, name, description, stats, t, digest, tags=tags, source=_source(t, i))


def _build_catalog(tables, headings, digest) -> list[dict[str, Any]]:
    entries = _build_weapons(tables, headings, digest)
    magazines: dict[str, dict[str, int]] = {}
    for t in tables:
        if t["kind"] == "magazine_size":
            for i in range(len(t["rows"])):
                r = _row(t, i)
                magazines[r.get("type", "")] = {k: _int(r.get(k, "")) for k in ("standard", "extended", "drum")}
    for e in entries:
        mag = magazines.get(e["stats"].get("weapon_type", ""))
        if mag:
            e["stats"]["magazine_sizes"] = mag
    for t in tables:
        kind = t["kind"]
        for i in range(len(t["rows"])):
            r = _row(t, i)
            note = t["notes"][i]
            if kind == "armor":
                name = r.get("armortype")
                stats = parse_cost(r.get("cost", ""))
                stats.update({"sp": _int(r.get("damagestoppingpowersp", "")),
                              "armor_penalty": _armor_penalty(r.get("armorpenaltyminimum0", "")),
                              "locations": ["body", "head"]})
                if stats["sp"] is None:  # e.g. a shield row listed with hit points
                    hp = re.match(r"\s*(\d+)\s*HP", r.get("damagestoppingpowersp", ""), re.I)
                    stats.update({"hp": int(hp.group(1)) if hp else None, "locations": ["shield"]})
                desc = r.get("armordescription") or _fact_line([f"{name}: armor", f"SP {stats.get('sp')}" if stats.get("sp") else "",
                                                                 f"armor penalty {stats['armor_penalty']}", f"{stats.get('cost_eb')}eb"])
                entries.append(_entry("armor", name, desc, stats, t, digest, source=_source(t, i)))
            elif kind == "shield":
                name = r.get("shieldtype")
                stats = parse_cost(r.get("cost", ""))
                hp = re.match(r"\s*(\d+)", r.get("hitpointshp", ""))
                stats.update({"hp": int(hp.group(1)) if hp else None, "locations": ["shield"]})
                entries.append(_entry("armor", name, r.get("shielddescription", ""), stats, t, digest, source=_source(t, i)))
            elif kind == "cyberware":
                name = r.get("name")
                stats = parse_cost(r.get("cost", ""))
                stats["install"] = r.get("install")
                stats.update(parse_humanity_loss(r.get("hl", "")))
                desc = r.get("descriptiondata", "")
                if note:
                    desc = f"{desc} {note}"
                group = t["title"] or ""
                stats["group"] = re.sub(r"\s*\(.*\)\s*$", "", group).strip() or None
                foundation = re.search(r"Foundational Cyberware:\s*([^)]+)\)", group)
                if foundation:
                    stats["foundation"] = foundation.group(1).strip()
                entries.append(_entry("cyberware", name, desc, stats, t, digest, source=_source(t, i)))
            elif kind == "gear":
                name = r.get("item")
                desc = r.get("descriptiondata") or r.get("description") or ""
                entries.append(_priced_simple(t, i, "gear", name, desc, digest))
            elif kind == "attachment":
                name = r.get("attachment")
                prose = _prose_for(name, headings, t["pdf_page"])
                entries.append(_priced_simple(t, i, "attachment", name, prose["text"] if prose else "", digest))
            elif kind == "ammo":
                name = r.get("ammunitiontype")
                prose = _prose_for(name, headings, t["pdf_page"])
                extra = {}
                if prose:
                    avail = re.search(r"Ammo Types Available\s*:\s*(.+?)(?=\.|•|\sWhen\s|$)", prose["text"])
                    if avail:
                        extra["ammo_types"] = avail.group(1).strip()
                entries.append(_priced_simple(t, i, "ammo", name, prose["text"] if prose else "", digest, extra))
            elif kind == "drug":
                name = r.get("drug")
                prose = _prose_for(name, headings, t["pdf_page"])
                extra = {"primary_duration": r.get("primaryeffectduration"),
                         "secondary_dv": _int(r.get("secondaryeffectdv", "")), "kind": "street drug"}
                entries.append(_priced_simple(t, i, "drug", name, prose["text"] if prose else "", digest, extra, tags=["street drug"]))
            elif kind == "pharmaceutical":
                name = r.get("pharmaceutical")
                entries.append(_entry("drug", name, r.get("effect", ""), {"kind": "pharmaceutical"}, t, digest,
                                      tags=["pharmaceutical"], source=_source(t, i)))
            elif kind == "vehicle":
                name = r.get("vehicle")
                stats = parse_cost(r.get("cost", ""))
                stats.update({"sdp": _int(r.get("sdp", "")), "seats": r.get("seats"),
                              "speed_combat": r.get("speedcombat"), "speed_narrative": r.get("speednarrative"),
                              "vehicle_type": (t["title"] or "").strip() or None})
                if stats["seats"] and _int(stats["seats"]) is not None:
                    stats["seats"] = _int(stats["seats"])
                rooms = re.search(r"per room.*?minimum\s+(\w+)\s+rooms?", stats.get("cost_note", ""), re.I)
                if rooms:
                    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
                    count = _int(rooms.group(1)) or words.get(rooms.group(1).casefold())
                    stats.update({"cost_per_room_eb": stats["cost_eb"], "min_rooms": count})
                entries.append(_entry("vehicle", name, r.get("description", ""), stats, t, digest, source=_source(t, i)))
            elif kind == "cyberdeck":
                name = r.get("type")
                entries.append(_priced_simple(t, i, "hardware", name, _fact_line([f"{name}: cyberdeck", f"{r.get('slots')} slots"]),
                                              digest, {"slots": _int(r.get("slots", "")), "kind": "cyberdeck"}, tags=["cyberdeck"]))
            elif kind == "hardware":
                name = r.get("name")
                entries.append(_priced_simple(t, i, "hardware", name, r.get("data", ""), digest, {"kind": "cyberdeck hardware"}))
            elif kind in {"program", "black_ice"}:
                name = r.get("name")
                stats = parse_cost(r.get("cost", ""))
                stats["class"] = r.get("class")
                for key in ("per", "spd", "atk", "def", "rez"):
                    if key in r:
                        stats[key] = _int(r[key]) if _int(r[key]) is not None else r[key]
                stats["kind"] = "black ice" if kind == "black_ice" else "program"
                icon = re.sub(r"^icon\s*:\s*", "", note, flags=re.I) if note else ""
                if icon:
                    stats["icon"] = icon
                entries.append(_entry("program", name, r.get("effect", ""), stats, t, digest,
                                      tags=["black ice"] if kind == "black_ice" else [], source=_source(t, i)))
            elif kind == "demon":
                name = r.get("name")
                stats = parse_cost(r.get("cost", ""))
                stats.update({"rez": _int(r.get("rez", "")), "interface": _int(r.get("interface", "")),
                              "net_actions": _int(r.get("netactions", "")), "combat_number": _int(r.get("combatnumber", "")),
                              "kind": "demon"})
                icon = re.sub(r"^icon\s*:\s*", "", note, flags=re.I) if note else ""
                if icon:
                    stats["icon"] = icon
                prose = _prose_for(name, headings, t["pdf_page"])
                entries.append(_entry("program", name, prose["text"] if prose else _fact_line([f"{name}: demon", f"REZ {stats['rez']}"]),
                                      stats, t, digest, tags=["demon"], source=_source(t, i)))
            elif kind == "service":
                name = r.get("serviceentertainment")
                entries.append(_priced_simple(t, i, "service", name, _fact_line([f"{name}: service", f"{parse_cost(r.get('cost', '')).get('cost_eb')}eb"]), digest))
            elif kind == "lifestyle":
                name = r.get("lifestyle")
                entries.append(_priced_simple(t, i, "housing", name, r.get("whatitentails", ""), digest,
                                              {"kind": "lifestyle", "billing": "monthly"}, tags=["lifestyle"]))
            elif kind == "housing":
                name = r.get("realestate")
                rent = parse_cost(r.get("costtorentpermonth", ""))
                buy = parse_cost(r.get("costtobuy", ""))
                stats = {"kind": "housing", "rent_eb": rent.get("cost_eb"), "buy_eb": buy.get("cost_eb"),
                         "cost_eb": rent.get("cost_eb", 0), "rent_note": None if rent else r.get("costtorentpermonth")}
                entries.append(_entry("housing", name, _fact_line([f"{name}: housing",
                                                                   f"rent {r.get('costtorentpermonth')} per month",
                                                                   f"buy {r.get('costtobuy')}"]), stats, t, digest,
                                      source=_source(t, i)))
            elif kind == "critical_injury":
                name = r.get("injury")
                where = next((w for w in (norm_key(t["section_title"] or ""), norm_key(t["title"] or ""))
                              if "head" in w or "body" in w), "")
                location = "head" if "head" in where else "body"
                stats = {"roll": _int(r.get("roll2d6", "")), "location": location,
                         "quick_fix": r.get("quickfix"), "treatment": r.get("treatment")}
                entries.append(_entry("rule", f"{name} ({location.capitalize()} Critical Injury)", r.get("injuryeffect", ""), stats, t, digest,
                                      tags=["critical injury", location], source=_source(t, i)))
    entries.extend(_build_fashion(tables, digest))
    return entries


def _build_fashion(tables, digest) -> list[dict[str, Any]]:
    entries = []
    for t in tables:
        if t["kind"] != "fashion":
            continue
        garments = t["columns"][1:]
        # Each style cell is "<style name lines> + N keyword lines"; N is the
        # line count shared by most rows minus the one-line style names.
        counts = [len(cell_lines(rc[0])) for rc in t["raw_cells"]]
        n_traits = max(set(counts), key=counts.count) - 1 if counts else 0
        for i, row in enumerate(t["rows"]):
            lines = cell_lines(t["raw_cells"][i][0])
            if n_traits > 0 and len(lines) > n_traits:
                style, traits = " ".join(lines[:-n_traits]), lines[-n_traits:]
            else:
                style, traits = row[0], []
            for garment, cell in zip(garments, row[1:]):
                cost = parse_cost(cell)
                if "cost_eb" not in cost:
                    continue
                name = f"{style} {garment}"
                stats = {**cost, "style": style, "garment": garment, "style_traits": traits}
                entries.append(_entry("fashion", name, _fact_line([f"{name}: {style} style {garment.lower()}",
                                                                   ", ".join(traits), f"{cost['cost_eb']}eb"]),
                                      stats, t, digest, tags=[style], source={"table": t["id"], "columns": t["columns"], "cells": row}))
    return entries


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------

def _skill_name(header: str) -> str:
    """A dot-leader header's skill name, without its "(x2)" marker or stray leader dots."""
    name = re.sub(r"\s*\(\s*x\s*2\s*\)\s*$", "", header, flags=re.I)
    return re.sub(r"[.\s]+$", "", name).strip()


def _build_skills(conn: sqlite3.Connection, digest: str) -> list[dict[str, Any]]:
    printed = dict(conn.execute("SELECT pdf_page, printed_page FROM pages"))
    blocks = conn.execute("SELECT pdf_page, ordinal, text, role FROM source_blocks ORDER BY pdf_page, ordinal").fetchall()
    per_page: dict[int, int] = {}
    for pdf_page, _, text, _ in blocks:
        per_page[pdf_page] = per_page.get(pdf_page, 0) + sum(1 for ln in text.split("\n") if _HEADER.fullmatch(ln.strip()))
    skill_pages = {p for p, n in per_page.items() if n >= _SKILL_PAGE_MIN_HEADERS}
    found: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    current: dict[str, Any] | None = None
    for pdf_page, _, text, role in blocks:
        if pdf_page not in skill_pages:
            if current is not None:
                current = None
            continue
        if role == "heading":
            # Group headings ("Fighting Skills") end the running description.
            current = None
            continue
        if role != "body":
            continue
        for line in text.split("\n"):
            match = _HEADER.fullmatch(line.strip())
            if match:
                raw, stat = match.groups()
                cost = 2 if re.search(r"\(\s*x\s*2\s*\)\s*$", raw, re.I) else 1
                name = _skill_name(raw)
                key = _normalize(name)
                if key not in found:
                    found[key] = {"name": name, "stat": stat.upper(), "cost": cost, "pdf_page": pdf_page,
                                  "printed_page": printed.get(pdf_page), "descriptions": []}
                    order.append(key)
                elif (found[key]["stat"], found[key]["cost"]) != (stat.upper(), cost):
                    raise ValueError(f"Conflicting source definitions for skill {name!r}")
                current = {"key": key, "lines": []}
                found[key]["descriptions"].append(current["lines"])
            elif current is not None and line.strip():
                current["lines"].append(line.strip())
    entries = []
    for key in order:
        item = found[key]
        texts = [flat(" ".join(lines)) for lines in item["descriptions"]]
        desc = max(texts, key=len) if texts else ""
        specializable = key in _SPECIALIZABLE
        tags = ["skill", item["stat"].lower()] + (["x2"] if item["cost"] == 2 else []) + (["specializable"] if specializable else [])
        entry = _entry("skill", item["name"], desc, {"stat": item["stat"], "cost_multiplier": item["cost"],
                                                     "specializable": specializable},
                       None, digest, pdf_page=item["pdf_page"], printed_page=item["printed_page"], tags=tags[1:])
        entry["stats"]["specializable"] = specializable
        entries.append(entry)
    return entries


# --------------------------------------------------------------------------
# Roles, starter kits and role tables
# --------------------------------------------------------------------------

# A kit line continues the previous item when it starts lowercase / with a
# quantity or a trailing noun, or when the previous line ends mid-phrase.
_KIT_CONTINUATION = re.compile(r"^(?:[a-z]|x\s*\d|\(|(?:Ammunition|Ammo|Body Armor|Head Armor|Armor|Pistol|Weapon|Grenade|Rifle|Shell)\b)")
_KIT_DANGLING = re.compile(r"(?:\b(?:or|and|Basic|Heavy|Very|Light|Incendiary|Smoke|the|a)|,)$")


def parse_kit(cell: str) -> list[dict[str, Any]]:
    """Split a starter-kit cell into fixed items and either/or choices."""
    items: list[str] = []
    for line in cell_lines(cell):
        if items and (_KIT_DANGLING.search(items[-1]) or _KIT_CONTINUATION.match(line)):
            items[-1] = f"{items[-1]} {line}"
        else:
            items.append(line)
    result = []
    for raw in items:
        options = [o.strip() for o in re.split(r"\s+or\s+", raw) if o.strip()]
        parsed = []
        for option in options:
            qty = re.search(r"\s*x\s*(\d+)\s*$", option)
            name = option[:qty.start()].strip() if qty else option
            parsed.append({"item": name, "qty": int(qty.group(1)) if qty else 1})
        if len(parsed) == 1:
            result.append({"type": "fixed", **parsed[0]})
        elif parsed:
            result.append({"type": "choice", "options": parsed})
    return result


def _role_names(tables: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for t in tables:
        if t["kind"] == "role_skill_list":
            for column in t["columns"]:
                role = re.sub(r"\s*skills\s*$", "", column, flags=re.I).strip()
                if role and role not in names:
                    names.append(role)
    return names


def role_data(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    roles = {name: {"skills": [], "streetrat_skills": {}, "starter_weapons_armor": [], "starter_outfit": [],
                    "starter_cyberware": [], "stat_templates": []} for name in _role_names(tables)}
    for t in tables:
        kind = t["kind"]
        if kind == "role_skill_levels":
            for g, role in enumerate(t["groups"]):
                if role not in roles:
                    continue
                levels = {}
                for row in t["rows"]:
                    if 2 * g + 1 < len(row) and row[2 * g] and _int(row[2 * g + 1]) is not None:
                        levels[row[2 * g]] = _int(row[2 * g + 1])
                roles[role]["streetrat_skills"] = levels
        elif kind == "role_skill_list":
            for j, column in enumerate(t["columns"]):
                role = re.sub(r"\s*skills\s*$", "", column, flags=re.I).strip()
                if role in roles:
                    roles[role]["skills"] = [r[j] for r in t["rows"] if j < len(r) and r[j]]
        elif kind in {"starter_weapons_armor", "starter_outfit", "starter_cyberware"}:
            suffix = {"starter_weapons_armor": "weapons/armor", "starter_outfit": "outfit", "starter_cyberware": "cyberware"}[kind]
            for j, column in enumerate(t["columns"]):
                role = re.sub(rf"\s*{re.escape(suffix)}\s*$", "", column, flags=re.I).strip()
                if role in roles and t["raw_cells"]:
                    cell = "\n".join(rc[j] for rc in t["raw_cells"] if j < len(rc) and rc[j])
                    kit = parse_kit(cell)
                    for item in [k for k in kit if k["type"] == "fixed" and re.match(r"\d+\s+Humanity Loss\b", k["item"])]:
                        kit.remove(item)
                        roles[role]["starter_humanity_loss"] = int(item["item"].split()[0])
                    roles[role][kind] = kit
    # STAT template tables follow a "▶<Role>" heading (stored as the table title).
    for t in tables:
        if t["kind"] == "stat_template" and t["title"]:
            role = next((r for r in roles if norm_key(t["title"]) == norm_key(r)), None)
            if role and not roles[role]["stat_templates"]:
                roles[role]["stat_templates"] = [[_int(c) for c in row[1:]] for row in t["rows"]]
    return roles


# --------------------------------------------------------------------------
# Sections and roles from the outline
# --------------------------------------------------------------------------

def _build_sections(conn: sqlite3.Connection, roles: dict[str, dict[str, Any]], digest: str) -> list[dict[str, Any]]:
    from knowledge import section_text

    rows = conn.execute(
        "SELECT s.id, s.title, s.start_pdf, s.end_pdf, s.printed_start, s.kind, s.level, p.title AS parent_title "
        "FROM source_sections s LEFT JOIN source_sections p ON p.id = s.parent_id ORDER BY s.start_pdf, s.anchor_ordinal"
    ).fetchall()
    title_counts: dict[str, int] = {}
    for row in rows:
        title_counts[_normalize(row[1])] = title_counts.get(_normalize(row[1]), 0) + 1
    role_keys = {norm_key(r): r for r in roles}
    role_done: set[str] = set()
    ability_by_role: dict[str, str] = {}
    entries = []
    from knowledge import _SIDEBAR_PARENT
    for sid, title, start, end, printed, kind, level, parent_title in rows:
        if _SIDEBAR_PARENT.match(title):
            continue  # outline containers with no text of their own
        text = section_text(conn, sid)
        if not text:
            continue
        role = role_keys.get(norm_key(title))
        if role and role not in role_done:
            role_done.add(role)
            stats = {"start_pdf": start, "end_pdf": end, **{k: v for k, v in roles[role].items() if v}}
            ability = re.search(r"Role Ability\s*:\s*([A-Z][\w' -]+?)(?=\s+The\b|\s{2}|$)", _section_headings(conn, sid))
            if ability:
                stats["ability"] = ability.group(1).strip()
                ability_by_role[role] = stats["ability"]
            entries.append(_entry("role", role, text, stats, None, digest, pdf_page=start, printed_page=printed,
                                  section_id=sid, tags=[sid]))
            continue
        name = title
        if title_counts.get(_normalize(title), 0) > 1 and parent_title:
            name = f"{title} ({parent_title})"
        tags = [sid] + (["sidebar"] if kind == "sidebar" else [])
        entry = _entry("rule", name, text, {"start_pdf": start, "end_pdf": end, "level": level}, None, digest,
                       pdf_page=start, printed_page=printed, section_id=sid, tags=tags)
        entry["id"] = f"corebook:rule:{sid}"
        entries.append(entry)
    return entries


# Outline nodes whose structure maps onto library categories. Keyed on outline
# titles (structure), never on page numbers.
#   children   -> each child section becomes one entry
#   decorated  -> each "▶ Name ◀" sub-heading inside the subtree becomes one entry
#   forms      -> "▶ Form ◀" sub-headings with their "▶Move" headings as structured moves
_SECTION_MAPS: list[tuple[re.Pattern[str], str, str, str]] = [
    (re.compile(r"^the neocorps$", re.I), "children", "faction", "corporation"),
    (re.compile(r"^key places in and around night city$", re.I), "decorated", "location", "district"),
    (re.compile(r"^martial arts$", re.I), "forms", "rule", "martial art"),
]


def _subtree_blocks(conn: sqlite3.Connection, section_id: str) -> list[tuple[int, int, str, str]]:
    """Blocks from a section's heading to the end of its last descendant section."""
    rows = conn.execute("SELECT id, parent_id, start_pdf, end_pdf, anchor_ordinal, end_ordinal FROM source_sections").fetchall()
    children: dict[str, list[tuple]] = {}
    by_id = {r[0]: r for r in rows}
    for r in rows:
        children.setdefault(r[1], []).append(r)
    stack, last = [by_id[section_id]], by_id[section_id]
    while stack:
        node = stack.pop()
        if (node[3], node[5] or 10**6) > (last[3], last[5] or 10**6):
            last = node
        stack.extend(children.get(node[0], []))
    start, anchor = by_id[section_id][2], by_id[section_id][4]
    end, end_ordinal = last[3], last[5]
    out = []
    for pdf_page, ordinal, text, role in conn.execute(
            "SELECT pdf_page, ordinal, text, role FROM source_blocks WHERE pdf_page BETWEEN ? AND ? ORDER BY pdf_page, ordinal",
            (start, end)):
        if pdf_page == start and anchor is not None and ordinal <= anchor:
            continue
        if pdf_page == end and end_ordinal is not None and ordinal >= end_ordinal:
            break
        out.append((pdf_page, ordinal, text, role))
    return out


def _decorated(text: str) -> str | None:
    match = re.fullmatch(r"▶\s*(.+?)\s*◀", flat(text))
    return match.group(1) if match else None


def _build_mapped_sections(conn: sqlite3.Connection, digest: str) -> list[dict[str, Any]]:
    from knowledge import section_text

    printed = dict(conn.execute("SELECT pdf_page, printed_page FROM pages"))
    sections = conn.execute("SELECT id, title, parent_id, start_pdf FROM source_sections").fetchall()
    entries = []
    for pattern, how, category, kind in _SECTION_MAPS:
        for sid, title, _, _ in sections:
            if not pattern.match(title):
                continue
            if how == "children":
                for cid, ctitle, parent, start in sections:
                    if parent == sid:
                        text = section_text(conn, cid)
                        if text:
                            entries.append(_entry(category, ctitle, text, {"kind": kind}, None, digest, pdf_page=start,
                                                  printed_page=printed.get(start), section_id=cid, tags=[kind]))
                continue
            current: dict[str, Any] | None = None
            items: list[dict[str, Any]] = []
            for pdf_page, _, text, role in _subtree_blocks(conn, sid):
                name = _decorated(text) if role == "heading" else None
                if name:
                    current = {"name": name, "pdf_page": pdf_page, "parts": [], "moves": []}
                    items.append(current)
                elif current is None:
                    continue
                elif role == "heading" and how == "forms" and flat(text).startswith("▶"):
                    current["moves"].append({"name": flat(text).lstrip("▶ ").strip(), "parts": []})
                elif role == "heading":
                    current = None
                elif role == "body":
                    (current["moves"][-1]["parts"] if current["moves"] else current["parts"]).append(text)
            for item in items:
                stats: dict[str, Any] = {"kind": kind}
                if how == "forms" and not item["moves"]:
                    continue
                if item["moves"]:
                    stats["moves"] = []
                    for m in item["moves"]:
                        text = flat(" ".join(m["parts"]))
                        dv = re.search(r"\bDV\s?(\d+)", text)
                        stats["moves"].append({"name": m["name"], "description": text, "dv": int(dv.group(1)) if dv else None})
                text = flat(" ".join(item["parts"])) or "; ".join(m["name"] for m in stats.get("moves", []))
                if text:
                    entries.append(_entry(category, item["name"], text, stats, None, digest, pdf_page=item["pdf_page"],
                                          printed_page=printed.get(item["pdf_page"]), section_id=sid, tags=[kind]))
    return entries


def _section_headings(conn: sqlite3.Connection, section_id: str) -> str:
    row = conn.execute("SELECT start_pdf,end_pdf,anchor_ordinal,end_ordinal FROM source_sections WHERE id=?", (section_id,)).fetchone()
    start, end, anchor, end_ordinal = row
    titles = []
    for pdf_page, ordinal, text in conn.execute(
            "SELECT pdf_page, ordinal, text FROM source_blocks WHERE role='heading' AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page, ordinal",
            (start, end)):
        if pdf_page == start and anchor is not None and ordinal <= anchor:
            continue
        if pdf_page == end and end_ordinal is not None and ordinal >= end_ordinal:
            break
        titles.append(flat(text).lstrip("▶ "))
    return "  ".join(titles)


# --------------------------------------------------------------------------
# Build-time entry point and request-time readers
# --------------------------------------------------------------------------

def _merge(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per (category, name): keep the richest description, record other pages."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for e in entries:
        key = (e["category"], e["norm_name"])
        if key not in merged:
            merged[key] = e
            order.append(key)
            continue
        kept = merged[key]
        rank = lambda x: (not x["generated_description"], len(x["description"]))  # noqa: E731
        winner, other = (e, kept) if rank(e) > rank(kept) else (kept, e)
        stats = {**other["stats"], **winner["stats"]}
        pages = sorted({p for p in [winner["pdf_page"], other["pdf_page"], *winner["stats"].get("also_pdf_pages", []),
                                    *other["stats"].get("also_pdf_pages", [])] if p is not None} - {winner["pdf_page"]})
        if pages:
            stats["also_pdf_pages"] = pages
        winner["stats"] = stats
        merged[key] = winner
    used: set[str] = set()
    result = []
    for key in order:
        e = merged[key]
        base = e["id"]
        n = 2
        while e["id"] in used:
            e["id"] = f"{base}-{n}"
            n += 1
        used.add(e["id"])
        result.append(e)
    return result


def extract(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (normalized tables, rule entries) for an index being built."""
    digest_row = conn.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()
    if not digest_row or not digest_row[0]:
        raise ValueError("Rules index has no source_sha256 metadata")
    digest = digest_row[0]
    tables = load_tables(conn)
    headings = heading_index(conn)
    roles = role_data(tables)
    entries = (_build_skills(conn, digest) + _build_catalog(tables, headings, digest)
               + _build_mapped_sections(conn, digest) + _build_sections(conn, roles, digest))
    return tables, _merge(entries)


def _connect(rules_path: str | Path) -> sqlite3.Connection:
    uri = Path(rules_path).expanduser().resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1 FROM rule_entries LIMIT 1")
    except sqlite3.Error as exc:
        raise ValueError(f"Cannot read rules catalog (rebuild the index): {exc}") from exc
    return conn


def entries(rules_path: str | Path, category: str | None = None) -> list[dict[str, Any]]:
    """Every materialized Corebook entry (optionally one category), without any cap."""
    with closing(_connect(rules_path)) as conn:
        if category:
            rows = conn.execute("SELECT * FROM rule_entries WHERE category=? ORDER BY name COLLATE NOCASE, id", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rule_entries ORDER BY category, name COLLATE NOCASE, id").fetchall()
    return [_decode(r) for r in rows]


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["stats"] = json.loads(value.pop("stats_json"))
    value["tags"] = json.loads(value.pop("tags_json"))
    value["source_ref"] = json.loads(value.pop("source_json") or "{}")
    return value


def skills(rules_path: str | Path) -> dict[str, dict[str, Any]]:
    """Skill name -> {stat, cost, source_sha256, pdf_page, printed_page}."""
    catalog = {}
    for e in entries(rules_path, "skill"):
        catalog[e["name"]] = {"stat": e["stats"]["stat"], "cost": e["stats"]["cost_multiplier"],
                              "source_sha256": e["source_sha256"], "pdf_page": e["pdf_page"],
                              "printed_page": e["printed_page"]}
    if not catalog:
        raise ValueError("No skill definitions found in the rules index")
    return catalog


def lookup_skill(catalog: dict[str, dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Look up a canonical skill; allow only source-defined specialization forms."""
    if not isinstance(name, str):
        return None
    key = _normalize(name)
    for canonical, item in catalog.items():
        if _normalize(canonical) == key:
            return item
    match = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", key)
    if not match or not match.group(2).strip() or match.group(1).strip() not in _SPECIALIZABLE:
        return None
    base = match.group(1).strip()
    return next((item for canonical, item in catalog.items() if _normalize(canonical) == base), None)


PRICED_CATEGORIES = ("weapon", "armor", "cyberware", "gear", "program", "hardware", "fashion", "drug", "ammo",
                     "attachment", "vehicle", "service", "housing")


def items(rules_path: str | Path) -> dict[str, dict[str, Any]]:
    """Priced Corebook entries keyed by entry id (materialized at build time)."""
    result: dict[str, dict[str, Any]] = {}
    with closing(_connect(rules_path)) as conn:
        rows = conn.execute(
            f"SELECT * FROM rule_entries WHERE category IN ({','.join('?' for _ in PRICED_CATEGORIES)}) "
            "AND json_type(stats_json, '$.cost_eb') = 'integer' ORDER BY category, name COLLATE NOCASE, id",
            PRICED_CATEGORIES).fetchall()
    for e in map(_decode, rows):
        cost = e["stats"]["cost_eb"]
        result[e["id"]] = {"name": e["name"], "cost": cost, "category": e["category"], "pdf_page": e["pdf_page"],
                           "printed_page": e["printed_page"], "source_sha256": e["source_sha256"],
                           "stats": e["stats"], "summary": e["summary"], "description": e["description"],
                           "columns": e["source_ref"].get("columns", []), "cells": e["source_ref"].get("cells", [])}
    return result


def rule_tables(rules_path: str | Path, kind: str | None = None) -> list[dict[str, Any]]:
    """Normalized source tables (optionally one registry kind) with columns, rows and row notes."""
    with closing(_connect(rules_path)) as conn:
        sql = "SELECT * FROM rule_tables" + (" WHERE kind=?" if kind else "") + " ORDER BY pdf_page, id"
        rows = conn.execute(sql, (kind,) if kind else ()).fetchall()
    out = []
    for r in rows:
        value = dict(r)
        value["columns"] = json.loads(value.pop("columns_json"))
        value["rows"] = json.loads(value.pop("rows_json"))
        value["notes"] = json.loads(value.pop("notes_json"))
        out.append(value)
    return out


def roles(rules_path: str | Path) -> dict[str, dict[str, Any]]:
    """Role name -> role entry (description, ability, skills, starter kits, STAT templates)."""
    return {e["name"]: e for e in entries(rules_path, "role")}


def skill_groups(rules_path: str | Path) -> dict[str, str]:
    """Skill name -> the book's category: the "<Category> Skills" heading its definition sits under."""
    names = {_normalize(name): name for name in skills(rules_path)}
    groups: dict[str, str] = {}
    group = None
    with closing(_connect(rules_path)) as conn:
        for text, role in conn.execute("SELECT text, role FROM source_blocks ORDER BY pdf_page, ordinal"):
            if role == "heading":
                match = re.fullmatch(r"(.+?) Skills?", flat(text))
                group = match.group(1) if match else None
            elif group:
                for line in text.split("\n"):
                    header = _HEADER.fullmatch(line.strip())
                    name = names.get(_normalize(_skill_name(header.group(1)))) if header else None
                    if name:
                        groups.setdefault(name, group)
    missing = sorted(set(names.values()) - set(groups))
    if missing:
        raise ValueError(f"No skill category found in the rules index for: {', '.join(missing)}")
    return groups


def role_lifepaths(rules_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Role name -> [{title, options}] from the role-based lifepath roll tables.

    Each role-based lifepath page carries its role's name as a heading, so a
    roll table belongs to the role named on its page.
    """
    names = {name.casefold(): name for name in roles(rules_path)}
    with closing(_connect(rules_path)) as conn:
        first, last = conn.execute(
            "SELECT p.start_pdf, MAX(c.end_pdf) FROM source_sections p JOIN source_sections c ON c.parent_id=p.id "
            "WHERE p.title='Role-Based Lifepaths'").fetchone()
        page_roles = {
            pdf_page: names[flat(text).casefold()]
            for pdf_page, text in conn.execute(
                "SELECT pdf_page, text FROM source_blocks WHERE role='heading' AND pdf_page BETWEEN ? AND ?", (first, last))
            if flat(text).casefold() in names
        }
    result: dict[str, list[dict[str, Any]]] = {}
    for table in rule_tables(rules_path, "roll_table"):
        role = page_roles.get(table["pdf_page"])
        if role:
            result.setdefault(role, []).append({
                "title": (table["title"] or "").strip(" ▶◀:"),
                "options": [f"{row[-1]} {note}".strip() for row, note in zip(table["rows"], table["notes"])],
            })
    missing = sorted(set(names.values()) - set(result))
    if missing:
        raise ValueError(f"No role-based lifepath tables found in the rules index for: {', '.join(missing)}")
    return result
