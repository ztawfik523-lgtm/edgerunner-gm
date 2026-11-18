"""Pure health, recovery and treatment actions for character records."""
from __future__ import annotations

import copy
import re
import secrets
from typing import Any, Callable

from combat import daily_heal, death_save, stabilize_check
from mechanics import roll_dice, skill_check
from combat import _CRITICALS

SOURCE = "Cyberpunk RED Core Rulebook, pp. 186–188, 221–223, 230"


def _d(record):
    return record.setdefault("detail", {})


def _stats(ch):
    return ch.get("stats", ch.get("detail", {}).get("stats", {}))


def _skills(ch):
    return ch.get("skills", ch.get("detail", {}).get("skills", {}))


def _skill(skills, *names):
    for name in names:
        if name in skills:
            return skills[name]
    return None


def _roll(action, actor, target, args, randbelow):
    stats = _stats(actor); skills = _skills(actor)
    if action == "stabilize":
        hp, max_hp = target.get("hp", 0), target.get("max_hp", 1)
        name = "mortal" if hp < 1 else "serious" if hp < (max_hp + 1)//2 else "light"
        first = _skill(skills, "First Aid", "first_aid")
        para = _skill(skills, "Paramedic", "paramedic")
        if first is None and para is None: raise ValueError("actor needs First Aid or Paramedic")
        requested = args.get("skill")
        options = {"First Aid": first, "Paramedic": para}
        skill_name = requested if requested in options and options[requested] is not None else max(((k,v) for k,v in options.items() if v is not None), key=lambda x:x[1])[0]
        skill = options[skill_name]
        check = stabilize_check(stats.get("TECH", 0), skill, name, randbelow=randbelow)
        if check["success"]:
            detail = _d(target); detail["stabilized"] = True
            if name == "mortal":
                target["hp"] = 1; detail["unconscious_minutes"] = 1
                detail["death_save_penalty"] = detail.get("death_save_base_penalty", 0)
        check["skill"] = skill_name
        return {"action": action, "success": check["success"], "check": check, "source": SOURCE}
    raise ValueError("unsupported action")


def _has_medtech(ch):
    return any(isinstance(r, dict) and r.get("role") == "Medtech" and r.get("rank", 0) > 0
               for r in _d(ch).get("roles", []))


def _therapy(chars, actor_id, target_id, args, randbelow):
    if actor_id == target_id: raise ValueError("Medtech cannot perform therapy on self")
    actor, target = chars[actor_id], chars[target_id]
    skills = _skills(actor); medtech = _skill(skills, "Medical Tech", "Medical Technology")
    if not _has_medtech(actor) or type(medtech) is not int or medtech <= 0:
        raise ValueError("actor must be a Medtech with Medical Tech")
    kind = args.get("therapy")
    data = {"standard": (500, 15, 2), "extreme": (1000, 17, 4), "addiction": (1000, 15, 0)}
    if kind not in data: raise ValueError("therapy must be standard, extreme or addiction")
    cost, dv, dice = data[kind]
    if type(target.get("money")) is not int or target["money"] < cost:
        raise ValueError("insufficient funds")
    target["money"] -= cost
    check = skill_check(_stats(actor).get("TECH", 0), medtech, dv, randbelow=randbelow)
    ad = _d(target)
    outcome = {"therapy": kind, "success": check["success"], "check": check, "cost": cost, "minutes": 10080, "source": SOURCE}
    if not check["success"]: return outcome
    if kind == "addiction":
        addiction = args.get("addiction")
        addictions = ad.setdefault("addictions", [])
        if not isinstance(addiction, str) or addiction not in addictions: raise ValueError("named existing addiction required")
        addictions.remove(addiction)
        target_clock = ad.get("clock_minutes", 0)
        ad.setdefault("addiction_auto_fail_until", {})[addiction] = target_clock + 525600
        ad.setdefault("rehab_auto_fail_until", {})[addiction] = target_clock + 525600
    else:
        rolls = roll_dice(dice, 6, randbelow)
        humanity = target.get("humanity", ad.get("humanity"))
        initial_emp = ad.get("initial_emp", target.get("initial_emp"))
        if type(humanity) is not int or type(initial_emp) is not int:
            raise ValueError("humanity and recorded initial_emp are required")
        max_humanity = initial_emp * 10
        for item in ad.get("cyberware", []):
            if not isinstance(item, dict): continue
            if item.get("humanity_loss", 0) == 0: continue
            max_humanity -= 4 if item.get("borgware") else 2
        new_humanity = min(max_humanity, humanity + sum(rolls))
        target["humanity"] = new_humanity
        if "humanity" in ad: ad["humanity"] = new_humanity
        stats = target.setdefault("stats", ad.setdefault("stats", {})); stats["EMP"] = new_humanity // 10
        outcome.update(dice=rolls, humanity=new_humanity, max_humanity=max_humanity, emp=stats["EMP"])
    return outcome


