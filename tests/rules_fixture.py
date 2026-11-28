"""Synthetic layout pages for building rules indexes through the real pipeline.

Pages mimic the structure the extractor relies on (edge page numbers, running
headers, heading blocks, line-detected tables with realistic column headers)
using invented text only.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import redkb

WIDTH, HEIGHT = 603.0, 783.0


def block(text: str, y: float, *, x: float = 63.0, size: float = 11.0, bold: bool = False, width: float = 460.0,
          runin: str = "") -> dict[str, Any]:
    lines = max(1, text.count("\n") + 1)
    return {"x0": x, "y0": y, "x1": x + width, "y1": y + 13.5 * lines, "text": text, "size": size, "bold": bold,
            "runin": runin}


def heading(text: str, y: float, *, size: float = 14.0) -> dict[str, Any]:
    return block(text, y, size=size)


def table(rows: list[list[str]], y: float, *, row_height: float = 18.0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A line-detected grid plus the text blocks drawn inside it."""
    bbox = [63.0, y, 540.0, y + row_height * len(rows)]
    blocks = [block("\n".join(cell for cell in row if cell), y + i * row_height + 2, x=66.0, size=10.0, width=470.0)
              for i, row in enumerate(rows)]
    for b in blocks:
        b["y1"] = min(b["y1"], b["y0"] + row_height - 3)
    return {"bbox": bbox, "rows": rows}, blocks


def page(pdf_page: int, printed: int | None, content: Iterable[Any], *, header: str = "SYNTHETIC CHAPTER") -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    if printed is not None:
        blocks.append({"x0": 17.0, "y0": 744.0, "x1": 50.0, "y1": 765.0, "text": str(printed), "size": 19.0, "bold": False})
    blocks.append({"x0": 18.0, "y0": 27.0, "x1": 448.0, "y1": 47.0, "text": header, "size": 19.0, "bold": False})
    for item in content:
        if isinstance(item, tuple):
            grid, inner = item
            tables.append(grid)
            blocks.extend(inner)
        else:
            blocks.append(item)
    return {"pdf_page": pdf_page, "width": WIDTH, "height": HEIGHT, "blocks": blocks, "tables": tables}


def build(path: Path, pages: list[dict[str, Any]], toc: list[list[Any]] = (), digest: str = "d" * 64) -> Path:
    """Write a complete rules index from synthetic pages (pdf pages may be sparse)."""
    by_no = {p["pdf_page"]: p for p in pages}
    full = [by_no.get(n) or page(n, None, []) for n in range(1, max(by_no) + 1)]
    conn = sqlite3.connect(path)
    try:
        redkb.write_index(conn, full, list(toc), {"source_filename": "synthetic.pdf", "source_sha256": digest})
        conn.commit()
    finally:
        conn.close()
    return path


RANGED_HEADER = ["Weapon Type", "Weapon Skill", "Single Shot Damage", "Standard Magazine", "Rate of Fire (ROF)",
                 "Hands Required", "Can be Concealed?", "Cost"]
ARMOR_HEADER = ["Armor Type", "Armor Description", "Damage Stopping Power (SP)", "Armor Penalty (Minimum 0)", "Cost"]
CYBERWARE_HEADER = ["Name", "Install", "Description & Data", "Cost", "HL"]
GEAR_HEADER = ["Item", "Description & Data", "Cost"]
PROGRAM_HEADER = ["Name", "Class", "ATK", "DEF", "REZ", "Effect", "Cost"]
BLACK_ICE_HEADER = ["Name", "Class", "PER", "SPD", "ATK", "DEF", "REZ", "Effect", "Cost"]
HARDWARE_HEADER = ["Name", "Data", "Cost"]
CYBERDECK_HEADER = ["Type", "Cost", "Slots"]


