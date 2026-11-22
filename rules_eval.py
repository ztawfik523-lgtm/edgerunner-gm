"""Authoritative shared Cyberpunk RED character & rules evaluator.

Single source of truth for derived stats (effective EMP, initial EMP, effective BODY),
normalized critical injuries, armor/wound/injury/substance/NET/Solo check modifiers,
equipment view synchronization, and Death Save penalty invariants.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable
import secrets

import combat

_ROLE_ABILITY_TO_ROLE: dict[str, str] = {
    "interface": "Netrunner",
    "charismatic impact": "Rockerboy",
    "credibility": "Media",
    "operator": "Fixer",
    "moto": "Nomad",
    "combat awareness": "Solo",
    "backup": "Lawman",
    "teamwork": "Exec",
    "maker": "Tech",
    "medicine": "Medtech",
}

_MAKER_SPECIALTIES: dict[str, str] = {
    "field expertise": "Field Expertise",
    "field_expertise": "Field Expertise",
    "upgrade expertise": "Upgrade Expertise",
    "upgrade_expertise": "Upgrade Expertise",
    "fabrication expertise": "Fabrication Expertise",
    "fabrication_expertise": "Fabrication Expertise",
    "invention expertise": "Invention Expertise",
    "invention_expertise": "Invention Expertise",
}

_MEDTECH_SPECIALTIES: dict[str, str] = {
    "surgery": "Surgery",
    "pharmaceuticals": "Pharmaceuticals",
    "cryosystem operation": "Cryosystem Operation",
    "cryosystem_operation": "Cryosystem Operation",
}

_ARMOR_PENALTY_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("metalgear", 4),
    ("flak", 4),
    ("heavy armorjack", 2),
    ("medium armorjack", 2),
    ("light armorjack", 0),
    ("kevlar", 0),
    ("leathers", 0),
    ("bodyweight", 0),
    ("subdermal", 0),
    ("skinweave", 0),
    ("skin weave", 0),
)

_RANGED_SKILLS = frozenset({
    "handgun",
    "shoulder arms",
    "archery",
    "heavy weapons",
    "autofire",
})

_MELEE_SKILLS = frozenset({
    "brawling",
    "melee weapon",
})

_SPEECH_SKILLS = frozenset({
    "acting",
    "bribery",
    "conversation",
    "interrogation",
    "persuasion",
    "streetwise",
    "trading",
    "charismatic impact",
    "credibility",
})

_HAND_SKILLS = frozenset({
    "pick lock",
    "pick pocket",
    "sleight of hand",
    "forgery",
    "surgery",
    "first aid",
    "paramedic",
    "weaponstech",
    "cybertech",
    "electronics/security tech",
    "basic tech",
    "archery",
    "play instrument",
})

_ATTACK_SKILLS = _RANGED_SKILLS | _MELEE_SKILLS

_CANONICAL_AMMO_KINDS: dict[str, str] = {
    "m pistol": "M Pistol",
    "h pistol": "H Pistol",
    "vh pistol": "VH Pistol",
    "slug": "Slug",
    "rifle": "Rifle",
    "arrow": "Arrow",
    "grenade": "Grenade",
    "rocket": "Rocket",
    "battery": "Battery",
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _norm(value: Any) -> str:
    text = re.sub(r"\s*/\s*", "/", str(value or "").strip())
    return re.sub(r"\s+", " ", text).casefold()


def _detail_ro(char: dict[str, Any]) -> dict[str, Any]:
    detail = char.get("detail")
    return detail if isinstance(detail, dict) else {}


def _stats_ro(char: dict[str, Any]) -> dict[str, Any]:
    stats = char.get("stats")
    if isinstance(stats, dict):
        return stats
    detail_stats = _detail_ro(char).get("stats")
    return detail_stats if isinstance(detail_stats, dict) else {}


def _skills_ro(char: dict[str, Any]) -> dict[str, Any]:
    skills = char.get("skills")
    if isinstance(skills, dict):
        return skills
    detail_skills = _detail_ro(char).get("skills")
    return detail_skills if isinstance(detail_skills, dict) else {}


def _stat_lookup(stats: dict[str, Any], key: str) -> int:
    if key in stats and _is_int(stats[key]):
        return int(stats[key])
    key_norm = key.casefold()
    for k, v in stats.items():
        if isinstance(k, str) and k.strip().casefold() == key_norm and _is_int(v):
            return int(v)
    return 0


def _iter_owned_items(char: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None]]:
    """Yield (name_or_id, item_dict_or_none) for cyberware, equipment, and inventory."""
    detail = _detail_ro(char)
    found: list[tuple[str, dict[str, Any] | None]] = []

    def _add_entry(entry: Any) -> None:
        if isinstance(entry, str) and entry.strip():
            found.append((entry.strip(), None))
        elif isinstance(entry, dict):
            if entry.get("installed") is False or entry.get("disabled") is True or entry.get("equipped") is False:
                return
            label = entry.get("name") or entry.get("type") or entry.get("id") or ""
            if isinstance(label, str) and label.strip():
                found.append((label.strip(), entry))

    cyberware = detail.get("cyberware")
    if isinstance(cyberware, list):
        for entry in cyberware:
            _add_entry(entry)

    equipment = detail.get("equipment")
    if isinstance(equipment, dict):
        for bucket in equipment.values():
            if isinstance(bucket, list):
                for entry in bucket:
                    _add_entry(entry)
    elif isinstance(equipment, list):
        for entry in equipment:
            _add_entry(entry)

    inventory = char.get("inventory")
    if isinstance(inventory, dict):
        for key, qty in inventory.items():
            if isinstance(key, str) and key.strip() and _is_int(qty) and qty > 0:
                found.append((key.strip(), None))
    elif isinstance(inventory, list):
        for entry in inventory:
            _add_entry(entry)

    return found


def _criticals_index() -> tuple[dict[str, tuple[str, int, str, str, str]], dict[str, list[tuple[str, int, str, str, str, str]]]]:
    table = getattr(combat, "CRITICAL_INJURIES", None) or combat._CRITICALS
    by_id: dict[str, tuple[str, int, str, str, str]] = {}
    by_name: dict[str, list[tuple[str, int, str, str, str, str]]] = {}
    for loc, entries in table.items():
        if not isinstance(entries, dict):
            continue
        for roll, meta in entries.items():
            if not isinstance(meta, (tuple, list)) or len(meta) < 4:
                continue
            name, effects, quick_fix, treatment = str(meta[0]), str(meta[1]), str(meta[2]), str(meta[3])
            cid = f"{loc}:{roll}"
            by_id[cid] = (str(loc), int(roll), name, effects, quick_fix, treatment)  # type: ignore[assignment]
            by_name.setdefault(_norm(name), []).append((cid, str(loc), int(roll), name, effects, quick_fix, treatment))  # type: ignore[arg-type]
    return by_id, by_name  # type: ignore[return-value]


def effective_initial_emp(char: dict[str, Any]) -> int:
    """Resolve starting/initial EMP before cyberware humanity loss."""
    detail = _detail_ro(char)
    creation = detail.get("creation") if isinstance(detail.get("creation"), dict) else {}
    for candidate in (creation.get("initial_emp"), detail.get("initial_emp"), char.get("initial_emp")):
        if _is_int(candidate):
            return max(0, candidate)

    humanity = char.get("humanity")
    if humanity is None and "humanity" not in char:
        humanity = detail.get("humanity")
    if _is_int(humanity):
        total_hl = 0
        cyberware = detail.get("cyberware")
        if isinstance(cyberware, list):
            for entry in cyberware:
                if not isinstance(entry, dict):
                    continue
                hl = entry.get("hl", entry.get("humanity_loss", 0))
                if _is_int(hl) and hl > 0:
                    total_hl += hl
        return max(0, (int(humanity) + total_hl) // 10)

    return max(0, _stat_lookup(_stats_ro(char), "EMP"))


def effective_emp(char: dict[str, Any]) -> int:
    """Resolve current effective EMP from Humanity (or stats['EMP'] fallback)."""
    humanity = char.get("humanity")
    if humanity is None and "humanity" not in char:
        humanity = _detail_ro(char).get("humanity")
    if humanity is not None and not isinstance(humanity, bool):
        try:
            return max(0, int(humanity) // 10)
        except (TypeError, ValueError):
            pass
    return max(0, _stat_lookup(_stats_ro(char), "EMP"))


def sync_emp_from_humanity(char: dict[str, Any]) -> int:
    """Sync char['stats']['EMP'] from Humanity whenever Humanity is recorded."""
    emp = effective_emp(char)
    humanity = char.get("humanity")
    if humanity is None and "humanity" not in char:
        humanity = _detail_ro(char).get("humanity")
    if humanity is not None and not isinstance(humanity, bool):
        stats = char.get("stats")
        if not isinstance(stats, dict):
            stats = {}
            char["stats"] = stats
        stats["EMP"] = emp
    return emp


def effective_body(char: dict[str, Any]) -> int:
    """Resolve effective BODY including creation overrides and installed Linear Frames."""
    detail = _detail_ro(char)
    creation = detail.get("creation") if isinstance(detail.get("creation"), dict) else {}
    best = max(0, _stat_lookup(_stats_ro(char), "BODY"))

    for candidate in (detail.get("effective_body"), creation.get("effective_body")):
        if _is_int(candidate):
            best = max(best, candidate)

    for label, entry in _iter_owned_items(char):
        text = label
        if entry and isinstance(entry.get("id"), str):
            text = f"{label} {entry['id']}"
        low = text.casefold()
        if "linear frame" in low or "linear-frame" in low:
            if "beta" in low or "ß" in text or "β" in low:
                best = max(best, 14)
            elif "sigma" in low or "∑" in text or "Σ" in text or "σ" in low:
                best = max(best, 12)

    return max(0, best)


def active_injuries(char: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize and deduplicate injuries from top-level and detail.injuries."""
    detail = _detail_ro(char)
    now = detail.get("clock_minutes", 0)
    if not _is_int(now):
        now = 0
    by_id, by_name = _criticals_index()

    raw_items: list[Any] = []
    if isinstance(detail.get("injuries"), list):
        raw_items.extend(detail["injuries"])
    if isinstance(char.get("injuries"), list):
        raw_items.extend(char["injuries"])

    dedup: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in raw_items:
        if isinstance(item, str):
            raw_name = item.strip()
            if not raw_name:
                continue
            raw_dict: dict[str, Any] = {"name": raw_name}
        elif isinstance(item, dict):
            if item.get("effect_removed") or item.get("removed"):
                continue
            raw_dict = dict(item)
        else:
            continue

        raw_id = raw_dict.get("id")
        raw_id_str = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else ""
        raw_name = raw_dict.get("name")
        raw_name_str = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else ""

        meta: tuple[str, str, int, str, str, str, str] | None = None
        if raw_id_str and raw_id_str in by_id:
            loc, roll, cname, ceffects, cquick, ctreat = by_id[raw_id_str]  # type: ignore[misc]
            meta = (raw_id_str, loc, roll, cname, ceffects, cquick, ctreat)
        elif raw_name_str and _norm(raw_name_str) in by_name:
            matches = by_name[_norm(raw_name_str)]
            chosen = matches[0]
            if raw_id_str and ":" in raw_id_str:
                pref_loc = raw_id_str.split(":", 1)[0].strip().casefold()
                chosen = next((m for m in matches if m[1].casefold() == pref_loc), chosen)
            elif not raw_id_str and len(matches) > 1:
                chosen = next((m for m in matches if f"id:{m[0]}" in dedup), chosen)
            meta = chosen

        if meta is not None:
            canon_id, loc, roll, cname, ceffects, cquick, ctreat = meta
            effective_id = canon_id if (not raw_id_str or raw_id_str.endswith(":aimed_leg")) else raw_id_str
            name_val = raw_name_str or cname
            effects_val = str(raw_dict.get("effects") or ceffects)
            quick_fix_val = str(raw_dict.get("quick_fix") or cquick)
            treatment_val = str(raw_dict.get("treatment") or ctreat)
            default_ds_pen = 1 if "base death-save penalty +1" in ceffects.casefold() else 0
            dedup_key = f"id:{canon_id}"
        else:
            if not raw_name_str and not raw_id_str:
                continue
            effective_id = raw_id_str
            name_val = raw_name_str or raw_id_str
            loc = str(raw_dict.get("location") or "")
            effects_val = str(raw_dict.get("effects") or "")
            quick_fix_val = str(raw_dict.get("quick_fix") or "")
            treatment_val = str(raw_dict.get("treatment") or "")
            if effects_val:
                m_ds = re.search(r"death[- ]save\s+penalty\s*\+\s*(\d+)", effects_val, re.I)
                default_ds_pen = int(m_ds.group(1)) if m_ds else 0
            else:
                default_ds_pen = 1
            dedup_key = f"name:{_norm(name_val)}" if name_val else f"id:{effective_id}"

        explicit_ds = raw_dict.get("death_save_penalty")
        ds_pen = int(explicit_ds) if _is_int(explicit_ds) else default_ds_pen

        sup_until = raw_dict.get("effect_suppressed_until")
        has_sup_until = _is_int(sup_until)
        if "suppressed" in raw_dict:
            is_suppressed = bool(raw_dict["suppressed"]) or (has_sup_until and sup_until > now)
        elif has_sup_until:
            is_suppressed = sup_until > now
        else:
            is_suppressed = bool(raw_dict.get("quick_fixed")) and raw_dict.get("suppressed") is not False

        normalized: dict[str, Any] = {
            **raw_dict,
            "id": effective_id,
            "name": name_val,
            "location": loc,
            "effects": effects_val,
            "quick_fix": quick_fix_val,
            "treatment": treatment_val,
            "death_save_penalty": ds_pen,
            "suppressed": bool(is_suppressed),
            "quick_fixed": bool(raw_dict.get("quick_fixed", False)),
            "treated": bool(raw_dict.get("treated", False)),
        }

        if dedup_key in dedup:
            existing = dedup[dedup_key]
            existing["suppressed"] = existing["suppressed"] or normalized["suppressed"]
            existing["quick_fixed"] = existing["quick_fixed"] or normalized["quick_fixed"]
            existing["treated"] = existing["treated"] or normalized["treated"]
            if "death_save_penalty" in raw_dict and _is_int(raw_dict["death_save_penalty"]):
                existing["death_save_penalty"] = ds_pen
        else:
            dedup[dedup_key] = normalized
            order.append(dedup_key)

    return [dedup[k] for k in order]


