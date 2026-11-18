"""Bounded, provenance-preserving source structure for the local rules index."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any


def _slug(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "section"


def build_structure(conn: sqlite3.Connection, pdf: Any) -> None:
    """Create source structure tables using only PDF-derived navigation evidence."""
    conn.executescript("""
        CREATE TABLE source_sections(id TEXT PRIMARY KEY,title TEXT NOT NULL,start_pdf INTEGER NOT NULL,end_pdf INTEGER NOT NULL,printed_start INTEGER);
        CREATE TABLE source_blocks(pdf_page INTEGER NOT NULL,ordinal INTEGER NOT NULL,x0 REAL,y0 REAL,x1 REAL,y1 REAL,text TEXT NOT NULL,PRIMARY KEY(pdf_page,ordinal));
        CREATE TABLE source_tables(pdf_page INTEGER NOT NULL,ordinal INTEGER NOT NULL,bbox_json TEXT,cells_json TEXT NOT NULL,PRIMARY KEY(pdf_page,ordinal));
    """)
    count = len(pdf)
    candidates: list[tuple[str, int, int | None]] = []
    toc = pdf.get_toc() or []
    if toc:
        for item in toc:
            if len(item) >= 3 and isinstance(item[0], int) and isinstance(item[1], str) and isinstance(item[2], int) and 1 <= item[2] <= count:
                candidates.append((item[1].strip(), item[2], None))
    else:
        # A conservative contents-line recognizer. Printed page resolution is
        # exclusively against the indexed running-header values.
        line_re = re.compile(r"^\s*(.{2,120}?)\s*(?:\.{2,}|…+)\s*(\d{1,4})\s*$")
        for ix in range(min(12, count)):
            text = pdf[ix].get_text("text")
            if not re.search(r"\bcontents\b|\btable\s+of\s+contents\b", text, re.I):
                continue
            for line in text.splitlines():
                match = line_re.match(line)
                if not match:
                    continue
                title, printed = match.group(1).strip(), int(match.group(2))
                rows = conn.execute("SELECT pdf_page FROM pages WHERE printed_page=?", (printed,)).fetchall()
                if len(rows) == 1:
                    candidates.append((title, int(rows[0][0]), printed))
    # Preserve input order among equal starts; discard unresolvable TOC starts.
    candidates = [(t, p, n) for t, p, n in candidates if t and 1 <= p <= count]
    candidates.sort(key=lambda x: x[1])
    used: dict[str, int] = {}
    for i, (title, start, printed) in enumerate(candidates):
        if printed is None:
            row = conn.execute("SELECT printed_page FROM pages WHERE pdf_page=?", (start,)).fetchone()
            printed = row[0] if row else None
        base = f"{_slug(title)}-{start}"
        used[base] = used.get(base, 0) + 1
        ident = base if used[base] == 1 else f"{base}-{used[base]}"
        end = candidates[i + 1][1] - 1 if i + 1 < len(candidates) and candidates[i + 1][1] > start else (candidates[i + 1][1] if i + 1 < len(candidates) else count)
        conn.execute("INSERT INTO source_sections VALUES(?,?,?,?,?)", (ident, title, start, max(start, end), printed))
    from layout import extract_tables
    for ix, page in enumerate(pdf, 1):
        for ordinal, block in enumerate(page.get_text("blocks"), 1):
            if len(block) >= 5 and (len(block) < 7 or block[6] == 0) and isinstance(block[4], str) and block[4].strip():
                conn.execute("INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?)", (ix, ordinal, *[float(x) for x in block[:4]], block[4]))
        try:
            tables = extract_tables(page)
        except (AttributeError, TypeError, ValueError):
            tables = []
        for ordinal, table in enumerate(tables, 1):
            conn.execute("INSERT INTO source_tables VALUES(?,?,?,?)", (ix, ordinal, json.dumps(table.get("bbox")), json.dumps(table.get("rows"), ensure_ascii=False)))


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


def catalog(db_path: str | Path) -> dict[str, Any]:
    with closing(_open(db_path)) as conn:
        return {"sections": [dict(r) for r in conn.execute("SELECT id,title,start_pdf,end_pdf,printed_start FROM source_sections ORDER BY start_pdf,id")], "source_sha256": _meta(conn)}


def _page(conn: sqlite3.Connection, pdf_page: int) -> dict[str, Any]:
    row = conn.execute("SELECT pdf_page,printed_page,header,text FROM pages WHERE pdf_page=?", (pdf_page,)).fetchone()
    if row is None:
        raise ValueError(f"PDF page {pdf_page} is missing")
    value = dict(row)
    value["source_sha256"] = _meta(conn)
    value["citation"] = f"Corebook printed p.{row['printed_page']} (PDF p.{pdf_page})" if row["printed_page"] else f"Corebook PDF p.{pdf_page}"
    value["blocks"] = [dict(r) for r in conn.execute("SELECT ordinal,x0,y0,x1,y1,text FROM source_blocks WHERE pdf_page=? ORDER BY ordinal", (pdf_page,))]
    value["tables"] = [{"ordinal": r[0], "bbox": json.loads(r[1]) if r[1] else None, "cells": json.loads(r[2])} for r in conn.execute("SELECT ordinal,bbox_json,cells_json FROM source_tables WHERE pdf_page=? ORDER BY ordinal", (pdf_page,))]
    value["sections"] = [dict(r) for r in conn.execute("SELECT id,title,start_pdf,end_pdf,printed_start FROM source_sections WHERE start_pdf<=? AND end_pdf>=? ORDER BY start_pdf", (pdf_page,pdf_page))]
    return value


def section(db_path: str | Path, section_id: str, offset: int = 0, limit: int = 8) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("offset must be nonnegative and limit must be from 1 to 12")
    with closing(_open(db_path)) as conn:
        meta = _meta(conn)
        row = conn.execute("SELECT * FROM source_sections WHERE id=?", (section_id,)).fetchone()
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