def line(text: str, x: float, y: float, *, rotated: bool = False, emphasis: bool = False) -> dict[str, Any]:
    """One visible text line, as `layout.visible_lines` returns it."""
    width = 12.0 if rotated else 5.0 * len(text)
    return {"x0": x, "y0": y, "x1": x + width, "y1": y + (120.0 if rotated else 12.0), "text": text,
            "rotated": rotated, "emphasis": emphasis}


def stat_block_lines(name: str, top: float = 100.0) -> list[dict[str, Any]]:
    """An invented stat block in the book's grid: vertical name, labelled cells, weapon and armor tables."""
    out = [line(name.lower(), 60.0, top, rotated=True)]
    for row, labels in enumerate((("INT", "REF", "DEX", "TECH", "COOL"), ("WILL", "LUCK", "MOVE", "BODY", "EMP"))):
        for column, label in enumerate(labels):
            x, y = 100.0 + 90 * column, top + 30 * row
            value = "—" if label == "LUCK" else "6 (4)" if label == "REF" else "5"
            out += [line(f"▶{label}", x, y), line(value, x + 40, y)]
    for column, (label, value) in enumerate((("Hit Points", "30"), ("Seriously Wounded", "15"), ("Death Save", "5"))):
        out += [line(f"▶{label}", 100.0 + 170 * column, top + 70), line(value, 190.0 + 170 * column, top + 70)]
    out += [
        line("Weapons", 220.0, top + 105), line("Armor: Test Weave", 410.0, top + 105),
        line("Poor Quality VH Pistol", 105.0, top + 122), line("4d6", 232.0, top + 122),
        line("Medium Melee", 262.0, top + 124), line("Weapon", 262.0, top + 138), line("2d6", 368.0, top + 131),
        line("Head", 410.0, top + 122), line("7 SP", 475.0, top + 122),
        line("Body", 410.0, top + 140), line("11 SP", 475.0, top + 140),
        line("▶Skill Bases", 100.0, top + 170), line("Handgun 10 (8), Evasion 7, Local Expert", 150.0, top + 170),
        line("(Your Home) 5, Test Instinct 4, Tactics", 150.0, top + 181),
        line("▶Cyberware & Special Equipment VH Pistol Ammo x30, Flash-", 100.0, top + 200),
        line("light", 200.0, top + 212),
        line(f"The {name} is considered Mooks here.", 80.0, top + 240, emphasis=True),
    ]
    return out


def add_skill_definitions(path: Path, lines: list[str], pdf_page: int = 900) -> None:
    """Append dot-leader skill definition blocks to an existing index and re-materialize the library."""
    import library

    conn = sqlite3.connect(path)
    try:
        start = conn.execute("SELECT COALESCE(MAX(ordinal), 0) FROM source_blocks WHERE pdf_page=?", (pdf_page,)).fetchone()[0]
        for i, line in enumerate(lines, start + 1):
            conn.execute("INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (pdf_page, i, 63.0, 60.0 + 14 * i, 300.0, 72.0 + 14 * i, line, 11.0, 1, "body", ""))
        library.build_library(conn)
        conn.commit()
    finally:
        conn.close()


def pdf_page(book: Any, printed: int | None, header: str, body: str, *, fontsize: float = 10) -> Any:
    """Add a PDF page with a top running header, body text and a bottom-edge page number."""
    page = book.new_page()
    page.insert_text((50, 30), header, fontsize=fontsize)
    page.insert_text((50, 100), body, fontsize=fontsize)
    if printed is not None:
        page.insert_text((40, page.rect.height - 20), str(printed), fontsize=fontsize)
    return page


def add_role(path: Path, name: str, templates: list[list[int]], streetrat_skills: dict[str, int]) -> None:
    """Insert a materialized role entry (call after anything that re-materializes the library)."""
    stats = {"stat_templates": templates, "streetrat_skills": streetrat_skills}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO rule_entries(id,name,norm_name,category,summary,description,stats_json,tags_json,source_sha256)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (f"corebook:role:{name.lower()}", name, name.lower(), "role", name, name, json.dumps(stats), "[]", "test"),
        )
        conn.commit()
    finally:
        conn.close()


