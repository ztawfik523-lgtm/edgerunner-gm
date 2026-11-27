"""Bounded query expansion for vehicle collision terminology."""
from pathlib import Path
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redkb
from tests.rules_fixture import pdf_page


def test_vehicle_collision_query_expands_for_ramming_passage(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    with fitz.open() as book:
        pdf_page(book, 192, "VEHICLE COMBAT", "Ramming a vehicle causes a crash. Resolve impact damage with 6d6.")
        book.save(pdf)
    db = tmp_path / "rules.sqlite"
    redkb.build_index(pdf, db)

    results = redkb.search_pages(db, "roll for vehicle combat collision", lexical_only=True)
    assert results
    assert results[0]["printed_page"] == 192
    assert results[0]["retrieval_method"] == "passage_bm25+expanded"


def test_unrelated_crash_query_is_not_expanded(tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    with fitz.open() as book:
        pdf_page(book, 192, "VEHICLE COMBAT", "Ramming a vehicle causes a crash.")
        pdf_page(book, 193, "SOFTWARE", "The application crash reports an error.")
        book.save(pdf)
    db = tmp_path / "rules.sqlite"
    redkb.build_index(pdf, db)

    assert redkb._expanded_vehicle_query("software crash") is None
    results = redkb.search_pages(db, "software crash", lexical_only=True)
    assert results[0]["printed_page"] == 193
    assert all("+expanded" not in row["retrieval_method"] for row in results)
    assert results[0]["retrieval_method"] == "passage_bm25"
