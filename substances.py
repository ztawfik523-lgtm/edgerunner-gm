"""Street drugs and Medtech pharmaceuticals for character records."""
from __future__ import annotations

import copy
import secrets
from mechanics import skill_check, roll_dice
import rules_eval

SOURCE = "Cyberpunk RED Core Rulebook, pp. 228–230, 357–358"
DRUGS = {
    "BlackLace": (1440, 17), "BlueGlass": (240, 15), "Boost": (1440, 17),
    "Smash": (240, 15), "Synthcoke": (240, 15),
}
SKILL_BOOST = ("Dance", "Contortionist", "Conversation", "Human Perception", "Persuasion", "Acting")


def _detail(ch):
    return ch.setdefault("detail", {})


def _stat(ch, name):
    return ch.get("stats", _detail(ch).get("stats", {})).get(name, 0)


def _skills(ch):
    return ch.get("skills", _detail(ch).get("skills", {}))


def effective_values(character):
    """Return calculated stats, skills and condition flags without altering base values."""
    stats, skills = copy.deepcopy(character.get("stats", {})), copy.deepcopy(character.get("skills", {}))
    d = character.get("detail", {}); now = d.get("clock_minutes", 0)
    drugs = d.get("drugs", {})
    conditions = {}
    for drug, state in drugs.items():
        if not isinstance(state, dict) or state.get("expires_at", 0) <= now: continue
        if drug == "BlackLace": conditions["ignore_serious_wounded"] = True
        elif drug == "Boost": stats["INT"] = stats.get("INT", 0) + 2
        elif drug == "Synthcoke": stats["REF"] = stats.get("REF", 0) + 1; conditions["paranoid_ideation"] = True
        elif drug == "Smash":
            for name in SKILL_BOOST: skills[name] = skills.get(name, 0) + 2
        elif drug == "BlueGlass" and drug in d.get("addictions", []): conditions["immune_to_blueglass_flashing"] = True
    pharma = d.get("pharmaceutical_effects", {})
    if isinstance(pharma, dict):
        stim = pharma.get("Stim")
        if isinstance(stim, dict) and stim.get("expires_at", 0) > now and stim.get("ignore_serious_wounded", True):
            conditions["ignore_serious_wounded"] = True
        surge = pharma.get("Surge")
        if isinstance(surge, dict) and surge.get("expires_at", 0) > now and surge.get("no_sleep_impairment", True):
            conditions["no_sleep_impairment"] = True
    for drug in d.get("addictions", []):
        active = isinstance(drugs.get(drug), dict) and drugs[drug].get("expires_at", 0) > now
        if drug == "BlackLace" and not active: stats["REF"] = stats.get("REF", 0) - 2
        elif drug == "Boost": stats["INT"] = stats.get("INT", 0) - 2
        elif drug == "Synthcoke" and not active: stats["REF"] = stats.get("REF", 0) - 2
        elif drug == "Smash":
            for name in SKILL_BOOST: skills[name] = skills.get(name, 0) - 2
    emp = character.get("humanity", d.get("humanity"))
    initial_emp = d.get("initial_emp", character.get("initial_emp"))
    if type(emp) is int:
        stats["EMP"] = max(0, emp // 10)
    elif type(initial_emp) is int:
        stats["EMP"] = max(0, initial_emp)
    for k, v in list(stats.items()):
        if type(v) is int:
            stats[k] = max(0, v)
    for k, v in list(skills.items()):
        if type(v) is int:
            skills[k] = max(0, v)
    return stats, skills, conditions


def _inventory(ch):
    inv = ch.get("inventory")
    if inv is None or inv == []:
        inv = {}
        ch["inventory"] = inv
    if isinstance(inv, dict): return inv
    raise ValueError("inventory must be a mapping of item ids to quantities")


def _consume(ch, item):
    inv = _inventory(ch)
    if type(inv.get(item)) is not int or inv[item] < 1: raise ValueError(f"missing dose: {item}")
    inv[item] -= 1


def _consume_dose(ch, *inv_keys, detail_pharma=None):
    inv = ch.get("inventory")
    if inv is None or inv == []:
        inv = {}
        ch["inventory"] = inv
    if not isinstance(inv, dict):
        raise ValueError("inventory must be a mapping of item ids to quantities")
    for key in inv_keys:
        if type(inv.get(key)) is int and inv[key] >= 1:
            inv[key] -= 1
            if detail_pharma and key == f"pharma:{detail_pharma}":
                pharma_bag = _detail(ch).get("pharmaceuticals")
                if isinstance(pharma_bag, dict) and type(pharma_bag.get(detail_pharma)) is int and pharma_bag[detail_pharma] >= 1:
                    pharma_bag[detail_pharma] -= 1
            return
    if detail_pharma:
        pharma_bag = _detail(ch).get("pharmaceuticals")
        if isinstance(pharma_bag, dict) and type(pharma_bag.get(detail_pharma)) is int and pharma_bag[detail_pharma] >= 1:
            pharma_bag[detail_pharma] -= 1
            return
    raise ValueError(f"missing dose: {detail_pharma or inv_keys[0]}")


def _restore_black_lace_humanity(target, lost_amount):
    if type(lost_amount) is not int or lost_amount <= 0:
        return 0
    d = _detail(target)
    h = target.get("humanity", d.get("humanity"))
    if type(h) is not int:
        return 0
    init_emp = rules_eval.effective_initial_emp(target)
    max_h = init_emp * 10
    for cw in d.get("cyberware", []):
        if not isinstance(cw, dict) or cw.get("installed") is False:
            continue
        hl = cw.get("hl")
        if hl is None or hl == 0:
            hl = cw.get("humanity_loss", 0)
        if type(hl) is int and hl > 0:
            max_h -= 4 if cw.get("borgware") else 2
    max_h = max(h, max_h)
    restored = min(lost_amount, max(0, max_h - h))
    if restored > 0:
        target["humanity"] = h + restored
        d["humanity"] = target["humanity"]
        emp = rules_eval.sync_emp_from_humanity(target)
        if isinstance(d.get("stats"), dict):
            d["stats"]["EMP"] = emp
    return restored


def process_expirations(character, now_minutes, randbelow=secrets.randbelow, *, prev_minutes=None):
    """Expire active drugs whose duration elapsed at or before now_minutes and resolve addiction checks."""
    if type(now_minutes) is not int or now_minutes < 0:
        raise ValueError("now_minutes must be a nonnegative integer")
    d = _detail(character)
    raw_prev = prev_minutes if prev_minutes is not None else d.get("clock_minutes", 0)
    old_clock = raw_prev if type(raw_prev) is int else 0
    cur_clock = d.get("clock_minutes", 0)
    d["clock_minutes"] = max(cur_clock if type(cur_clock) is int else 0, now_minutes)
    checks = []
    drugs = d.get("drugs")
    if not isinstance(drugs, dict):
        return checks
    for drug, state in list(drugs.items()):
        if not isinstance(state, dict) or state.get("expires_at", 0) > now_minutes:
            continue
        drugs.pop(drug)
        if drug not in DRUGS:
            continue
        stat, skills, _ = effective_values(character)
        skill_name = "Resist Torture/Drugs"
        skill = skills.get("Resist Torture/Drugs")
        if skill is None:
            if "Resist Torture Drugs" in skills:
                skill_name = "Resist Torture Drugs"
                skill = skills["Resist Torture Drugs"]
            elif "Resist Torture" in skills:
                skill_name = "Resist Torture"
                skill = skills["Resist Torture"]
            else:
                skill = 0
        auto_until = d.get("addiction_auto_fail_until", {}).get(drug, d.get("rehab_auto_fail_until", {}).get(drug, 0))
        if state.get("auto_fail") or old_clock < auto_until or now_minutes < auto_until:
            check = {"success": False, "automatic_failure": True, "dv": DRUGS[drug][1]}
        else:
            ctx = rules_eval.effective_check_context(character, "WILL", skill_name)
            will_val = max(0, stat.get("WILL", 0) + ctx["net_debuff"])
            check = skill_check(
                will_val,
                skill,
                DRUGS[drug][1],
                modifier=ctx["wound_penalty"] + ctx["injury_penalty"],
                randbelow=randbelow,
            )
        addicted = d.setdefault("addictions", [])
        if check["success"]:
            # Routine secondary check expiration does not cure existing addiction (p. 227)
            if drug == "BlackLace" and state.get("black_lace_humanity", 0):
                _restore_black_lace_humanity(character, state["black_lace_humanity"])
        elif drug not in addicted:
            addicted.append(drug)
        checks.append({"drug": drug, **check})
    return checks


def _has_medtech(ch):
    return any(isinstance(r, dict) and r.get("role") == "Medtech" and type(r.get("rank")) is int and r["rank"] > 0
               for r in _detail(ch).get("roles", []))


def apply_action(characters, actor_id, action, args, randbelow=secrets.randbelow):
    if not isinstance(characters, dict) or actor_id not in characters or not isinstance(args, dict):
        raise ValueError("characters, valid actor_id and args are required")
    chars = copy.deepcopy(characters); actor = chars[actor_id]
    target_id = args.get("target_id", actor_id)
    if target_id not in chars: raise ValueError("unknown target_id")
    target = chars[target_id]; d = _detail(target); now = d.get("clock_minutes", 0)
    if action in ("street_drug", "consume_drug"):
        drug = args.get("drug", args.get("name"))
        if drug not in DRUGS: raise ValueError("unknown street drug")
        if args.get("willing") is False or (target_id != actor_id and args.get("willing") is not True):
            raise ValueError("target must be willing; unwilling administration requires attack coordinator proof")
        process_expirations(target, now, randbelow=randbelow)
        duration, dv = DRUGS[drug]
        _consume_dose(actor, "drug:" + drug, drug)
        state = d.setdefault("drugs", {}).setdefault(drug, {"expires_at": now, "doses": 0, "black_lace_humanity": 0})
        state["expires_at"] = max(now, state.get("expires_at", now)) + duration
        state["doses"] = state.get("doses", 0) + 1
        auto_until = d.get("addiction_auto_fail_until", {}).get(drug, d.get("rehab_auto_fail_until", {}).get(drug, 0))
        if now < auto_until:
            state["auto_fail"] = True
        humanity_loss = []
        if drug == "BlackLace":
            humanity_loss = roll_dice(2, 6, randbelow); loss = sum(humanity_loss)
            h = target.get("humanity", d.get("humanity"))
            if type(h) is not int: raise ValueError("Black Lace requires recorded humanity")
            target["humanity"] = max(0, h - loss); d["humanity"] = target["humanity"]
            state["black_lace_humanity"] = state.get("black_lace_humanity", 0) + loss
            emp = rules_eval.sync_emp_from_humanity(target)
            if isinstance(d.get("stats"), dict):
                d["stats"]["EMP"] = emp
        result = {"drug": drug, "expires_at": state["expires_at"], "humanity_loss_dice": humanity_loss, "source": SOURCE}
    elif action == "advance_time":
        minutes = args.get("minutes")
        if type(minutes) is not int or minutes < 0: raise ValueError("minutes must be a nonnegative integer")
        checks = process_expirations(target, now + minutes, randbelow=randbelow, prev_minutes=now)
        result = {"minutes": minutes, "expired_drug_checks": checks, "source": SOURCE}
    elif action == "flash_out":
        is_addicted = "BlueGlass" in d.get("addictions", [])
        is_active = isinstance(d.get("drugs", {}).get("BlueGlass"), dict) and d["drugs"]["BlueGlass"].get("expires_at", 0) > now
        can_flash = (is_active and not is_addicted) or (is_addicted and not is_active)
        if args.get("gm_confirmed_flash") is not True or not can_flash or args.get("target_id", actor_id) != actor_id:
            raise ValueError("GM-confirmed Blue Glass flash-out requires active primary effect or unmedicated addiction")
        d["conditions"] = d.get("conditions", {}); d["conditions"]["flash_out"] = True
        result = {"condition": "flash_out", "action_lost": True, "source": SOURCE}
    elif action in ("pharmaceutical", "administer_pharma"):
        name = args.get("pharmaceutical", args.get("name"))
        if name not in ("Antibiotic", "Rapidetox", "Speedheal", "Stim", "Surge"): raise ValueError("unknown pharmaceutical")
        if not _has_medtech(actor): raise ValueError("actor must be a Medtech")
        if args.get("willing") is False or (target_id != actor_id and args.get("willing") is not True):
            raise ValueError("pharmaceutical target must be explicitly willing")
        process_expirations(target, now, randbelow=randbelow)
        effects = d.setdefault("pharmaceutical_effects", {})
        end = effects.get(name, {})
        cooldown = {"Speedheal": 1440, "Stim": 1440, "Surge": 10080}.get(name)
        if cooldown and end.get("cooldown_until", 0) > now: raise ValueError("pharmaceutical is still on cooldown")
        if name == "Antibiotic":
            if effects.get(name, {}).get("expires_at", 0) > now: raise ValueError("Antibiotic already active")
            if not d.get("stabilized"): raise ValueError("Antibiotic requires natural healing to have begun")
        elif name == "Speedheal" and target.get("hp", 0) < 1:
            raise ValueError("Speedheal cannot be used while mortally wounded")
        _consume_dose(actor, "pharma:" + name, name, detail_pharma=name)
        extra = {}
        if name == "Antibiotic":
            effects[name] = {"expires_at": now + 10080, "daily_hp": 2}
        elif name == "Rapidetox":
            purged = d.pop("drugs", None) or {}
            d.pop("intoxicants", None); d.pop("poisons", None)
            if isinstance(purged, dict):
                bl = purged.get("BlackLace")
                if isinstance(bl, dict) and bl.get("black_lace_humanity", 0):
                    restored_hl = _restore_black_lace_humanity(target, bl["black_lace_humanity"])
                    if restored_hl:
                        extra["restored_humanity"] = restored_hl
        elif name == "Speedheal":
            heal = rules_eval.effective_body(target) + _stat(target, "WILL")
            target["hp"] = min(target.get("max_hp", target.get("hp", 0)), target.get("hp", 0) + heal)
            effects[name] = {"cooldown_until": now + 1440}
        elif name == "Stim":
            effects[name] = {"expires_at": now + 60, "ignore_serious_wounded": True, "cooldown_until": now + 1440}
        else:
            effects[name] = {"expires_at": now + 1440, "no_sleep_impairment": True, "cooldown_until": now + 10080}
        result = {"pharmaceutical": name, **extra, "source": SOURCE}
    else: raise ValueError("unknown substance action")
    return {"characters": chars, "result": result}
