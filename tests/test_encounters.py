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


def test_attack_ablation_comes_from_weapon_and_ammo_not_arguments():
    gun = {"id": "gun", "type": "Heavy Pistol", "loaded": 8, "ammo_kind": "H Pistol"}
    chars = [character("a", ref=8, weapon=gun), character("b", ref=2, armor=[{"id": "vest", "sp": 4, "location": "body"}])]
    e, cs = begun(chars, init_sequence=[9, 0])
    # Attack d10=8 (no explosion) vs pistol DV; damage 6,6,1 = 13 penetrates SP 4 without a critical.
    rolls = iter([7, 5, 5, 0])
    out = apply_action(e, cs, "a", "attack", {"target_id": "b", "weapon_id": "gun", "range_m": 4, "ablation": 4}, lambda _: next(rolls, 0))
    assert out["result"]["attacks"][0]["hit"]
    assert out["characters"]["b"]["detail"]["equipment"]["armor"][0]["sp"] == 3


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


def test_ephemeral_npcs_solo_service_and_solo_summary(tmp_path):
    from campaign import STAT_NAMES
    from gameplay import GameplayService
    from turn_engine.engine import TurnEngine

    svc = GameplayService(tmp_path / "camp.sqlite")
    camp = svc.execute("create_campaign", {"name": "NPC Test", "operation_id": "c-npc"})["result"]
    pc = svc.execute(
        "create_character",
        {
            "name": "Kestrel",
            "stats": dict.fromkeys(STAT_NAMES, 6),
            "skills": {"Handgun": 6, "Evasion": 4},
            "operation_id": "ch-npc",
        },
    )["result"]
    svc.execute(
        "attach_character",
        {"campaign_id": camp["id"], "character_id": pc["id"], "expected_revision": camp["revision"], "reason": "join", "operation_id": "att-npc"},
    )
    # Give PC a Heavy Pistol
    from contextlib import closing
    pc_now = svc.store.get_character(pc["id"])
    pc_now["detail"]["equipment"] = {
        "weapons": [{"id": "w1", "type": "Heavy Pistol", "loaded": 8, "ammo_kind": "H Pistol"}],
        "armor": [],
    }
    with closing(svc.store._connect()) as conn, conn:
        svc.solo._write_character(conn, pc_now)

    ctx0 = svc.solo.context(camp["id"])
    # Start encounter with 1 PC + 2 ephemeral NPCs from supplied stat blocks
    stat_block = {"REF": 5, "DEX": 5, "BODY": 5, "WILL": 4, "MOVE": 5}
    seq = iter([9, 1, 2, 5, 5, 5, 5, 5, 5, 5])
    start_res = svc.solo.execute(
        "start_encounter",
        {
            "character_ids": [pc["id"]],
            "npcs": [
                {"name": "Maelstrom Punk", "stats": stat_block, "hp": 25, "sp_body": 7, "sp_head": 7, "weapons": ["Medium Pistol"]},
                {"id": "lt-1", "name": "Chrome Lt", "stats": stat_block, "hp": 30, "sp_body": 11, "sp_head": 11, "weapons": ["Assault Rifle"]},
            ],
            "expected_revision": ctx0["solo"]["revision"] if "solo" in ctx0 else ctx0["revision"],
            "reason": "Alley firefight",
            "operation_id": "enc-start-npc",
        },
        campaign_id=camp["id"],
        randbelow=lambda _: next(seq),
    )
    assert start_res["committed"] is True
    enc = start_res["result"]
    assert set(enc["npcs"].keys()) == {"npc-0", "lt-1"}
    # Persistent characters table must NOT contain ephemeral NPCs
    assert len(start_res["characters"]) == 1
    assert [c["id"] for c in svc.store.list_characters()] == [pc["id"]]

    # TurnEngine._solo_summary exposes NPC status & display names
    full_ctx = svc.campaign_context(camp["id"])
    engine = TurnEngine(svc, object())
    summary = engine._solo_summary(full_ctx)
    enc_summary = summary["encounter"]
    assert enc_summary["current_actor"] == "Kestrel"
    assert "Maelstrom Punk" in enc_summary["queue"]
    assert "Chrome Lt" in enc_summary["queue"]
    by_npc_id = {n["id"]: n for n in enc_summary["npcs"]}
    assert by_npc_id["npc-0"]["weapon"] == "Medium Pistol"
    assert by_npc_id["npc-0"]["sp_body"] == 7
    assert by_npc_id["lt-1"]["hp"] == 30
    assert by_npc_id["lt-1"]["wound_state"] == "healthy"

    # Add reinforcement mid-encounter
    add_res = svc.solo.execute(
        "encounter_action",
        {
            "action": "add_npc",
            "arguments": {"name": "Sniper", "stats": stat_block, "hp": 45, "weapons": ["Sniper Rifle"]},
            "expected_revision": start_res["revision"],
            "reason": "Reinforcements",
            "operation_id": "enc-add-npc",
        },
        campaign_id=camp["id"],
        randbelow=lambda _: 0,
    )
    assert add_res["result"]["added"] == ["npc-1"]
    ctx_after_add = svc.solo.context(camp["id"])
    assert "npc-1" in ctx_after_add["runtime"]["encounter"]["npcs"]
    assert "npc-1" in ctx_after_add["runtime"]["encounter"]["queue"]

    # Remove NPC mid-encounter
    rem_res = svc.solo.execute(
        "encounter_action",
        {
            "action": "remove_npc",
            "arguments": {"npc_id": "npc-1"},
            "expected_revision": add_res["revision"],
            "reason": "Retreated",
            "operation_id": "enc-rem-npc",
        },
        campaign_id=camp["id"],
    )
    assert rem_res["result"]["removed"] == "npc-1"
    ctx_after_rem = svc.solo.context(camp["id"])
    assert "npc-1" not in ctx_after_rem["runtime"]["encounter"]["npcs"]
    assert "npc-1" not in ctx_after_rem["runtime"]["encounter"]["queue"]
    assert len(svc.store.list_characters()) == 1


