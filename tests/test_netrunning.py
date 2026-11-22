import copy

import pytest

import netrunning


def setup_run(programs=()):
    arch = netrunning.create_architecture([
        {"id": 1, "type": "password", "dv": 5, "adjacent": [2]},
        {"id": 2, "type": "ice", "ice": "Giant", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "x"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 4, {"capacity": 7, "programs": list(programs)}, arch, "ap", 2)
    return run, arch


def fixed(*values):
    seq = iter(values)
    return lambda n: next(seq, 0)


def test_budget_and_input_isolation():
    r, a = setup_run()
    original = copy.deepcopy((r, a))
    out = netrunning.apply_action(r, a, "jack_in", randbelow=fixed(0))
    assert out["run"]["actions_remaining"] == 2
    assert (r, a) == original
    assert netrunning.apply_action(out["run"], out["architecture"], "new_turn")["run"]["actions_remaining"] == 3


def test_backdoor_requires_strict_success():
    r, a = setup_run()
    r["connected"] = True
    out = netrunning.apply_action(r, a, "backdoor", {"floor_id": 1}, randbelow=fixed(0))
    # interface=4, randbelow=0 -> die=1 (crit fail), further=0 -> die=1, critical_adjustment=-1
    # total = base(4) + 1 + (-1) + 0 = 4
    assert out["result"]["check"]["total"] == 4
    assert not out["result"]["check"]["success"]
    assert out["architecture"]["floors"][0]["type"] == "password"


def test_slide_once_each_turn():
    r, a = setup_run()
    # Use interface 8 (budget 3) so we have enough actions: jack_in(1), backdoor(1), move(1), slide(1) = 4 > 3
    # Actually need interface 10 (budget 4) or just do fewer actions
    # Let's use interface 10 and manually set up the encounter
    arch = netrunning.create_architecture([
        {"id": 1, "type": "password", "dv": 5, "adjacent": [2]},
        {"id": 2, "type": "ice", "ice": "Giant", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "x"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 10, {"capacity": 7, "programs": []}, arch, "ap", 2)
    # Jack in, pass password, move to ICE floor to trigger encounter
    out = netrunning.apply_action(run, arch, "jack_in", randbelow=fixed(0))
    run, arch = out["run"], out["architecture"]
    out = netrunning.apply_action(run, arch, "backdoor", {"floor_id": 1}, randbelow=fixed(9))
    run, arch = out["run"], out["architecture"]
    out = netrunning.apply_action(run, arch, "move", {"floor_id": 2}, randbelow=fixed(0, 9))
    run, arch = out["run"], out["architecture"]
    # Now slide from floor 2 to floor 3 (file) - adjacent
    args = {"ice_floor_id": 2, "floor_id": 3}
    out = netrunning.apply_action(run, arch, "slide", args, fixed(9, 0, 0, 0))
    assert out["result"]["escaped"]
    # Second slide in same turn should fail (slide_used=True)
    out2 = netrunning.apply_action(out["run"], out["architecture"], "slide", args)
    assert not out2["result"]["success"]


def test_ice_encounter_and_unsafe_exit_effects():
    r, a = setup_run()
    r.update(connected=True, floor_id=1)
    r["passed_passwords"] = [1]
    out = netrunning.apply_action(r, a, "move", {"floor_id": 2}, fixed(0, 9))
    assert out["encounter_effects"]
    exit_result = netrunning.apply_action(out["run"], out["architecture"], "jack_out")
    assert exit_result["character_effects"] == []
    unsafe = netrunning.apply_action(out["run"], out["architecture"], "move", {"distance": 7})
    assert unsafe["result"]["unsafe_effects"][0]["name"] == "Giant"


def test_program_lifecycle_and_virus_survives_exit():
    r, a = setup_run(["See Ya"])
    r.update(connected=True, floor_id=3)
    active = netrunning.apply_action(r, a, "activate_program", {"instance_id": "p0"})
    assert active["run"]["deck"]["programs"][0]["active"]
    fail = netrunning.apply_action(active["run"], active["architecture"], "activate_program", {"instance_id": "p0"})
    assert not fail["result"]["success"]
    started = netrunning.apply_action(active["run"], active["architecture"], "virus_start", {"virus": {"description": "disable node", "dv": 5, "actions_required": 3}})
    refreshed = netrunning.apply_action(started["run"], started["architecture"], "new_turn")
    partial = netrunning.apply_action(refreshed["run"], refreshed["architecture"], "virus_work")
    worked = netrunning.apply_action(partial["run"], partial["architecture"], "virus_work", randbelow=fixed(9))
    assert len(worked["architecture"]["viruses"]) == 1
    exited = netrunning.apply_action(worked["run"], worked["architecture"], "jack_out")
    assert len(exited["architecture"]["viruses"]) == 1


def test_deck_rejects_noncanonical_metadata_and_capacity():
    _, a = setup_run()
    with pytest.raises(ValueError):
        netrunning.create_run("c", 1, {"capacity": 1, "programs": ["Giant"]}, a, "ap", 1)
    with pytest.raises(ValueError):
        netrunning.create_run("c", 1, {"capacity": 7, "programs": [{"name": "Armor", "atk": 99}]}, a, "ap", 1)


def test_kraken_and_superglue_blocks_move_slide_jack_out_and_expires_in_new_turn():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2]},
        {"id": 2, "type": "ice", "ice": "Kraken", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "data"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 8, {"capacity": 7, "programs": []}, arch, "ap", 2)
    run["connected"] = True
    run["floor_id"] = 2
    arch["floors"][1]["ice"]["pursuing"] = True
    run["encountered_ice"] = [2]
    # Kraken hits on ice_turn (attacker=8 vs def=8; attacker rolls 9->10, defender rolls 0->1)
    hit = netrunning.apply_action(run, arch, "ice_turn", {"ice_floor_id": 2}, randbelow=fixed(9, 0, 0, 0))
    r_blocked, a_blocked = hit["run"], hit["architecture"]
    assert r_blocked["conditions"]["cannot_move"] is True
    assert r_blocked["conditions"]["cannot_jack_out"] is True
    assert not netrunning.apply_action(r_blocked, a_blocked, "move", {"floor_id": 3})["result"]["success"]
    assert not netrunning.apply_action(r_blocked, a_blocked, "slide", {"ice_floor_id": 2, "floor_id": 3})["result"]["success"]
    assert not netrunning.apply_action(r_blocked, a_blocked, "jack_out")["result"]["success"]

    # After 1 new_turn: still blocked (turns 2 -> 1)
    t1 = netrunning.apply_action(r_blocked, a_blocked, "new_turn")
    assert t1["run"]["conditions"]["cannot_move_turns"] == 1
    assert not netrunning.apply_action(t1["run"], t1["architecture"], "move", {"floor_id": 3})["result"]["success"]
    assert not netrunning.apply_action(t1["run"], t1["architecture"], "jack_out")["result"]["success"]

    # Unsafe exit still allowed while safe jack_out is blocked
    unsafe = netrunning.apply_action(t1["run"], t1["architecture"], "move", {"distance": 7})
    assert unsafe["run"]["connected"] is False
    assert unsafe["result"]["unsafe_effects"][0]["name"] == "Kraken"

    # After 2nd new_turn: block clears completely
    t2 = netrunning.apply_action(t1["run"], t1["architecture"], "new_turn")
    assert "cannot_move" not in t2["run"]["conditions"]
    assert "cannot_jack_out" not in t2["run"]["conditions"]
    assert netrunning.apply_action(t2["run"], t2["architecture"], "jack_out")["result"]["success"]


def test_skunk_slide_penalty_and_clear_on_derez():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2]},
        {"id": 2, "type": "ice", "ice": "Skunk", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "loot"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 4, {"capacity": 7, "programs": []}, arch, "ap", 2)
    run.update(connected=True, floor_id=2, discovered=[1, 2])
    arch["floors"][1]["ice"]["pursuing"] = True
    run["encountered_ice"] = [2]
    # Runner interface 4 + die 5 (rb=4) = 9, Skunk per 2 + die 5 (rb=4) = 7; with -2 Skunk penalty: 7 vs 7 (tie -> ICE wins!)
    slide = netrunning.apply_action(run, arch, "slide", {"ice_floor_id": 2, "floor_id": 3}, randbelow=fixed(4, 4))
    assert slide["result"]["check"]["attacker"]["modifier"] == -2
    assert not slide["result"].get("escaped")

    # Derez Skunk with zap -> clears slide_penalty
    run["conditions"]["slide_penalty"] = -2
    run["actions_remaining"] = 3
    arch["floors"][1]["ice"]["rez"] = 1
    zapped = netrunning.apply_action(run, arch, "zap", {"target_floor_id": 2}, randbelow=fixed(8, 1, 5))
    assert zapped["architecture"]["floors"][1]["ice"]["rezzed"] is False
    assert "slide_penalty" not in zapped["run"]["conditions"]


