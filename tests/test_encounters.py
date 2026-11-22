import copy

import pytest

from encounters import WEAPONS, RANGE_DVS, apply_action, start_encounter


def character(cid, ref=6, dex=6, move=5, body=5, hp=25, weapon=None, armor=None):
    detail = {"equipment": {"weapons": [weapon] if weapon else [], "armor": armor or []},
              "conditions": {}, "injuries": [], "inventory": {"ammo:M Pistol": 20}}
    return {"id": cid, "stats": {"REF": ref, "DEX": dex, "MOVE": move, "BODY": body},
            "skills": {"Handgun": 6, "Melee Weapon": 6, "Brawling": 6, "Evasion": 4},
            "hp": hp, "max_hp": 25, "luck_remaining": 2, "inventory": {"ammo:M Pistol": 20}, "detail": detail}


def begun(chars, init_sequence=None):
    # distinct initiative dice in input order
    if init_sequence is None:
        init_sequence = [0, 1, 2, 9, 0, 6, 7, 8, 9, 4, 5]
    seq = iter(init_sequence)
    e = start_encounter(chars, lambda _: next(seq))
    state = {c["id"]: c for c in chars}
    return e, state


def test_canonical_source_numeric_weapon_and_range_facts():
    assert WEAPONS["Heavy Pistol"] == {"range": "pistol", "skill": "Handgun", "damage": (3, 6), "magazine": 8, "ammo": "H Pistol", "rof": 2, "hands": 1}
    assert RANGE_DVS["assault_rifle"] == (17, 16, 15, 13, 15, 20, 25, 30)


def test_turn_owner_split_movement_run_costs_action_and_detail_persists():
    chars = [character("pc"), character("npc", ref=3)]
    e, cs = begun(chars)
    actor = e["queue"][0]
    other = e["queue"][1]
    with pytest.raises(ValueError): apply_action(e, cs, other, "move")
    a = apply_action(e, cs, actor, "move", {"meters": 3})
    b = apply_action(a["encounter"], a["characters"], actor, "move", {"meters": 2})
    c = apply_action(b["encounter"], b["characters"], actor, "run", {"meters": 4})
    d = c["characters"][actor]["detail"]
    assert d["position_m"] == 9
    assert d["encounter_turn"]["action_used"]
    with pytest.raises(ValueError): apply_action(c["encounter"], c["characters"], actor, "run", {"meters": 1})


def test_ranged_attack_spends_ammo_uses_canonical_damage_and_armor_head_multiplier():
    gun = {"id": "gun", "type": "Heavy Pistol", "loaded": 8, "ammo_kind": "H Pistol"}
    chars = [character("a", weapon=gun), character("b", ref=3, armor=[{"id": "vest", "sp": 4, "location": "head"}])]
    e, cs = begun(chars); attacker = e["queue"][0]; defender = "b" if attacker == "a" else "a"
    # Sequence: attack d10=10 (exploding d10=1), three weapon damage dice=6,6,1; critical table draw.
    rolls = iter([9, 0, 5, 5, 0, 0])
    out = apply_action(e, cs, attacker, "attack", {"target_id": defender, "weapon_id": "gun", "range_m": 4, "location": "head"}, lambda _: next(rolls))
    weapon = out["characters"][attacker]["detail"]["equipment"]["weapons"][0]
    assert weapon["loaded"] == 7
    result = out["result"]["attacks"][0]
    assert result["hit"]
    assert result["damage"]["effective_sp"] == 4
    assert out["characters"][defender]["hp"] <= cs[defender]["hp"]


def test_empty_ammo_autofire_and_reload_full_mag_only():
    gun = {"id": "smg", "type": "SMG", "loaded": 0, "ammo_kind": "M Pistol"}
    chars = [character("a", weapon=gun), character("b", ref=3)]
    e, cs = begun(chars); actor = e["queue"][0]; target = "b" if actor == "a" else "a"
    with pytest.raises(ValueError): apply_action(e, cs, actor, "attack", {"mode": "autofire", "target_id": target, "weapon_id": "smg", "range_m": 10}, lambda _: 0)
    cs[actor]["inventory"]["ammo:M Pistol"] = 30
    loaded = apply_action(e, cs, actor, "reload", {"weapon_id": "smg"}, lambda _: 0)
    assert loaded["characters"][actor]["detail"]["equipment"]["weapons"][0]["loaded"] == 30


def test_melee_range_brawling_and_no_damage_when_attack_misses():
    knife = {"id": "knife", "type": "Light Melee Weapon", "loaded": None, "ammo_kind": None}
    chars = [character("a", weapon=knife), character("b", ref=3)]
    e, cs = begun(chars); actor = e["queue"][0]; target = "b" if actor == "a" else "a"
    with pytest.raises(ValueError): apply_action(e, cs, actor, "attack", {"target_id": target, "weapon_id": "knife", "range_m": 3}, lambda _: 0)
    result = apply_action(e, cs, actor, "attack", {"target_id": target, "mode": "brawling", "range_m": 1}, lambda _: 0)
    assert result["characters"][target]["hp"] <= cs[target]["hp"]
    assert "position_m" not in cs[actor]["detail"]


