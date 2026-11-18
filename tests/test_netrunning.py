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
    assert out["result"]["check"]["total"] == 5
    assert not out["result"]["check"]["success"]
    assert out["architecture"]["floors"][0]["type"] == "password"


def test_slide_once_each_turn():
    r, a = setup_run()
    r.update(connected=True, floor_id=2)
    args = {"ice_floor_id": 2}
    out = netrunning.apply_action(r, a, "slide", args, fixed(9))
    assert out["result"]["escaped"]
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
    started = netrunning.apply_action(active["run"], active["architecture"], "virus_start", {"virus": {"description": "disable node", "dv": 5, "actions_required": 2}})
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
