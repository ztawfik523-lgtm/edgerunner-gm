import sqlite3

import pytest

import knowledge


class Page:
    def __init__(self, text="", blocks=(), tables=()):
        self.text, self.blocks, self.tables = text, blocks, tables

    def get_text(self, mode="text"):
        return self.blocks if mode == "blocks" else self.text

    def find_tables(self, strategy="lines"):
        return type("Found", (), {"tables": self.tables})()


class Table:
    bbox = (1, 2, 30, 40)

    def extract(self):
        return [["Alpha", "Beta"], ["1", "2"]]


class PDF(list):
    def __init__(self, pages, toc=()):
        super().__init__(pages)
        self.toc = toc

    def get_toc(self):
        return self.toc


def make_db(tmp_path, printed=(None, 10, 11, 12)):
    path = tmp_path / "index.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,header TEXT,text TEXT)")
    conn.execute("CREATE TABLE metadata(key TEXT,value TEXT)")
    conn.execute("INSERT INTO metadata VALUES('source_sha256','abc123')")
    for ix, number in enumerate(printed, 1):
        conn.execute("INSERT INTO pages VALUES(?,?,?,?)", (ix, number, "Header", f"Page {ix}"))
    return path, conn


def test_toc_sections_preserve_structured_source_and_pagination(tmp_path):
    path, conn = make_db(tmp_path)
    pdf = PDF([Page(blocks=[(1, 2, 3, 4, "block text", 0, 0)]), Page(tables=[Table()]), Page(), Page()],
              [[1, "First Section", 2], [1, "Last Section", 4]])
    knowledge.build_structure(conn, pdf)
    conn.commit()
    conn.close()
    catalog = knowledge.catalog(path)
    assert [s["start_pdf"] for s in catalog["sections"]] == [2, 4]
    assert catalog["source_sha256"] == "abc123"
    result = knowledge.section(path, catalog["sections"][0]["id"], limit=1)
    assert result["pages"][0]["citation"] == "Corebook printed p.10 (PDF p.2)"
    assert result["next_offset"] == 1
    assert result["pages"][0]["tables"][0]["bbox"] == [1, 2, 30, 40]
    assert result["pages"][0]["tables"][0]["cells"] == [["Alpha", "Beta"], ["1", "2"]]
    assert knowledge.pages(path, [10])["pages"][0]["pdf_page"] == 2
    with pytest.raises(ValueError, match="ambiguous"):
        knowledge.pages(path, [10, 99])


def test_contents_resolves_only_explicit_printed_page_values(tmp_path):
    path, conn = make_db(tmp_path, (None, 30, 31, None))
    pdf = PDF([Page("Contents\nKnown .... 30\nUnmarked .... 40"), Page(), Page(), Page()])
    knowledge.build_structure(conn, pdf)
    conn.commit()
    conn.close()
    sections = knowledge.catalog(path)["sections"]
    assert [(s["title"], s["start_pdf"], s["printed_start"]) for s in sections] == [("Known", 2, 30)]


def test_absent_structure_validation_and_unknown_section(tmp_path):
    path, conn = make_db(tmp_path)
    conn.close()
    with pytest.raises(ValueError, match="rebuild"):
        knowledge.catalog(path)
    conn = sqlite3.connect(path)
    knowledge.build_structure(conn, PDF([Page()]))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="Unknown section"):
        knowledge.section(path, "not-a-section")
    with pytest.raises(ValueError, match="limit"):
        knowledge.section(path, "missing", limit=13)
