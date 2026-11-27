import sqlite3

import pytest

import knowledge
from tests import rules_fixture as rf


def _book(tmp_path):
    pages = [
        rf.page(1, None, [rf.heading("First Section", 100), rf.block("Opening text of the first section.", 130)]),
        # The outline points one page early; the heading block decides where the section starts.
        rf.page(2, 10, [rf.block("More of the first section.", 100),
                        rf.heading("Second Section", 300), rf.block("Second section body.", 330),
                        rf.table([["Alpha", "Beta"], ["1", "2"]], 400)]),
        rf.page(3, 11, [rf.block("Second section continues.", 100)]),
        rf.page(4, 12, [rf.heading("Last Section", 100), rf.block("Final words.", 130)]),
    ]
    toc = [[1, "First Section", 1], [1, "Second Section", 1], [1, "Last Section", 4]]
    return rf.build(tmp_path / "index.sqlite", pages, toc, digest="abc123")


def test_toc_sections_anchor_to_heading_blocks_and_paginate(tmp_path):
    path = _book(tmp_path)
    catalog = knowledge.catalog(path)
    assert [(s["title"], s["start_pdf"]) for s in catalog["sections"]] == [
        ("First Section", 1), ("Second Section", 2), ("Last Section", 4)]
    assert catalog["source_sha256"] == "abc123"
    second = catalog["sections"][1]
    with sqlite3.connect(path) as conn:
        assert knowledge.section_text(conn, second["id"]) == "Second section body. Second section continues."
        assert knowledge.section_text(conn, catalog["sections"][0]["id"]) == (
            "Opening text of the first section. More of the first section.")
    result = knowledge.section(path, second["id"], limit=1)
    assert result["pages"][0]["citation"] == "Corebook printed p.10 (PDF p.2)"
    assert result["next_offset"] == 1
    assert result["pages"][0]["tables"][0]["cells"] == [["Alpha", "Beta"], ["1", "2"]]
    assert knowledge.pages(path, [10])["pages"][0]["pdf_page"] == 2
    with pytest.raises(ValueError, match="Page 99 not found"):
        knowledge.pages(path, [10, 99])


def test_absent_structure_validation_and_unknown_section(tmp_path):
    path = tmp_path / "bare.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE metadata(key TEXT,value TEXT)")
    with pytest.raises(ValueError, match="rebuild"):
        knowledge.catalog(path)
    path = _book(tmp_path)
    with pytest.raises(ValueError, match="Unknown section"):
        knowledge.section(path, "not-a-section")
    with pytest.raises(ValueError, match="limit"):
        knowledge.section(path, "missing", limit=13)