def _has_replaced_part(target, location):
    target_cyber = _d(target).get("cyberware", [])
    parts = {"body": "body", "head": "head"}
    return any(
        isinstance(x, dict) and (
            x.get("location") == parts.get(location) or
            (location == "body" and any(k in x.get("name", "").lower() for k in ("arm", "leg", "cyberarm", "cyberleg"))) or
            (location == "head" and any(k in x.get("name", "").lower() for k in ("eye", "audio", "ear", "cybereye", "cyberaudio")))
        )
        for x in target_cyber
    )


def _extract_dv_for_skill(source: str, skill: str) -> int:
    parts = source.split(" or ")
    for part in parts:
        if skill in part and "DV" in part:
            m = re.search(r"DV\s*(\d+)", part)
            if m: return int(m.group(1))
    for i, part in enumerate(parts):
        if skill in part:
            for later in parts[i:]:
                m = re.search(r"DV\s*(\d+)", later)
                if m: return int(m.group(1))
    m = re.search(r"DV\s*(\d+)", source)
    if m: return int(m.group(1))
    raise ValueError("canonical treatment does not specify a DV")


def _injury_care(actor, actor_id, target, target_id, action, args, randbelow):
    injury_id = args.get("injury_id")
    injuries = _d(target).get("injuries", [])
    injury = next((x for x in injuries if isinstance(x, dict) and x.get("id") == injury_id), None)
    if injury is None: raise ValueError("canonical injury_id not present on target")
    try:
        location, roll = injury_id.split(":", 1); roll = int(roll)
        metadata = _CRITICALS[location][roll]
    except (ValueError, KeyError, AttributeError): raise ValueError("invalid canonical injury id") from None
    name, effects, quick, treatment = metadata
    if action == "quick_fix":
        if quick == "N/A": raise ValueError("this injury has no Quick Fix")
        source = quick
    else:
        if actor_id == target_id: raise ValueError("cannot treat yourself")
        source = treatment
        if source == "Quick Fix permanently removes effect":
            source = quick
    skills = _skills(actor); choices = []
    for skill_name in ("First Aid", "Paramedic", "Surgery"):
        if skill_name in source and _skill(skills, skill_name) is not None:
            choices.append(skill_name)
    if _has_replaced_part(target, location) and _skill(skills, "Cybertech") is not None:
        choices.append("Cybertech")
    selected = args.get("skill")
    if selected not in choices: raise ValueError("selected skill is not permitted by injury metadata or actor skills")
    if selected == "Surgery" and not _has_medtech(actor): raise ValueError("Surgery requires Medtech role")
    if selected == "Cybertech":
        if not _has_replaced_part(target, location):
            raise ValueError("Cybertech applies only to a replaced body part")
        dvs = [int(x) for x in re.findall(r"DV\s*(\d+)", source)]
        dv = min(dvs) if dvs else 13
    else:
        dv = _extract_dv_for_skill(source, selected)
    check = skill_check(_stats(actor).get("TECH", 0), _skill(skills, selected), dv, randbelow=randbelow)
    if check["success"]:
        detail = _d(target)
        if action == "treat_injury":
            injuries.remove(injury)
        else:
            injury["effect_suppressed_until"] = detail.get("clock_minutes", 0) + 1440
            if action == "quick_fix" and treatment.startswith("Quick Fix"):
                injury["effect_suppressed_until"] = None; injury["effect_removed"] = True
        base = 0
        for current in injuries:
            if not isinstance(current, dict): continue
            try:
                loc, roll_text = current.get("id", "").split(":", 1)
                if "base death-save penalty +1" in _CRITICALS[loc][int(roll_text)][1].lower(): base += 1
            except (ValueError, KeyError):
                continue
        detail["death_save_base_penalty"] = base
    return {"success": check["success"], "check": check, "skill": selected, "injury": name, "minutes": 1 if action == "quick_fix" else 240, "source": SOURCE}