def test_unsafe_jack_out_clears_ice_and_passwords():
    r, a = setup_run()
    r.update(connected=True, floor_id=1, passed_passwords=[1])
    entered = netrunning.apply_action(r, a, "move", {"floor_id": 2}, fixed(0, 9))
    unsafe = netrunning.apply_action(entered["run"], entered["architecture"], "move", {"distance": 7})
    ur, ua = unsafe["run"], unsafe["architecture"]
    assert ur["connected"] is False
    assert ur["encountered_ice"] == []
    assert ur["passed_passwords"] == []
    assert ua["floors"][1]["ice"]["pursuing"] is False
    assert ua["floors"][1]["ice"]["encountered"] is False


def test_pathfinder_cyclic_graph_and_password_only_obstruction():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2, 3]},
        {"id": 2, "type": "control", "dv": 20, "control": {"device": "cam"}, "adjacent": [1, 3]},
        {"id": 3, "type": "ice", "ice": "Skunk", "dv": 20, "adjacent": [1, 2, 4]},
        {"id": 4, "type": "password", "dv": 20, "adjacent": [3, 5]},
        {"id": 5, "type": "file", "dv": 0, "file": {"name": "secret"}, "adjacent": [4]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 6, {"capacity": 7, "programs": ["See Ya"]}, arch, "ap", 2)
    run.update(connected=True, floor_id=1, discovered=[1])
    act = netrunning.apply_action(run, arch, "activate_program", {"instance_id": "p0"})
    # interface 6 + See Ya 2 + die 5 (rb=4) = 13 (< 20, so stops ONLY at password 4, NOT at control 2 or ice 3)
    pf = netrunning.apply_action(act["run"], act["architecture"], "pathfinder", randbelow=fixed(4))
    assert pf["result"]["check"]["modifier"] == 2
    assert set(pf["run"]["discovered"]) == {1, 2, 3, 4}
    assert 5 not in pf["run"]["discovered"]

    # Once password 4 is passed, pathfinder continues past 4 to reveal 5
    pf["run"]["passed_passwords"].append(4)
    pf2 = netrunning.apply_action(pf["run"], pf["architecture"], "pathfinder", randbelow=fixed(4))
    assert 5 in pf2["run"]["discovered"]

    # Derezzed See Ya provides 0 bonus
    pf["run"]["deck"]["programs"][0]["rez"] = 0
    pf_dead = netrunning.apply_action(pf["run"], pf["architecture"], "pathfinder", randbelow=fixed(4))
    assert pf_dead["result"]["check"]["modifier"] == 0


