"""Opt-in invariants for an index built from a real Corebook PDF.

Runs only when REDKB_DB points at such an index. Asserts structure and counts,
never book text, so nothing from the book lives in the repository.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

DB = os.environ.get("REDKB_DB")
pytestmark = pytest.mark.skipif(not DB or not Path(DB).is_file(), reason="REDKB_DB does not point at a built rules index")

# Lower bounds for extracted (not hand-typed) entries per category.
MIN_COUNTS = {
    "skill": 66, "role": 10, "weapon": 60, "armor": 9, "cyberware": 90, "gear": 50, "program": 25,
    "hardware": 8, "fashion": 90, "drug": 10, "ammo": 13, "attachment": 8, "vehicle": 14, "service": 30,
    "housing": 14, "faction": 10, "location": 10, "rule": 400,
}


@pytest.fixture(scope="module")
def conn():
    connection = sqlite3.connect(Path(DB).resolve().as_uri() + "?mode=ro", uri=True)
    yield connection
    connection.close()


def _extracted(conn):
    # Hand-typed top-up rows carry no source reference and are not section-derived.
    return conn.execute(
        "SELECT id, name, category, description, printed_page, section_id, source_json FROM rule_entries "
        "WHERE source_json != '{}' OR section_id IS NOT NULL OR category = 'skill'").fetchall()


def test_skill_count(conn):
    assert conn.execute("SELECT COUNT(*) FROM rule_entries WHERE category='skill'").fetchone()[0] == 66


def test_minimum_extracted_counts(conn):
    counts: dict[str, int] = {}
    for row in _extracted(conn):
        counts[row[2]] = counts.get(row[2], 0) + 1
    short = {cat: (counts.get(cat, 0), need) for cat, need in MIN_COUNTS.items() if counts.get(cat, 0) < need}
    assert not short


def test_descriptions_do_not_start_with_page_furniture(conn):
    headers = {r[0].casefold() for r in conn.execute("SELECT DISTINCT text FROM source_blocks WHERE role='running_header'")}
    page_header = {p: h.casefold() for p, h in conn.execute("SELECT pdf_page, header FROM pages") if h.casefold() in headers}
    offenders = []
    for row in conn.execute("SELECT name, description, printed_page, pdf_page FROM rule_entries "
                            "WHERE source_json != '{}' OR section_id IS NOT NULL OR category = 'skill'"):
        name, description, printed, pdf_page = row
        head = description[:120].casefold()
        if printed and re.match(rf"{printed}\b", head):
            offenders.append(name)
        header = page_header.get(pdf_page)
        if header and head.startswith(header) and not name.casefold().startswith(header):
            offenders.append(name)
    assert not offenders


def test_no_placeholder_descriptions_where_a_description_column_exists(conn):
    offenders = []
    for _, name, _, description, _, _, source in _extracted(conn):
        ref = json.loads(source)
        columns = [re.sub(r"[^a-z]", "", c.casefold()) for c in ref.get("columns", [])]
        has_column = any(c.startswith("description") or c in {"data", "effect", "whatitentails"} for c in columns)
        if "priced at" in description or (has_column and not description.strip()):
            offenders.append(name)
    assert not offenders


def test_role_descriptions_are_distinct(conn):
    roles = conn.execute("SELECT name, description, stats_json FROM rule_entries WHERE category='role'").fetchall()
    assert len(roles) == 10
    assert len({r[1] for r in roles}) == 10
    for _, description, stats in roles:
        data = json.loads(stats)
        assert len(description) > 200
        assert data.get("ability") and len(data.get("stat_templates", [])) == 10
        assert data.get("starter_weapons_armor") and data.get("starter_cyberware") and data.get("streetrat_skills")


def test_passages_have_no_line_break_hyphens(conn):
    broken = [t for (t,) in conn.execute("SELECT text FROM passages") if re.search(r"\w- (?!or |and |to )\w", t)]
    assert not broken


def test_rule_tables_cover_registry_kinds(conn):
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM rule_tables")}
    assert {"ranged_weapon", "melee_weapon", "cyberware", "program", "black_ice", "stat_template", "role_skill_list",
            "role_skill_levels", "critical_injury", "hustle", "roll_table", "fashion", "housing", "lifestyle"} <= kinds
