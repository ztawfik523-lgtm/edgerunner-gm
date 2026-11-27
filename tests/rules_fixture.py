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


def block(text: str, y: float, *, x: float = 63.0, size: float = 11.0, bold: bool = False, width: float = 460.0) -> dict[str, Any]:
    lines = max(1, text.count("\n") + 1)
    return {"x0": x, "y0": y, "x1": x + width, "y1": y + 13.5 * lines, "text": text, "size": size, "bold": bold}


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


def add_skill_definitions(path: Path, lines: list[str], pdf_page: int = 900) -> None:
    """Append dot-leader skill definition blocks to an existing index and re-materialize the library."""
    import library

    conn = sqlite3.connect(path)
    try:
        start = conn.execute("SELECT COALESCE(MAX(ordinal), 0) FROM source_blocks WHERE pdf_page=?", (pdf_page,)).fetchone()[0]
        for i, line in enumerate(lines, start + 1):
            conn.execute("INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (pdf_page, i, 63.0, 60.0 + 14 * i, 300.0, 72.0 + 14 * i, line, 11.0, 1, "body"))
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
