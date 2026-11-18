"""Pure role-ability and Improvement Point primitives (Cyberpunk RED Core Rulebook)."""
from __future__ import annotations

import copy
import secrets
from typing import Any, Callable
from mechanics import skill_check

ROLES = ("Rockerboy", "Solo", "Netrunner", "Tech", "Medtech", "Media", "Lawman", "Exec", "Fixer", "Nomad")
SOURCE_ROLES = "Cyberpunk RED Core Rulebook, pp. 142–163"
SOURCE_IP = "Cyberpunk RED Core Rulebook, pp. 408–411"
ROLE_IP_COST = {rank: rank * 60 for rank in range(1, 11)}
SKILL_IP_COST = {rank: rank * 20 for rank in range(1, 11)}
DIFFICULT_SKILL_IP_COST = {rank: rank * 40 for rank in range(1, 11)}
DIFFICULT_SKILLS = {"Autofire", "Demolitions", "Electronics/Security Tech", "Heavy Weapons", "Martial Arts", "Paramedic", "Pilot Air Vehicle"}
PHARMACEUTICALS = ("Antibiotic", "Rapidetox", "Speedheal", "Stim", "Surge")
PROJECTS = {"Cheap": (9, 60), "Everyday": (9, 60), "Costly": (13, 360), "Premium": (17, 1440), "Expensive": (21, 10080), "Very Expensive": (24, 20160), "Luxury": (29, 43200), "Super Luxury": (29, 43200)}


def _rank(value):
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError("rank must be an integer from 1 to 10")


def validate_role_choices(role: str, rank: int, choices: Any):
    """Validate supplied choice shape; source-dependent selections are never guessed."""
    if role not in ROLES: raise ValueError("unknown role")
    _rank(rank)
    if not isinstance(choices, (dict, list)): raise TypeError("choices must be an object or list")
    out = {"valid": True, "role": role, "rank": rank, "choices": copy.deepcopy(choices), "requires_human_ruling": False, "source": SOURCE_ROLES}
    if role in ("Solo", "Rockerboy", "Netrunner", "Media", "Lawman"):
        if choices not in ({}, []): raise ValueError(f"{role} has no rank-up choice in this role ability")
    elif role == "Tech":
        selected = choices.get("maker", []) if isinstance(choices, dict) else choices
        if not isinstance(selected, list): raise ValueError("maker must list Maker specialties")
        pairs = selected if all(isinstance(x, list) for x in selected) else None
        if pairs is not None:
            if len(pairs) != rank or any(len(pair) != 2 or pair[0] == pair[1] or any(v not in ("Field Expertise", "Upgrade Expertise", "Fabrication Expertise", "Invention Expertise") for v in pair) for pair in pairs): raise ValueError("choose two distinct Maker specialties at each role rank")
            selected = [v for pair in pairs for v in pair]
        elif len(selected) != rank * 2: raise ValueError("Tech gains two Maker specialty ranks per role rank")
        counts = {name: selected.count(name) for name in set(selected)}
        if any(count > rank for count in counts.values()): raise ValueError("specialty ranks cannot exceed Maker rank")
        out["maker_ranks"] = counts
    elif role == "Medtech":
        allocations = choices.get("medicine", {}) if isinstance(choices, dict) else None
        if not isinstance(allocations, dict) or set(allocations) - {"Surgery", "Pharmaceuticals", "Cryosystem Operation"}: raise ValueError("medicine must allocate to the three Medicine specialties")
        if any(type(v) is not int or v < 0 for v in allocations.values()) or sum(allocations.values()) != rank: raise ValueError("Medicine specialty points must total rank")
        if allocations.get("Pharmaceuticals", 0) > 5 or allocations.get("Cryosystem Operation", 0) > 5 or allocations.get("Surgery", 0) * 2 > 10: raise ValueError("Medicine specialty maximum exceeded")
        recipes = choices.get("recipes", []) if isinstance(choices, dict) else []
        pharma = allocations.get("Pharmaceuticals", 0)
        if not isinstance(recipes, list) or len(recipes) != pharma or any(x not in PHARMACEUTICALS for x in recipes): raise ValueError("choose one canonical pharmaceutical recipe per Pharmaceuticals point")
        out["initial_benefits"] = {"Surgery": allocations.get("Surgery", 0) * 2, "Medical Tech": pharma + allocations.get("Cryosystem Operation", 0), "pharmaceuticals": list(recipes)}
    elif role == "Exec":
        team = choices.get("team_member") if isinstance(choices, dict) else None
        if rank >= 3 and not isinstance(team, dict): raise ValueError("Exec team member choice required from rank 3")
        out["requires_human_ruling"] = True
        out["reason"] = "Team member's job-chart results and GM-controlled character details require adjudication."
    elif role == "Fixer":
        if not isinstance(choices, dict) or not isinstance(choices.get("language"), str) or not isinstance(choices.get("culture"), str): raise ValueError("Fixer choice requires language and culture")
    elif role == "Nomad":
        selected = choices.get("moto", []) if isinstance(choices, dict) else choices
        if not isinstance(selected, list) or len(selected) != rank or any(not isinstance(x, (str, dict)) for x in selected): raise ValueError("Nomad must select one Moto vehicle/upgrade option per rank")
        out["requires_human_ruling"] = True
        out["reason"] = "Vehicle and upgrade catalog validation is not available in this extract."
    return out


