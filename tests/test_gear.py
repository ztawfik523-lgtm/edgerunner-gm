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


def _extended_rules_db(path):
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE metadata(key TEXT,value TEXT);"
            "CREATE TABLE pages(pdf_page INTEGER,printed_page INTEGER,text TEXT);"
            "CREATE TABLE source_tables(pdf_page INTEGER,ordinal INTEGER,bbox_json TEXT,cells_json TEXT);"
        )
        db.execute("INSERT INTO metadata VALUES('source_sha256',?)", ("d" * 64,))
        db.execute("INSERT INTO pages VALUES(350,350,'')")
        tables = [
            [["Name", "WeaponType", "Cost"], ["Heavy Pistol", "Heavy Pistol", "100eb"]],
            [
                ["Armor Type", "Stopping Power (SP)", "Armor Penalty (Minimum 0)", "Cost"],
                ["Leathers", "4", "None", "20eb"],
                ["Kevlar", "7 SP", "-", "50eb"],
                ["Light Armorjack", "11", "0", "100eb"],
                ["Bodyweight Suit", "11", "None", "1000eb"],
                ["Medium Armorjack", "12", "-2 REF, DEX, and MOVE", "100eb"],
                ["Heavy Armorjack", "13", "-2", "500eb"],
                ["Flak", "15", "-4 REF, DEX, and MOVE", "500eb"],
                ["Metalgear", "18", "-4 REF, DEX, and MOVE", "5000eb"],
                ["Bulletproof Shield", "10 HP shield", "Requires 1 arm", "100eb"],
            ],
            [
                ["Name", "Slots", "Cost", "Description"],
                ["Cyberdeck (Poor Quality)", "5", "100eb", "5-slot entry deck"],
                ["Cyberdeck (Standard Quality)", "", "500eb", "Standard cyberdeck"],
                ["Cyberdeck (Excellent Quality)", "9 Slots", "1000eb", "High-end 9-slot deck"],
                ["Cyberdeck", "", "500eb", "Default slot cyberdeck"],
            ],
            [
                ["Name", "Class", "REZ", "Cost"],
                ["Eraser", "Booster", "7", "20eb"],
                ["Speedygonzalez", "Booster", "7", "100eb"],
                ["Armor", "Defender", "7", "50eb"],
                ["Hellhound", "Black ICE", "20", "500eb"],
            ],
            [
                ["Name", "Slots", "Cost"],
                ["Backup Drive (Cyberdeck · 2 Slots)", "2", "100eb"],
                ["Range Upgrade (Cyberdeck · 1 Slot)", "1", "100eb"],
                ["KRASH Barrier", "2", "100eb"],
            ],
            [["Name", "Cost"], ["Kibble", "10eb"]],
        ]
        db.executemany(
            "INSERT INTO source_tables VALUES(?,?,NULL,?)",
            [(350, i, json.dumps(table)) for i, table in enumerate(tables, 1)],
        )