def add_entry(path: Path, category: str, name: str, stats: dict[str, Any], tags: Iterable[str] = ()) -> None:
    """Insert one materialized catalog entry (call after anything that re-materializes the library)."""
    slug = "-".join(name.lower().split())
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO rule_entries(id,name,norm_name,category,summary,description,stats_json,tags_json,source_sha256)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (f"corebook:{category}:{slug}", name, name.lower(), category, name, name, json.dumps(stats), json.dumps(list(tags)), "test"),
        )
        conn.commit()
    finally:
        conn.close()


def add_table(path: Path, kind: str, title: str, columns: list[str], rows: list[list[str]], printed_page: int = 1) -> None:
    """Insert one materialized rule table."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("INSERT INTO rule_tables VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (f"{kind}-{title}", kind, title, kind, printed_page, printed_page, None,
                      json.dumps(columns), json.dumps(rows), json.dumps([""] * len(rows))))
        conn.commit()
    finally:
        conn.close()


def add_stat_overview(path: Path) -> None:
    """The one rule entry that describes all ten STATs, in "Name (ABBR): text" form (invented prose)."""
    names = {"INT": "Alpha", "WILL": "Bravo", "COOL": "Charlie", "EMP": "Delta", "TECH": "Echo", "REF": "Foxtrot",
             "LUCK": "Golf", "BODY": "Hotel", "DEX": "India", "MOVE": "Juliett"}
    body = "Intro sentence. " + " ".join(f"{name} ({key}): About {key}." for key, name in names.items())
    add_entry(path, "rule", "What are Statistics?", {})
    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE rule_entries SET description=? WHERE name='What are Statistics?'", (body,))
        conn.commit()
    finally:
        conn.close()


def add_creation_catalog(path: Path) -> None:
    """The priced items, armor and housing that character creation looks up (invented prices)."""
    priced = [("weapon", "Very Heavy Pistol", 100), ("weapon", "Heavy Pistol", 100), ("gear", "Agent", 100),
              ("fashion", "High Fashion Contact Lenses", 1000), ("fashion", "High Fashion Jacket", 1000)]
    for category, name, cost in priced:
        add_entry(path, category, name, {"cost_eb": cost})
    for name, sp, cost in [("Light Armorjack", 11, 100), ("Medium Armorjack", 12, 100), ("Bodyweight Suit", 11, 1000)]:
        add_entry(path, "armor", name, {"cost_eb": cost, "sp": sp})
    for name, hl, cost in [("Neural Link", 7, 500), ("Linear Frame Sigma", 14, 1000), ("Skin Weave", 7, 500),
                           ("Implanted Linear Frame Sigma", 14, 5000)]:
        add_entry(path, "cyberware", name, {"cost_eb": cost, "hl": hl})
    for name, kind, cost in [("Cargo Container", "housing", 1000), ("Cube Hotel", "housing", 500),
                             ("Corporate Conapt", "housing", 0), ("Kibble", "lifestyle", 100),
                             ("Generic Prepak", "lifestyle", 300)]:
        add_entry(path, "housing", name, {"cost_eb": cost, "kind": kind})
    add_stat_overview(path)


def add_campaign_presets(path: Path) -> None:
    """One district, corporation, zone type, threat rating and headline row."""
    add_entry(path, "location", "Test District", {"kind": "district"})
    add_entry(path, "faction", "Test Corp", {"kind": "corporation"})
    add_entry(path, "faction", "Test Gang", {"kind": "gang"})
    add_table(path, "zone_type", "Zones", ["Zone Type", "Description"], [["Test Zone", "A zone."]])
    add_table(path, "threat_rating", "Threats", ["Threat Rating", "Description"], [["Test Threat", "A threat."]])
    add_table(path, "screamsheet_headlines", "Headlines", ["1d10", "A", "B", "C"], [["1", "Mayor", "Opens", "Bridge"]])