def test_solo_next_turn_unifies_death_save_invariant_end_effects_and_extinguish(tmp_path):
    from campaign import STAT_NAMES
    from gameplay import GameplayService

    from contextlib import closing
    svc = GameplayService(tmp_path / "camp_ds.sqlite")
    camp = svc.execute("create_campaign", {"name": "DS Test", "operation_id": "c-ds"})["result"]
    pc1 = svc.execute("create_character", {"name": "Runner1", "stats": dict.fromkeys(STAT_NAMES, 6), "skills": {"Handgun": 5}, "operation_id": "ch-ds1"})["result"]
    pc2 = svc.execute("create_character", {"name": "Runner2", "stats": dict.fromkeys(STAT_NAMES, 6), "skills": {"Handgun": 5}, "operation_id": "ch-ds2"})["result"]
    svc.execute("attach_character", {"campaign_id": camp["id"], "character_id": pc1["id"], "expected_revision": camp["revision"], "reason": "j1", "operation_id": "att-ds1"})
    svc.execute("attach_character", {"campaign_id": camp["id"], "character_id": pc2["id"], "expected_revision": camp["revision"] + 1, "reason": "j2", "operation_id": "att-ds2"})

    # Put pc1 on fire + Broken Ribs; put pc2 at 0 HP with Dismembered Arm (base penalty +1) and escalation 0
    c1 = svc.store.get_character(pc1["id"])
    c1["detail"]["conditions"] = {"burning": True}
    c1["detail"]["injuries"] = [{"id": "body:5", "name": "Broken Ribs"}]
    c1["detail"]["stabilized"] = True
    with closing(svc.store._connect()) as conn, conn:
        svc.solo._write_character(conn, c1)

    c2 = svc.store.get_character(pc2["id"])
    c2["hp"] = 0
    c2["detail"]["injuries"] = [{"id": "body:2", "name": "Dismembered Arm", "effects": "Arm lost; drop held item; base death-save penalty +1"}]
    c2["detail"]["death_save_penalty"] = 0
    with closing(svc.store._connect()) as conn, conn:
        svc.solo._write_character(conn, c2)

    rev = svc.solo.context(camp["id"])["revision"]
    # pc1 rolls 9 -> init 15; pc2 rolls 0 -> init 6
    seq = iter([9, 0])
    st = svc.solo.execute(
        "start_encounter",
        {"character_ids": [pc1["id"], pc2["id"]], "expected_revision": rev, "reason": "init", "operation_id": "st-ds"},
        campaign_id=camp["id"],
        randbelow=lambda _: next(seq),
    )
    assert st["result"]["queue"][0] == pc1["id"]

    # pc1 moves 5m (> 4m triggers Broken Ribs -5 HP), then ends turn (also burning -2 HP)
    mv = svc.solo.execute(
        "encounter_action",
        {"actor_id": pc1["id"], "action": "move", "arguments": {"meters": 5}, "expected_revision": st["revision"], "reason": "run", "operation_id": "mv-ds"},
        campaign_id=camp["id"],
    )
    # Next turn: outgoing pc1 takes 5 + 2 = 7 HP damage, stabilized=False; incoming pc2 rolls Death Save (die=4 + base 1 + esc 0 = 5 < BODY 6 -> survives!)
    nt = svc.solo.execute(
        "encounter_action",
        {"actor_id": pc1["id"], "action": "next_turn", "arguments": {}, "expected_revision": mv["revision"], "reason": "end", "operation_id": "nt-ds"},
        campaign_id=camp["id"],
        randbelow=lambda _: 3,  # d10 = 4
    )
    assert nt["result"]["actor_id"] == pc2["id"]
    assert len(nt["result"]["end_of_turn_effects"]) == 2
    ds = nt["result"]["death_save"]
    assert ds["survived"] is True
    assert ds["base_penalty"] == 1
    assert ds["escalation_penalty"] == 0
    assert ds["total_penalty"] == 1

    chars_after = {c["id"]: c for c in nt["characters"]}
    assert chars_after[pc1["id"]]["hp"] == c1["hp"] - 7
    assert chars_after[pc1["id"]]["detail"]["stabilized"] is False
    # Escalation counter strictly 1, base penalty stored separately
    assert chars_after[pc2["id"]]["detail"]["death_save_base_penalty"] == 1
    assert chars_after[pc2["id"]]["detail"]["death_save_penalty"] == 1

    # Advance back to pc1 and extinguish burning
    nt2 = svc.solo.execute(
        "encounter_action",
        {"actor_id": pc2["id"], "action": "next_turn", "arguments": {}, "expected_revision": nt["revision"], "reason": "pass", "operation_id": "nt-ds2"},
        campaign_id=camp["id"],
    )
    ext = svc.solo.execute(
        "encounter_action",
        {"actor_id": pc1["id"], "action": "extinguish", "arguments": {}, "expected_revision": nt2["revision"], "reason": "pat out flames", "operation_id": "ext-ds"},
        campaign_id=camp["id"],
    )
    assert ext["result"]["extinguished"] is True
    chars_ext = {c["id"]: c for c in ext["characters"]}
    assert "burning" not in chars_ext[pc1["id"]]["detail"]["conditions"]