def _die(randbelow):
    if not callable(randbelow): raise TypeError("randbelow must be callable")
    n = randbelow(10)
    if type(n) is not int or not 0 <= n <= 9: raise ValueError("randbelow must return an integer in [0, 9]")
    return n + 1


def _role_data(ch):
    ext = ch.get("detail", ch)
    acq = ext.get("roles", [])
    if not isinstance(acq, list): raise ValueError("roles must be an ordered list")
    return ext, acq


def _active_rank(ch, role):
    ext, acq = _role_data(ch)
    return next((x.get("rank", 0) for x in reversed(acq) if x.get("role") == role), 0)


def _ruling(action, reason):
    return {"requires_human_ruling": True, "action": action, "reason": reason, "source": SOURCE_ROLES}


def _check(ch, skill_name, bonus, dv, randbelow):
    stats, skills = ch.get("stats", {}), ch.get("skills", {})
    if "TECH" not in stats or skill_name not in skills: raise ValueError("required TECH stat or stored skill is missing")
    return skill_check(stats["TECH"], skills[skill_name], dv, modifier=bonus, randbelow=randbelow)


def apply_action(character: dict, action: str, args: dict, randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    if not isinstance(character, dict) or not isinstance(args, dict): raise TypeError("character and args must be objects")
    ch = copy.deepcopy(character)
    ext, acquisitions = _role_data(ch)
    if action == "award_ip":
        amount, reason = args.get("amount"), args.get("reason")
        if type(amount) is not int or amount < 0 or not isinstance(reason, str) or not reason.strip(): raise ValueError("amount and explicit GM reason required")
        ext["ip"] = ext.get("ip", 0) + amount
        result = {"awarded": amount, "reason": reason, "ip": ext["ip"], "source": SOURCE_IP}
    elif action in ("spend_ip_skill", "spend_ip_role"):
        kind = args.get("kind", "typical")
        if action == "spend_ip_role":
            role = args.get("role")
            if role not in ROLES: raise ValueError("unknown role")
            current = _active_rank(ch, role); nxt = current + 1; _rank(nxt)
            cost = ROLE_IP_COST[nxt]
            latest = acquisitions[-1] if acquisitions else None
            if current == 0 and latest and latest.get("rank", 0) < 4: raise ValueError("latest acquired role must reach rank 4 before multiclassing")
            if current == 0 and latest is None: raise ValueError("initial role is created at rank 4 by character creation, not Improvement Point advancement")
            choices = args.get("choices", {})
            checked = validate_role_choices(role, nxt, choices)
            stored_choices = copy.deepcopy(choices)
            if role == "Tech" and isinstance(stored_choices, dict): stored_choices["maker_ranks"] = checked["maker_ranks"]
            if current == 0: acquisitions.append({"role": role, "rank": nxt, "choices": stored_choices})
            else:
                found = next(x for x in acquisitions if x.get("role") == role); found["rank"] = nxt; found["choices"] = stored_choices
            result = {"role": role, "rank": nxt, "cost": cost, "choice_validation": checked}
        else:
            skill = args.get("skill")
            skills = ch.get("skills", {})
            if not isinstance(skill, str) or skill not in skills: raise ValueError("skill must already exist in the character's skill map")
            current = skills[skill]
            if type(current) is not int or not 0 <= current < 10: raise ValueError("stored skill rank must be 0..9")
            if "current_rank" in args and args["current_rank"] != current: raise ValueError("current_rank does not match stored skill rank")
            nxt = current + 1
            is_difficult = skill in DIFFICULT_SKILLS or skill.split(" (", 1)[0].strip() in DIFFICULT_SKILLS
            expected = "difficult" if is_difficult else "typical"
            if kind != expected: raise ValueError(f"{skill} uses {expected} skill improvement pricing")
            cost = (DIFFICULT_SKILL_IP_COST if expected == "difficult" else SKILL_IP_COST)[nxt]
            ch.setdefault("skills", {})[skill] = nxt
            result = {"skill": skill, "rank": nxt, "cost": cost, "kind": kind}
        ip = ext.get("ip", 0)
        if type(ip) is not int or ip < cost: raise ValueError("insufficient IP")
        ext["ip"] = ip - cost
        result.update(ip=ext["ip"], source=SOURCE_IP)
    elif action == "solo_allocate":
        rank = _active_rank(ch, "Solo")
        if not rank: raise ValueError("character has no Solo rank")
        alloc = args.get("allocation")
        names = ("damage_deflection", "fumble_recovery", "initiative_reaction", "precision_attack", "spot_weakness", "threat_detection")
        if not isinstance(alloc, dict) or any(k not in names or type(v) is not int or v < 0 for k, v in alloc.items()): raise ValueError("invalid Combat Awareness allocation")
        costs = dict(damage_deflection=2, fumble_recovery=4, initiative_reaction=1, precision_attack=3, spot_weakness=1, threat_detection=1)
        if alloc.get("fumble_recovery", 0) not in (0, 1): raise ValueError("fumble_recovery is a single 0/1 allocation")
        if sum(costs[k] * v for k, v in alloc.items()) > rank: raise ValueError("allocation exceeds Combat Awareness rank")
        ext["solo_allocation"] = dict(alloc)
        result = {"allocation": dict(alloc), "spent": sum(costs[k]*v for k,v in alloc.items()), "source": "Cyberpunk RED Core Rulebook, pp. 146–147"}
    elif action in ("rocker_favor", "rocker_convert"):
        rank = _active_rank(ch, "Rockerboy")
        if not rank: raise ValueError("character has no Rockerboy rank")
        size = args.get("group_size", "single")
        dv = {"single": 8, "small": 10, "huge": 12}.get(size)
        if dv is None: raise ValueError("group_size must be single, small, or huge")
        if action == "rocker_convert" and (args.get("in_combat") is True or args.get("hostile") is True):
            result = _ruling(action, "Rockerboy conversion cannot be resolved mechanically in combat or against a hostile target.")
        elif action == "rocker_favor" and args.get("scope_approved") is not True:
            result = _ruling(action, "GM must determine whether the requested favor is within rank and adjudicate its narrative effect.")
        elif action == "rocker_convert" and args.get("target_eligible") is not True:
            result = _ruling(action, "GM determines whether target is already a Fan or actively dislikes the Rockerboy.")
        else:
            group_id = args.get("group_id")
            locks = ext.setdefault("favor_locks", {})
            now = args.get("now_minutes")
            if action == "rocker_favor":
                if not isinstance(group_id, str) or not group_id: raise ValueError("favor requires a nonempty group_id")
                if type(now) is not int or now < 0: raise ValueError("favor requires a monotonic now_minutes value")
                until = locks.get(group_id, 0)
                if type(until) is int and now < until: raise ValueError("this group is locked from repeat favor requests for one week")
            roll = rank + _die(randbelow); success = roll > dv
            result = {"success": success, "total": roll, "dv": dv, "dice": [roll-rank], "source": SOURCE_ROLES}
            if action == "rocker_favor" and not success: locks[group_id] = now + 10080
    elif action == "lawman_backup":
        rank = _active_rank(ch, "Lawman")
        if not rank: raise ValueError("character has no Lawman rank")
        if args.get("in_danger") is not True: result = _ruling(action, "Backup call requires GM-confirmed danger.")
        else:
            success_roll = _die(randbelow)
            result = {"success": success_roll <= rank, "call_die": success_roll, "source": "Cyberpunk RED Core Rulebook, pp. 158–160"}
            if success_roll <= rank:
                rounds = randbelow(6)
                if type(rounds) is not int or not 0 <= rounds <= 5: raise ValueError("randbelow must return integer in [0, 5] for d6")
                rounds += 1
                tier = min(rank + 1, 10) if rounds == 6 and rank < 10 else rank
                groups = 2 if rounds == 6 and rank == 10 else 1
                backup = {"arrival_rounds": rounds, "tier": tier, "groups": groups}
                ext.setdefault("backup", []).append(backup)
                result.update(backup)
    elif action == "exec_team":
        if not _active_rank(ch, "Exec"): raise ValueError("character has no Exec rank")
        members = ext.get("team", [])
        member = next((m for m in members if isinstance(m, dict) and m.get("id") == args.get("member_id")), None)
        if member is None: raise ValueError("member_id must identify a saved team member")
        if not isinstance(args.get("task"), str) or not args["task"]: raise ValueError("task is required")
        die = _die(randbelow)
        result = {"member_id": member["id"], "task": args["task"], "loyalty": member.get("loyalty"), "die": die, "success": die < member.get("loyalty", 0), "source": "Cyberpunk RED Core Rulebook, pp. 154–155"}
    elif action == "exec_change_loyalty":
        if not _active_rank(ch, "Exec"): raise ValueError("character has no Exec rank")
        table = {"compliment": 1, "bonus_200eb": 4, "support_against_management": 4, "earnings_20_percent": 6, "paid_time_off": 6, "risk_harm": 8, "no_gain_session": -1, "berate": -2, "ignore_contribution": -4}
        reason = args.get("reason"); delta = table.get(reason)
        if delta is None: raise ValueError("reason must name a sourced Loyalty table entry")
        member = next((m for m in ext.get("team", []) if isinstance(m, dict) and m.get("id") == args.get("member_id")), None)
        if member is None: raise ValueError("member_id must identify a saved team member")
        member["loyalty"] = member.get("loyalty", 0) + delta
        if args.get("session_end") is True: member["loyalty"] = min(10, member["loyalty"])
        result = {"member_id": member["id"], "loyalty": member["loyalty"], "adjustment": delta, "source": "Cyberpunk RED Core Rulebook, pp. 154–155"}
    elif action in ("tech_project_begin", "tech_project_work", "tech_project_finish"):
        rank = _active_rank(ch, "Tech")
        if not rank: raise ValueError("character has no Tech rank")
        kind, project_id = args.get("project_kind"), args.get("project_id")
        if kind not in ("upgrade", "fabricate", "invent"): raise ValueError("project_kind must be upgrade, fabricate, or invent")
        projects = ext.get("projects", {})
        if not isinstance(projects, dict): raise ValueError("projects must be an object")
        if action == "tech_project_begin":
            restarting = isinstance(project_id, str) and isinstance(projects.get(project_id), dict) and projects[project_id].get("state") == "failed_restart_required"
            if not isinstance(project_id, str) or not project_id or (project_id in projects and not restarting): raise ValueError("unique project_id required unless restarting a failed project")
            specialty = {"upgrade": "Upgrade Expertise", "fabricate": "Fabrication Expertise", "invent": "Invention Expertise"}[kind]
            choices = next((r.get("choices", {}) for r in reversed(acquisitions) if r.get("role") == "Tech"), {})
            maker = choices.get("maker", []) if isinstance(choices, dict) else []
            if not any(specialty in pair if isinstance(pair, list) else pair == specialty for pair in maker): raise ValueError(f"Tech lacks {specialty} specialty")
            catalog = ext.get("catalog_items", {})
            item_id = args.get("item_id")
            item = catalog.get(item_id) if isinstance(catalog, dict) and item_id else None
            if kind in ("upgrade", "fabricate") and (not isinstance(item, dict) or not item.get("source_sha256") or type(item.get("cost")) is not int):
                result = _ruling(action, "Only a verified saved catalog item with source hash and price can be upgraded or fabricated.")
            elif kind == "invent" and args.get("gm_approved") is not True:
                result = _ruling(action, "GM must approve and record invention function and price category before work begins.")
            else:
                category = args.get("category") if kind == "invent" else item.get("category")
                if category not in PROJECTS: result = _ruling(action, "The canonical item lacks a supported source price category.")
                elif kind == "invent" and category not in ("Expensive", "Very Expensive", "Luxury", "Super Luxury"):
                    raise ValueError("invented items must be Expensive or higher")
                else:
                    specialty_ranks = choices.get("maker_ranks", {}) if isinstance(choices, dict) else {}
                    srank = specialty_ranks.get(specialty, 0) if isinstance(specialty_ranks, dict) else 0
                    if type(srank) is not int or srank <= 0: raise ValueError("stored Maker specialty rank is required")
                    repair_skill = item.get("repair_skill") if item is not None else args.get("gm_repair_skill")
                    if not isinstance(repair_skill, str) or repair_skill not in ch.get("skills", {}):
                        result = _ruling(action, "A saved catalog repair skill or GM-approved invention repair skill is required.")
                    dv, duration = PROJECTS[category]
                    if category == "Super Luxury":
                        price = item["cost"] if kind != "invent" else args.get("approved_cost")
                        if type(price) is not int or price < 10000: raise ValueError("Super Luxury project requires verified cost >= 10000eb")
                        duration *= (price + 9999) // 10000
                    materials = 0
                    if kind == "upgrade":
                        if item_id in ext.get("upgraded_items", []): raise ValueError("an item may receive only one Upgrade Expertise upgrade")
                        upgrade_cost = item.get("invented_upgrade_price", 0)
                        if type(upgrade_cost) is not int or upgrade_cost < 0: result = _ruling(action, "Upgrade price must be a verified saved catalog field.")
                        else: materials = item["cost"] + upgrade_cost
                    elif kind == "fabricate":
                        materials = item.get("fabrication_material_cost")
                        if category == "Cheap": result = _ruling(action, "The source does not specify a category below Cheap for fabrication materials.")
                        elif type(materials) is not int or materials < 0: result = _ruling(action, "A source-verified one-category-lower material cost is required.")
                    if "result" not in locals() or not isinstance(result, dict):
                        if kind == "invent": materials = 0
                        money = ch.get("money", 0)
                        if isinstance(money, dict): money = money.get("eb", 0)
                        if type(money) is not int or (not restarting and money < materials): raise ValueError("insufficient eb for project materials")
                        if not restarting: ch["money"] = money - materials
                        projects = ext.setdefault("projects", {})
                        projects[project_id] = {"kind": kind, "item_id": item_id, "category": category, "skill": repair_skill, "dv": dv, "duration_minutes": duration, "elapsed_minutes": 0, "materials_cost": materials, "state": "working", "gm_approved": kind == "invent"}
                        result = {"project_id": project_id, "duration_minutes": duration, "materials_paid": 0 if restarting else materials, "restarted": restarting, "source": "Cyberpunk RED Core Rulebook, pp. 147–149"}
        else:
            project = projects.get(project_id)
            if not isinstance(project, dict) or project.get("kind") != kind: raise ValueError("project_id and project_kind must identify an active project")
            if action == "tech_project_work":
                elapsed = args.get("elapsed_minutes")
                if type(elapsed) is not int or elapsed < 0: raise ValueError("elapsed_minutes must be a nonnegative integer")
                project["elapsed_minutes"] += elapsed
                result = {"project_id": project_id, "elapsed_minutes": project["elapsed_minutes"], "complete": project["elapsed_minutes"] >= project["duration_minutes"]}
            elif project["elapsed_minutes"] < project["duration_minutes"]: raise ValueError("project duration has not elapsed")
            else:
                skill = project.get("skill") or args.get("repair_skill")
                specialty = {"upgrade": "Upgrade Expertise", "fabricate": "Fabrication Expertise", "invent": "Invention Expertise"}[kind]
                choices = next((r.get("choices", {}) for r in reversed(acquisitions) if r.get("role") == "Tech"), {})
                srank = choices.get("maker_ranks", {}).get(specialty, 0)
                check = _check(ch, skill, srank, project["dv"], randbelow)
                project["state"] = "complete" if check["success"] else "failed_restart_required"
                if check["success"] and kind in ("fabricate", "invent"):
                    ext.setdefault("inventory", []).append(project["item_id"] if project["item_id"] else {"invention": project_id, "approved": project["gm_approved"], "category": project["category"]})
                if check["success"] and kind == "upgrade": ext.setdefault("upgraded_items", []).append(project["item_id"])
                result = {"project_id": project_id, "check": check, "state": project["state"], "source": "Cyberpunk RED Core Rulebook, pp. 147–149"}
    elif action == "medtech_synthesize":
        rank = _active_rank(ch, "Medtech")
        if not rank: raise ValueError("character has no Medtech rank")
        recipe = args.get("recipe")
        acq = next((r for r in reversed(acquisitions) if r.get("role") == "Medtech"), {})
        learned = acq.get("choices", {}).get("recipes", [])
        if recipe not in PHARMACEUTICALS or recipe not in learned: raise ValueError("recipe must be learned in saved Medtech choices")
        skill = ch.get("skills", {}).get("Medical Tech")
        if type(skill) is not int: raise ValueError("stored Medical Tech skill required")
        money = ch.get("money", 0); money = money.get("eb", 0) if isinstance(money, dict) else money
        if type(money) is not int or money < 200: raise ValueError("synthesis requires 200eb materials")
        check = skill_check(ch.get("stats", {}).get("TECH"), skill, 13, randbelow=randbelow)
        ch["money"] = money - 200
        doses = skill if check["success"] else 0
        if doses:
            ext.setdefault("pharmaceuticals", {})[recipe] = ext.setdefault("pharmaceuticals", {}).get(recipe, 0) + doses
        result = {"recipe": recipe, "check": check, "doses": doses, "materials_spent": 200, "time_minutes": 60, "source": "Cyberpunk RED Core Rulebook, pp. 149–150"}
    elif action == "fixer_haggle":
        rank = _active_rank(ch, "Fixer")
        if not rank: raise ValueError("character has no Fixer rank")
        txn = args.get("transaction_id")
        if not isinstance(txn, str) or not txn: raise ValueError("transaction_id required")
        used_transactions = ext.get("fixer_transactions", [])
        if txn in used_transactions: raise ValueError("only one Fixer deal per transaction")
        if args.get("opponent_gm_approved") is not True: result = _ruling(action, "Opponent statistics are GM-provided context and require approval.")
        else:
            stats, skills = ch.get("stats", {}), ch.get("skills", {})
            op = args.get("opponent", {})
            if "COOL" not in stats or "Trading" not in skills or not isinstance(op, dict) or type(op.get("COOL")) is not int or type(op.get("Trading")) is not int: raise ValueError("stored fixer COOL/Trading and GM opponent stats required")
            own = skill_check(stats["COOL"], skills["Trading"], 0, modifier=rank, randbelow=randbelow)
            other_rank = op.get("Operator", 0)
            if type(other_rank) is not int or not 0 <= other_rank <= 10: raise ValueError("invalid GM opponent Operator rank")
            theirs = skill_check(op["COOL"], op["Trading"], 0, modifier=other_rank, randbelow=randbelow)
            success = own["total"] > theirs["total"]
            deal = args.get("deal")
            gates = {"discount_10": 1, "buy_5_get_1": 3, "job_pay_20": 5, "half_credit": 7, "discount_20": 9, "dangerous_job_double": 10}
            if deal not in gates: raise ValueError("unsupported Fixer deal")
            if rank < gates[deal]: raise ValueError("Operator rank does not unlock this deal")
            terms = {"discount_10": {"price_factor": .9 if args.get("side", "buy") == "buy" else 1.1}, "buy_5_get_1": {"bonus_item": 1}, "job_pay_20": {"pay_factor": 1.2}, "half_credit": {"pay_half_now": True}, "discount_20": {"price_factor": .8 if args.get("side", "buy") == "buy" else 1.2}, "dangerous_job_double": {"pay_factor": 2}}[deal]
            ext.setdefault("fixer_transactions", []).append(txn)
            result = {"success": success, "fixer_check": own, "opponent_check": theirs, "deal": deal if success else None, "terms": terms if success else None, "source": "Cyberpunk RED Core Rulebook, pp. 159–161"}
    elif action == "nomad_vehicle":
        rank = _active_rank(ch, "Nomad")
        if not rank: raise ValueError("character has no Nomad rank")
        catalog = ext.get("family_motorpool", [])
        if not isinstance(catalog, list): raise ValueError("saved family_motorpool must be a list")
        mode = args.get("mode")
        if mode == "swap":
            vehicle_id = args.get("vehicle_id")
            vehicle = next((v for v in catalog if isinstance(v, dict) and v.get("id") == vehicle_id and v.get("verified") is True), None)
            if vehicle is None: raise ValueError("swap target must be a verified family vehicle")
            if args.get("family_close") is not True or type(args.get("now_minutes")) is not int: result = _ruling(action, "Family availability and current campaign clock must be confirmed for a motorpool swap.")
            else:
                ready = args["now_minutes"] + 1440
                ext["pending_vehicle_swap"] = {"vehicle_id": vehicle_id, "ready_minutes": ready}
                result = {"pending_vehicle": vehicle_id, "ready_minutes": ready, "source": "Cyberpunk RED Core Rulebook, pp. 161–162"}
        elif mode == "complete_swap":
            pending = ext.get("pending_vehicle_swap")
            now = args.get("now_minutes")
            if not isinstance(pending, dict) or type(now) is not int or now < pending.get("ready_minutes", 0): raise ValueError("no completed next-morning family swap is ready")
            ext["active_vehicle"] = pending["vehicle_id"]; del ext["pending_vehicle_swap"]
            result = {"active_vehicle": ext["active_vehicle"], "source": "Cyberpunk RED Core Rulebook, pp. 161–162"}
        elif mode == "repair_destroyed":
            vehicle = next((v for v in catalog if isinstance(v, dict) and v.get("id") == args.get("vehicle_id") and v.get("verified") is True), None)
            if vehicle is None: raise ValueError("repair requires verified family vehicle")
            money = ch.get("money", 0); money = money.get("eb", 0) if isinstance(money, dict) else money
            if type(money) is not int or money < 500: raise ValueError("family repair costs 500eb")
            ch["money"] = money - 500; vehicle["repair_ready_minutes"] = args.get("now_minutes", 0) + 10080
            result = {"vehicle_id": vehicle["id"], "cost": 500, "ready_minutes": vehicle["repair_ready_minutes"], "source": "Cyberpunk RED Core Rulebook, p. 162"}
        elif mode == "purchase_upgrade":
            if rank < 10: raise ValueError("purchasing future upgrades at 1,000eb each requires Moto Rank 10")
            upgrade = next((u for u in ext.get("family_upgrades", []) if isinstance(u, dict) and u.get("id") == args.get("upgrade_id") and u.get("verified") is True), None)
            if upgrade is None: raise ValueError("upgrade must be in verified saved family upgrade catalog")
            money = ch.get("money", 0); money = money.get("eb", 0) if isinstance(money, dict) else money
            if type(money) is not int or money < 1000: raise ValueError("upgrade costs 1,000eb")
            ch["money"] = money - 1000; ext.setdefault("purchased_family_upgrades", []).append(upgrade["id"])
            result = {"upgrade_id": upgrade["id"], "cost": 1000, "source": "Cyberpunk RED Core Rulebook, p. 162"}
        else: result = _ruling(action, "Vehicle purchase/upgrade entitlements require a rank-specific saved family catalog choice; this operation is not applicable to unverified entries.")
    elif action == "media_rumor":
        rank = _active_rank(ch, "Media")
        if not rank: raise ValueError("character has no Media rank")
        rumor = args.get("rumor")
        passive = {"Vague": 7, "Typical": 9, "Substantial": 11, "Detailed": 13}
        if rumor not in passive: raise ValueError("unknown rumor category")
        week = args.get("week")
        if type(week) is not int or week < 0: raise ValueError("week index required")
        checks = ext.setdefault("media_rumor_checks", {})
        key = str(week)
        if checks.get(key, 0) >= 2: raise ValueError("Media passive rumor checks are limited to twice per week")
        checks[key] = checks.get(key, 0) + 1
        roll = rank + _die(randbelow)
        result = {"total": roll, "rumor": rumor if roll > passive[rumor] else None, "passive_dv": passive[rumor], "candidate_is_unverified": True, "source": "Cyberpunk RED Core Rulebook, pp. 151–152"}
    elif action == "media_publish":
        rank = _active_rank(ch, "Media")
        if not rank: raise ValueError("character has no Media rank")
        topic = args.get("topic")
        if not isinstance(topic, str) or not topic: raise ValueError("topic required")
        stories = ext.get("published_topics", {})
        if not isinstance(stories, dict): raise ValueError("published_topics must be an object")
        evidence = args.get("evidence_count", 0)
        if type(evidence) is not int or evidence < 0: raise ValueError("evidence_count must be nonnegative")
        if topic in stories and args.get("new_information") is not True: raise ValueError("same topic requires new information")
        chance = min(10, (2 if rank <= 2 else 3 if rank <= 4 else 4 if rank <= 6 else 5 if rank <= 8 else 6 if rank == 9 else 7) + int(evidence >= 1) + 2 * int(evidence > 4))
        die = _die(randbelow)
        if args.get("evidence_verified") is not True:
            result = {"chance_out_of_10": chance, "die": die, "requires_human_ruling": True, "reason": "GM must verify evidence and determine narrative impact; no publication state recorded.", "source": "Cyberpunk RED Core Rulebook, pp. 152–153"}
        else:
            success = die <= chance
            stories[topic] = {"new_information": args.get("new_information") is True}
            result = {"chance_out_of_10": chance, "die": die, "believed": success, "impact_requires_human_ruling": True, "reason": "Story impact is GM adjudicated.", "source": "Cyberpunk RED Core Rulebook, pp. 152–153"}
    elif action == "medtech_specialty":
        role = "Medtech"
        if not _active_rank(ch, role): raise ValueError(f"character has no {role} rank")
        result = _ruling(action, "Required source-derived prerequisites, costs, evidence, or GM adjudication are not fully validated for this operation; no state changed.")
    else: raise ValueError("unknown role action")
    return {"character": ch, "result": result}


ACTIONS = {name: name for name in ("award_ip", "spend_ip_skill", "spend_ip_role", "solo_allocate", "rocker_favor", "rocker_convert", "tech_project_begin", "tech_project_work", "tech_project_finish", "medtech_specialty", "medtech_synthesize", "media_publish", "media_rumor", "exec_team", "exec_change_loyalty", "lawman_backup", "fixer_haggle", "nomad_vehicle")}
