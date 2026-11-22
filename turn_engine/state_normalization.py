"""Character, party-grouping, NPC identity, clock-label, and campaign-state normalization helpers."""
from __future__ import annotations

import json
import re
from typing import Any

from combat import wound_state

_CLOCK_CATEGORIES = frozenset({"heat", "obligation", "deadline", "faction", "recovery"})

_CANONICAL_ROLE_CHECKS: dict[str, tuple[str, str]] = {
    "interface": ("Interface", "ROLE"),
    "charismatic impact": ("Charismatic Impact", "ROLE"),
    "credibility": ("Credibility", "ROLE"),
    "operator": ("Operator", "ROLE"),
    "moto": ("Moto", "ROLE"),
    "combat awareness": ("Combat Awareness", "ROLE"),
    "backup": ("Backup", "ROLE"),
    "teamwork": ("Teamwork", "ROLE"),
    "maker": ("Maker", "TECH"),
    "field expertise": ("Field Expertise", "TECH"),
    "upgrade expertise": ("Upgrade Expertise", "TECH"),
    "fabrication expertise": ("Fabrication Expertise", "TECH"),
    "invention expertise": ("Invention Expertise", "TECH"),
    "medicine": ("Medicine", "TECH"),
    "surgery": ("Surgery", "TECH"),
    "medical tech": ("Medical Tech", "TECH"),
    "medical technology": ("Medical Tech", "TECH"),
    "pharmaceuticals": ("Pharmaceuticals", "TECH"),
    "cryosystem operation": ("Cryosystem Operation", "TECH"),
}


def _format_clock_label(total_minutes: int) -> str:
    mins = max(0, int(total_minutes))
    day = (mins // 1440) + 1
    rem = mins % 1440
    hour = rem // 60
    minute = rem % 60
    if hour < 5:
        tod = "Late Night"
    elif hour < 8:
        tod = "Dawn"
    elif hour < 12:
        tod = "Morning"
    elif hour < 17:
        tod = "Afternoon"
    elif hour < 21:
        tod = "Evening"
    else:
        tod = "Night"
    return f"Day {day}, {hour:02d}:{minute:02d} ({tod})"


def _parse_clock_minutes(raw: Any) -> int | None:
    """Parse an HH:MM wall-clock string into minutes from 00:00 (0..1439)."""
    if not isinstance(raw, str):
        return None
    m = re.search(r"\b(\d{1,2}):(\d{2})(?:\s*(am|pm))?\b", raw.strip(), re.I)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _collect_npc_needles(
    known_npcs: dict[str, Any] | list[str] | set[str] | tuple[str, ...] | None,
) -> tuple[set[str], set[str]]:
    """Return (exact_npc_names, npc_first_tokens) in casefolded form."""
    exact: set[str] = set()
    tokens: set[str] = set()
    if not known_npcs:
        return exact, tokens
    items: list[str] = []
    if isinstance(known_npcs, dict):
        for k, v in known_npcs.items():
            if isinstance(k, str) and k.strip():
                items.append(k.strip())
            if isinstance(v, dict):
                for subk in ("handle", "name"):
                    sv = v.get(subk)
                    if isinstance(sv, str) and sv.strip():
                        items.append(sv.strip())
    elif isinstance(known_npcs, (list, set, tuple)):
        for entry in known_npcs:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip())
    for raw in items:
        base = raw.split("(", 1)[0].strip().casefold()
        full = raw.casefold()
        if full:
            exact.add(full)
        if base:
            exact.add(base)
            parts = base.split()
            if parts and len(parts[0]) >= 2:
                tokens.add(parts[0])
    return exact, tokens


