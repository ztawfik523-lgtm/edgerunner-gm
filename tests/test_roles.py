import pytest

import roles


def character(role, rank=4, ip=0):
    return {"stats": {}, "skills": {}, "hp": 20, "max_hp": 20, "humanity": 40,
            "money": 0, "inventory": [], "detail": {"roles": [{"role": role, "rank": rank, "choices": {}}], "ip": ip}}


def fixed(n):
    return lambda sides: n - 1


def test_role_choice_helper_is_explicit_about_unresolved_choice_catalog():
    # Tech requires pairs of specialties at each rank. Empty list is invalid.
    with pytest.raises(ValueError): roles.validate_role_choices("Tech", 4, {"maker": []})
    # Valid pairs: 4 ranks * 2 specialties = 8 total, as pairs
    result = roles.validate_role_choices("Tech", 4, {"maker": [["Field Expertise", "Upgrade Expertise"], ["Fabrication Expertise", "Invention Expertise"], ["Field Expertise", "Fabrication Expertise"], ["Upgrade Expertise", "Invention Expertise"]]})
    assert result["valid"] and not result["requires_human_ruling"]
    with pytest.raises(ValueError): roles.validate_role_choices("Unknown", 4, {})
    with pytest.raises(ValueError): roles.validate_role_choices("Solo", 11, {})


def test_solo_allocation_is_bounded_and_pure():
    original = character("Solo")
    changed = roles.apply_action(original, "solo_allocate", {"allocation": {"initiative_reaction": 4}}, fixed(1))
    assert changed["character"]["detail"]["solo_allocation"] == {"initiative_reaction": 4}
    assert "solo_allocation" not in original["detail"]
    with pytest.raises(ValueError): roles.apply_action(original, "solo_allocate", {"allocation": {"initiative_reaction": 5}})


def test_rocker_check_strict_dv_success_and_failure_lock():
    c = character("Rockerboy")
    # rocker_convert: rank=4, dv=8 (single). Need roll > 8. roll = rank + _die. _die = randbelow(10)+1.
    # fixed(5) -> randbelow=4 -> _die=5 -> roll=9 > 8 = success
    success = roles.apply_action(c, "rocker_convert", {"target_eligible": True, "group_size": "single"}, fixed(5))
    assert success["result"]["total"] == 9 and success["result"]["success"]
    # rocker_favor: rank=4, dv=10 (small). fixed(3) -> randbelow=2 -> _die=3 -> roll=7 > 10 = False
    failure = roles.apply_action(c, "rocker_favor", {"scope_approved": True, "group_size": "small", "group_id": "x", "now_minutes": 0}, fixed(3))
    assert not failure["result"]["success"]
    assert failure["character"]["detail"]["favor_locks"]["x"] == 10080


def test_ip_costs_ties_and_multiclass_gate():
    c = character("Solo", 4, 540)
    promoted = roles.apply_action(c, "spend_ip_role", {"role": "Solo"})
    assert promoted["result"]["rank"] == 5 and promoted["result"]["cost"] == 300
    # Rank 4 permits multiclassing; rank 1 costs 60 IP.
    c["detail"]["ip"] = 60
    multi = roles.apply_action(c, "spend_ip_role", {"role": "Nomad", "choices": {"moto": ["vehicle"]}})
    assert multi["character"]["detail"]["roles"][-1]["role"] == "Nomad"
    assert multi["result"]["rank"] == 1 and multi["result"]["cost"] == 60


def test_skill_ip_pricing_and_human_ruling_no_mutation():
    c = character("Tech", 4, 80)
    c["skills"]["Athletics"] = 3
    spent = roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 3})
    assert spent["result"]["cost"] == 80 and spent["character"]["detail"]["ip"] == 0
    # lawman_backup on non-Lawman raises ValueError (no Lawman rank)
    with pytest.raises(ValueError, match="no Lawman rank"):
        roles.apply_action(c, "lawman_backup", {})


