import sqlite3

import pytest

from sourcecatalog import lookup_skill, skills
from sourcecatalog import items, package


def make_index(path, pages, digest="a" * 64):
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);")
        db.execute("INSERT INTO metadata VALUES('source_sha256',?)", (digest,))
        db.executemany("INSERT INTO pages VALUES(?,?,?)", pages)


def test_extracts_skill_headers_and_excludes_other_pages(tmp_path):
    db = tmp_path / "rules.sqlite"
    make_index(db, [
        (83, 82, "Drive Land Vehicle. ................................REF\nPilot Air Vehicle (x2)...............................REF\nStreetwise. ........................................ COOL\nNot a skill...........................................Nope"),
        (90, 89, "Unrelated...........................................INT"),
    ])
    catalog = skills(db)
    assert list(catalog) == ["Drive Land Vehicle", "Pilot Air Vehicle", "Streetwise"]
    assert catalog["Drive Land Vehicle"] == {
        "stat": "REF", "cost": 1, "source_sha256": "a" * 64,
        "pdf_page": 83, "printed_page": 82,
    }
    assert catalog["Pilot Air Vehicle"]["cost"] == 2


def test_lookup_specializations_and_normalization(tmp_path):
    db = tmp_path / "rules.sqlite"
    make_index(db, [(83, 82, "Electronics/Security Tech (x2).............TECH\nLanguage........................................INT\nScience..........................................INT")])
    catalog = skills(db)
    assert lookup_skill(catalog, "electronics / security tech (choose 1)")["cost"] == 2
    assert lookup_skill(catalog, "Language (Streetslang)") == catalog["Language"]
    assert lookup_skill(catalog, "Science ()") is None
    assert lookup_skill(catalog, "Invented (specialization)") is None


def test_conflicting_definitions_fail_and_database_is_read_only(tmp_path):
    db = tmp_path / "rules.sqlite"
    make_index(db, [(83, 82, "Athletics.................................DEX"), (84, 83, "Athletics.................................REF")])
    with pytest.raises(ValueError, match="Conflicting"):
        skills(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2


def test_missing_source_metadata_or_catalog_is_rejected(tmp_path):
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);")
    with pytest.raises(ValueError, match="source_sha256"):
        skills(db)


def make_item_index(path, pages, tables, digest="b" * 64):
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);")
        db.execute("INSERT INTO metadata VALUES('source_sha256',?)", (digest,))
        db.executemany("INSERT INTO pages VALUES(?,?,?)", pages)
        db.execute("CREATE TABLE source_tables(pdf_page INTEGER,ordinal INTEGER,bbox_json TEXT,cells_json TEXT)")
        import json
        db.executemany("INSERT INTO source_tables VALUES(?,?,NULL,?)",
                       [(page, n, json.dumps(rows)) for page, n, rows in tables])


def test_items_prices_categories_variants_and_raw_cells(tmp_path):
    db = tmp_path / "items.sqlite"
    make_item_index(db, [(200, 199, "")], [
        (200, 1, [["Name", "WeaponType", "Cost"], ["Test Rifle", "Rifle", "1,000eb (V. Expensive)"]]),
        (200, 2, [["Name", "WeaponType", "Cost"], ["Test Rifle", "Rifle", "500eb (Expensive)"]]),
        (200, 3, [["Name", "WeaponType", "Cost"], ["Ambiguous", "Rifle", "100eb or 200eb"]]),
        (200, 4, [["Name", "WeaponType", "Cost"], ["Range", "Rifle", "100-200eb"]]),
    ])
    catalog = items(db)
    assert len(catalog) == 2
    first = next(value for value in catalog.values() if value["cost"] == 1000)
    assert first["category"] == "weapon"
    assert first["cells"] == ["Test Rifle", "Rifle", "1,000eb (V. Expensive)"]
    assert first["columns"] == ["Name", "WeaponType", "Cost"]
    assert first["verification"] == "extracted_requires_layout_verification"
    assert "variants" in first


def test_items_supplemental_rows_and_package_role_evidence(tmp_path):
    db = tmp_path / "packages.sqlite"
    make_item_index(db, [
        (99, 98, "Weapons and Armor\nRockerboy | Weapons | Armor\nRockerboy | Pistol | Light Armor"),
        (104, 103, "Outfit\nRockerboy | Nomad style"),
        (118, 117, "Cyberware\nRockerboy | Neural Link"),
        (150, 149, "Table 1:\nName | Cost\nFallback Item | 250eb"),
    ], [])
    assert next(iter(items(db).values()))["name"] == "Fallback Item"
    result = package(db, "Rockerboy", "outfit")
    assert len(result["sections"]) == 1
    assert result["sections"][0]["printed_page"] == 103
    assert "Rockerboy | Nomad style" in result["sections"][0]["extracted_tokens"]
    assert package(db, "Solo", "outfit")["sections"] == []


def test_items_and_package_require_source_hash_and_validate_package_kind(tmp_path):
    db = tmp_path / "missing.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);")
    with pytest.raises(ValueError, match="source_sha256"):
        items(db)
    with pytest.raises(ValueError, match="kind"):
        package(db, "Solo", "unknown")
