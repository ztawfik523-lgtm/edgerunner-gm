"""Regression tests; a tiny synthetic book means no copyrighted PDF in Git."""
import json
from pathlib import Path

import fitz
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redkb


@pytest.fixture()
def fixture_db(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    book = fitz.open()
    for n, content in [
        (129, "Skill Check Resolution: STAT + Skill + 1d10 beats the DV."),
        (130, "Critical Success: when you roll a natural 10, roll another 1d10 and add it. Critical Failure: on a natural 1, subtract another 1d10."),
        (131, "Awareness Skills: Concentration and Perception."),
    ]:
        page = book.new_page()
        page.insert_text((50, 60), f"{n}\nGETTING IT DONE\n{content}", fontsize=10)
    book.save(pdf)
    book.close()
    db = tmp_path / "rules.sqlite"
    stats = redkb.build_index(pdf, db)
    assert stats["indexed_pages"] == 3
    assert stats["fts_rows"] == 3
    return db


def test_page_lookup(fixture_db):
    page = redkb.read_page(fixture_db, 130)
    assert page["pdf_page"] == 2
    assert "Critical Success" in page["text"]
    assert redkb.read_page(fixture_db, 2, "pdf")["printed_page"] == 130
    assert redkb.read_page(fixture_db, 140) is None


def test_keyword_retrieval(fixture_db):
    hits = redkb.search_pages(fixture_db, "Critical Success Critical Failure natural 10")
    assert hits[0]["printed_page"] == 130
    assert "printed p.130" in hits[0]["citation"]


def test_explicit_page_routing(fixture_db):
    printed = redkb.search_pages(fixture_db, "Read printed page 130 and tell me the critical failures")[0]
    assert printed["printed_page"] == 130
    assert printed["pdf_page"] == 2
    assert printed["citation"] == "Corebook printed p.130 (PDF p.2)"
    assert "Critical Failure" in printed["text"]
    assert "Critical Failure" in printed["excerpt"]

    pdf = redkb.search_pages(fixture_db, "open PDF page 2")[0]
    assert pdf["pdf_page"] == 2
    assert pdf["printed_page"] == 130
    assert pdf["citation"] == "Corebook printed p.130 (PDF p.2)"
    assert "Critical Success" in pdf["text"]
    assert redkb.search_pages(fixture_db, "PDF p. 2")[0]["pdf_page"] == 2

    assert redkb.search_pages(fixture_db, "PDF page 130") == []
    assert redkb.search_pages(fixture_db, "printed page 2") == []
    assert redkb.search_pages(fixture_db, "page 1000 critical success") == []
    assert redkb.search_pages(fixture_db, "page 0 critical success") == []
    assert "1" in redkb._terms("natural 1")


def test_phrase_lookup(fixture_db):
    assert redkb.find_phrase(fixture_db, "Critical Success")[0]["printed_page"] == 130
    assert redkb.find_phrase(fixture_db, "imaginary passage") == []


def test_clean_rebuild_is_atomic(fixture_db, tmp_path):
    prior = redkb.inspect_index(fixture_db)["source_sha256"]
    with pytest.raises(FileNotFoundError):
        redkb.build_index(tmp_path / "missing.pdf", fixture_db)
    assert redkb.inspect_index(fixture_db)["source_sha256"] == prior


def test_golden_evaluator(fixture_db, tmp_path):
    cases = tmp_path / "golden.json"
    cases.write_text(json.dumps([{"query": "critical success natural 10", "expected_printed_pages": [130], "top_k": 2}]))
    assert redkb.evaluate(fixture_db, cases)["passed"] == 1


def test_no_page_number_invented():
    assert redkb.get_printed_page("GETTING IT DONE\nText") is None
    assert redkb.get_printed_page("130\nGETTING IT DONE\nText") == 130
    assert redkb.get_printed_page("BY NEIL BRANQUINHO\n189\nFRIDAY NIGHT FIREFIGHT") == 189


def test_api_cors_is_opt_in(fixture_db):
    import asyncio

    async def request(app, origin):
        messages = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": "/health", "raw_path": b"/health",
                 "query_string": b"", "headers": [(b"origin", origin.encode())],
                 "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1), "root_path": ""}
        await app(scope, receive, send)
        return dict(messages[0]["headers"])

    origin = "http://127.0.0.1:8000"
    assert b"access-control-allow-origin" not in asyncio.run(request(redkb.make_api(fixture_db), origin))
    app = redkb.make_api(fixture_db, (origin,))
    assert asyncio.run(request(app, origin))[b"access-control-allow-origin"] == origin.encode()
    assert b"access-control-allow-origin" not in asyncio.run(request(app, "https://example.com"))