def test_virus_start_requires_deepest_floor_and_password_retreat():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2]},
        {"id": 2, "type": "password", "dv": 10, "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "core"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 6, {"capacity": 7, "programs": []}, arch, "ap", 2)
    run.update(connected=True, floor_id=2)

    # Unpassed password blocks moving deeper to 3, but allows retreating back to 1
    deeper = netrunning.apply_action(run, arch, "move", {"floor_id": 3})
    assert not deeper["result"]["success"]
    assert deeper["result"]["blocked_by"] == "password"
    retreat = netrunning.apply_action(run, arch, "move", {"floor_id": 1})
    assert retreat["result"]["success"]
    assert retreat["run"]["floor_id"] == 1

    # Virus start fails on floor 1 or 2, succeeds on deepest floor 3
    v_args = {"virus": {"description": "wipe logs", "dv": 6, "actions_required": 1}}
    assert not netrunning.apply_action(retreat["run"], retreat["architecture"], "virus_start", v_args)["result"]["success"]
    run["floor_id"] = 3
    ok = netrunning.apply_action(run, arch, "virus_start", v_args, randbelow=fixed(8))
    assert ok["result"]["success"]
    assert len(ok["architecture"]["viruses"]) == 1


def test_speed_booster_and_cloak_eraser():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2]},
        {"id": 2, "type": "ice", "ice": "Giant", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "f"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 8, {"capacity": 7, "programs": ["Speedy Gonzalvez", "Eraser"]}, arch, "ap", 2)
    run.update(connected=True, floor_id=1)
    r1 = netrunning.apply_action(run, arch, "activate_program", {"instance_id": "p0"})
    r2 = netrunning.apply_action(r1["run"], r1["architecture"], "activate_program", {"instance_id": "p1"})
    clk = netrunning.apply_action(r2["run"], r2["architecture"], "cloak", randbelow=fixed(4))
    # interface 8 + die 5 + Eraser 2 = 15
    assert clk["result"]["check"]["modifier"] == 2
    assert clk["result"]["check"]["total"] == 15
    assert clk["run"]["cloak_dv"] == 15

    mv = netrunning.apply_action(clk["run"], clk["architecture"], "move", {"floor_id": 2}, randbelow=fixed(4, 4))
    assert mv["result"]["speed_check"]["check"]["attacker"]["modifier"] == 2
    sl = netrunning.apply_action(mv["run"], mv["architecture"], "slide", {"ice_floor_id": 2, "floor_id": 3}, randbelow=fixed(4, 4))
    assert sl["result"]["check"]["attacker"]["modifier"] == 2


