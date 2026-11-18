import json
import sqlite3

from gear import apply_action


def rules_db(path):
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT); CREATE TABLE source_tables(pdf_page INTEGER,ordinal INTEGER,bbox_json TEXT,cells_json TEXT);")
        db.execute("INSERT INTO metadata VALUES('source_sha256',?)", ('c' * 64,))
        db.execute("INSERT INTO pages VALUES(200,199,'')")
        rows = [
            [["Name", "WeaponType", "Cost"], ["Medium Pistol", "Medium Pistol", "50eb"]],
            [["Name", "ArmorType", "Cost", "SP", "ArmorPenalty"], ["Test Armor", "Armorjack", "100eb", "11", "2"]],
            [["Name", "Cost"], ["Consumable", "20eb"]],
        ]
        db.executemany("INSERT INTO source_tables VALUES(?,?,NULL,?)",
                       [(200, i, json.dumps(table)) for i, table in enumerate(rows, 1)])


def test_canonical_purchase_price_and_deep_copy(tmp_path):
    path = tmp_path / "rules.sqlite"
    rules_db(path)
    from sourcecatalog import items
    item_id = next(k for k, v in items(path).items() if v["name"] == "Medium Pistol")
    original = {"money": 100, "inventory": {}}
    out = apply_action(original, "buy", {"item_id": item_id, "quantity": 1, "price": 1}, path, lambda n: 0)
    assert out["character"]["money"] == 50
    assert out["character"]["inventory"][item_id] == 1
    assert original == {"money": 100, "inventory": {}}


def test_owned_weapon_and_armor_equipment(tmp_path):
    path = tmp_path / "rules.sqlite"
    rules_db(path)
    from sourcecatalog import items
    catalog = items(path)
    weapon = next(k for k, v in catalog.items() if v["name"] == "Medium Pistol")
    armor = next(k for k, v in catalog.items() if v["name"] == "Test Armor")
    ch = {"inventory": {weapon: 1, armor: 1}}
    equipped = apply_action(ch, "equip_weapon", {"item_id": weapon}, path, lambda n: 0)["character"]
    assert equipped["detail"]["equipment"]["weapons"][0]["type"] == "Medium Pistol"
    armored = apply_action(ch, "equip_armor", {"item_id": armor, "location": "body"}, path, lambda n: 0)["character"]
    assert armored["detail"]["equipment"]["armor"][0]["sp"] == 11


def test_rejects_unowned_or_arbitrary_catalog_data(tmp_path):
    path = tmp_path / "rules.sqlite"
    rules_db(path)
    from sourcecatalog import items
    item_id = next(iter(items(path)))
    import pytest
    with pytest.raises(ValueError, match="owned"):
        apply_action({}, "equip_weapon", {"item_id": item_id}, path, lambda n: 0)
    with pytest.raises(ValueError, match="exact source-catalog"):
        apply_action({}, "buy", {"item_id": "invented", "price": 0}, path, lambda n: 0)
