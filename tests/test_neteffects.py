import copy

from neteffects import resolve_effect


def run(*programs, hardware=()):
    return {"deck": {"programs": [dict(instance_id=str(i), name=n, type=t, active=a, rez=r,
                                            max_rez=r, destroyed=False)
                                      for i, (n, t, a, r) in enumerate(programs)],
                          "hardware": list(hardware)}, "conditions": {}}


def fixed(value):
    return lambda stop: value


def test_brain_damage_armor_shield_and_input_is_immutable():
    state = run(("Armor", "Defender", True, 7), ("Shield", "Defender", True, 7))
    before = copy.deepcopy(state)
    # Vrizzbolt is an Anti-Personnel Attacker (runner vs runner), so black_ice=False
    result = resolve_effect("Vrizzbolt", state, randbelow=fixed(0), black_ice=False)
    assert result["dice"] == [1]
    assert result["character_effects"][0]["amount"] == 0
    assert result["run"]["deck"]["programs"][1]["rez"] == 0
    assert state == before


def test_fire_and_insulated_wiring():
    plain = resolve_effect("Hellbolt", run(), randbelow=fixed(5))
    insulated = resolve_effect("Hellhound", run(hardware=("Insulated Wiring",)), randbelow=fixed(5))
    assert plain["character_effects"][-1]["amount"] == 2
    assert len(insulated["character_effects"]) == 1


def test_random_program_destruction_and_hardened_circuitry():
    state = run(("Tool", "Defender", True, 7), ("Other", "Attacker", True, 3))
    destroyed = resolve_effect("Poison Flatline", state, randbelow=fixed(1))
    assert destroyed["run"]["deck"]["programs"][1]["destroyed"]
    state["deck"]["hardware"].append("Hardened Circuitry")
    result = resolve_effect("Poison Flatline", state, randbelow=fixed(0))
    assert not result["run"]["deck"]["programs"][0]["destroyed"]
    assert result["run"]["deck"]["programs"][0]["rez"] == 0


def test_attack_needs_valid_program_target_and_applies_damage():
    state = run(("target", "Black ICE", True, 20))
    missing = resolve_effect("Killer", state, randbelow=fixed(0))
    assert missing["requires_human_ruling"]
    result = resolve_effect("Killer", state, target_program_id="0", randbelow=fixed(5))
    assert result["dice"] == [6] * 4
    assert result["run"]["deck"]["programs"][0]["destroyed"]


def test_exit_and_typed_conditions():
    giant = resolve_effect("Giant", run(), randbelow=fixed(0))
    assert giant["forced_exit"] == {"safe": False, "exclude_self": True, "program": "Giant"}
    nerves = resolve_effect("Nervescrub", run(), randbelow=fixed(2))
    assert [e["value"] for e in nerves["character_effects"]] == [3, 3, 3]
    assert all(e["type"] == "condition" for e in nerves["character_effects"])