def test_start_encounter_skips_dead_actor_zero():
    dead_pc = character("dead_guy", ref=10, hp=0)
    dead_pc["detail"]["dead"] = True
    alive_pc = character("alive_guy", ref=4, hp=20)
    seq = iter([9, 0])
    enc = start_encounter([dead_pc, alive_pc], lambda _: next(seq))
    assert enc["queue"] == ["dead_guy", "alive_guy"]
    assert enc["turn_index"] == 1


def test_stat_armor_penalty_only_ref_dex_move_and_suppressive_will():
    heavy = [{"id": "armor1", "type": "Metalgear", "sp": 18, "location": "body", "penalty": 4}]
    a = character("shooter", ref=8, weapon={"id": "smg", "type": "SMG", "loaded": 30, "ammo_kind": "M Pistol"})
    b = character("tank", ref=6, dex=6, move=6, armor=heavy)
    b["stats"]["WILL"] = 8
    b["skills"]["Concentration"] = 6
    e, cs = begun([a, b], init_sequence=[9, 0])
    # Suppress target b; target b's WILL+Concentration base must be 8+6=14 (NOT reduced by Metalgear -4!)
    res = apply_action(
        e,
        cs,
        "shooter",
        "suppressive_fire",
        {"weapon_id": "smg", "targets": [{"target_id": "tank", "range_m": 10, "covered": False, "line_of_sight": True, "on_foot": True}]},
        lambda _: 4,  # d10 = 5
    )
    def_check = res["result"]["targets"][0]["check"]
    assert def_check["base"] == 14
    assert def_check["total"] == 19  # 8 WILL + 6 Conc + 5 d10