def _resolve_character(
    actor: str | None,
    characters: list[dict[str, Any]],
    *,
    known_npcs: dict[str, Any] | list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    if not characters:
        return None
    if not isinstance(actor, str) or not actor.strip():
        return characters[0] if len(characters) == 1 else None
    raw_actor = actor.strip()
    needle = raw_actor.casefold()

    # 1. Exact match by ID, name, or street handle (case-insensitive for name/handle).
    for char in characters:
        d = char.get("detail") or {}
        handle = str(d.get("handle") or "").strip()
        cname = str(char.get("name") or "").strip()
        if char.get("id") == raw_actor or cname.casefold() == needle or (handle and handle.casefold() == needle):
            return char

    # 2. Reject known NPC names/handles so NPC checks never fuzzy-match onto a PC.
    npc_exact, npc_tokens = _collect_npc_needles(known_npcs)
    if needle in npc_exact:
        return None

    # 3. Unambiguous first-token match against street handle or non-hidden name.
    token_matches: list[dict[str, Any]] = []
    for char in characters:
        d = char.get("detail") or {}
        handle = str(d.get("handle") or "").strip()
        cname = str(char.get("name") or "").strip()
        hidden = bool(d.get("real_name_hidden", False))
        candidates: list[str] = []
        if handle:
            candidates.append(handle)
        if cname and (not hidden or not handle):
            candidates.append(cname)
        matched_this = False
        for cand in candidates:
            parts = cand.split()
            if parts and parts[0].casefold() == needle and needle not in npc_tokens:
                matched_this = True
                break
        if matched_this:
            token_matches.append(char)

    if len(token_matches) == 1:
        return token_matches[0]
    return None


def _summarize_character(char: dict[str, Any], *, include_hidden: bool = True) -> dict[str, Any]:
    """Render canonical snapshot of character state for rules planning and narration."""
    max_h = int(char.get("max_hp") or 0)
    body_stat = int((char.get("stats") or {}).get("BODY", 0))
    move_stat = int((char.get("stats") or {}).get("MOVE", 0))
    d = char.get("detail") or {}
    role_ext = d.get("role_ext") or {}
    char_ip = int(role_ext.get("ip") or d.get("ip") or 0)
    handle = str(d.get("handle") or char.get("name") or "").strip()
    real_name = str(d.get("real_name") or "").strip()
    real_name_hidden = bool(d.get("real_name_hidden", True if (handle and real_name) else False))
    expose_real = bool(real_name) and (include_hidden or not real_name_hidden)
    if handle and real_name and real_name_hidden:
        if include_hidden:
            identity_note = f"Street Handle: '{handle}' | Real Name: '{real_name}' (HIDDEN/SECRET — NPCs and the world DO NOT know their real name unless revealed in play)"
        else:
            identity_note = f"Street Handle: '{handle}' (Real identity hidden)"
    elif handle and real_name:
        identity_note = f"Street Handle: '{handle}' | Real Name: '{real_name}' (Publicly known)"
    else:
        identity_note = f"Street Handle: '{handle}' (Goes by handle only)"
    detail_out = dict(d)
    if not include_hidden and real_name_hidden:
        detail_out.pop("real_name", None)
    display_name = handle if (not include_hidden and real_name_hidden and handle) else char["name"]
    return {
        "id": char["id"],
        "name": display_name,
        "handle": handle,
        **({"real_name": real_name} if expose_real else {}),
        "real_name_hidden": real_name_hidden,
        "identity_note": identity_note,
        **({"gender": str(d["gender"]).strip()} if isinstance(d.get("gender"), str) and str(d["gender"]).strip() else {}),
        **({"pronouns": str(d["pronouns"]).strip()} if isinstance(d.get("pronouns"), str) and str(d["pronouns"]).strip() else {}),
        **({"owner_username": d["owner_username"]} if d.get("owner_username") else {}),
        **({"color": d["color"]} if d.get("color") else {}),
        "hp": char["hp"],
        "max_hp": char["max_hp"],
        "seriously_wounded": (max_h + 1) // 2,
        "death_save": int((d.get("creation") or {}).get("effective_body") or d.get("death_save") or body_stat),
        "wound_state": wound_state(max(0, char["hp"]), char["max_hp"], move_stat),
        "humanity": char["humanity"],
        "luck_remaining": char["luck_remaining"],
        "money": char["money"],
        "ip": char_ip,
        "stats": char["stats"],
        "skills": char["skills"],
        "inventory": char.get("inventory") or {},
        **({"equipped_weapon": d["equipped_weapon"]} if isinstance(d.get("equipped_weapon"), str) and d["equipped_weapon"].strip() else {}),
        **({"equipped_armor": d["equipped_armor"]} if isinstance(d.get("equipped_armor"), dict) and d["equipped_armor"].get("name") else {}),
        **({"equipped_head_armor": d["equipped_head_armor"]} if isinstance(d.get("equipped_head_armor"), dict) and d["equipped_head_armor"].get("name") else {}),
        "detail": detail_out,
    }


def _normalize_character_changes(
    raw_changes: dict[str, Any], current_char: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    mapped = dict(raw_changes)
    if "eddies" in mapped and "money" not in mapped:
        mapped["money"] = mapped.pop("eddies")
    allowed = {"hp", "money", "inventory", "humanity"}
    ignored = sorted(k for k in mapped if k not in allowed)
    clean: dict[str, Any] = {}
    notes: list[str] = []
    if ignored:
        notes.append(f"Ignored unsupported character field(s): {', '.join(ignored)}")
    for num_key in ("hp", "money", "humanity"):
        if num_key in mapped and mapped[num_key] is not None:
            try:
                clean[num_key] = int(mapped[num_key])
            except (TypeError, ValueError):
                notes.append(f"Ignored non-integer character {num_key}: {mapped[num_key]!r}")
    if "inventory" in mapped and mapped["inventory"] is not None:
        merged_inv = dict(current_char.get("inventory") or {})
        raw_inv = mapped["inventory"]
        if isinstance(raw_inv, dict):
            for item_name, qty in raw_inv.items():
                name = str(item_name).strip()[:120]
                if not name:
                    continue
                if qty is None:
                    merged_inv.pop(name, None)
                    continue
                try:
                    n_qty = int(qty)
                except (TypeError, ValueError):
                    n_qty = 1
                if n_qty <= 0:
                    merged_inv.pop(name, None)
                else:
                    merged_inv[name] = n_qty
            clean["inventory"] = merged_inv
        elif isinstance(raw_inv, list):
            for entry in raw_inv:
                name = str(entry).strip()[:120]
                if name:
                    merged_inv[name] = merged_inv.get(name, 0) + 1
            clean["inventory"] = merged_inv
    return clean, notes


def _slug_channel_id(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").strip().lower()).strip("-")
    return f"scene-{slug[:42]}" if slug else "scene-split"


def parse_party_locations(state: dict[str, Any] | None) -> dict[str, Any]:
    disc = (state or {}).get("discoveries") or {}
    raw = disc.get("__party_locations")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                locs = parsed.get("locations") if isinstance(parsed.get("locations"), dict) else {}
                chans = parsed.get("channels") if isinstance(parsed.get("channels"), dict) else {}
                mode = "split" if parsed.get("mode") == "split" else "together"
                return {
                    "mode": mode,
                    "locations": {str(k): str(v).strip()[:160] for k, v in locs.items() if str(k).strip() and str(v).strip()},
                    "channels": chans,
                }
        except json.JSONDecodeError:
            pass
    return {"mode": "together", "locations": {}, "channels": {}}


def compute_party_grouping(
    characters: list[dict[str, Any]],
    state: dict[str, Any] | None,
    active_channel_id: str = "main",
) -> dict[str, Any]:
    """Resolve whether attached PCs are together or split into separate scene channels."""
    default_scene = str((state or {}).get("scene") or "").strip() or "Current Scene"
    stored = parse_party_locations(state)
    locs: dict[str, str] = stored["locations"]
    stored_channels: dict[str, Any] = stored.get("channels") or {}
    pc_rows: list[dict[str, Any]] = []
    for c in characters:
        cid = str(c.get("id") or "")
        d = c.get("detail") or {}
        handle = str(d.get("handle") or c.get("name") or "Edgerunner").strip()
        loc = locs.get(cid) or locs.get(handle) or default_scene
        pc_rows.append({"id": cid, "handle": handle, "location": loc, "norm": " ".join(loc.lower().split())})

    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in pc_rows:
        clusters.setdefault(row["norm"], []).append(row)

    is_split = len(characters) >= 2 and (len(clusters) > 1 or stored["mode"] == "split" and len(stored_channels) > 1)
    channels_list: list[dict[str, Any]] = []
    char_channel_map: dict[str, str] = {}

    if is_split:
        used_ids: set[str] = set()
        for norm_loc, members in clusters.items():
            loc_label = members[0]["location"]
            existing_cid = None
            member_ids = {m["id"] for m in members}
            for ch_id, ch_meta in stored_channels.items():
                if isinstance(ch_meta, dict):
                    ch_mems = set(ch_meta.get("character_ids") or [])
                    if ch_mems & member_ids and ch_id not in used_ids and ch_id != "main":
                        existing_cid = ch_id
                        break
            cid = existing_cid or _slug_channel_id(loc_label)
            base_cid = cid
            suffix = 2
            while cid in used_ids or cid == "main":
                cid = f"{base_cid}-{suffix}"
                suffix += 1
            used_ids.add(cid)
            channels_list.append({
                "id": cid,
                "name": loc_label,
                "location": loc_label,
                "character_ids": [m["id"] for m in members],
                "handles": [m["handle"] for m in members],
            })
            for m in members:
                char_channel_map[m["id"]] = cid
    else:
        for row in pc_rows:
            char_channel_map[row["id"]] = "main"

    active_chan = str(active_channel_id or "main").strip() or "main"
    active_group = next((ch for ch in channels_list if ch["id"] == active_chan), None) if is_split else None
    if is_split and active_group is not None:
        present_handles = active_group["handles"]
        absent = [f"{r['handle']} (@ {r['location']})" for r in pc_rows if r["id"] not in set(active_group["character_ids"])]
        prompt_summary = (
            f"SPLIT PARTY — Active Scene Channel '{active_group['location']}' ({active_chan}): "
            f"Present here: {', '.join(present_handles)}. "
            f"Elsewhere (NOT present in this scene): {', '.join(absent) if absent else 'none'}."
        )
    elif is_split:
        parts = [f"[{', '.join(ch['handles'])}] @ {ch['location']} ({ch['id']})" for ch in channels_list]
        prompt_summary = "SPLIT PARTY — Separate groups: " + " | ".join(parts)
    elif pc_rows:
        prompt_summary = f"TOGETHER — All party members ({', '.join(r['handle'] for r in pc_rows)}) are together at: {pc_rows[0]['location']}."
    else:
        prompt_summary = f"Scene location: {default_scene}."

    return {
        "mode": "split" if is_split else "together",
        "characters": [{"id": r["id"], "handle": r["handle"], "location": r["location"], "channel_id": char_channel_map.get(r["id"], "main")} for r in pc_rows],
        "channels": channels_list,
        "char_channel_map": char_channel_map,
        "active_channel_id": active_chan,
        "active_location": active_group["location"] if active_group else (pc_rows[0]["location"] if pc_rows and not is_split else default_scene),
        "prompt_summary": prompt_summary,
    }


def _encode_party_locations_json(mode: str, locations: dict[str, str], channels: dict[str, Any]) -> str:
    """Serialize __party_locations cleanly within the 2000-char discovery field limit without breaking JSON."""
    payload = {
        "mode": mode,
        "locations": {str(k)[:48]: str(v)[:100] for k, v in locations.items()},
        "channels": {
            str(cid)[:40]: {
                "id": str(meta.get("id") or cid)[:40],
                "name": str(meta.get("name") or "")[:64],
                "location": str(meta.get("location") or "")[:64],
                "character_ids": [str(x)[:48] for x in (meta.get("character_ids") or [])],
                "handles": [str(x)[:32] for x in (meta.get("handles") or [])],
            }
            for cid, meta in (channels or {}).items()
            if isinstance(meta, dict)
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(raw) <= 2000:
        return raw
    payload["locations"] = {k: v[:40] for k, v in payload["locations"].items()}
    for meta in payload["channels"].values():
        meta["name"] = meta["name"][:32]
        meta["location"] = meta["location"][:32]
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(raw) <= 2000:
        return raw
    # Last resort: drop redundant channel mirrors since compute_party_grouping rebuilds them from locations
    payload["channels"] = {}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)[:2000]


def _encode_npc_identities_json(cur_ids: dict[str, dict[str, Any]]) -> str:
    """Serialize __npc_identities within 1950 chars without ever producing truncated invalid JSON."""
    clean: dict[str, dict[str, Any]] = dict(cur_ids)
    raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    while len(raw) > 1950 and clean:
        first_key = next(iter(clean))
        clean.pop(first_key, None)
        raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    return raw if len(raw) <= 1950 else "{}"


def encode_campaign_meta_json(meta: dict[str, Any]) -> str:
    """Serialize __campaign_meta safely within 1950 chars without truncating JSON."""
    if not isinstance(meta, dict):
        return "{}"
    clean: dict[str, Any] = {}
    for k in ("district", "zone_type", "threat_rating", "caper_style"):
        val = str(meta.get(k) or "").strip()[:120]
        if val:
            clean[k] = val
    hook = str(meta.get("screamsheet_hook") or "").strip()[:360]
    if hook:
        clean["screamsheet_hook"] = hook
    factions = [str(f).strip()[:60] for f in (meta.get("factions") or []) if str(f).strip()][:8]
    if factions:
        clean["factions"] = factions
    raw_fd = meta.get("faction_details")
    if isinstance(raw_fd, list):
        fds = [
            {
                "name": str(item.get("name") or "").strip()[:60],
                "disposition": str(item.get("disposition") or "Neutral").strip()[:24],
                **({"turf": str(item.get("turf") or "").strip()[:120]} if str(item.get("turf") or "").strip() else {}),
            }
            for item in raw_fd[:6]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if fds:
            clean["faction_details"] = fds
    raw_locs = meta.get("locations")
    if isinstance(raw_locs, list):
        locs = [
            {
                "name": str(item.get("name") or "").strip()[:80],
                **({"district": str(item.get("district") or "").strip()[:60]} if str(item.get("district") or "").strip() else {}),
                **({"security": str(item.get("security") or "").strip()[:48]} if str(item.get("security") or "").strip() else {}),
                **({"notes": str(item.get("notes") or "").strip()[:140]} if str(item.get("notes") or "").strip() else {}),
            }
            for item in raw_locs[:6]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if locs:
            clean["locations"] = locs
    raw_gig = meta.get("gig")
    if isinstance(raw_gig, dict) and any(str(raw_gig.get(x) or "").strip() for x in ("title", "client", "target", "notes")):
        gig_obj: dict[str, Any] = {}
        for gk, glim in (("title", 90), ("client", 80), ("target", 120), ("deadline", 60), ("notes", 160)):
            gv = str(raw_gig.get(gk) or "").strip()[:glim]
            if gv:
                gig_obj[gk] = gv
        if isinstance(raw_gig.get("payout_eb"), (int, float)) and raw_gig["payout_eb"] >= 0:
            gig_obj["payout_eb"] = int(raw_gig["payout_eb"])
        if gig_obj:
            clean["gig"] = gig_obj
    raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    for drop_key in ("locations", "faction_details", "gig", "screamsheet_hook"):
        if len(raw) <= 1950:
            break
        clean.pop(drop_key, None)
        raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    return raw if len(raw) <= 1950 else "{}"


def parse_campaign_meta(state: dict[str, Any] | None) -> dict[str, Any]:
    """Decode __campaign_meta from campaign state discoveries."""
    disc = (state or {}).get("discoveries") or {}
    raw = disc.get("__campaign_meta")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def encode_session_zero_json(cfg: dict[str, Any]) -> str:
    """Serialize __session_zero safely within 1950 chars."""
    if not isinstance(cfg, dict):
        return "{}"
    clean: dict[str, Any] = {}
    for k, lim in (
        ("gm_style", 40),
        ("narrator_length", 32),
        ("narrator_pacing", 32),
        ("lethality_dial", 40),
        ("economy_dial", 40),
        ("campaign_scope", 40),
        ("crew_concept", 320),
        ("lines_and_veils", 500),
    ):
        val = str(cfg.get(k) or "").strip()[:lim]
        if val and val != "inherit":
            clean[k] = val
    if isinstance(cfg.get("starting_clock_minutes"), int) and cfg["starting_clock_minutes"] >= 0:
        clean["starting_clock_minutes"] = int(cfg["starting_clock_minutes"])
    raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    if len(raw) > 1950 and "lines_and_veils" in clean:
        clean["lines_and_veils"] = str(clean["lines_and_veils"])[:240]
        raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    if len(raw) > 1950 and "crew_concept" in clean:
        clean["crew_concept"] = str(clean["crew_concept"])[:160]
        raw = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    return raw if len(raw) <= 1950 else "{}"


def parse_session_zero(state: dict[str, Any] | None) -> dict[str, Any]:
    """Decode __session_zero from campaign state discoveries."""
    disc = (state or {}).get("discoveries") or {}
    raw = disc.get("__session_zero")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def apply_pc_locations_to_discoveries(
    current_state: dict[str, Any],
    characters: list[dict[str, Any]],
    pc_locations: dict[str, Any] | None = None,
    *,
    all_together_location: str | None = None,
) -> dict[str, str]:
    """Return an updated discoveries dict with __party_locations encoded."""
    disc = dict((current_state or {}).get("discoveries") or {})
    default_scene = str((current_state or {}).get("scene") or "").strip() or "Current Scene"
    if isinstance(all_together_location, str) and all_together_location.strip():
        loc = all_together_location.strip()[:160]
        locs = {str(c["id"]): loc for c in characters if c.get("id")}
        disc["__party_locations"] = _encode_party_locations_json("together", locs, {})
        return disc

    stored = parse_party_locations(current_state)
    locs = dict(stored["locations"])
    for c in characters:
        cid = str(c.get("id") or "")
        if cid and cid not in locs:
            locs[cid] = default_scene

    if isinstance(pc_locations, dict):
        for raw_actor, raw_loc in pc_locations.items():
            loc_str = str(raw_loc or "").strip()[:160]
            if not loc_str:
                continue
            matched = _resolve_character(str(raw_actor), characters)
            key = str(matched["id"]) if matched else str(raw_actor).strip()
            if key:
                locs[key] = loc_str

    # Recompute clusters naturally without forcing "split" when everyone converges to one location.
    temp_state = {
        **(current_state or {}),
        "discoveries": {
            **disc,
            "__party_locations": _encode_party_locations_json("together", locs, stored.get("channels") or {}),
        },
    }
    grouped = compute_party_grouping(characters, temp_state)
    channels_map = {ch["id"]: ch for ch in grouped["channels"]} if grouped["mode"] == "split" else {}
    disc["__party_locations"] = _encode_party_locations_json(grouped["mode"], locs, channels_map)
    return disc


def parse_npc_identities_public(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    disc = (state or {}).get("discoveries") or {}
    raw = disc.get("__npc_identities")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                out: dict[str, dict[str, Any]] = {}
                for k, v in parsed.items():
                    if isinstance(k, str) and k.strip() and isinstance(v, dict):
                        out[k.strip()] = {
                            "handle": str(v.get("handle") or k).strip(),
                            **({"real_name": str(v["real_name"]).strip()} if isinstance(v.get("real_name"), str) and v["real_name"].strip() else {}),
                            "real_name_hidden": bool(v.get("real_name_hidden", True)),
                            **({"personality": str(v["personality"]).strip()} if isinstance(v.get("personality"), str) and v["personality"].strip() else {}),
                            **({"speech_style": str(v["speech_style"]).strip()} if isinstance(v.get("speech_style"), str) and v["speech_style"].strip() else {}),
                        }
                return out
        except json.JSONDecodeError:
            pass
    return {}


def build_npc_profiles(
    state: dict[str, Any] | None,
    gm_secrets: dict[str, str] | None = None,
    *,
    include_hidden: bool = True,
) -> dict[str, dict[str, Any]]:
    """Combine public NPC entries, public identity metadata, and secret NPC legal names."""
    public_ids = parse_npc_identities_public(state)
    profiles: dict[str, dict[str, Any]] = {}
    for npc_name in ((state or {}).get("npcs") or {}).keys():
        clean = str(npc_name).strip()
        if clean:
            profiles[clean] = dict(public_ids.get(clean) or {"handle": clean, "real_name_hidden": False})
    for handle, entry in public_ids.items():
        if handle not in profiles:
            profiles[handle] = dict(entry)
    for sk, sv in (gm_secrets or {}).items():
        if isinstance(sk, str) and sk.startswith("__npc_real:") and isinstance(sv, str) and sv.strip():
            handle = sk[len("__npc_real:"):].strip()
            if not handle:
                continue
            prof = profiles.setdefault(handle, {"handle": handle, "real_name_hidden": True})
            prof["real_name_hidden"] = True
            if include_hidden:
                prof["real_name"] = sv.strip()
    if not include_hidden:
        for prof in profiles.values():
            if prof.get("real_name_hidden"):
                prof.pop("real_name", None)
    return profiles


def _format_session_zero_and_meta_block(raw_state: dict[str, Any] | None) -> str:
    """Format compact per-campaign Session Zero dials and World Setup metadata for prompts."""
    sz = parse_session_zero(raw_state)
    meta = parse_campaign_meta(raw_state)
    parts: list[str] = []
    if meta:
        world_bits: list[str] = []
        if meta.get("district"):
            zone = f" [{meta['zone_type']}]" if meta.get("zone_type") else ""
            threat = f" (Threat: {meta['threat_rating']})" if meta.get("threat_rating") else ""
            world_bits.append(f"District: {meta['district']}{zone}{threat}")
        if meta.get("caper_style"):
            world_bits.append(f"Caper Style: {meta['caper_style']}")
        if isinstance(meta.get("factions"), list) and meta["factions"]:
            world_bits.append(f"Active Factions: {', '.join(str(x) for x in meta['factions'])}")
        if isinstance(meta.get("gig"), dict) and meta["gig"].get("title"):
            g = meta["gig"]
            pay = f" ({g['payout_eb']} eb)" if g.get("payout_eb") else ""
            world_bits.append(f"Starting Gig: {g['title']}{pay}")
        if world_bits:
            parts.append("Campaign World Setup: " + " | ".join(world_bits))
    if sz:
        sz_bits: list[str] = []
        for key, label in (
            ("campaign_scope", "Scope"),
            ("lethality_dial", "Lethality"),
            ("economy_dial", "Economy"),
            ("crew_concept", "Crew Concept"),
        ):
            if sz.get(key):
                sz_bits.append(f"{label}: {sz[key]}")
        if sz_bits:
            parts.append("Session Zero Dials: " + " | ".join(sz_bits))
        if sz.get("lines_and_veils"):
            parts.append(f"Table Safety Boundaries (Lines & Veils — STRICTLY RESPECT): {sz['lines_and_veils']}")
    return ("\n".join(parts) + "\n") if parts else ""


def _visible_state_for_prompt(state: dict[str, Any]) -> dict[str, Any]:
    """Return narrative state with internal __* storage keys stripped from discoveries."""
    cleaned = dict(state or {})
    disc = dict(cleaned.get("discoveries") or {})
    cleaned["discoveries"] = {k: v for k, v in disc.items() if not str(k).startswith("__")}
    return cleaned


def _visible_gm_secrets_for_prompt(gm_secrets: dict[str, Any] | None) -> dict[str, Any]:
    """Strip internal __npc_real:* storage keys from prompt gm_secrets (surfaced via npc_profiles)."""
    return {
        k: v
        for k, v in (gm_secrets or {}).items()
        if not str(k).startswith("__npc_real:")
    }


def _normalize_campaign_changes(
    raw_changes: dict[str, Any],
    current_state: dict[str, Any],
    *,
    characters: list[dict[str, Any]] | None = None,
    existing_secrets: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    mapped = dict(raw_changes)
    if "location" in mapped and "scene" not in mapped:
        mapped["scene"] = mapped.pop("location")
    pc_locations_in = mapped.pop("pc_locations", None)
    all_together_in = mapped.pop("all_together", None)
    npc_identities_in = mapped.pop("npc_identities", None)
    allowed = {"scene", "summary", "npcs", "objectives", "discoveries", "unresolved"}
    ignored = sorted(k for k in mapped if k not in allowed)
    clean: dict[str, Any] = {}
    notes: list[str] = []
    if ignored:
        notes.append(f"Ignored unsupported campaign field(s): {', '.join(ignored)}")
    for text_key in ("scene", "summary"):
        if text_key in mapped and mapped[text_key] is not None:
            clean[text_key] = str(mapped[text_key]).strip()[:4000]
    for section in ("npcs", "objectives", "discoveries", "unresolved"):
        if section not in mapped or mapped[section] is None:
            continue
        merged = dict(current_state.get(section) or {})
        val = mapped[section]
        if isinstance(val, dict):
            for k, v in val.items():
                key = str(k).strip()[:100]
                if not key:
                    continue
                if v is None or (isinstance(v, str) and not v.strip()):
                    merged.pop(key, None)
                elif isinstance(v, dict):
                    text_v = ", ".join(f"{sk}: {sv}" for sk, sv in v.items() if sv is not None)
                    merged[key] = (text_v or json.dumps(v))[:2000]
                else:
                    merged[key] = str(v).strip()[:2000]
        elif isinstance(val, list):
            for entry in val:
                text_entry = str(entry).strip()
                if text_entry:
                    merged[text_entry[:100]] = text_entry[:2000]
        if len(merged) > 40:
            if section == "discoveries":
                internal_items = [(k, v) for k, v in merged.items() if str(k).startswith("__")]
                user_items = [(k, v) for k, v in merged.items() if not str(k).startswith("__")]
                keep_user = max(0, 40 - len(internal_items))
                kept = internal_items + (user_items[-keep_user:] if keep_user > 0 else [])
                merged = dict(kept[-40:])
            else:
                merged = dict(list(merged.items())[-40:])
        clean[section] = merged

    if characters is not None and (isinstance(pc_locations_in, dict) or (isinstance(all_together_in, str) and all_together_in.strip())):
        base_state = {**current_state, **clean}
        clean["discoveries"] = apply_pc_locations_to_discoveries(
            base_state,
            characters,
            pc_locations_in if isinstance(pc_locations_in, dict) else None,
            all_together_location=all_together_in if isinstance(all_together_in, str) else None,
        )

    if isinstance(npc_identities_in, dict):
        base_disc = dict(clean.get("discoveries") or current_state.get("discoveries") or {})
        cur_ids = parse_npc_identities_public({"discoveries": base_disc})
        for raw_handle, raw_meta in npc_identities_in.items():
            handle = str(raw_handle or "").strip()[:80]
            if not handle:
                continue
            if raw_meta is None:
                cur_ids.pop(handle, None)
            elif isinstance(raw_meta, dict):
                hidden = bool(raw_meta.get("real_name_hidden", True))
                rname = str(raw_meta.get("real_name") or "").strip()[:100]
                prev_entry = cur_ids.get(handle) or {}
                if not hidden and not rname:
                    sec_val = (existing_secrets or {}).get(f"__npc_real:{handle}") or ""
                    rname = (str(sec_val).strip() or str(prev_entry.get("real_name") or "").strip())[:100]
                entry: dict[str, Any] = {"handle": handle, "real_name_hidden": hidden}
                if not hidden and rname:
                    entry["real_name"] = rname
                pers = str(raw_meta.get("personality") or prev_entry.get("personality") or "").strip()[:140]
                speech = str(raw_meta.get("speech_style") or prev_entry.get("speech_style") or "").strip()[:140]
                if pers:
                    entry["personality"] = pers
                if speech:
                    entry["speech_style"] = speech
                cur_ids[handle] = entry
        base_disc["__npc_identities"] = _encode_npc_identities_json(cur_ids)
        clean["discoveries"] = base_disc

    return clean, notes