def test_equip_armor_corebook_headers_penalties_and_monotonic_index(tmp_path):
    path = tmp_path / "rules.sqlite"
    _extended_rules_db(path)
    from sourcecatalog import items

    catalog = items(path)
    by_name = {v["name"]: k for k, v in catalog.items()}
    inv = {by_name[name]: 1 for name in (
        "Leathers", "Kevlar", "Light Armorjack", "Bodyweight Suit",
        "Medium Armorjack", "Heavy Armorjack", "Flak", "Metalgear", "Bulletproof Shield",
    )}
    ch = {"money": 0, "inventory": inv, "detail": {"next_armor_index": 3}}

    expected = [
        ("Leathers", 4, 0),
        ("Kevlar", 7, 0),
        ("Light Armorjack", 11, 0),
        ("Medium Armorjack", 12, 2),
        ("Heavy Armorjack", 13, 2),
        ("Flak", 15, 4),
        ("Metalgear", 18, 4),
        ("Bulletproof Shield", 0, 0),
    ]
    for offset, (name, exp_sp, exp_pen) in enumerate(expected):
        out = apply_action(ch, "equip_armor", {"item_id": by_name[name], "location": "body"}, path, lambda n: 0)
        eq = out["result"]["equipped"]
        assert eq["id"] == f"armor-{3 + offset}"
        assert eq["item_id"] == by_name[name]
        assert eq["sp"] == exp_sp
        assert eq["penalty"] == exp_pen
        ch = out["character"]

    assert ch["detail"]["next_armor_index"] == 3 + len(expected)
    assert ch["detail"]["equipped_armor"] == {"name": "Metalgear", "sp": 18, "penalty": 4}

    # Bodyweight suit (1 copy) can equip both body and head, then rejects duplicate body
    bw_id = by_name["Bodyweight Suit"]
    ch = apply_action(ch, "equip_armor", {"item_id": bw_id, "location": "body"}, path, lambda n: 0)["character"]
    ch = apply_action(ch, "equip_armor", {"item_id": bw_id, "location": "head"}, path, lambda n: 0)["character"]
    assert ch["detail"]["equipped_head_armor"] == {"name": "Bodyweight Suit", "sp": 11, "penalty": 0}
    import pytest
    with pytest.raises(ValueError, match="more copies"):
        apply_action(ch, "equip_armor", {"item_id": bw_id, "location": "body"}, path, lambda n: 0)


def test_ownership_caps_and_sell_consume_equipped_protection(tmp_path):
    path = tmp_path / "rules.sqlite"
    _extended_rules_db(path)
    from sourcecatalog import items
    import pytest

    catalog = items(path)
    by_name = {v["name"]: k for k, v in catalog.items()}
    pistol = by_name["Heavy Pistol"]
    armor = by_name["Light Armorjack"]

    ch = {"money": 0, "inventory": {pistol: 2, armor: 1, "ammo: m pistol": "12"}}
    out = apply_action(ch, "equip_weapon", {"item_id": pistol}, path, lambda n: 0)
    ch = out["character"]
    assert ch["detail"]["equipment"]["weapons"][0]["item_id"] == pistol
    assert ch["detail"]["equipped_weapon"] == "Heavy Pistol"
    assert ch["inventory"]["ammo:M Pistol"] == 12

    # Sell 1 unequipped spare pistol succeeds; selling last equipped pistol fails
    ch = apply_action(ch, "sell", {"item_id": pistol, "quantity": 1}, path, lambda n: 0)["character"]
    assert ch["money"] == 100
    with pytest.raises(ValueError, match="cannot equip more copies"):
        apply_action(ch, "equip_weapon", {"item_id": pistol}, path, lambda n: 0)
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "sell", {"item_id": pistol, "quantity": 1}, path, lambda n: 0)
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "consume", {"item_id": pistol, "quantity": 1}, path, lambda n: 0)

    # Equipped armor cannot be sold
    ch = apply_action(ch, "equip_armor", {"item_id": armor, "location": "body"}, path, lambda n: 0)["character"]
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "sell", {"item_id": armor, "quantity": 1}, path, lambda n: 0)