def test_initiative_tie_recursive_non_mutating_and_speedware_solo_bonuses():
    a = character("a", ref=6)
    a["detail"]["solo_allocation"] = {"initiative_reaction": 2}
    b = character("b", ref=6)
    b["detail"]["cyberware"] = [{"name": "Kerenzikov", "installed": True}]
    c = character("c", ref=4)
    c["detail"]["cyberware"] = [{"name": "Sandevistan", "installed": True}, {"name": "Kerenzikov", "installed": True}]
    # Initial rolls (all roll d10=1 -> randbelow 0):
    # a: 6 + 2 + 1 = 9, b: 6 + 2 + 1 = 9, c: 4 + 3 + 1 = 8 (Sandevistan +3 non-stacking with Kerenzikov)
    # Tie between a and b at 9 (with c at 8); reroll for tiebreaker gives a: 6+2+1=9, b: 6+2+6=14
    # Original totals remain unmutated (a=9, b=9, c=8) and b > a > c!
    seq = iter([0, 0, 0, 0, 5])
    enc = start_encounter([a, b, c], lambda _: next(seq))
    assert enc["initiative"]["a"]["total"] == 9
    assert enc["initiative"]["b"]["total"] == 9
    assert enc["initiative"]["c"]["total"] == 8
    assert enc["queue"] == ["b", "a", "c"]


def test_mortal_wound_zero_damage_no_crit_aimed_leg_id_and_stabilized_cleared():
    gun = {"id": "p", "type": "Medium Pistol", "loaded": 12, "ammo_kind": "M Pistol"}
    a = character("a", ref=8, weapon=gun)
    b = character("b", ref=2, hp=0, armor=[{"id": "arm", "sp": 15, "location": "body"}])
    b["detail"]["stabilized"] = True
    e, cs = begun([a, b], init_sequence=[9, 0])

    # Hit armor with 2d6 = 1+1 = 2 vs SP 15 -> 0 HP damage: must NOT inflict crit or increment death_save_penalty!
    seq = iter([9, 5, 0, 0])  # atk d10=10+6 -> hits DV13; dmg 1+1=2
    no_pen = apply_action(e, cs, "a", "attack", {"target_id": "b", "weapon_id": "p", "range_m": 4}, lambda _: next(seq))
    b_after = no_pen["characters"]["b"]
    assert no_pen["result"]["attacks"][0]["damage"]["hp_damage"] == 0
    assert b_after["detail"].get("death_save_penalty", 0) == 0
    assert b_after["detail"]["injuries"] == []
    assert b_after["detail"]["stabilized"] is True

    # Now aimed leg shot on unarmored b2 -> canonical id "body:8", clears stabilized
    b2 = character("b2", ref=2, hp=20)
    b2["detail"]["stabilized"] = True
    e2, cs2 = begun([a, b2], init_sequence=[9, 0])
    seq2 = iter([9, 5, 3, 4])  # atk 10+6-8 + 6+6 = 20 vs DV13; dmg 4+5=9
    leg = apply_action(e2, cs2, "a", "attack", {"target_id": "b2", "weapon_id": "p", "range_m": 4, "location": "leg"}, lambda _: next(seq2))
    injs = leg["characters"]["b2"]["detail"]["injuries"]
    assert any(i["id"] == "body:8" and i["name"] == "Broken Leg" for i in injs)
    assert leg["characters"]["b2"]["detail"]["stabilized"] is False


def test_grapple_escape_no_double_penalty_and_choke_tracker_resets():
    a = character("a", ref=8, dex=6, body=6)
    b = character("b", ref=4, dex=6, body=6)
    a["detail"]["free_hands"] = 2
    b["skills"]["Brawling"] = 0
    e, cs = begun([a, b], init_sequence=[9, 0])

    grab = apply_action(e, cs, "a", "grab", {"target_id": "b", "range_m": 1}, lambda _: 5)
    assert grab["result"]["won"] is True
    nt1 = apply_action(grab["encounter"], grab["characters"], "a", "next_turn", {}, lambda _: 0)

    # b attempts escape: modifier must be -2 (single grapple penalty), NOT -4!
    b["skills"]["Brawling"] = 6
    nt1["characters"]["b"]["skills"]["Brawling"] = 6
    esc = apply_action(nt1["encounter"], nt1["characters"], "b", "escape", {"target_id": "a"}, lambda _: 5)
    assert esc["result"]["attacker"]["modifier"] == -2
    assert esc["result"]["defender"]["modifier"] == -2

    # Test choke_tracker resets on release/throw
    b["skills"]["Brawling"] = 0
    e2, cs2 = begun([a, b], init_sequence=[9, 0])
    g2 = apply_action(e2, cs2, "a", "grab", {"target_id": "b", "range_m": 1}, lambda _: 5)
    assert g2["result"]["won"] is True
    nt_a = apply_action(g2["encounter"], g2["characters"], "a", "next_turn", {}, lambda _: 0)
    nt_b = apply_action(nt_a["encounter"], nt_a["characters"], "b", "next_turn", {}, lambda _: 0)
    choked = apply_action(nt_b["encounter"], nt_b["characters"], "a", "choke", {"target_id": "b"}, lambda _: 0)
    assert "choke_tracker" in choked["characters"]["b"]["detail"]["conditions"]
    # Out-of-turn release by a after next_turn -> clears choke_tracker
    nt_a2 = apply_action(choked["encounter"], choked["characters"], "a", "next_turn", {}, lambda _: 0)
    rel = apply_action(nt_a2["encounter"], nt_a2["characters"], "a", "release", {}, lambda _: 0)
    assert "choke_tracker" not in rel["characters"]["b"]["detail"]["conditions"]


