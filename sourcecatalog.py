"""Read-only, source-derived catalog of Cyberpunk RED core skills."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

STATS = frozenset("INT REF DEX TECH COOL WILL LUCK MOVE BODY EMP".split())
_HEADER = re.compile(r"^(.+?)\.{2,}\s*(INT|REF|DEX|TECH|COOL|WILL|LUCK|MOVE|BODY|EMP)\s*$", re.I)
_SPECIALIZABLE = {"language", "local expert", "science", "play instrument", "martial arts"}


def _normalize(value: str) -> str:
    value = re.sub(r"\s*\(choose\s*1\)\s*", " ", value, flags=re.I)
    value = re.sub(r"\s*\(x\s*2\)\s*", " ", value, flags=re.I)
    value = re.sub(r"\s*/\s*", "/", value)
    return re.sub(r"\s+", " ", value.strip()).casefold()


def skills(rules_path: str | Path) -> dict[str, dict[str, Any]]:
    """Extract skill names and stats from source skill-definition pages in SQLite."""
    uri = Path(rules_path).expanduser().resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.row_factory = sqlite3.Row
            metadata = dict(connection.execute("SELECT key,value FROM metadata"))
            digest = metadata.get("source_sha256")
            if not digest:
                raise ValueError("Rules index has no source_sha256 metadata")
            rows = connection.execute("SELECT pdf_page,printed_page,text FROM pages ORDER BY pdf_page").fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(f"Cannot read rules skill catalog: {exc}") from exc

    catalog: dict[str, dict[str, Any]] = {}
    # These are the actual skill-definition spread (printed 82–85); other
    # dot-leader headings elsewhere in the book are not skill definitions.
    for row in rows:
        printed = row["printed_page"]
        if printed is None:
            printed = next((int(line.strip()) for line in str(row["text"]).splitlines()[:4]
                            if re.fullmatch(r"8[2-5]", line.strip())), None)
        if printed is None or not 82 <= int(printed) <= 85:
            continue
        for line in str(row["text"]).splitlines():
            match = _HEADER.fullmatch(line.strip())
            if not match:
                continue
            raw, stat = match.groups()
            cost = 2 if re.search(r"\(\s*x\s*2\s*\)\s*$", raw, re.I) else 1
            name = re.sub(r"\s*\(\s*x\s*2\s*\)\s*$", "", raw, flags=re.I)
            name = re.sub(r"[.\s]+$", "", name).strip()
            key = _normalize(name)
            item = {"stat": stat.upper(), "cost": cost, "source_sha256": digest,
                    "pdf_page": int(row["pdf_page"]),
                    "printed_page": int(printed) if printed is not None else None}
            previous = next((existing for existing in catalog if _normalize(existing) == key), None)
            if previous is not None:
                if (catalog[previous]["stat"], catalog[previous]["cost"]) != (item["stat"], cost):
                    raise ValueError(f"Conflicting source definitions for skill {name!r}")
                continue
            catalog.setdefault(name, item)
    if not catalog:
        raise ValueError("No skill definitions found on source pages 82–85")
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


def _cell_rows(raw: Any) -> list[list[str]]:
    """Read table rows from either the structured table store or serialized page text."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return [[cell.strip() for cell in line.split("|")] for line in raw.splitlines()
                    if "|" in line]
    if not isinstance(raw, list):
        return []
    result = []
    for row in raw:
        if isinstance(row, list):
            result.append(["" if cell is None else re.sub(r"\s+", " ", str(cell)).strip() for cell in row])
    return result


def _catalog_data(rules_path: str | Path):
    uri = Path(rules_path).expanduser().resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            digest = meta.get("source_sha256")
            if not digest:
                raise ValueError("Rules index has no source_sha256 metadata")
            pages = conn.execute("SELECT pdf_page,printed_page,text FROM pages ORDER BY pdf_page").fetchall()
            tables = {}
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_tables'").fetchone()
            if exists:
                for row in conn.execute("SELECT pdf_page,ordinal,cells_json FROM source_tables ORDER BY pdf_page,ordinal"):
                    tables.setdefault(int(row["pdf_page"]), []).append(_cell_rows(row["cells_json"]))
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(f"Cannot read rules item catalog: {exc}") from exc
    return digest, pages, tables


def _page_number(row) -> int | None:
    if row["printed_page"] is not None:
        return int(row["printed_page"])
    return next((int(line.strip()) for line in str(row["text"]).splitlines()[:5]
                 if re.fullmatch(r"\d{1,3}", line.strip())), None)


def _tables_for_page(row, stored) -> list[list[list[str]]]:
    if stored:
        return stored
    text = str(row["text"])
    sections = re.split(r"(?m)^Table\s+\d+\s*:\s*$", text)
    result = []
    for section in sections[1:]:
        rows = _cell_rows(section)
        if rows:
            result.append(rows)
    return result


def _category(headers: list[str]) -> str:
    joined = " ".join(re.sub(r"[^a-z]", "", h.lower()) for h in headers)
    if "ammo" in joined or "ammunition" in joined:
        return "ammo"
    if "attachment" in joined or "optic" in joined or "rail" in joined:
        return "attachment"
    if "vehicle" in joined or "sdp" in joined or "seats" in joined or "mph" in joined:
        return "vehicle"
    if "drug" in joined or "streetdrug" in joined or "primaryeffect" in joined or "secondaryeffect" in joined:
        return "drug"
    if "housing" in joined or "rent" in joined or "accommodation" in joined:
        return "housing"
    if "service" in joined or "lifestyle" in joined or "trauma" in joined or "therapy" in joined:
        return "service"
    if "weapontype" in joined or "weapon" in joined:
        return "weapon"
    if "armortype" in joined or "armor" in joined:
        return "armor"
    if "cyberware" in joined or "install" in joined or "humanityloss" in joined or re.search(r"\bhl\b", " ".join(headers), re.I):
        return "cyberware"
    if "program" in joined or "rez" in joined or "class" in joined:
        return "program"
    if "hardware" in joined:
        return "hardware"
    if "fashion" in joined or "style" in joined or "clothing" in joined or "outfit" in joined or "garment" in joined:
        return "fashion"
    return "gear"


