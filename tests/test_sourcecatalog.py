import sqlite3

import pytest

from sourcecatalog import items, lookup_skill, skills
from tests import rules_fixture as rf


def _skill_page(pdf_page, printed, lines):
    return rf.page(pdf_page, printed, [rf.block(line, 74 + 30 * i) for i, line in enumerate(lines)])


def test_extracts_skill_headers_and_excludes_other_pages(tmp_path):
    db = rf.build(tmp_path / "rules.sqlite", [
        _skill_page(83, 82, ["Drive Land Vehicle. ................................REF", "Skill of driving.",
                             "Pilot Air Vehicle (x2)...............................REF",
                             "Streetwise. ........................................ COOL",
                             "Not a skill...........................................Nope"]),
        _skill_page(90, 89, ["Unrelated...........................................INT"]),
    ], digest="a" * 64)
    catalog = skills(db)
    assert list(catalog) == ["Drive Land Vehicle", "Pilot Air Vehicle", "Streetwise"]
    assert catalog["Drive Land Vehicle"] == {
        "stat": "REF", "cost": 1, "source_sha256": "a" * 64,
        "pdf_page": 83, "printed_page": 82,
    }
    assert catalog["Pilot Air Vehicle"]["cost"] == 2


def test_lookup_specializations_and_normalization(tmp_path):
    db = rf.build(tmp_path / "rules.sqlite", [_skill_page(83, 82, [
        "Electronics/Security Tech (x2).............TECH",
        "Language........................................INT",
        "Science..........................................INT"])])
    catalog = skills(db)
    assert lookup_skill(catalog, "electronics / security tech (choose 1)")["cost"] == 2
    assert lookup_skill(catalog, "Language (Streetslang)") == catalog["Language"]
    assert lookup_skill(catalog, "Science ()") is None
    assert lookup_skill(catalog, "Invented (specialization)") is None


def test_conflicting_definitions_fail_the_build(tmp_path):
    with pytest.raises(ValueError, match="Conflicting"):
        rf.build(tmp_path / "rules.sqlite", [_skill_page(83, 82, [
            "Athletics.................................DEX",
            "Athletics.................................REF",
            "Stealth...................................DEX"])])


def test_unbuilt_catalog_is_rejected(tmp_path):
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);")
    with pytest.raises(ValueError, match="rebuild"):
        skills(db)


def test_items_prices_categories_and_source_cells(tmp_path):
    db = rf.build(tmp_path / "items.sqlite", [rf.page(200, 199, [
        rf.table([rf.RANGED_HEADER,
                  ["Test Rifle", "Shoulder Arms", "5d6", "25 (Rifle)", "1", "2", "NO", "1,000eb (V. Expensive)"]], 80),
        rf.table([rf.GEAR_HEADER, ["Test Kit", "Assorted tools.", "Premium (100eb)"]], 300),
    ])], digest="b" * 64)
    catalog = items(db)
    rifle = next(value for value in catalog.values() if value["name"] == "Test Rifle")
    assert rifle["cost"] == 1000 and rifle["category"] == "weapon"
    assert rifle["stats"]["price_category"] == "Very Expensive"
    assert rifle["stats"]["magazine"] == 25 and rifle["stats"]["concealable"] is False
    assert rifle["columns"] == rf.RANGED_HEADER
    kit = next(value for value in catalog.values() if value["name"] == "Test Kit")
    assert kit["cost"] == 100 and kit["description"] == "Assorted tools."