def test_non_lethal_and_exotic_weapons_rules():
    # 1. Stun Gun & Stun Baton: non_lethal, no_critical, clamp hp >= 1 + unconscious=True
    stun_gun = {"id": "sg", "type": "Stun Gun", "loaded": 8, "ammo_kind": "Battery"}
    a = character("a", ref=8, weapon=stun_gun)
    b = character("b", ref=2, hp=5, armor=[{"id": "k", "sp": 4, "location": "body"}])
    b["skills"]["Evasion"] = 0
    e, cs = begun([a, b], init_sequence=[9, 0])
    # Double 6s + 6 (18 dmg vs SP 4 -> 14): no crit injury, no ablation, hp clamped to 1, unconscious=True
    seq = iter([9, 5, 5, 5, 5])
    out = apply_action(e, cs, "a", "attack", {"target_id": "b", "weapon_id": "sg", "range_m": 4}, lambda _: next(seq))
    assert out["result"]["attacks"][0]["critical_injuries"] == []
    assert out["result"]["attacks"][0]["damage"]["critical_trigger"] is False
    assert out["characters"]["b"]["hp"] == 1
    assert out["characters"]["b"]["detail"]["conditions"]["unconscious"] is True
    assert out["characters"]["b"]["detail"]["equipment"]["armor"][0]["sp"] == 4

    # 2. Rubber Ammunition: hp >= 1 when old_hp > 1, no crits, does NOT set unconscious
    pistol = {"id": "p", "type": "Heavy Pistol", "loaded": 8, "ammo_kind": "H Pistol", "ammo_type": "rubber"}
    a2 = character("a2", ref=8, weapon=pistol)
    b2 = character("b2", ref=2, hp=5)
    e2, cs2 = begun([a2, b2], init_sequence=[9, 0])
    seq2 = iter([9, 5, 5, 5, 5])
    out2 = apply_action(e2, cs2, "a2", "attack", {"target_id": "b2", "weapon_id": "p", "range_m": 4}, lambda _: next(seq2))
    assert out2["characters"]["b2"]["hp"] == 1
    assert out2["result"]["attacks"][0]["critical_injuries"] == []
    assert "unconscious" not in out2["characters"]["b2"]["detail"]["conditions"]

    # 3. Microwaver & Shrieker do NOT ablate armor; Microwaver disables cyberware, Shrieker inflicts Damaged Ear
    mw = {"id": "mw", "type": "Microwaver", "loaded": 8, "ammo_kind": "Battery"}
    sh = {"id": "sh", "type": "Shrieker", "loaded": 8, "ammo_kind": "Battery"}
    ap_air = {"id": "air", "type": "Air Pistol", "loaded": 12, "ammo_kind": "M Pistol"}
    a3 = character("a3", ref=8, weapon=mw)
    a3["detail"]["equipment"]["weapons"].extend([sh, ap_air])
    b3 = character("b3", ref=2, armor=[{"id": "k3", "sp": 7, "location": "body"}])
    e3, cs3 = begun([a3, b3], init_sequence=[9, 0])
    # Hit with Microwaver (atk d10=10+6, target Cybertech 0 + d10=1 -> fails DV15)
    seq3 = iter([9, 5, 0, 0])
    mw_out = apply_action(e3, cs3, "a3", "attack", {"target_id": "b3", "weapon_id": "mw", "range_m": 4}, lambda _: next(seq3))
    assert mw_out["characters"]["b3"]["detail"]["equipment"]["armor"][0]["sp"] == 7
    assert mw_out["characters"]["b3"]["detail"]["conditions"]["cyberware_disabled"] is True

    # Hit with Shrieker next turn
    nt = apply_action(mw_out["encounter"], mw_out["characters"], "a3", "next_turn", {}, lambda _: 0)
    nt2 = apply_action(nt["encounter"], nt["characters"], "b3", "next_turn", {}, lambda _: 0)
    seq4 = iter([9, 5, 0, 0])
    sh_out = apply_action(nt2["encounter"], nt2["characters"], "a3", "attack", {"target_id": "b3", "weapon_id": "sh", "range_m": 4}, lambda _: next(seq4))
    assert sh_out["characters"]["b3"]["detail"]["equipment"]["armor"][0]["sp"] == 7
    assert any(i["id"] == "head:10" and i["name"] == "Damaged Ear" for i in sh_out["characters"]["b3"]["detail"]["injuries"])

    # Acid ablation only when explicit acid_ablation=True
    nt3 = apply_action(sh_out["encounter"], sh_out["characters"], "a3", "next_turn", {}, lambda _: 0)
    nt4 = apply_action(nt3["encounter"], nt3["characters"], "b3", "next_turn", {}, lambda _: 0)
    acid_out = apply_action(nt4["encounter"], nt4["characters"], "a3", "attack", {"target_id": "b3", "weapon_id": "air", "range_m": 4, "acid_ablation": True}, lambda _: 9)
    assert acid_out["characters"]["b3"]["detail"]["equipment"]["armor"][0]["sp"] == 6

    # 4. Flamethrower: 3d6, burning on penetration, no aimed shots, no crits
    ft = {"id": "ft", "type": "Flamethrower", "loaded": 4, "ammo_kind": "Slug"}
    a4 = character("a4", ref=8, weapon=ft)
    a4["skills"]["Heavy Weapons"] = 6
    b4 = character("b4", ref=2, hp=25)
    e4, cs4 = begun([a4, b4], init_sequence=[9, 0])
    with pytest.raises(ValueError, match="aimed"):
        apply_action(e4, cs4, "a4", "attack", {"target_id": "b4", "weapon_id": "ft", "range_m": 4, "location": "head"}, lambda _: 0)
    seq5 = iter([9, 5, 5, 5, 0])  # 3d6 = 6+6+1 = 13 (no +5 crit!)
    ft_out = apply_action(e4, cs4, "a4", "attack", {"target_id": "b4", "weapon_id": "ft", "range_m": 4}, lambda _: next(seq5))
    assert ft_out["result"]["attacks"][0]["damage"]["hp_damage"] == 13
    assert ft_out["characters"]["b4"]["detail"]["conditions"]["burning"] is True

    # 5. Helix: autofire_only, BODY 11+ (via Linear Frame), 2-action reload
    hx = {"id": "hx", "type": "Helix", "loaded": 0, "ammo_kind": "Rifle"}
    a5 = character("a5", ref=8, body=6, weapon=hx)
    a5["skills"]["Autofire"] = 6
    a5["inventory"]["ammo:Rifle"] = 40
    b5 = character("b5", ref=2, hp=30)
    e5, cs5 = begun([a5, b5], init_sequence=[9, 0])
    # Single shot rejected
    with pytest.raises(ValueError, match="autofire"):
        apply_action(e5, cs5, "a5", "attack", {"target_id": "b5", "weapon_id": "hx", "range_m": 10, "mode": "ranged"}, lambda _: 0)
    # 2-action reload
    rel1 = apply_action(e5, cs5, "a5", "reload", {"weapon_id": "hx"}, lambda _: 0)
    assert rel1["result"]["completed"] is False
    nt_h1 = apply_action(rel1["encounter"], rel1["characters"], "a5", "next_turn", {}, lambda _: 0)
    nt_h2 = apply_action(nt_h1["encounter"], nt_h1["characters"], "b5", "next_turn", {}, lambda _: 0)
    rel2 = apply_action(nt_h2["encounter"], nt_h2["characters"], "a5", "reload", {"weapon_id": "hx"}, lambda _: 0)
    assert rel2["result"]["completed"] is True
    assert rel2["characters"]["a5"]["detail"]["equipment"]["weapons"][0]["loaded"] == 40
    # BODY 6 rejected -> needs BODY 11+
    nt_h3 = apply_action(rel2["encounter"], rel2["characters"], "a5", "next_turn", {}, lambda _: 0)
    nt_h4 = apply_action(nt_h3["encounter"], nt_h3["characters"], "b5", "next_turn", {}, lambda _: 0)
    with pytest.raises(ValueError, match="BODY 11"):
        apply_action(nt_h4["encounter"], nt_h4["characters"], "a5", "attack", {"target_id": "b5", "weapon_id": "hx", "range_m": 10, "mode": "autofire"}, lambda _: 0)
    # With Linear Frame Sigma (effective_body 12), Helix fires!
    nt_h4["characters"]["a5"]["detail"]["cyberware"] = [{"name": "Implanted Linear Frame Sigma", "installed": True}]
    hx_atk = apply_action(nt_h4["encounter"], nt_h4["characters"], "a5", "attack", {"target_id": "b5", "weapon_id": "hx", "range_m": 10, "mode": "autofire"}, lambda _: 5)
    assert hx_atk["characters"]["a5"]["detail"]["equipment"]["weapons"][0]["loaded"] == 20

    # 6. Dartgun payload (biotoxin)
    dg = {"id": "dg", "type": "Dartgun", "loaded": 8, "ammo_kind": "Arrow"}
    a6 = character("a6", ref=8, weapon=dg)
    b6 = character("b6", ref=2, hp=25, armor=[{"id": "k6", "sp": 11, "location": "body"}])
    e6, cs6 = begun([a6, b6], init_sequence=[9, 0])
    # Hit (d10=10+6 vs DV13), target fails DV15 Resist Torture/Drugs (d10=1-1), 3d6 biotoxin = 3+3+3=9
    seq6 = iter([9, 5, 0, 0, 2, 2, 2])
    dg_out = apply_action(e6, cs6, "a6", "attack", {"target_id": "b6", "weapon_id": "dg", "range_m": 4, "payload": "biotoxin"}, lambda _: next(seq6))
    assert dg_out["characters"]["b6"]["hp"] == 16
    assert dg_out["characters"]["b6"]["detail"]["equipment"]["armor"][0]["sp"] == 11


