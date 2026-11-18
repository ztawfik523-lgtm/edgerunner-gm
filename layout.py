"""Conservative extraction of structured tables from PyMuPDF pages."""
from __future__ import annotations

import re
from typing import Any


def _normalize_cell(value: Any) -> str:
    """Normalize spacing without adding content to a source cell."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def extract_tables(page: Any) -> list[dict[str, Any]]:
    """Return plausible line-detected tables, omitting likely false positives.

    Cell strings and empty cells are retained as extracted. This intentionally
    does not attempt to infer merged-cell values or table headers.
    """
    found = page.find_tables(strategy="lines")
    result: list[dict[str, Any]] = []
    for table in found.tables:
        rows = [[_normalize_cell(cell) for cell in row] for row in table.extract()]
        # Some detected grids enclose an entire duplicated page/table as one
        # giant spanning row. Omit that row, not the useful cell rows below it.
        rows = [row for row in rows if not any(len(cell) > 600 for cell in row)]
        if len(rows) < 2:
            continue
        columns = max((len(row) for row in rows), default=0)
        if columns < 2:
            continue
        populated_rows = sum(sum(bool(cell) for cell in row) >= 2 for row in rows)
        if populated_rows < 2:
            continue
        result.append({"bbox": table.bbox, "rows": rows})
    return result


def table_text(tables: list[dict[str, Any]]) -> str:
    """Serialize extracted tables with explicit numbering and cell boundaries."""
    sections = []
    for index, table in enumerate(tables, start=1):
        lines = [f"Table {index}:"]
        lines.extend(" | ".join(row) for row in table["rows"])
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
