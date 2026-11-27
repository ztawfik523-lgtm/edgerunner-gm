"""Bounded, provenance-preserving source structure for the local rules index."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any

from layout import flat, norm_key

_SIDEBAR_PARENT = re.compile(r"^(?:sidebars?|advertisements?)$", re.I)


def _slug(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "section"


def _anchor(title: str, toc_page: int, pages: dict[int, dict[str, Any]]) -> tuple[int, int | None]:
    """Locate the heading block that starts a TOC entry near its outline page.

    Outline targets are often off by a page (several entries share a spread),
    so the heading block itself decides where a section starts.
    """
    key = norm_key(title)
    best: tuple[int, int, int, int] | None = None  # (score, -distance, -ordinal, page)
    best_hit: tuple[int, int | None] = (toc_page, None)
    if not key:
        return best_hit
    for distance, page_no in enumerate((toc_page, toc_page + 1, toc_page - 1, toc_page + 2)):
        page = pages.get(page_no)
        if page is None:
            continue
        for ordinal, block in enumerate(page["blocks"], 1):
            if block.get("role") not in {"heading", "body"}:
                continue
            whole = norm_key(block["text"])
            first = norm_key(block["text"].split("\n", 1)[0])
            heading = block.get("role") == "heading"
            if whole == key or first == key:
                score = 5 if heading else 3
            elif heading and len(whole) >= 5 and (key.startswith(whole) or whole.startswith(key)):
                score = 2
            else:
                continue
            candidate = (score, -distance, -ordinal, page_no)
            if best is None or candidate > best:
                best = candidate
                best_hit = (page_no, ordinal)
    return best_hit


def build_structure(conn: sqlite3.Connection, toc: list[Any], pages: list[dict[str, Any]]) -> None:
    """Write sections (anchored to heading blocks), blocks and tables from one layout pass."""
    conn.executescript("""
        CREATE TABLE source_sections(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, start_pdf INTEGER NOT NULL, end_pdf INTEGER NOT NULL,
            printed_start INTEGER, level INTEGER NOT NULL, parent_id TEXT, kind TEXT NOT NULL,
            anchor_ordinal INTEGER, end_ordinal INTEGER);
        CREATE TABLE source_blocks(
            pdf_page INTEGER NOT NULL, ordinal INTEGER NOT NULL, x0 REAL, y0 REAL, x1 REAL, y1 REAL,
            text TEXT NOT NULL, size REAL, bold INTEGER, role TEXT NOT NULL, PRIMARY KEY(pdf_page, ordinal));
        CREATE TABLE source_tables(
            pdf_page INTEGER NOT NULL, ordinal INTEGER NOT NULL, bbox_json TEXT, cells_json TEXT NOT NULL,
            title TEXT, first_block INTEGER, PRIMARY KEY(pdf_page, ordinal));
    """)
    by_no = {p["pdf_page"]: p for p in pages}
    count = len(pages)
    entries: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for position, item in enumerate(toc or []):
        if not (len(item) >= 3 and isinstance(item[0], int) and isinstance(item[1], str) and isinstance(item[2], int)):
            continue
        level, title, target = item[0], item[1].strip(), item[2]
        if not title or not 1 <= target <= count:
            continue
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        sidebar = bool(_SIDEBAR_PARENT.match(title) or (parent and parent["kind"] == "sidebar"))
        start, ordinal = _anchor(title, target, by_no)
        entry = {"title": title, "level": level, "start": start, "ordinal": ordinal, "position": position,
                 "parent": parent, "kind": "sidebar" if sidebar else "section"}
        entries.append(entry)
        stack.append(entry)
    entries.sort(key=lambda e: (e["start"], e["ordinal"] or 0, e["position"]))
    used: dict[str, int] = {}
    for entry in entries:
        base = f"{_slug(entry['title'])}-{entry['start']}"
        used[base] = used.get(base, 0) + 1
        entry["id"] = base if used[base] == 1 else f"{base}-{used[base]}"
    for i, entry in enumerate(entries):
        # Main-flow sections end where the next main-flow heading starts; a
        # sidebar heading inside a page does not cut the surrounding text.
        following = next((e for e in entries[i + 1:] if entry["kind"] == "sidebar" or e["kind"] == "section"), None)
        if following is None:
            end, end_ordinal = count, None
        elif following["ordinal"] is None or following["start"] > entry["start"] and following["ordinal"] <= 1:
            end, end_ordinal = max(entry["start"], following["start"] - 1), None
        else:
            end, end_ordinal = following["start"], following["ordinal"]
        if end == entry["start"] and end_ordinal is not None and entry["ordinal"] is not None and end_ordinal <= entry["ordinal"]:
            end_ordinal = None
        printed = by_no.get(entry["start"], {}).get("printed_page")
        conn.execute("INSERT INTO source_sections VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (entry["id"], entry["title"], entry["start"], max(entry["start"], end), printed, entry["level"],
                      entry["parent"]["id"] if entry["parent"] else None, entry["kind"], entry["ordinal"], end_ordinal))
    for page in pages:
        blocks = page["blocks"]
        for ordinal, block in enumerate(blocks, 1):
            conn.execute("INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (page["pdf_page"], ordinal, block["x0"], block["y0"], block["x1"], block["y1"], block["text"],
                          block.get("size"), int(bool(block.get("bold"))), block.get("role", "body")))
        for ordinal, table in enumerate(page["tables"], 1):
            x0, y0, x1, y1 = table["bbox"]
            inside = [i for i, b in enumerate(blocks, 1)
                      if b["x0"] >= x0 - 2 and b["x1"] <= x1 + 2 and b["y0"] >= y0 - 2 and b["y1"] <= y1 + 2]
            above = [b for b in blocks if b.get("role") in {"heading", "body"} and b["y1"] <= y0 + 2
                     and y0 - b["y1"] <= 90 and b["x1"] > x0 and b["x0"] < x1 and len(flat(b["text"])) <= 120]
            # A caption drawn inside the grid (above the header row) wins over text above the grid.
            caption = next((flat(blocks[i - 1]["text"]) for i in inside
                            if flat(blocks[i - 1]["text"]).startswith("▶") and len(flat(blocks[i - 1]["text"])) <= 60), None)
            if caption is None and above:
                caption = flat(max(above, key=lambda b: b["y1"])["text"])
            title = caption.strip("▶◀ ").strip() if caption else None
            conn.execute("INSERT INTO source_tables VALUES(?,?,?,?,?,?)",
                         (page["pdf_page"], ordinal, json.dumps(table["bbox"]),
                          json.dumps(table["rows"], ensure_ascii=False), title, min(inside) if inside else None))


def _open(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"source_sections", "source_blocks", "source_tables"} <= tables:
        conn.close()
        raise ValueError("Source structure is absent; rebuild the index")
    return conn


def _meta(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM metadata WHERE key='source_sha256'").fetchone()
    return row[0] if row else None


_SECTION_COLUMNS = "id,title,start_pdf,end_pdf,printed_start,level,parent_id,kind"


def catalog(db_path: str | Path) -> dict[str, Any]:
    with closing(_open(db_path)) as conn:
        return {"sections": [dict(r) for r in conn.execute(f"SELECT {_SECTION_COLUMNS} FROM source_sections ORDER BY start_pdf,anchor_ordinal,id")], "source_sha256": _meta(conn)}


def _page(conn: sqlite3.Connection, pdf_page: int) -> dict[str, Any]:
    row = conn.execute("SELECT pdf_page,printed_page,header,text FROM pages WHERE pdf_page=?", (pdf_page,)).fetchone()
    if row is None:
        raise ValueError(f"PDF page {pdf_page} is missing")
    value = dict(row)
    value["source_sha256"] = _meta(conn)
    value["citation"] = f"Corebook printed p.{row['printed_page']} (PDF p.{pdf_page})" if row["printed_page"] else f"Corebook PDF p.{pdf_page}"
    value["blocks"] = [dict(r) for r in conn.execute("SELECT ordinal,x0,y0,x1,y1,text,role FROM source_blocks WHERE pdf_page=? ORDER BY ordinal", (pdf_page,))]
    value["tables"] = [{"ordinal": r[0], "bbox": json.loads(r[1]) if r[1] else None, "cells": json.loads(r[2]), "title": r[3]} for r in conn.execute("SELECT ordinal,bbox_json,cells_json,title FROM source_tables WHERE pdf_page=? ORDER BY ordinal", (pdf_page,))]
    value["sections"] = [dict(r) for r in conn.execute(f"SELECT {_SECTION_COLUMNS} FROM source_sections WHERE start_pdf<=? AND end_pdf>=? ORDER BY start_pdf", (pdf_page, pdf_page))]
    return value


def section(db_path: str | Path, section_id: str, offset: int = 0, limit: int = 8) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("offset must be nonnegative and limit must be from 1 to 12")
    with closing(_open(db_path)) as conn:
        meta = _meta(conn)
        row = conn.execute(f"SELECT {_SECTION_COLUMNS} FROM source_sections WHERE id=?", (section_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown section id: {section_id}")
        nums = list(range(row["start_pdf"], row["end_pdf"] + 1))[offset:offset + limit]
        result = [_page(conn, n) for n in nums]
        return {"section": dict(row), "pages": result, "next_offset": offset + len(result) if offset + len(result) < row["end_pdf"] - row["start_pdf"] + 1 else None, "source_sha256": meta}


def pages(db_path: str | Path, page_numbers: list[int], numbering: str = "printed") -> dict[str, Any]:
    if numbering not in {"printed", "pdf"} or not isinstance(page_numbers, list) or not 1 <= len(page_numbers) <= 12 or any(type(n) is not int or n < 1 for n in page_numbers) or len(set(page_numbers)) != len(page_numbers):
        raise ValueError("page_numbers must contain 1 to 12 unique positive integers; numbering must be printed or pdf")
    with closing(_open(db_path)) as conn:
        meta = _meta(conn)
        output = []
        for number in page_numbers:
            rows = conn.execute(f"SELECT pdf_page FROM pages WHERE {'printed_page' if numbering == 'printed' else 'pdf_page'}=?", (number,)).fetchall()
            if not rows:
                raise ValueError(f"Page {number} not found")
            if len(rows) != 1:
                raise ValueError(f"Page {number} is ambiguous")
            output.append(_page(conn, rows[0][0]))
        return {"pages": output, "source_sha256": meta}


def section_text(conn: sqlite3.Connection, section_id: str, max_chars: int = 4000) -> str:
    """Body text of one section: from its heading block to the next section's heading block."""
    row = conn.execute("SELECT start_pdf,end_pdf,anchor_ordinal,end_ordinal FROM source_sections WHERE id=?", (section_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown section id: {section_id}")
    start_pdf, end_pdf, anchor, end_ordinal = row
    parts: list[str] = []
    size = 0
    for pdf_page, ordinal, text, role in conn.execute(
            "SELECT pdf_page,ordinal,text,role FROM source_blocks WHERE pdf_page BETWEEN ? AND ? ORDER BY pdf_page,ordinal",
            (start_pdf, end_pdf)):
        if pdf_page == start_pdf and anchor is not None and ordinal <= anchor:
            continue
        if pdf_page == end_pdf and end_ordinal is not None and ordinal >= end_ordinal:
            break
        if role != "body":
            continue
        parts.append(text)
        size += len(text)
        if size >= max_chars:
            break
    return " ".join(flat(p) for p in parts)[:max_chars].strip()