_COST = re.compile(r"(?<![\w])\d[\d,]*\s*eb\b", re.I)
_NAME_HEADER_KEYS = frozenset({
    "name", "item", "itemname", "weaponname", "cyberwarename", "weapontype",
    "meleeweapontype", "armortype", "vehicle", "vehiclename", "drug", "drugname",
    "ammo", "ammotype", "attachment", "housing", "housingtype", "service",
    "servicetype", "lifestyle", "fashion", "style", "garment", "program", "hardware",
})
_COST_HEADER_KEYS = frozenset({
    "cost", "price", "costeb", "priceeb", "rent", "renteb", "rentebmo", "monthlyeb",
})
_EB_HEADER_KEYS = frozenset({"costeb", "priceeb", "renteb", "rentebmo", "monthlyeb"})


def _cost(cell: str, *, allow_bare_int: bool = False) -> int | None:
    if re.search(r"(?:\d\s*[-–—]|[-–—]\s*\d)|\bor\b|\bto\b", cell, re.I):
        return None
    matches = list(_COST.finditer(cell))
    if len(matches) == 1:
        token = matches[0].group(0)
        return int(re.sub(r"[^0-9]", "", token))
    if allow_bare_int and not matches:
        stripped = cell.strip().replace(",", "")
        if re.fullmatch(r"\d+", stripped):
            return int(stripped)
    return None


def items(rules_path: str | Path) -> dict[str, dict[str, Any]]:
    """Return explicitly priced source table entries, retaining extraction evidence."""
    digest, pages, stored = _catalog_data(rules_path)
    result: dict[str, dict[str, Any]] = {}
    variants: dict[str, list[tuple[str, int]]] = {}
    for page in pages:
        printed = _page_number(page)
        for table_no, rows in enumerate(_tables_for_page(page, stored.get(int(page["pdf_page"]), [])), 1):
            if len(rows) < 2:
                continue
            header_index = next((i for i, row in enumerate(rows) if any(re.sub(r"[^a-z]", "", c.casefold()) in _COST_HEADER_KEYS for c in row)), None)
            if header_index is None: continue
            headers = rows[header_index]
            norm_headers = [re.sub(r"[^a-z]", "", h.casefold()) for h in headers]
            name_col = next((i for i, h in enumerate(norm_headers) if h in _NAME_HEADER_KEYS), None)
            cost_col = next((i for i, h in enumerate(norm_headers) if h in _COST_HEADER_KEYS), None)
            if name_col is None or cost_col is None:
                continue
            allow_bare = norm_headers[cost_col] in _EB_HEADER_KEYS
            category = _category(headers)
            for row_no, cells in enumerate(rows[header_index+1:], header_index+1):
                if max(name_col, cost_col) >= len(cells):
                    continue
                name = cells[name_col].strip()
                cost = _cost(cells[cost_col], allow_bare_int=allow_bare)
                if not name or cost is None:
                    continue
                key = _normalize(name)
                item_id = f"{key}#pdf{int(page['pdf_page'])}-t{table_no}-r{row_no}"
                record = {"name": name, "cost": cost, "category": category,
                          "pdf_page": int(page["pdf_page"]), "printed_page": printed,
                          "source_sha256": digest, "cells": cells, "columns": headers,
                          "verification": "extracted_requires_layout_verification"}
                result[item_id] = record
                variants.setdefault(key, []).append((item_id, cost))
    for same_name in variants.values():
        costs = {cost for _, cost in same_name}
        if len(costs) > 1:
            for item_id, _ in same_name:
                result[item_id]["variants"] = [other for other, _ in same_name]
    return result


def package(rules_path: str | Path, role: str, kind: str) -> dict[str, Any]:
    """Return raw table evidence for a role's explicit starting package section."""
    if not isinstance(role, str) or not role.strip() or kind not in {"weapons", "outfit", "cyberware"}:
        raise ValueError("role must be nonempty and kind must be weapons, outfit, or cyberware")
    digest, pages, stored = _catalog_data(rules_path)
    labels = {"weapons": 98, "outfit": 103, "cyberware": 117}
    candidates = []
    for page in pages:
        printed = _page_number(page)
        if printed != labels[kind]:
            continue
        text = str(page["text"])
        tables = _tables_for_page(page, stored.get(int(page["pdf_page"]), []))
        role_re = re.compile(rf"(?<!\w){re.escape(role.strip())}(?!\w)", re.I)
        for table_no, rows in enumerate(tables, 1):
            if not any(role_re.search(cell) for row in rows for cell in row):
                continue
            candidates.append({"role": role.strip(), "kind": kind, "pdf_page": int(page["pdf_page"]),
                               "printed_page": printed, "source_sha256": digest,
                               "cells": rows, "columns": rows[0] if rows else [],
                               "table": table_no, "extracted_tokens": [cell for row in rows for cell in row if cell]})
        if not tables and role_re.search(text):
            candidates.append({"role": role.strip(), "kind": kind, "pdf_page": int(page["pdf_page"]),
                               "printed_page": printed, "source_sha256": digest,
                               "cells": [], "columns": [], "extracted_tokens": [line.strip() for line in text.splitlines() if role_re.search(line)]})
    return {"role": role.strip(), "kind": kind, "sections": candidates,
            "verification": "extracted_requires_layout_verification"}
