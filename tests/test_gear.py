from gear import apply_action
from tests import rules_fixture as rf


def rules_db(path):
    rf.build(path, [rf.page(200, 199, [
        rf.table([rf.RANGED_HEADER,
                  ["Medium Pistol", "Handgun", "2d6", "12 (M Pistol)", "2", "1", "YES", "50eb (Costly)"]], 80),
        rf.table([rf.ARMOR_HEADER, ["Test Armor", "Layered synthetic weave.", "11", "-2 REF, DEX, and MOVE", "100eb (Premium)"]], 200),
        rf.table([rf.GEAR_HEADER, ["Consumable", "Single-use test supply.", "20eb (Everyday)"]], 320),
    ])], digest="c" * 64)


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
    item_id = next(k for k, v in items(path).items() if v["name"] == "Medium Pistol")
    import pytest
    with pytest.raises(ValueError, match="owned"):
        apply_action({}, "equip_weapon", {"item_id": item_id}, path, lambda n: 0)
    with pytest.raises(ValueError, match="exact source-catalog"):
        apply_action({}, "buy", {"item_id": "invented", "price": 0}, path, lambda n: 0)


def _extended_rules_db(path):
    rf.build(path, [rf.page(350, 350, [
        rf.table([rf.RANGED_HEADER,
                  ["Heavy Pistol", "Handgun", "3d6", "8 (H Pistol)", "2", "1", "YES", "100eb (Premium)"]], 60),
        rf.table([rf.ARMOR_HEADER,
                  ["Leathers", "Road leathers.", "4", "None", "20eb (Everyday)"],
                  ["Kevlar", "Woven vest.", "7", "None", "50eb (Costly)"],
                  ["Light Armorjack", "Mesh and plates.", "11", "None", "100eb (Premium)"],
                  ["Bodyweight Suit", "Full skinsuit.", "11", "None", "1,000eb (V. Expensive)"],
                  ["Medium Armorjack", "Heavier plates.", "12", "-2 REF, DEX, and MOVE", "100eb (Premium)"],
                  ["Heavy Armorjack", "Thickest plates.", "13", "-2 REF, DEX, and MOVE", "500eb (Expensive)"],
                  ["Flak", "Flak vest and pants.", "15", "-4 REF, DEX, and MOVE", "500eb (Expensive)"],
                  ["Metalgear", "Rigid shell.", "18", "-4 REF, DEX and MOVE", "5,000eb (Luxury)"],
                  ["Bulletproof Shield", "Transparent shield.", "10 HP, which is reduced by damage",
                   "None, but always takes up one arm", "100eb (Premium)"]], 110),
        rf.table([rf.GEAR_HEADER,
                  ["Cyberdeck (Poor Quality)", "Entry deck. 5 slots.", "100eb (Premium)"],
                  ["Cyberdeck (Standard Quality)", "Standard cyberdeck.", "500eb (Expensive)"],
                  ["Cyberdeck (Excellent Quality)", "High-end deck. 9 slots.", "1,000eb (V. Expensive)"],
                  ["Cyberdeck", "Default cyberdeck.", "500eb (Expensive)"],
                  ["Kibble", "Dry rations.", "10eb (Cheap)"]], 300),
        rf.table([rf.PROGRAM_HEADER,
                  ["Eraser", "Booster", "0", "0", "7", "Boosts cloaking.", "20eb (Everyday)"],
                  ["Speedygonzalez", "Booster", "0", "0", "7", "Boosts speed.", "100eb (Premium)"],
                  ["Armor", "Defender", "0", "0", "7", "Reduces brain damage.", "50eb (Costly)"]], 420),
        rf.table([rf.BLACK_ICE_HEADER,
                  ["Hellhound", "Anti-Personnel Black ICE", "6", "6", "6", "2", "20", "Burns the intruder.", "500eb (Expensive)"]], 520),
        rf.table([rf.HARDWARE_HEADER,
                  ["Backup Drive (Cyberdeck · 2 Slots)", "Stores destroyed programs.", "100eb (Premium)"],
                  ["Range Upgrade (Cyberdeck · 1 Slot)", "Longer access range.", "100eb (Premium)"],
                  ["KRASH Barrier", "Blocks forced jack-outs.", "100eb (Premium)"]], 580),
    ])])


def test_equip_armor_corebook_headers_penalties_and_monotonic_index(tmp_path):
    path = tmp_path / "rules.sqlite"
    _extended_rules_db(path)
    from sourcecatalog import items

    catalog = items(path)
    by_name = {v["name"]: k for k, v in catalog.items() if v["category"] == "armor"}
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