def test_fixed_rng_tie_fails_explicitly_instead_of_looping_forever():
    chars = [character("a", ref=5), character("b", ref=5)]
    with pytest.raises(ValueError, match="tie unresolved"):
        start_encounter(chars, lambda _: 0)


def test_second_rof2_attack_is_allowed_but_action_then_exhausts():
    gun = {"id": "p", "type": "Medium Pistol", "loaded": 12, "ammo_kind": "M Pistol"}
    chars = [character("a", weapon=gun), character("b", ref=3), character("c", ref=2)]
    # "a" (REF=6) rolls 9 -> initiative 15; "b" (REF=3) rolls 0 -> 3; "c" (REF=2) rolls 0 -> 2. "a" acts first.
    e, cs = begun(chars, init_sequence=[9, 0, 0, 9, 0, 6, 7, 8, 9, 4, 5])
    actor = e["queue"][0]
    assert actor == "a"
    first = "b"
    # Keep attack checks below hit threshold; attacks still consume rounds and their ROF slots.
    out = apply_action(e, cs, actor, "attack", {"target_id": first, "weapon_id": "p", "range_m": 5}, lambda _: 0)
    second = next(k for k in out["characters"] if k not in (actor, first))
    out = apply_action(out["encounter"], out["characters"], actor, "attack", {"target_id": second, "weapon_id": "p", "range_m": 5}, lambda _: 0)
    assert out["characters"][actor]["detail"]["equipment"]["weapons"][0]["loaded"] == 10
    with pytest.raises(ValueError): apply_action(out["encounter"], out["characters"], actor, "run", {"meters": 1}, lambda _: 0)


def test_brawling_uses_melee_reach_and_head_hit_preserves_negative_hp():
    chars = [character("a"), character("b", ref=3, hp=2)]
    # "a" (REF=6) rolls 9 -> initiative 15; "b" (REF=3) rolls 0 -> 6. "a" acts first.
    e, cs = begun(chars, init_sequence=[9, 0, 9, 0, 6, 7, 8, 9, 4, 5])
    actor = e["queue"][0]
    assert actor == "a"
    target = "b"
    with pytest.raises(ValueError): apply_action(e, cs, actor, "attack", {"mode": "brawling", "target_id": target, "range_m": 3}, lambda _: 0)
    # Use RNG that makes attack hit: attacker rolls 10 (crit), defender rolls 1 (crit fail)
    # Then damage: 3d6 for brawling (BODY=6) -> all 6s for max damage
    rng_seq = iter([9, 0, 5, 0, 5, 5, 5])  # init a=9,b=0; atk=9(def=10), def=0(def=1); atk crit=5(def=6); def crit=0(def=1); dmg=5,5,5(def=6,6,6)
    out = apply_action(e, cs, actor, "attack", {"mode": "brawling", "target_id": target, "range_m": 1, "location": "head"}, lambda _: next(rng_seq))
    assert out["characters"][target]["hp"] <= 0


def test_grapple_requires_free_hand_and_choke_uses_direct_damage():
    chars = [character("a"), character("b", ref=3)]
    chars[0]["detail"]["free_hands"] = 1
    chars[1]["skills"]["Brawling"] = 0
    e, cs = begun(chars); actor = e["queue"][0]; target = "b" if actor == "a" else "a"
    out = apply_action(e, cs, actor, "grab", {"target_id": target, "range_m": 1}, lambda _: 0)
    if not out["result"]["won"]: return
    turn = apply_action(out["encounter"], out["characters"], actor, "next_turn", {}, lambda _: 0)
    other = turn["result"]["actor_id"]
    turn = apply_action(turn["encounter"], turn["characters"], other, "next_turn", {}, lambda _: 0)
    choked = apply_action(turn["encounter"], turn["characters"], actor, "choke", {"target_id": target}, lambda _: 0)
    assert choked["characters"][target]["hp"] == 20


def test_unresolved_explosive_placement_rejects_without_consuming_ammo():
    launcher = {"id": "gl", "type": "Grenade Launcher", "loaded": 2, "ammo_kind": "Grenade"}
    chars = [character("a", weapon=launcher), character("b", ref=3)]
    e, cs = begun(chars); actor = e["queue"][0]
    with pytest.raises(ValueError, match="area placement"):
        apply_action(e, cs, actor, "attack", {"target_id": "b", "weapon_id": "gl", "range_m": 10}, lambda _: 0)
    assert cs[actor]["detail"]["equipment"]["weapons"][0]["loaded"] == 2