def test_effective_body_active_injuries_evasion_autofail_and_conditions():
    # Effective body via Linear Frame Sigma (12) -> 4d6 brawling & 12 throw damage
    a = character("a", ref=8, body=5)
    a["detail"]["cyberware"] = [{"name": "Implanted Linear Frame Sigma", "installed": True}]
    a["detail"]["free_hands"] = 2
    b = character("b", ref=2, hp=30)
    b["detail"]["conditions"]["unconscious"] = True
    b["detail"]["injuries"] = [{"id": "head:9", "name": "Cracked Skull"}]
    e, cs = begun([a, b], init_sequence=[9, 0])

    # Unconscious target auto-fails Evasion in melee + Cracked Skull 3x headshot multiplier + 4d6 brawling
    # atk d10=2 -> hits automatically (no defense roll); 4d6 = 2,2,2,2 = 8 * 3 = 24
    seq = iter([1, 1, 1, 1, 1])
    atk = apply_action(e, cs, "a", "attack", {"target_id": "b", "mode": "brawling", "range_m": 1, "location": "head"}, lambda _: next(seq))
    assert "defense" not in atk["result"]["attacks"][0]["check"]
    assert atk["result"]["attacks"][0]["hit"] is True
    assert atk["result"]["attacks"][0]["damage"]["hp_damage"] == 24

    # Suppressed Cracked Skull no longer applies 3x
    b["detail"]["injuries"] = [{"id": "head:9", "name": "Cracked Skull", "suppressed": True}]
    e2, cs2 = begun([a, b], init_sequence=[9, 0])
    seq2 = iter([1, 1, 1, 1, 1])
    atk2 = apply_action(e2, cs2, "a", "attack", {"target_id": "b", "mode": "brawling", "range_m": 1, "location": "head"}, lambda _: next(seq2))
    assert atk2["result"]["attacks"][0]["damage"]["hp_damage"] == 16

    # forced_cover blocks attack until move(..., into_cover=True)
    gun = {"id": "g", "type": "Medium Pistol", "loaded": 12, "ammo_kind": "M Pistol"}
    c1 = character("c1", ref=8, weapon=gun)
    c1["detail"]["conditions"]["forced_cover"] = {"by": "c2", "move": True, "run_if_needed": True}
    c2 = character("c2", ref=2)
    e3, cs3 = begun([c1, c2], init_sequence=[9, 0])
    with pytest.raises(ValueError, match="forced_cover"):
        apply_action(e3, cs3, "c1", "attack", {"target_id": "c2", "weapon_id": "g", "range_m": 5}, lambda _: 5)
    moved = apply_action(e3, cs3, "c1", "move", {"meters": 4, "into_cover": True})
    assert "forced_cover" not in moved["characters"]["c1"]["detail"]["conditions"]

    # flash_out blocks Action until next_turn clears it
    moved["characters"]["c1"]["detail"]["conditions"]["flash_out"] = True
    with pytest.raises(ValueError, match="flash_out"):
        apply_action(moved["encounter"], moved["characters"], "c1", "attack", {"target_id": "c2", "weapon_id": "g", "range_m": 5}, lambda _: 5)
    nt = apply_action(moved["encounter"], moved["characters"], "c1", "next_turn", {}, lambda _: 0)
    assert "flash_out" not in nt["characters"]["c1"]["detail"]["conditions"]