def test_once_per_netrun_backup_drive_flak_superglue():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2]},
        {"id": 2, "type": "empty", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "f"}, "adjacent": [2]},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run(
        "c", 8,
        {"capacity": 10, "programs": ["Flak", "Flak", "Superglue", "Sword"], "hardware": ["Backup Drive"]},
        arch, "ap", 2,
    )
    run.update(connected=True, floor_id=1)
    run["deck"]["programs"][3]["destroyed"] = True
    run["deck"]["programs"][3]["rez"] = 0

    # Backup Drive works once per Netrun
    b1 = netrunning.apply_action(run, arch, "backup_drive", {"instance_id": "p3"})
    assert b1["result"]["success"] and b1["result"]["restored"] == "p3"
    assert not b1["run"]["deck"]["programs"][3]["destroyed"]
    b1["run"]["deck"]["programs"][3]["destroyed"] = True
    b2 = netrunning.apply_action(b1["run"], b1["architecture"], "backup_drive", {"instance_id": "p3"})
    assert not b2["result"]["success"]

    # Flak works once per Netrun (even across deactivation or second copy)
    f1 = netrunning.apply_action(b2["run"], b2["architecture"], "activate_program", {"instance_id": "p0"})
    assert f1["result"]["success"]
    f_deact = netrunning.apply_action(f1["run"], f1["architecture"], "deactivate_program", {"instance_id": "p0"})
    f_turn = netrunning.apply_action(f_deact["run"], f_deact["architecture"], "new_turn")
    assert not netrunning.apply_action(f_turn["run"], f_turn["architecture"], "activate_program", {"instance_id": "p0"})["result"]["success"]
    assert not netrunning.apply_action(f_turn["run"], f_turn["architecture"], "activate_program", {"instance_id": "p1"})["result"]["success"]

    # Superglue works once per Netrun
    s1 = netrunning.apply_action(f_turn["run"], f_turn["architecture"], "activate_program", {"instance_id": "p2", "target_interface": 2}, randbelow=fixed(5, 2, 1))
    assert s1["result"]["success"]
    s_turn = netrunning.apply_action(s1["run"], s1["architecture"], "new_turn")
    assert not netrunning.apply_action(s_turn["run"], s_turn["architecture"], "activate_program", {"instance_id": "p2", "target_interface": 2})["result"]["success"]


def test_move_distance_and_branch_validation():
    arch = netrunning.create_architecture([
        {"id": 1, "type": "empty", "adjacent": [2, 4]},
        {"id": 2, "type": "empty", "adjacent": [1, 3]},
        {"id": 3, "type": "file", "dv": 0, "file": {"name": "a"}, "adjacent": [2]},
        {"id": 4, "type": "password", "dv": 10, "adjacent": [1, 5]},
        {"id": 5, "type": "file", "dv": 0, "file": {"name": "b"}, "adjacent": [4]},
        {"id": 6, "type": "empty", "adjacent": []},
    ], [{"id": "ap", "floor_id": 1}])
    run = netrunning.create_run("c", 6, {"capacity": 7, "programs": []}, arch, "ap", 2)
    run.update(connected=True, floor_id=1)

    assert not netrunning.apply_action(run, arch, "move", {"floor_id": 6})["result"]["success"]
    assert not netrunning.apply_action(run, arch, "move", {"floor_id": 99})["result"]["success"]
    assert not netrunning.apply_action(run, arch, "move", {"floor_id": 5})["result"]["success"]
    # Clear multi-hop path 1 -> 2 -> 3 succeeds
    ok = netrunning.apply_action(run, arch, "move", {"floor_id": 3})
    assert ok["result"]["success"]
    assert ok["run"]["floor_id"] == 3


