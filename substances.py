"""Street drugs and Medtech pharmaceuticals for character records."""
from __future__ import annotations

import copy
import secrets
from mechanics import skill_check, roll_dice

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
        active = True
        if drug == "BlackLace": conditions["ignore_serious_wounded"] = True
        elif drug == "Boost": stats["INT"] = stats.get("INT", 0) + 2
        elif drug == "Synthcoke": stats["REF"] = stats.get("REF", 0) + 1; conditions["paranoid_ideation"] = True
        elif drug == "Smash":
            for name in SKILL_BOOST: skills[name] = skills.get(name, 0) + 2
        elif drug == "BlueGlass" and drug in d.get("addictions", []): conditions["immune_to_blueglass_flashing"] = True
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
        stats["EMP"] = emp // 10
    elif type(initial_emp) is int:
        stats["EMP"] = initial_emp
    return stats, skills, conditions


def _inventory(ch):
    inv = ch.setdefault("inventory", {})
    if isinstance(inv, dict): return inv
    raise ValueError("inventory must be a mapping of item ids to quantities")


def _consume(ch, item):
    inv = _inventory(ch)
    if type(inv.get(item)) is not int or inv[item] < 1: raise ValueError(f"missing dose: {item}")
    inv[item] -= 1


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
    if action == "street_drug":
        drug = args.get("drug", args.get("name"))
        if drug not in DRUGS: raise ValueError("unknown street drug")
        if args.get("willing") is False or (target_id != actor_id and args.get("willing") is not True):
            raise ValueError("target must be willing; unwilling administration requires attack coordinator proof")
        duration, dv = DRUGS[drug]
        _consume(actor, "drug:" + drug)
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
            target.setdefault("stats", {})["EMP"] = target["humanity"] // 10
        result = {"drug": drug, "expires_at": state["expires_at"], "humanity_loss_dice": humanity_loss, "source": SOURCE}
    elif action == "advance_time":
        minutes = args.get("minutes")
        if type(minutes) is not int or minutes < 0: raise ValueError("minutes must be a nonnegative integer")
        old, new = now, now + minutes; d["clock_minutes"] = new; checks = []
        for drug, state in list(d.get("drugs", {}).items()):
            if not isinstance(state, dict) or not old < state.get("expires_at", 0) <= new: continue
            d["drugs"].pop(drug)
            if drug not in DRUGS: continue
            stat, skills, _ = effective_values(target)
            skill = skills.get("Resist Torture/Drugs", skills.get("Resist Torture Drugs", skills.get("Resist Torture", 0)))
            auto_until = d.get("addiction_auto_fail_until", {}).get(drug, d.get("rehab_auto_fail_until", {}).get(drug, 0))
            if state.get("auto_fail") or old < auto_until or new < auto_until:
                check = {"success": False, "automatic_failure": True, "dv": DRUGS[drug][1]}
            else:
                check = skill_check(stat.get("WILL", 0), skill, DRUGS[drug][1], randbelow=randbelow)
            addicted = d.setdefault("addictions", [])
            if check["success"]:
                # Routine secondary check expiration does not cure existing addiction (p. 227)
                if drug == "BlackLace" and state.get("black_lace_humanity", 0):
                    h = target.get("humanity", d.get("humanity", 0)); restored = min(state["black_lace_humanity"], (d.get("initial_emp", target.get("initial_emp", 0))*10)-h)
                    target["humanity"] = h + max(0, restored); d["humanity"] = target["humanity"]
                    target.setdefault("stats", {})["EMP"] = target["humanity"] // 10
            elif drug not in addicted:
                addicted.append(drug)
            checks.append({"drug": drug, **check})
        result = {"minutes": minutes, "expired_drug_checks": checks, "source": SOURCE}
    elif action == "flash_out":
        is_addicted = "BlueGlass" in d.get("addictions", [])
        is_active = isinstance(d.get("drugs", {}).get("BlueGlass"), dict) and d["drugs"]["BlueGlass"].get("expires_at", 0) > now
        can_flash = (is_active and not is_addicted) or (is_addicted and not is_active)
        if args.get("gm_confirmed_flash") is not True or not can_flash or args.get("target_id", actor_id) != actor_id:
            raise ValueError("GM-confirmed Blue Glass flash-out requires active primary effect or unmedicated addiction")
        d["conditions"] = d.get("conditions", {}); d["conditions"]["flash_out"] = True
        result = {"condition": "flash_out", "action_lost": True, "source": SOURCE}
    elif action == "pharmaceutical":
        name = args.get("pharmaceutical", args.get("name"))
        if name not in ("Antibiotic", "Rapidetox", "Speedheal", "Stim", "Surge"): raise ValueError("unknown pharmaceutical")
        if not _has_medtech(actor): raise ValueError("actor must be a Medtech")
        if args.get("willing") is False or (target_id != actor_id and args.get("willing") is not True):
            raise ValueError("pharmaceutical target must be explicitly willing")
        _consume(actor, "pharma:" + name)
        effects = d.setdefault("pharmaceutical_effects", {})
        end = effects.get(name, {})
        cooldown = {"Speedheal": 1440, "Stim": 1440, "Surge": 10080}.get(name)
        if cooldown and end.get("cooldown_until", 0) > now: raise ValueError("pharmaceutical is still on cooldown")
        if name == "Antibiotic":
            if effects.get(name, {}).get("expires_at", 0) > now: raise ValueError("Antibiotic already active")
            if not d.get("stabilized"): raise ValueError("Antibiotic requires natural healing to have begun")
            effects[name] = {"expires_at": now + 10080, "daily_hp": 2}
        elif name == "Rapidetox":
            d.pop("drugs", None); d.pop("intoxicants", None); d.pop("poisons", None)
        elif name == "Speedheal":
            if target.get("hp", 0) < 1: raise ValueError("Speedheal cannot be used while mortally wounded")
            target["hp"] = min(target.get("max_hp", target["hp"]), target.get("hp", 0) + _stat(target, "BODY") + _stat(target, "WILL"))
            effects[name] = {"cooldown_until": now + 1440}
        elif name == "Stim":
            effects[name] = {"expires_at": now + 60, "ignore_serious_wounded": True, "cooldown_until": now + 1440}
        else: effects[name] = {"expires_at": now + 1440, "no_sleep_impairment": True, "cooldown_until": now + 10080}
        result = {"pharmaceutical": name, "source": SOURCE}
    else: raise ValueError("unknown substance action")
    return {"characters": chars, "result": result}