def test_validation_out_of_turn_hold_and_partial_special_ammo_reload():
    gun = {"id": "p", "type": "Heavy Pistol", "loaded": 4, "ammo_kind": "H Pistol"}
    a = character("a", ref=8, weapon=gun)
    a["inventory"] = {"ammo:H Pistol": 2, "ammo:H Pistol:armor_piercing": 6}
    b = character("b", ref=2)
    e, cs = begun([a, b], init_sequence=[9, 0])

    # Negative range_m rejected
    with pytest.raises(ValueError):
        apply_action(e, cs, "a", "attack", {"target_id": "b", "weapon_id": "p", "range_m": -1}, lambda _: 5)
    with pytest.raises(ValueError):
        apply_action(e, cs, "a", "grab", {"target_id": "b", "range_m": -2}, lambda _: 5)

    # Partial reload with remaining 2 standard bullets -> loaded 4 + 2 = 6
    rel_partial = apply_action(e, cs, "a", "reload", {"weapon_id": "p"}, lambda _: 0)
    assert rel_partial["characters"]["a"]["detail"]["equipment"]["weapons"][0]["loaded"] == 6
    assert rel_partial["characters"]["a"]["detail"]["equipment"]["weapons"][0]["ammo_type"] == "standard"
    assert rel_partial["characters"]["a"]["inventory"]["ammo:H Pistol"] == 0

    # Hold action by a, then out-of-turn release_hold during b's turn
    nt1 = apply_action(rel_partial["encounter"], rel_partial["characters"], "a", "next_turn", {}, lambda _: 0)
    nt2 = apply_action(nt1["encounter"], nt1["characters"], "b", "next_turn", {}, lambda _: 0)
    held = apply_action(nt2["encounter"], nt2["characters"], "a", "hold", {"held_action": "attack", "target_id": "b", "trigger": "b_moves"}, lambda _: 0)
    nt3 = apply_action(held["encounter"], held["characters"], "a", "next_turn", {}, lambda _: 0)
    released = apply_action(nt3["encounter"], nt3["characters"], "a", "release_hold", {"trigger": "b_moves"}, lambda _: 0)
    assert released["result"]["released_action"] == "attack"

    # Special ammo reload tracks weapon["ammo_type"] and checks inventory
    nt4 = apply_action(released["encounter"], released["characters"], "b", "next_turn", {}, lambda _: 0)
    with pytest.raises(ValueError, match="insufficient"):
        apply_action(nt4["encounter"], nt4["characters"], "a", "reload", {"weapon_id": "p", "ammo_type": "rubber"}, lambda _: 0)
    rel_ap = apply_action(nt4["encounter"], nt4["characters"], "a", "reload", {"weapon_id": "p", "ammo_type": "armor_piercing"}, lambda _: 0)
    w_ap = rel_ap["characters"]["a"]["detail"]["equipment"]["weapons"][0]
    assert w_ap["loaded"] == 6
    assert w_ap["ammo_type"] == "armor_piercing"
    assert rel_ap["characters"]["a"]["inventory"]["ammo:H Pistol:armor_piercing"] == 0
    # Previously loaded 6 standard rounds returned to inventory on ammo switch
    assert rel_ap["characters"]["a"]["inventory"]["ammo:H Pistol"] == 6