def test_solo_net_step_empty_anti_program_target_and_solo_summary_unwrap(tmp_path):
    from contextlib import closing
    from campaign import STAT_NAMES
    from gameplay import GameplayService
    from turn_engine.engine import TurnEngine

    gp = GameplayService(tmp_path / "net.sqlite")
    camp = gp.execute("create_campaign", {"name": "Net Op", "operation_id": "op-camp"})["result"]
    pc = gp.execute(
        "create_character",
        {
            "name": "Zero",
            "stats": dict.fromkeys(STAT_NAMES, 6),
            "skills": {"Interface": 4},
            "operation_id": "op-pc",
        },
    )["result"]
    gp.execute(
        "attach_character",
        {"campaign_id": camp["id"], "character_id": pc["id"], "expected_revision": camp["revision"], "reason": "join", "operation_id": "op-att"},
    )
    pc_now = gp.store.get_character(pc["id"])
    pc_now["detail"]["roles"] = [{"role": "Netrunner", "rank": 4}]
    pc_now["detail"]["deck"] = {"capacity": 7, "programs": [], "hardware": []}
    with closing(gp.store._connect()) as conn, conn:
        gp.solo._write_character(conn, pc_now)

    svc = gp.solo
    arch_res = svc.execute(
        "create_architecture",
        {
            "floors": [
                {"id": 1, "type": "empty", "adjacent": [2]},
                {"id": 2, "type": "ice", "ice": "Killer", "adjacent": [1]},
            ],
            "access_points": [{"id": "ap1", "floor_id": 1}],
            "operation_id": "op-arch",
            "reason": "arch",
            "expected_revision": 0,
        },
        camp["id"],
    )
    arch_id = arch_res["result"]["architecture_id"]
    run_res = svc.execute(
        "start_netrun",
        {
            "character_id": pc["id"],
            "architecture_id": arch_id,
            "access_point_id": "ap1",
            "distance": 2,
            "operation_id": "op-run",
            "reason": "jack in",
            "expected_revision": 1,
        },
        camp["id"],
    )
    run_id = run_res["result"]["run_id"]
    svc.execute(
        "net_action",
        {
            "run_id": run_id,
            "action": "jack_in",
            "operation_id": "op-ji",
            "reason": "enter",
            "expected_revision": 2,
        },
        camp["id"],
        randbelow=fixed(0),
    )
    # Move onto Killer floor with empty deck -> must commit cleanly without crashing or rolling back
    mv = svc.execute(
        "net_action",
        {
            "run_id": run_id,
            "action": "move",
            "arguments": {"floor_id": 2},
            "operation_id": "op-mv",
            "reason": "move to killer",
            "expected_revision": 3,
        },
        camp["id"],
        randbelow=fixed(0, 9),
    )
    assert mv["committed"] is True
    assert mv["result"]["view"]["run"]["floor_id"] == 2

    # Advance encounter turn -> Killer ice_turn runs with 0 active programs -> commits cleanly
    nt = svc.execute(
        "encounter_action",
        {
            "action": "next_turn",
            "actor_id": pc["id"],
            "operation_id": "op-nt",
            "reason": "ice turn",
            "expected_revision": 4,
        },
        camp["id"],
        randbelow=fixed(0),
    )
    assert nt["committed"] is True

    # Verify TurnEngine._solo_summary unwraps nested solo.runtime.runs[id].run
    full_ctx = gp.campaign_context(camp["id"])
    summary = TurnEngine(gp, object())._solo_summary(full_ctx)
    assert run_id in summary["active_runs"]
    assert summary["active_runs"][run_id]["connected"] is True
    assert summary["active_runs"][run_id]["floor"] == 2
    assert isinstance(summary["active_runs"][run_id]["actions_remaining"], int)