def _parse_armor_penalty(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return abs(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() in {"none", "no penalty", "n/a", "-", "0"}:
            return 0
        if re.fullmatch(r"[+-]?\s*\d+", text):
            return abs(int(text.replace(" ", "")))
        match = re.match(r"^[+-]?\s*(\d+)\b", text)
        if match:
            return int(match.group(1))
        match = re.search(r"(?:^|[\s(])-\s*(\d+)\b", text)
        if match:
            return int(match.group(1))
    return 0


def _armor_piece_penalty(piece: Any) -> int:
    if piece is None or isinstance(piece, bool):
        return 0
    if isinstance(piece, (int, str)):
        parsed = _parse_armor_penalty(piece)
        if parsed > 0:
            return parsed
        if isinstance(piece, str):
            low = piece.casefold()
            for kw, val in _ARMOR_PENALTY_KEYWORDS:
                if kw in low:
                    return val
        return 0
    if not isinstance(piece, dict):
        return 0
    if piece.get("equipped") is False:
        return 0

    for key in ("penalty", "armor_penalty", "armor_penalty_minimum_0"):
        if key in piece and piece[key] is not None:
            return _parse_armor_penalty(piece[key])
    stats = piece.get("stats")
    if isinstance(stats, dict):
        for key in ("armor_penalty_minimum_0", "armor_penalty", "penalty"):
            if key in stats and stats[key] is not None:
                return _parse_armor_penalty(stats[key])

    label = f"{piece.get('type', '')} {piece.get('name', '')}".casefold()
    for kw, val in _ARMOR_PENALTY_KEYWORDS:
        if kw in label:
            return val
    return 0


def effective_armor_penalty(char: dict[str, Any]) -> int:
    """Return non-negative armor penalty magnitude across all worn armor views."""
    detail = _detail_ro(char)
    candidates: list[int] = [
        _parse_armor_penalty(char.get("armor_penalty")),
        _parse_armor_penalty(detail.get("armor_penalty")),
        _armor_piece_penalty(detail.get("equipped_armor")),
        _armor_piece_penalty(detail.get("equipped_head_armor")),
    ]

    equipment = detail.get("equipment")
    if isinstance(equipment, dict) and isinstance(equipment.get("armor"), list):
        for piece in equipment["armor"]:
            candidates.append(_armor_piece_penalty(piece))

    top_armor = char.get("armor")
    if isinstance(top_armor, list):
        for piece in top_armor:
            candidates.append(_armor_piece_penalty(piece))
    else:
        candidates.append(_armor_piece_penalty(top_armor))

    return max(candidates, default=0)


def _has_pain_editor(char: dict[str, Any]) -> bool:
    for label, entry in _iter_owned_items(char):
        text = label.casefold()
        entry_id = str(entry.get("id") or "").casefold() if entry else ""
        if "pain editor" in text or "pain-editor" in text or "pain_editor" in text or "pain-editor" in entry_id:
            return True
    return False


def _substance_values_safe(char: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from substances import effective_values

    safe_char = {
        **char,
        "stats": _stats_ro(char),
        "skills": _skills_ro(char),
        "detail": _detail_ro(char),
    }
    try:
        return effective_values(safe_char)
    except Exception:
        return dict(_stats_ro(char)), dict(_skills_ro(char)), {}


def _has_serious_wound_suppression(char: dict[str, Any], sub_conds: dict[str, Any]) -> bool:
    if sub_conds.get("ignore_serious_wounded"):
        return True
    detail = _detail_ro(char)
    now = detail.get("clock_minutes", 0)
    if not _is_int(now):
        now = 0

    conds = detail.get("conditions")
    if isinstance(conds, dict) and conds.get("ignore_serious_wounded"):
        return True

    pharma = detail.get("pharmaceutical_effects")
    if isinstance(pharma, dict):
        stim = pharma.get("Stim")
        if isinstance(stim, dict) and _is_int(stim.get("expires_at")) and stim["expires_at"] > now:
            if stim.get("ignore_serious_wounded", True):
                return True

    for container_key in ("drugs", "substances"):
        container = detail.get(container_key)
        if not isinstance(container, dict):
            continue
        for name, state in container.items():
            if str(name).strip().casefold() not in {"blacklace", "black lace", "stim"}:
                continue
            if state is True:
                return True
            if isinstance(state, dict):
                if state.get("active") is True:
                    return True
                exp = state.get("expires_at")
                if _is_int(exp) and exp > now:
                    return True
    return False


def effective_wound_penalty(char: dict[str, Any]) -> int:
    """Return signed wound action penalty (0, -2, or -4), honoring Pain Editor/BlackLace/Stim."""
    raw_max_hp = char.get("max_hp")
    raw_hp = char.get("hp")
    if not _is_int(raw_max_hp) or raw_max_hp < 1:
        if _is_int(raw_hp) and raw_hp > 0:
            max_hp = raw_hp
        elif _is_int(raw_hp) and raw_hp <= 0:
            max_hp = 1
        else:
            return 0
    else:
        max_hp = raw_max_hp

    hp = raw_hp if _is_int(raw_hp) else max_hp
    move = max(0, _stat_lookup(_stats_ro(char), "MOVE"))
    penalty = int(combat.wound_state(hp, max_hp, move)["action_penalty"])
    if penalty == 0:
        return 0
    if _has_pain_editor(char):
        return 0
    if penalty == -2:
        _, _, sub_conds = _substance_values_safe(char)
        if _has_serious_wound_suppression(char, sub_conds):
            return 0
    return penalty


def _resolve_net_debuff(char: dict[str, Any], stat_key: str | None) -> int:
    if not stat_key or stat_key == "ROLE":
        return 0
    detail = _detail_ro(char)
    now = detail.get("clock_minutes", 0)
    if not _is_int(now):
        now = 0

    def _extract_mag(val: Any) -> int:
        if _is_int(val):
            return abs(val)
        if isinstance(val, dict):
            exp = val.get("expires_at")
            if _is_int(exp) and exp <= now:
                return 0
            for k in ("value", "amount", "penalty"):
                if _is_int(val.get(k)):
                    return abs(int(val[k]))
        return 0

    total_mag = 0
    stat_norm = stat_key.casefold()

    net_debuffs = detail.get("net_debuffs")
    if isinstance(net_debuffs, dict):
        for k, v in net_debuffs.items():
            kn = _norm(k)
            if kn == stat_norm:
                total_mag += _extract_mag(v)
            elif kn in {"liche", "nervescrub"} and stat_key in {"INT", "REF", "DEX"}:
                total_mag += _extract_mag(v)
            elif kn == "scorpion" and stat_key == "MOVE":
                total_mag += _extract_mag(v)
    elif isinstance(net_debuffs, list):
        for entry in net_debuffs:
            if not isinstance(entry, dict):
                continue
            target = _norm(entry.get("stat") or entry.get("name") or "")
            if target == stat_norm:
                total_mag += _extract_mag(entry)
            elif target in {"liche", "nervescrub"} and stat_key in {"INT", "REF", "DEX"}:
                total_mag += _extract_mag(entry)
            elif target == "scorpion" and stat_key == "MOVE":
                total_mag += _extract_mag(entry)

    conditions = detail.get("conditions")
    if isinstance(conditions, dict):
        for k, v in conditions.items():
            kn = _norm(k)
            if kn == stat_norm:
                total_mag += _extract_mag(v)
            elif kn in {"liche", "nervescrub"} and stat_key in {"INT", "REF", "DEX"}:
                total_mag += _extract_mag(v)
            elif kn == "scorpion" and stat_key == "MOVE":
                total_mag += _extract_mag(v)

    return -total_mag if total_mag > 0 else 0


def _resolve_skill_or_specialty(char: dict[str, Any], skill: str | None) -> tuple[str | None, int]:
    if not isinstance(skill, str) or not skill.strip():
        return None, 0
    detail = _detail_ro(char)
    skills_map = _skills_ro(char)
    wanted = _norm(skill)

    matched_name: str | None = None
    best = 0
    found_in_skills = False

    for k, v in skills_map.items():
        if isinstance(k, str) and _norm(k) == wanted and _is_int(v):
            matched_name = k
            best = max(0, int(v))
            found_in_skills = True
            break

    if wanted in _MAKER_SPECIALTIES or wanted.replace("_", " ") in _MAKER_SPECIALTIES:
        canonical = _MAKER_SPECIALTIES.get(wanted) or _MAKER_SPECIALTIES[wanted.replace("_", " ")]
        canon_norm = _norm(canonical)
        matched_name = matched_name or canonical
        maker_ranks = detail.get("maker_ranks")
        if isinstance(maker_ranks, dict):
            for k, v in maker_ranks.items():
                if _norm(k).replace("_", " ") == canon_norm and _is_int(v):
                    best = max(best, int(v))
        roles = detail.get("roles")
        if isinstance(roles, list):
            for entry in roles:
                if not isinstance(entry, dict) or _norm(entry.get("role")) != "tech":
                    continue
                choices = entry.get("choices") if isinstance(entry.get("choices"), dict) else {}
                for container in (entry.get("maker_ranks"), choices.get("maker_ranks")):
                    if isinstance(container, dict):
                        for k, v in container.items():
                            if _norm(k).replace("_", " ") == canon_norm and _is_int(v):
                                best = max(best, int(v))
                maker_list = choices.get("maker")
                if isinstance(maker_list, list):
                    flat = [
                        item for elem in maker_list
                        for item in (elem if isinstance(elem, list) else [elem])
                        if isinstance(item, str)
                    ]
                    count = sum(1 for item in flat if _norm(item).replace("_", " ") == canon_norm)
                    best = max(best, count)
        return matched_name, best

    if wanted in _MEDTECH_SPECIALTIES or wanted.replace("_", " ") in _MEDTECH_SPECIALTIES:
        canonical = _MEDTECH_SPECIALTIES.get(wanted) or _MEDTECH_SPECIALTIES[wanted.replace("_", " ")]
        canon_norm = _norm(canonical)
        matched_name = matched_name or canonical
        medtech = detail.get("medtech")
        if isinstance(medtech, dict):
            for k, v in medtech.items():
                if _norm(k).replace("_", " ") == canon_norm and _is_int(v):
                    best = max(best, int(v))
        roles = detail.get("roles")
        if isinstance(roles, list):
            for entry in roles:
                if not isinstance(entry, dict) or _norm(entry.get("role")) != "medtech":
                    continue
                choices = entry.get("choices") if isinstance(entry.get("choices"), dict) else {}
                for container in (entry.get("medicine"), choices.get("medicine")):
                    if isinstance(container, dict):
                        for k, v in container.items():
                            if _norm(k).replace("_", " ") == canon_norm and _is_int(v):
                                best = max(best, int(v))
        return matched_name, best

    if wanted in _ROLE_ABILITY_TO_ROLE:
        target_role = _ROLE_ABILITY_TO_ROLE[wanted]
        matched_name = matched_name or skill.strip()
        roles = detail.get("roles")
        has_roles_list = isinstance(roles, list) and len(roles) > 0
        if isinstance(roles, list):
            for entry in roles:
                if isinstance(entry, dict) and str(entry.get("role") or "").strip().casefold() == target_role.casefold():
                    rank = entry.get("rank")
                    if _is_int(rank):
                        best = max(best, int(rank))
        top_role = str(char.get("role") or detail.get("role") or "").strip()
        top_rank = char.get("role_rank", detail.get("role_rank"))
        if _is_int(top_rank):
            if top_role.casefold() == target_role.casefold() or (not top_role and not has_roles_list):
                best = max(best, int(top_rank))
        return matched_name, best

    if found_in_skills:
        return matched_name, best
    return skill.strip(), 0


def _injury_penalty_for_check(
    injuries: list[dict[str, Any]],
    stat_key: str | None,
    skill_norm: str,
    tag_set: set[str],
) -> tuple[int, list[str]]:
    penalty = 0
    reasons: list[str] = []

    is_ranged = (
        "ranged" in tag_set
        or skill_norm in _RANGED_SKILLS
        or ("attack" in tag_set and "melee" not in tag_set and skill_norm not in _MELEE_SKILLS and not skill_norm.startswith("martial arts"))
    )
    is_melee = (
        "melee" in tag_set
        or skill_norm in _MELEE_SKILLS
        or skill_norm.startswith("martial arts")
    )
    is_perception = "perception" in tag_set or skill_norm == "perception"
    is_vision = "vision" in tag_set or (is_perception and "hearing" not in tag_set)
    is_hearing = "hearing" in tag_set or (is_perception and "vision" not in tag_set)
    is_speech = "speech" in tag_set or "social" in tag_set or skill_norm in _SPEECH_SKILLS
    is_hand = bool(tag_set & {"hand", "hands", "manual"}) or skill_norm in _HAND_SKILLS

    for inj in injuries:
        if inj.get("suppressed") or inj.get("treated") or inj.get("quick_fixed"):
            continue
        name = str(inj.get("name") or "")
        name_norm = _norm(name)
        delta = 0

        if name_norm in {"brain injury", "concussion"}:
            delta = -2
        elif name_norm == "lost eye" and (is_ranged or is_vision):
            delta = -4
        elif name_norm == "damaged eye" and (is_ranged or is_vision):
            delta = -2
        elif name_norm == "torn muscle" and is_melee:
            delta = -2
        elif name_norm == "broken jaw" and is_speech:
            delta = -4
        elif name_norm == "lost ear" and is_hearing:
            delta = -4
        elif name_norm == "damaged ear" and is_hearing:
            delta = -2
        elif name_norm == "crushed fingers" and is_hand:
            delta = -4
        elif stat_key == "MOVE":
            if name_norm in {"collapsed lung", "sprained ankle"}:
                delta = -2
            elif name_norm == "broken leg":
                delta = -4
            elif name_norm == "dismembered leg":
                delta = -6

        if delta < 0:
            penalty += delta
            reasons.append(f"{name} ({delta})")

    return penalty, reasons


def effective_check_context(
    char: dict[str, Any],
    stat: str | None,
    skill: str | None,
    *,
    tags: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Compute effective stat, skill, modifiers, and breakdown for a skill/stat check."""
    detail = _detail_ro(char)
    stats_map = _stats_ro(char)
    stat_key = stat.strip().upper() if isinstance(stat, str) and stat.strip() else None
    tag_set = {_norm(t) for t in tags if isinstance(t, str) and t.strip()}
    reasons: list[str] = []

    if stat_key is None or stat_key == "ROLE":
        base_stat_value = 0
    elif stat_key == "EMP":
        base_stat_value = effective_emp(char)
    elif stat_key == "BODY":
        base_stat_value = effective_body(char)
    else:
        base_stat_value = max(0, _stat_lookup(stats_map, stat_key))

    resolved_skill, skill_value = _resolve_skill_or_specialty(char, skill)
    skill_norm = _norm(resolved_skill or skill or "")

    sub_stats, sub_skills, _ = _substance_values_safe(char)
    substance_stat_delta = 0
    if stat_key and stat_key not in {"ROLE", "EMP", "BODY"}:
        raw_stat = max(0, _stat_lookup(stats_map, stat_key))
        if stat_key in sub_stats and _is_int(sub_stats[stat_key]):
            substance_stat_delta = int(sub_stats[stat_key]) - raw_stat

    substance_skill_delta = 0
    if skill_norm:
        raw_skill = 0
        for k, v in _skills_ro(char).items():
            if isinstance(k, str) and _norm(k) == skill_norm and _is_int(v):
                raw_skill = int(v)
                break
        for k, v in sub_skills.items():
            if isinstance(k, str) and _norm(k) == skill_norm and _is_int(v):
                substance_skill_delta = int(v) - raw_skill
                break

    substance_modifier = substance_stat_delta + substance_skill_delta
    if substance_stat_delta:
        reasons.append(f"substance stat ({substance_stat_delta:+d} {stat_key})")
    if substance_skill_delta:
        reasons.append(f"substance skill ({substance_skill_delta:+d} {resolved_skill})")

    net_debuff = _resolve_net_debuff(char, stat_key)
    if net_debuff < 0:
        reasons.append(f"NET debuff ({net_debuff} {stat_key})")

    if stat_key is None or stat_key == "ROLE":
        stat_value = 0
    else:
        stat_value = max(0, base_stat_value + substance_stat_delta + net_debuff)

    armor_mag = effective_armor_penalty(char) if stat_key in {"REF", "DEX", "MOVE"} else 0
    armor_penalty = -armor_mag if armor_mag > 0 else 0
    if armor_penalty < 0:
        reasons.append(f"armor penalty ({armor_penalty})")

    wound_penalty = effective_wound_penalty(char)
    if wound_penalty < 0:
        reasons.append(f"wound penalty ({wound_penalty})")

    injuries = active_injuries(char)
    injury_penalty, injury_reasons = _injury_penalty_for_check(injuries, stat_key, skill_norm, tag_set)
    reasons.extend(injury_reasons)

    solo_raw = detail.get("solo_allocation")
    if not isinstance(solo_raw, dict):
        solo_raw = detail.get("combat_awareness")
    solo_alloc = solo_raw if isinstance(solo_raw, dict) else {}

    def _solo_pts(key: str) -> int:
        val = solo_alloc.get(key, 0)
        return max(0, val) if _is_int(val) else 0

    threat_detection = _solo_pts("threat_detection")
    precision_pts = _solo_pts("precision_attack")
    fumble_pts = _solo_pts("fumble_recovery")
    spot_weakness = _solo_pts("spot_weakness")
    damage_deflection = _solo_pts("damage_deflection")
    initiative_reaction = _solo_pts("initiative_reaction")
    fumble_recovery = bool(solo_alloc.get("fumble_recovery") is True or fumble_pts >= 4)

    solo_bonus = 0
    if threat_detection and (skill_norm == "perception" or "perception" in tag_set):
        solo_bonus += threat_detection
        reasons.append(f"Combat Awareness: Threat Detection (+{threat_detection})")

    is_attack = (
        bool(tag_set & {"attack", "ranged", "melee"})
        or skill_norm in _ATTACK_SKILLS
        or skill_norm.startswith("martial arts")
    )
    if precision_pts >= 3 and is_attack:
        prec_bonus = precision_pts // 3
        solo_bonus += prec_bonus
        reasons.append(f"Combat Awareness: Precision Attack (+{prec_bonus})")

    if initiative_reaction and ("initiative" in tag_set or skill_norm == "initiative"):
        solo_bonus += initiative_reaction
        reasons.append(f"Combat Awareness: Initiative Reaction (+{initiative_reaction})")

    if fumble_recovery:
        reasons.append("Combat Awareness: Fumble Recovery")

    total_modifier = armor_penalty + wound_penalty + injury_penalty + substance_skill_delta + solo_bonus
    effective_base = stat_value + skill_value + total_modifier

    return {
        "stat": stat_key,
        "base_stat_value": base_stat_value,
        "stat_value": stat_value,
        "skill": resolved_skill,
        "skill_value": skill_value,
        "armor_penalty": armor_penalty,
        "wound_penalty": wound_penalty,
        "injury_penalty": injury_penalty,
        "substance_modifier": substance_modifier,
        "net_debuff": net_debuff,
        "solo_bonus": solo_bonus,
        "fumble_recovery": fumble_recovery,
        "spot_weakness": spot_weakness,
        "damage_deflection": damage_deflection,
        "initiative_reaction": initiative_reaction,
        "total_modifier": total_modifier,
        "effective_base": effective_base,
        "reasons": reasons,
    }


def _is_cyberarm_entry(entry: Any) -> bool:
    if isinstance(entry, str):
        low = entry.casefold()
        return "cyberarm" in low and not any(x in low for x in ("option", "gauntlet", "covering", "sleeve"))
    if isinstance(entry, dict):
        if entry.get("installed") is False or entry.get("disabled") is True:
            return False
        if entry.get("type") == "cyberarm":
            return True
        name = str(entry.get("name") or "").casefold()
        eid = str(entry.get("id") or "").casefold()
        if "cyberarm" in name and not any(x in name for x in ("option", "gauntlet", "covering", "sleeve")):
            return True
        if "cyberarm" in eid and "option" not in eid:
            return True
    return False


def sync_equipment_views(char: dict[str, Any]) -> dict[str, Any]:
    """Synchronize equipment, hand/cyberarm flags, ammo inventory, and UI summary keys in-place."""
    from encounters import WEAPONS

    detail = char.get("detail")
    if not isinstance(detail, dict):
        detail = {}
        char["detail"] = detail

    equipment = detail.get("equipment")
    if not isinstance(equipment, dict):
        equipment = {}
        detail["equipment"] = equipment

    weapons = equipment.get("weapons")
    if not isinstance(weapons, list):
        weapons = []
        equipment["weapons"] = weapons

    armor_list = equipment.get("armor")
    if not isinstance(armor_list, list):
        armor_list = []
        equipment["armor"] = armor_list

    if not _is_int(detail.get("free_hands")):
        detail["free_hands"] = 2

    cyberware = detail.get("cyberware")
    has_cyberarm = detail.get("cyberarm") is True or (
        isinstance(cyberware, list) and any(_is_cyberarm_entry(cw) for cw in cyberware)
    )
    detail["cyberarm"] = has_cyberarm

    inventory = char.get("inventory")
    if inventory is None:
        inventory = {}
        char["inventory"] = inventory
    if isinstance(inventory, dict):
        ammo_updates: dict[str, int] = {}
        for key in list(inventory.keys()):
            if not isinstance(key, str):
                continue
            m = re.match(r"^\s*ammo\s*:\s*(.+?)\s*$", key, re.I)
            if not m:
                continue
            raw_kind = re.sub(r"\s+", " ", m.group(1)).strip()
            canon_kind = _CANONICAL_AMMO_KINDS.get(raw_kind.casefold(), raw_kind)
            canon_key = f"ammo:{canon_kind}"
            val = inventory.pop(key)
            if _is_int(val):
                count = max(0, int(val))
            elif isinstance(val, str) and re.fullmatch(r"\s*[+-]?\d+\s*", val):
                count = max(0, int(val.strip()))
            else:
                count = 0
            ammo_updates[canon_key] = ammo_updates.get(canon_key, 0) + count
        inventory.update(ammo_updates)

    # Sync weapons <-> equipped_weapon
    weapon_types = [str(w.get("type") or w.get("name") or "").strip() for w in weapons if isinstance(w, dict)]
    weapon_types = [w for w in weapon_types if w]
    eq_weapon = detail.get("equipped_weapon")
    eq_weapon_str = eq_weapon.strip() if isinstance(eq_weapon, str) and eq_weapon.strip() else ""
    if weapon_types:
        if not eq_weapon_str or _norm(eq_weapon_str) not in {_norm(w) for w in weapon_types}:
            detail["equipped_weapon"] = weapon_types[-1]
    elif eq_weapon_str:
        cleaned_eq = re.sub(r"\s*—.*$", "", eq_weapon_str).strip()
        cleaned_eq_noparen = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned_eq).strip()
        matched_type = next(
            (w for candidate in (eq_weapon_str, cleaned_eq, cleaned_eq_noparen)
             for w in WEAPONS if _norm(w) == _norm(candidate)),
            None,
        )
        if matched_type is not None:
            defn = WEAPONS[matched_type]
            idx = detail.get("next_weapon_index", len(weapons))
            if not _is_int(idx) or idx < len(weapons):
                idx = len(weapons)
            weapons.append({
                "id": f"weapon-{idx}",
                "type": matched_type,
                "loaded": int(defn.get("magazine") or 0),
                "ammo_kind": defn.get("ammo"),
            })
            detail["next_weapon_index"] = idx + 1

    # Sync armor <-> equipped_armor / equipped_head_armor
    body_armors = [
        a for a in armor_list
        if isinstance(a, dict) and a.get("equipped") is not False and str(a.get("location") or "body").strip().casefold() in {"body", "body & head"}
    ]
    head_armors = [
        a for a in armor_list
        if isinstance(a, dict) and a.get("equipped") is not False and str(a.get("location") or "").strip().casefold() in {"head", "body & head"}
    ]

    def _armor_summary(piece: dict[str, Any]) -> dict[str, Any]:
        name_val = str(piece.get("type") or piece.get("name") or "").strip()
        sp_val = int(piece["sp"]) if _is_int(piece.get("sp")) else 0
        summary: dict[str, Any] = {"name": name_val, "sp": sp_val}
        if _is_int(piece.get("penalty")):
            summary["penalty"] = int(piece["penalty"])
        return summary

    if body_armors:
        best_body = max(body_armors, key=lambda a: int(a["sp"]) if _is_int(a.get("sp")) else 0)
        detail["equipped_armor"] = _armor_summary(best_body)
    elif isinstance(detail.get("equipped_armor"), dict) and str(detail["equipped_armor"].get("name") or "").strip():
        ea = detail["equipped_armor"]
        ea_name = str(ea["name"]).strip()
        ea_sp = int(ea["sp"]) if _is_int(ea.get("sp")) else 0
        ea_pen = _armor_piece_penalty(ea)
        idx = detail.get("next_armor_index", len(armor_list))
        if not _is_int(idx) or idx < len(armor_list):
            idx = len(armor_list)
        piece = {
            "id": f"armor-{idx}",
            "type": ea_name,
            "sp": ea_sp,
            "max_sp": ea_sp,
            "location": "body",
            "penalty": ea_pen,
        }
        armor_list.append(piece)
        detail["next_armor_index"] = idx + 1
        detail["equipped_armor"] = _armor_summary(piece)

    if head_armors:
        best_head = max(head_armors, key=lambda a: int(a["sp"]) if _is_int(a.get("sp")) else 0)
        detail["equipped_head_armor"] = _armor_summary(best_head)
    elif isinstance(detail.get("equipped_head_armor"), dict) and str(detail["equipped_head_armor"].get("name") or "").strip():
        eh = detail["equipped_head_armor"]
        eh_name = str(eh["name"]).strip()
        eh_sp = int(eh["sp"]) if _is_int(eh.get("sp")) else 0
        eh_pen = _armor_piece_penalty(eh)
        idx = detail.get("next_armor_index", len(armor_list))
        if not _is_int(idx) or idx < len(armor_list):
            idx = len(armor_list)
        piece = {
            "id": f"armor-{idx}",
            "type": eh_name,
            "sp": eh_sp,
            "max_sp": eh_sp,
            "location": "head",
            "penalty": eh_pen,
        }
        armor_list.append(piece)
        detail["next_armor_index"] = idx + 1
        detail["equipped_head_armor"] = _armor_summary(piece)

    return char


def recompute_death_save_base_penalty(char: dict[str, Any]) -> int:
    """Count active unsuppressed Critical Injuries imposing a Death Save penalty and store it."""
    total = 0
    for inj in active_injuries(char):
        if inj.get("suppressed") or inj.get("treated") or inj.get("quick_fixed"):
            continue
        pen = inj.get("death_save_penalty", 1)
        if _is_int(pen) and pen > 0:
            total += int(pen)
    detail = char.setdefault("detail", {})
    if not isinstance(detail, dict):
        detail = {}
        char["detail"] = detail
    detail["death_save_base_penalty"] = total
    return total


def apply_death_save(char: dict[str, Any], randbelow: Callable[[int], int] = secrets.randbelow) -> dict[str, Any]:
    """Roll a Death Save using base_penalty + escalation_penalty and update escalation counter."""
    detail = char.setdefault("detail", {})
    if not isinstance(detail, dict):
        detail = {}
        char["detail"] = detail

    base_penalty = recompute_death_save_base_penalty(char)
    raw_esc = detail.get("death_save_penalty", 0)
    escalation_penalty = max(0, int(raw_esc)) if _is_int(raw_esc) else 0

    total_penalty = base_penalty + escalation_penalty
    res = copy.deepcopy(combat.death_save(effective_body(char), total_penalty, randbelow=randbelow))
    next_escalation = escalation_penalty + 1
    detail["death_save_penalty"] = next_escalation

    if res["dead"]:
        detail["dead"] = True
        conds = detail.get("conditions")
        if not isinstance(conds, dict):
            conds = {}
            detail["conditions"] = conds
        conds["dead"] = True

    res.update({
        "base_penalty": base_penalty,
        "escalation_penalty": escalation_penalty,
        "total_penalty": total_penalty,
        "next_escalation_penalty": next_escalation,
    })
    return res