def test_solo_precision_cost_and_fumble_boolean_allocation():
    c = character("Solo")
    assert roles.apply_action(c, "solo_allocate", {"allocation": {"precision_attack": 1}})["result"]["spent"] == 3
    with pytest.raises(ValueError): roles.apply_action(c, "solo_allocate", {"allocation": {"fumble_recovery": 2}})


def test_lawman_backup_exact_roll_and_rounds():
    c = character("Lawman", 4)
    # success_roll: randbelow(10) -> need <= 4 for success at rank 4. Use 3 -> success_roll=4 <= 4 = True
    # rounds: randbelow(6) -> need 5 for rounds=6. Use 5 -> rounds=6
    # Sequence: success_roll randbelow=3, rounds randbelow=5
    seq = iter([3, 5])
    result = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: next(seq))
    assert result["result"]["success"] and result["result"]["arrival_rounds"] == 6
    assert result["result"]["tier"] == 5


def test_stored_skill_rank_controls_ip_upgrade():
    c = character("Solo", ip=80)
    c["skills"]["Athletics"] = 3
    with pytest.raises(ValueError): roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 2})
    spent = roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics", "current_rank": 3})
    assert spent["result"]["rank"] == 4


def test_lawman_backup_failure_and_tier_10_two_groups():
    c = character("Lawman", 4)
    fail = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: 9)
    assert fail["result"]["success"] is False
    c = character("Lawman", 10)
    success = roles.apply_action(c, "lawman_backup", {"in_danger": True}, lambda sides: 0 if sides == 10 else 5)
    assert success["result"]["arrival_rounds"] == 6
    assert success["result"]["groups"] == 2 and success["result"]["tier"] == 10