def apply_action(characters: dict, actor_id: str, action: str, args: dict,
                 randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    """Resolve one action without mutating input. GM time advancement is explicit via elapsed_minutes."""
    if not isinstance(characters, dict) or actor_id not in characters or not isinstance(args, dict):
        raise ValueError("characters, valid actor_id and args are required")
    chars = copy.deepcopy(characters); actor = chars[actor_id]
    target_id = args.get("target_id", actor_id)
    if target_id not in chars: raise ValueError("unknown target_id")
    target = chars[target_id]; detail = _d(target)
    if action == "stabilize":
        result = _roll(action, actor, target, args, randbelow)
    elif action == "rest":
        days = args.get("days")
        if type(days) is not int or days < 0: raise ValueError("days must be nonnegative integer")
        light = args.get("light_activity") is True
        healed = target.get("hp", 0)
        if light:
            for _ in range(days):
                healed = daily_heal(healed, target.get("max_hp", 1), _stats(target).get("BODY", 0), detail.get("stabilized", False), True)["new_hp"]
        else:
            detail["stabilized"] = False
        target["hp"] = healed
        result = {"healed_to": healed, "days": days, "light_activity": light, "source": SOURCE}
    elif action == "death_save":
        check = death_save(_stats(target).get("BODY", 0), detail.get("death_save_penalty", 0), randbelow)
        detail["death_save_penalty"] = check["next_penalty"]
        if check["dead"]: detail["dead"] = True
        result = check
    elif action == "therapy":
        result = _therapy(chars, actor_id, target_id, args, randbelow)
    elif action in ("quick_fix", "treat_injury"):
        if not args.get("injury_id") or (action == "treat_injury" and actor_id == target_id):
            result = {"requires_human_ruling": True, "action": action,
                      "reason": "Actor cannot self-treat critical injury or missing canonical injury_id requires human ruling.", "source": SOURCE}
        else:
            result = _injury_care(actor, actor_id, target, target_id, action, args, randbelow)
    elif action in ("install_cyberware", "remove_cyberware", "street_drug"):
        result = {"requires_human_ruling": True, "action": action,
                  "reason": "Canonical cyberware/drug catalog is not supplied to this action.", "source": SOURCE}
    else: raise ValueError("unknown health action")
    if not result.get("requires_human_ruling"):
        elapsed = args.get("elapsed_minutes", 0)
        if type(elapsed) is not int or elapsed < 0: raise ValueError("elapsed_minutes must be nonnegative integer")
        if action == "therapy": elapsed = 10080
        if action == "quick_fix": elapsed = 1
        if action == "treat_injury": elapsed = 240
        if action == "rest": elapsed = days * 1440
        detail["clock_minutes"] = detail.get("clock_minutes", 0) + elapsed
        if action in ("therapy", "treat_injury") and actor_id != target_id:
            ad = _d(actor); ad["clock_minutes"] = ad.get("clock_minutes", 0) + elapsed
    return {"characters": chars, "result": result}


def install_cyberware(characters: dict, actor_id: str, args: dict, catalog: dict,
                      randbelow: Callable[[int], int] = secrets.randbelow) -> dict:
    """Install only a canonical catalog item; absent/insufficient metadata never invents Humanity loss."""
    chars = copy.deepcopy(characters); target_id = args.get("target_id", actor_id)
    item_id = args.get("item_id")
    item = catalog.get(item_id) if isinstance(catalog, dict) else None
    if not isinstance(item, dict):
        return {"characters": chars, "result": {"requires_human_ruling": True, "reason": "Unknown canonical cyberware item."}}
    ch = chars[target_id]; detail = _d(ch); money = ch.get("money")
    cost = item.get("cost")
    if type(cost) is not int or type(money) is not int or money < cost:
        return {"characters": chars, "result": {"success": False, "reason": "insufficient_funds"}}
    return {"characters": chars, "result": {"requires_human_ruling": True, "reason": "Canonical Humanity-loss dice and installation prerequisites are not validated."}}