def test_equip_deck_install_program_and_install_hardware(tmp_path):
    path = tmp_path / "rules.sqlite"
    _extended_rules_db(path)
    from sourcecatalog import items
    import pytest

    catalog = items(path)
    by_name = {v["name"]: k for k, v in catalog.items()}

    poor_deck = by_name["Cyberdeck (Poor Quality)"]
    std_deck = by_name["Cyberdeck (Standard Quality)"]
    exc_deck = by_name["Cyberdeck (Excellent Quality)"]
    default_deck = by_name["Cyberdeck"]
    eraser = by_name["Eraser"]
    speedy = by_name["Speedygonzalez"]
    hellhound = by_name["Hellhound"]
    backup = by_name["Backup Drive (Cyberdeck · 2 Slots)"]
    krash = by_name["KRASH Barrier"]
    kibble = by_name["Kibble"]

    ch = {
        "money": 0,
        "inventory": {
            poor_deck: 1, std_deck: 1, exc_deck: 1, default_deck: 1,
            eraser: 1, speedy: 1, hellhound: 1, backup: 1, krash: 1, kibble: 1,
        },
    }

    # Installing program/hardware without a deck fails
    with pytest.raises(ValueError, match="no cyberdeck"):
        apply_action(ch, "install_program", {"item_id": eraser}, path, lambda n: 0)
    with pytest.raises(ValueError, match="no cyberdeck"):
        apply_action(ch, "install_hardware", {"item_id": krash}, path, lambda n: 0)

    # Non-deck/program/hardware returns requires_human_ruling
    assert apply_action(ch, "equip_deck", {"item_id": kibble}, path, lambda n: 0)["result"]["requires_human_ruling"] is True
    assert apply_action(ch, "install_program", {"item_id": kibble}, path, lambda n: 0)["result"]["requires_human_ruling"] is True
    assert apply_action(ch, "install_hardware", {"item_id": kibble}, path, lambda n: 0)["result"]["requires_human_ruling"] is True

    # Slot detection across deck tiers
    assert apply_action(ch, "equip_deck", {"item_id": exc_deck}, path, lambda n: 0)["result"]["equipped_deck"]["slots"] == 9
    assert apply_action(ch, "equip_deck", {"item_id": std_deck}, path, lambda n: 0)["result"]["equipped_deck"]["slots"] == 7
    assert apply_action(ch, "equip_deck", {"item_id": default_deck}, path, lambda n: 0)["result"]["equipped_deck"]["slots"] == 7
    poor_out = apply_action(ch, "equip_deck", {"item_id": poor_deck}, path, lambda n: 0)
    ch = poor_out["character"]
    assert ch["detail"]["deck"] == {
        "item_id": poor_deck,
        "name": "Cyberdeck (Poor Quality)",
        "slots": 5,
        "capacity": 5,
        "programs": [],
        "hardware": [],
    }

    # Cannot sell equipped cyberdeck or re-equip same single copy
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "sell", {"item_id": poor_deck, "quantity": 1}, path, lambda n: 0)
    with pytest.raises(ValueError, match="more copies"):
        apply_action(ch, "equip_deck", {"item_id": poor_deck}, path, lambda n: 0)

    # Install 1-slot program, alias program, 2-slot Black ICE, and 2-slot hardware into 5-slot deck
    p1 = apply_action(ch, "install_program", {"item_id": eraser}, path, lambda n: 0)
    assert p1["result"]["installed_program"] == {
        "id": "prog-0", "item_id": eraser, "name": "Eraser",
        "rez": 7, "max_rez": 7, "slots": 1, "active": False,
    }
    ch = p1["character"]

    p2 = apply_action(ch, "install_program", {"item_id": speedy}, path, lambda n: 0)
    assert p2["result"]["installed_program"]["name"] == "Speedy Gonzalvez"
    assert p2["result"]["installed_program"]["slots"] == 1
    ch = p2["character"]

    h1 = apply_action(ch, "install_hardware", {"item_id": backup}, path, lambda n: 0)
    assert h1["result"]["installed_hardware"] == {
        "id": "hw-0", "item_id": backup, "name": "Backup Drive", "slots": 2,
    }
    ch = h1["character"]

    # 4/5 slots used -> Black ICE (2 slots) and 2-slot hardware (2 slots) overflow
    with pytest.raises(ValueError, match="insufficient cyberdeck slots"):
        apply_action(ch, "install_program", {"item_id": hellhound}, path, lambda n: 0)
    with pytest.raises(ValueError, match="insufficient cyberdeck slots"):
        apply_action(ch, "install_hardware", {"item_id": krash}, path, lambda n: 0)

    # Cannot sell installed program or hardware
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "sell", {"item_id": eraser, "quantity": 1}, path, lambda n: 0)
    with pytest.raises(ValueError, match="equipped"):
        apply_action(ch, "sell", {"item_id": backup, "quantity": 1}, path, lambda n: 0)