def test_media_passive_rumor_limited_twice_weekly():
    c = character("Media")
    one = roles.apply_action(c, "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))
    assert one["result"]["total"] == 12 and one["result"]["rumor"] == "Vague"
    two = roles.apply_action(one["character"], "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))
    with pytest.raises(ValueError): roles.apply_action(two["character"], "media_rumor", {"rumor": "Vague", "week": 3}, fixed(8))


def test_fix_haggle_failure_does_not_grant_terms():
    c = character("Fixer", 10)
    c["stats"]["COOL"] = 2
    c["skills"]["Trading"] = 2
    # Fixer: roll=1 (crit fail, further=10 -> -10). Opponent: roll=10 (crit success, further=10 -> +10).
    # Fixer total = 2+2+1-10 = -5. Opponent total = 10+10+10+10 = 40. Fixer loses.
    seq = iter([0, 9, 9, 9])
    result = roles.apply_action(c, "fixer_haggle", {"transaction_id": "t1", "opponent_gm_approved": True,
        "opponent": {"COOL": 10, "Trading": 10}, "deal": "discount_10"}, lambda sides: next(seq))
    assert result["result"]["success"] is False and result["result"]["terms"] is None


def test_exec_1d6_loyalty_natural_1_and_negative_loyalty_betrayal():
    c = character("Exec", 4)
    c["detail"]["team"] = [{"id": "m1", "name": "Kaito", "role": "Bodyguard", "loyalty": 4}]
    seen_sides = []

    def d6_four(sides):
        seen_sides.append(sides)
        return 3  # die = 4 (fails < 4, passes if 1d6 wasn't 1d10)

    res = roles.apply_action(c, "exec_team", {"member_id": "m1", "task": "Hold the door"}, d6_four)
    assert seen_sides == [6]
    assert res["result"]["die"] == 4
    assert res["result"]["success"] is False

    # Natural 1 sets leave_after_job / resigned
    nat1 = roles.apply_action(c, "exec_team", {"member_id": "m1", "task": "Hold the door"}, lambda sides: 0)
    assert nat1["result"]["die"] == 1
    assert nat1["result"]["success"] is True
    assert nat1["result"]["leave_after_job"] is True
    assert nat1["character"]["detail"]["team"][0]["leave_after_job"] is True
    assert nat1["character"]["detail"]["team"][0]["resigned"] is True

    # Negative loyalty table entries & betrayal when loyalty <= 0
    betrayed = roles.apply_action(c, "exec_change_loyalty", {"member_id": "m1", "reason": "endanger"})
    assert betrayed["result"]["loyalty"] == -2
    assert betrayed["result"]["betrayed"] is True
    assert betrayed["result"]["resigned"] is True
    assert betrayed["character"]["detail"]["team"][0]["betrayed"] is True


def test_medtech_synthesize_inventory_wound_penalty_and_clock():
    c = character("Medtech", 4)
    c["stats"] = {"TECH": 8, "MOVE": 6}
    c["skills"] = {"Medical Tech": 6}
    c["money"] = 500
    c["hp"] = 5
    c["max_hp"] = 30  # Seriously Wounded (-2)
    c["detail"]["roles"] = [{"role": "Medtech", "rank": 4, "choices": {"medicine": {"Pharmaceuticals": 2, "Surgery": 1, "Cryosystem Operation": 1}, "recipes": ["Speedheal", "Stim"]}}]

    # 8 + 6 + 2(die) - 2(wound) = 14 > 13 -> succeeds; 6 doses stored in both inventory & detail
    ok = roles.apply_action(c, "medtech_synthesize", {"recipe": "Speedheal"}, fixed(2))
    assert ok["result"]["doses"] == 6
    assert ok["character"]["inventory"]["pharma:Speedheal"] == 6
    assert ok["character"]["detail"]["pharmaceuticals"]["Speedheal"] == 6
    assert ok["character"]["detail"]["clock_minutes"] == 60
    assert ok["character"]["money"] == 300


def test_solo_allocate_wires_with_rules_eval():
    import rules_eval

    c = character("Solo", 7)
    c["stats"] = {"REF": 7, "INT": 6}
    c["skills"] = {"Handgun": 5}
    allocated = roles.apply_action(c, "solo_allocate", {"allocation": {"precision_attack": 1, "fumble_recovery": 1}})
    char_after = allocated["character"]
    ctx = rules_eval.effective_check_context(char_after, "REF", "Handgun", tags=("attack", "ranged"))
    assert ctx["solo_bonus"] == 1
    assert ctx["fumble_recovery"] is True


def test_tech_project_derives_price_category_enforces_working_and_writes_inventory():
    c = character("Tech", 4)
    c["stats"] = {"TECH": 8}
    c["skills"] = {"Handgun": 6}
    c["money"] = 500
    c["inventory"] = {}
    c["detail"]["roles"] = [{
        "role": "Tech",
        "rank": 4,
        "choices": {
            "maker": [["Field Expertise", "Upgrade Expertise"], ["Fabrication Expertise", "Invention Expertise"], ["Field Expertise", "Fabrication Expertise"], ["Upgrade Expertise", "Invention Expertise"]],
            "maker_ranks": {"Field Expertise": 2, "Upgrade Expertise": 2, "Fabrication Expertise": 2, "Invention Expertise": 2},
        },
    }]
    c["detail"]["catalog_items"] = {
        "heavy_pistol": {"name": "Heavy Pistol", "cost": 100, "category": "weapon", "source_sha256": "abc123", "repair_skill": "Handgun"},
    }
    begun = roles.apply_action(c, "tech_project_begin", {"project_kind": "fabricate", "project_id": "fab-1", "item_id": "heavy_pistol"})
    assert begun["result"]["category"] == "Premium"
    assert begun["result"]["materials_paid"] == 50  # One category lower than Premium (100) is Costly (50)
    worked = roles.apply_action(begun["character"], "tech_project_work", {"project_id": "fab-1", "project_kind": "fabricate", "elapsed_minutes": 1440})
    assert worked["result"]["complete"] is True
    finished = roles.apply_action(worked["character"], "tech_project_finish", {"project_id": "fab-1", "project_kind": "fabricate"}, fixed(5))
    assert finished["result"]["state"] == "complete"
    assert finished["character"]["inventory"]["heavy_pistol"] == 1

    # Cannot advance or finish an already-completed project
    with pytest.raises(ValueError, match="working"):
        roles.apply_action(finished["character"], "tech_project_work", {"project_id": "fab-1", "project_kind": "fabricate", "elapsed_minutes": 60})
    with pytest.raises(ValueError, match="working"):
        roles.apply_action(finished["character"], "tech_project_finish", {"project_id": "fab-1", "project_kind": "fabricate"}, fixed(5))


def test_media_publish_setdefault_and_exploding_rocker_media_checks():
    m = character("Media", 4)
    pub = roles.apply_action(m, "media_publish", {"topic": "Corp Scandal", "evidence_count": 2, "evidence_verified": True}, fixed(2))
    assert pub["result"]["believed"] is True
    assert len(pub["character"]["detail"]["media"]["published_stories"]) == 1
    assert "Corp Scandal" in pub["character"]["detail"]["published_topics"]

    # Media rumor explodes on natural 10 (10 + 5 + rank 4 = 19 > 13 Detailed)
    seq = iter([9, 4])
    rumor = roles.apply_action(m, "media_rumor", {"rumor": "Detailed", "week": 1}, lambda s: next(seq))
    assert rumor["result"]["total"] == 19
    assert rumor["result"]["rumor"] == "Detailed"

    # Rockerboy Charismatic Impact fumbles on natural 1 (1 - 5 + rank 4 = 0)
    r = character("Rockerboy", 4)
    seq2 = iter([0, 4])
    fumble = roles.apply_action(r, "rocker_convert", {"target_eligible": True, "group_size": "single"}, lambda s: next(seq2))
    assert fumble["result"]["total"] == 0
    assert fumble["result"]["success"] is False


def test_spend_ip_zero_to_one_role_benefits_duplicate_medtech_and_nomad_upgrades():
    c = character("Tech", 4, ip=200)
    c["skills"] = {"Athletics": 0}
    # 0 -> 1 typical skill (20 IP) and unlisted difficult skill (0 -> 1, 40 IP)
    s1 = roles.apply_action(c, "spend_ip_skill", {"skill": "Athletics"})
    assert s1["result"]["rank"] == 1 and s1["result"]["cost"] == 20
    s2 = roles.apply_action(s1["character"], "spend_ip_skill", {"skill": "Martial Arts (Karate)"})
    assert s2["result"]["rank"] == 1 and s2["result"]["cost"] == 40

    # Duplicate Medtech recipe rejected
    med = character("Medtech", 4, ip=500)
    with pytest.raises(ValueError, match="duplicate"):
        roles.validate_role_choices("Medtech", 2, {"medicine": {"Pharmaceuticals": 2}, "recipes": ["Speedheal", "Speedheal"]})

    # Nomad vehicle validation & upgrade attachment
    nomad = character("Nomad", 10)
    nomad["money"] = 2000
    nomad["detail"]["family_motorpool"] = [{"id": "compact-groundcar", "name": "Compact Groundcar", "verified": True, "upgrades": []}]
    nomad["detail"]["active_vehicle"] = "compact-groundcar"
    nomad["detail"]["family_upgrades"] = [{"id": "nos", "name": "NOS (Nitrous Boost)", "verified": True}]
    with pytest.raises(ValueError, match="now_minutes"):
        roles.apply_action(nomad, "nomad_vehicle", {"mode": "repair_destroyed", "vehicle_id": "compact-groundcar", "now_minutes": -5})
    upg = roles.apply_action(nomad, "nomad_vehicle", {"mode": "purchase_upgrade", "upgrade_id": "nos"})
    assert "NOS (Nitrous Boost)" in upg["character"]["detail"]["family_motorpool"][0]["upgrades"]
