"""Prompt message builders and roll-ledger formatters for Planner, Narrator, Chronicler, and Intro passes."""
from __future__ import annotations

import json
from typing import Any, Callable

from turn_engine.settings import (
    _DEFAULT_INTRO_PROMPT,
    _DEFAULT_NARRATOR_PERSONA,
    _DEFAULT_PLAYER_MESSAGE_TEMPLATE,
    _GM_STYLE_HINTS,
    _LENGTH_HINTS,
    _PACING_HINTS,
)
from turn_engine.state_normalization import (
    _format_session_zero_and_meta_block,
    _summarize_character,
    _visible_state_for_prompt,
    build_npc_profiles,
    compute_party_grouping,
)


def format_player_message(
    text: str,
    speaker_name: str | None = None,
    *,
    prompt_settings: dict[str, str] | None = None,
) -> str:
    clean_text = text.strip() if isinstance(text, str) else ""
    speaker = speaker_name.strip() if isinstance(speaker_name, str) and speaker_name.strip() else ""
    if not speaker:
        return clean_text
    ps = prompt_settings or {}
    tpl = (ps.get("player_message_template") or "").strip() or _DEFAULT_PLAYER_MESSAGE_TEMPLATE
    if "{message}" not in tpl:
        tpl = f"{tpl} {{message}}".strip()
    return tpl.replace("{speaker}", speaker).replace("{message}", clean_text)


def format_roll_ledger(executed: dict[str, Any], *, tagged_single_pass: bool = False) -> str:
    """Render an unambiguous plain-text roll ledger for the Narrator."""
    if tagged_single_pass:
        return "  (single-pass mode: emit planned checks inside <gm_ops> if needed; do not invent dice totals)"
    outcomes = executed.get("outcomes") or {}
    rolls = outcomes.get("rolls") or []
    lines: list[str] = []
    if not rolls:
        lines.append("  NONE (0 rolls executed this turn — DO NOT print or invent any dice roll, d10 result, total, or 'vs DV' pass/fail line).")
    else:
        for idx, r in enumerate(rolls, start=1):
            verdict = "SUCCESS" if r.get("success") else "FAILURE"
            crit = ""
            if r.get("critical") == "critical_success":
                crit = " [CRITICAL SUCCESS]"
            elif r.get("critical") == "fumble":
                crit = " [CRITICAL FUMBLE]"
            if not r.get("success") and isinstance(r.get("dv"), int) and isinstance(r.get("total"), int):
                gap = r["dv"] - r["total"]
                if gap <= 2:
                    crit += f" [NARROW MISS by {gap}]"
                else:
                    crit += f" [CLEAR FAILURE by {gap} — action DENIED/BLOCKED]"
            skill_part = f"{r.get('skill')} ({r.get('stat')})" if r.get("skill") else str(r.get("stat") or "Check")
            mods = []
            if r.get("modifier"):
                mods.append(f"mod {r['modifier']:+d}")
            if r.get("luck_spent"):
                mods.append(f"LUCK +{r['luck_spent']}")
            if r.get("wound_modifier"):
                mods.append(f"wound {r['wound_modifier']:+d}")
            mod_txt = f" ({', '.join(mods)})" if mods else ""
            lines.append(
                f"  Roll #{idx}: {r.get('actor')} — {skill_part}: base {r.get('base')} + dice {r.get('dice')}{mod_txt} = TOTAL {r.get('total')} vs DV {r.get('dv')} => {verdict}{crit}"
                + (f" | {r['reason']}" if r.get("reason") else "")
            )
    for blk in outcomes.get("blocked_checks") or []:
        lines.append(f"  BLOCKED CHECK (did NOT roll): {blk}")
    unspent = outcomes.get("unspent_luck_requested") or 0
    if unspent:
        lines.append(f"  PRE-COMMITTED LUCK NOT SPENT: player offered {unspent} LUCK, but no check rolled; inform player LUCK remains unspent.")
    return "\n".join(lines)


def build_planner_messages(
    prep: dict[str, Any],
    user_text: str,
    *,
    overclock: bool,
    luck_spend: int = 0,
    speaker: dict[str, str] | None = None,
    guidance: str | None = None,
    turn_settings: dict[str, Any] | None = None,
    prompt_settings: dict[str, str] | None = None,
    effective_turn_settings: dict[str, Any] | None = None,
    solo_summary: dict[str, Any] | None = None,
    player_message_formatter: Callable[[str, str | None], str] | None = None,
) -> list[dict[str, str]]:
    ctx = prep["context"]
    state = _visible_state_for_prompt(ctx["campaign"]["state"])
    chars_summary = [_summarize_character(c) for c in ctx["characters"]]
    chan = str(prep.get("channel_id") or "main")
    grouping = prep.get("party_grouping") or compute_party_grouping(ctx["characters"], ctx["campaign"]["state"], active_channel_id=chan)
    npc_profiles = prep.get("npc_profiles") or build_npc_profiles(ctx["campaign"]["state"], prep.get("gm_secrets") or {}, include_hidden=True)
    cards = [
        {
            "id": e["id"],
            "name": e["name"],
            "category": e["category"],
            "summary": e["summary"],
            "stats": e["stats"],
            "page": e.get("printed_page"),
        }
        for e in prep["citations"]
    ]
    gm_secrets = prep.get("gm_secrets") or {}
    clocks = prep.get("clocks") or []
    solo_summary = solo_summary if solo_summary is not None else {}
    speaker_name = speaker["name"] if speaker and speaker.get("name") else ""
    party_names = [str(c.get("name") or "").strip() for c in ctx["characters"] if str(c.get("name") or "").strip()]
    party_line = f"Party characters in campaign: {', '.join(party_names)}.\n" if len(party_names) > 1 else ""
    speaker_line = (
        f"Active player speaker for this turn: {speaker_name} (character_id={speaker['id']}).\n"
        if speaker and speaker_name
        else ""
    )
    guidance_line = (
        f"Director note for this regeneration: {guidance.strip()}\n"
        if isinstance(guidance, str) and guidance.strip()
        else ""
    )
    t_settings = turn_settings or {}
    p_settings = prompt_settings or {}
    eff_settings = effective_turn_settings if effective_turn_settings is not None else t_settings
    fmt_player = player_message_formatter or (lambda txt, spk=None: format_player_message(txt, spk, prompt_settings=p_settings))

    style_key = str(eff_settings.get("gm_style") or "grounded")
    style_hint = _GM_STYLE_HINTS.get(style_key, _GM_STYLE_HINTS["grounded"])
    sz_meta_block = _format_session_zero_and_meta_block(ctx["campaign"]["state"])
    default_step = int(eff_settings.get("default_time_step_minutes") or 0)
    world_prefix = (p_settings.get("world_rules_prefix") or "").strip()
    dialogue_rules = (p_settings.get("player_dialogue_rules") or "").strip()
    multiplayer_rules = (p_settings.get("multiplayer_rules") or "").strip()
    planner_extra = (p_settings.get("planner_extra") or "").strip()
    planner_core = (p_settings.get("planner_core_rules") or "").strip()
    allow_homebrew = bool(eff_settings.get("allow_ai_homebrew", True))
    custom_lines = sz_meta_block
    if world_prefix:
        custom_lines += f"Campaign World / Table Rules:\n{world_prefix}\n"
    if dialogue_rules:
        custom_lines += f"Player Dialogue & Action Parsing:\n{dialogue_rules}\n"
    if multiplayer_rules:
        custom_lines += f"Multi-Player / Co-op Turn Rules:\n{multiplayer_rules}\n"
    if planner_extra:
        custom_lines += f"Custom Planner Instructions:\n{planner_extra}\n"
    step_note = f"- Default fallback if time passed without another value: {default_step}m.\n" if default_step > 0 else ""
    homebrew_note = "" if allow_homebrew else "- Leave `new_homebrew` empty (`[]`); auto-saving AI homebrew is disabled.\n"
    core_block = f"Planning rules:\n{planner_core}\n" if planner_core else ""
    system_prompt = (
        "You are the Cyberpunk RED Rules Planner. Return ONLY a single valid JSON object with no markdown or prose.\n"
        f"Campaign Style: {style_hint}\n"
        f"{custom_lines}"
        "Schema:\n"
        "{\n"
        '  "checks": [{"actor": "name", "skill": "Handgun|Interface|Perception|...", "stat": "REF|INT|ROLE|...", "dv": 13, "modifier": 0, "luck": 0, "overclock": false, "reason": "..."}],\n'
        '  "start_time": "22:15",\n'
        '  "time_elapsed_minutes": 0,\n'
        '  "state_ops": [{"type": "update_campaign", "changes": {"scene": "5th & Main, Night Market loading dock", "summary": "...", "npcs": {"NPC Handle": "Role, location — Disposition (Neutral 0); tie-in"}, "npc_identities": {"NPC Handle": {"real_name": "Optional legal name", "real_name_hidden": true, "personality": "temperament/traits", "speech_style": "cadence/verbal quirks"}}, "pc_locations": {"PC Handle": "Location if split"}, "all_together": "Shared location if reunited", "objectives": {"Clear your name": "Active"}, "discoveries": {"Topic": "Observed clue"}}, "reason": "..."}],\n'
        '  "solo_ops": [{"action": "economy_action|health_action|gear_action|role_action|start_encounter|encounter_action|end_encounter", "subaction": "job_reward|pay_month|hustle|rest|stabilize|quick_fix|treat_injury|buy|sell|equip_weapon|equip_armor|award_ip|solo_allocate|attack|move|reload|next_turn", "actor": "name", "arguments": {...}, "reason": "..."}],\n'
        '  "clock_ops": [{"id": "militech-heat", "name": "Militech Sweep Heat", "delta": 1, "segments": 4, "category": "heat|obligation|deadline|faction|recovery", "visibility": "public|secret", "note": "..."}],\n'
        '  "gm_secrets": {"npc_or_topic": "private GM truth, motive, trap, or null once learned by PC"},\n'
        '  "new_homebrew": [{"name": "...", "category": "skill|weapon|armor|cyberware|gear|role|rule|npc|faction|location|ammo|attachment|vehicle|drug|service|housing|mook|encounter|streetslang|screamsheet", "summary": "...", "description": "...", "stats": {...}}],\n'
        '  "gm_notes": "short resolution guidance"\n'
        "}\n"
        f"{core_block}"
        f"{step_note}"
        f"{homebrew_note}"
        f"{party_line}"
        f"Party Grouping & Locations: {grouping.get('prompt_summary')}\n"
        f"{speaker_line}"
        f"{guidance_line}"
        f"Overclock requested by player: {overclock}.\n"
        f"Pre-committed LUCK by player: {max(0, int(luck_spend))}.\n"
        f"Pre-rolled server dice pool available if needed: {json.dumps(prep['dice_pool'])}.\n"
        f"Narrative Memory: {json.dumps(state)}\n"
        f"NPC Identities (Respect real_name_hidden): {json.dumps(npc_profiles)}\n"
        f"Solo Engine State: {json.dumps(solo_summary)}\n"
        f"Active Clocks (secret clocks are GM-only): {json.dumps(clocks)}\n"
        f"Hidden GM Secrets (NEVER expose in state_ops unless earned): {json.dumps(gm_secrets)}\n"
        f"Characters: {json.dumps(chars_summary)}\n"
        f"Retrieved Library Entries: {json.dumps(cards)}"
    )
    hist_win = max(4, min(200, int(t_settings.get("history_window", 14))))
    msgs = [{"role": "system", "content": system_prompt}]
    main_tail = prep.get("main_tail") or []
    if chan != "main" and main_tail and not prep["branch"]:
        tail_lines = [
            f"{(m.get('metadata') or {}).get('speaker_name') or m['role']}: {m['content'][:320]}"
            for m in main_tail
        ]
        msgs.append({"role": "system", "content": "Prior Main Table context before party split:\n" + "\n".join(tail_lines)})
    for item in prep["branch"][-hist_win:]:
        meta = item.get("metadata") or {}
        if item["role"] == "system" and (meta.get("session_started") or meta.get("party_transition")):
            continue
        item_speaker = meta.get("speaker_name")
        content = fmt_player(item["content"], item_speaker) if item["role"] == "user" else item["content"]
        msgs.append({"role": item["role"], "content": content})
    msgs.append({"role": "user", "content": fmt_player(user_text, speaker_name)})
    return msgs


def build_intro_messages(
    prep: dict[str, Any],
    user_text: str,
    *,
    speaker: dict[str, str] | None = None,
    guidance: str | None = None,
    campaign_context: dict[str, Any] | None = None,
    prompt_settings: dict[str, str] | None = None,
    player_message_formatter: Callable[[str, str | None], str] | None = None,
) -> list[dict[str, str]]:
    ctx = campaign_context or prep["context"]
    camp = ctx["campaign"]
    state = _visible_state_for_prompt(camp["state"])
    chars = [_summarize_character(c) for c in ctx["characters"]]
    p_settings = prompt_settings or {}
    fmt_player = player_message_formatter or (lambda txt, spk=None: format_player_message(txt, spk, prompt_settings=p_settings))
    intro_prompt = (p_settings.get("intro_prompt") or "").strip() or _DEFAULT_INTRO_PROMPT
    world_prefix = (p_settings.get("world_rules_prefix") or "").strip()
    extra_world = f"\nTable World Rules:\n{world_prefix}\n" if world_prefix else ""
    sz_meta_block = _format_session_zero_and_meta_block(camp["state"])
    guidance_line = (
        f"\nDirector Regeneration Note: {guidance.strip()}\n"
        if isinstance(guidance, str) and guidance.strip()
        else ""
    )
    system_prompt = (
        f"{intro_prompt}\n"
        f"{extra_world}"
        f"{sz_meta_block}"
        f"{guidance_line}"
        f"Active Campaign: {camp.get('name', 'Night City Run')} (Session {camp.get('session_number', 1)})\n"
        f"Campaign Scene: {state.get('scene') or '(not yet set)'}\n"
        f"Campaign Summary: {state.get('summary') or '(not yet set)'}\n"
        f"Known NPCs: {json.dumps(state.get('npcs') or {})}\n"
        f"Party Characters Attached: {json.dumps(chars)}"
    )
    speaker_name = speaker["name"] if speaker and speaker.get("name") else ""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": fmt_player(user_text, speaker_name)},
    ]


def build_narrator_messages(
    prep: dict[str, Any],
    user_text: str,
    executed: dict[str, Any],
    *,
    tagged_single_pass: bool = False,
    speaker: dict[str, str] | None = None,
    guidance: str | None = None,
    campaign_context: dict[str, Any] | None = None,
    turn_settings: dict[str, Any] | None = None,
    prompt_settings: dict[str, str] | None = None,
    effective_turn_settings: dict[str, Any] | None = None,
    solo_summary: dict[str, Any] | None = None,
    saved_npcs: list[dict[str, Any]] | None = None,
    player_message_formatter: Callable[[str, str | None], str] | None = None,
    roll_ledger_formatter: Callable[..., str] | None = None,
) -> list[dict[str, str]]:
    ctx = campaign_context or prep["context"]
    state = _visible_state_for_prompt(ctx["campaign"]["state"])
    chan = str(prep.get("channel_id") or "main")
    grouping = compute_party_grouping(ctx["characters"], ctx["campaign"]["state"], active_channel_id=chan)
    gm_secrets = executed.get("gm_secrets", prep.get("gm_secrets") or {})
    npc_profiles = build_npc_profiles(ctx["campaign"]["state"], gm_secrets, include_hidden=True)
    cards = [
        {
            "name": e["name"],
            "category": e["category"],
            "summary": e["summary"],
            **(
                {"description": str(e["description"])[:360]}
                if e.get("source") == "homebrew"
                and e.get("description")
                and e["description"] != e["summary"]
                else {}
            ),
            "stats": e["stats"],
        }
        for e in prep["citations"]
    ]
    narrator_chars = [_summarize_character(c) for c in ctx["characters"]]
    clocks = executed.get("clocks", prep.get("clocks") or [])
    solo_summary = solo_summary if solo_summary is not None else {}
    speaker_name = speaker["name"] if speaker and speaker.get("name") else ""
    party_names = [str(c.get("name") or "").strip() for c in narrator_chars if str(c.get("name") or "").strip()]
    party_line = (
        f"\n- Party Roster: {', '.join(party_names)}"
        if len(party_names) > 1
        else ""
    )
    speaker_line = (
        f"\n- Active Player / Speaker: {speaker_name}"
        if speaker and speaker_name
        else ""
    )
    guidance_line = (
        f"\n- Director Regeneration Note: {guidance.strip()}"
        if isinstance(guidance, str) and guidance.strip()
        else ""
    )
    t_settings = turn_settings or {}
    p_settings = prompt_settings or {}
    eff_settings = effective_turn_settings if effective_turn_settings is not None else t_settings
    fmt_player = player_message_formatter or (lambda txt, spk=None: format_player_message(txt, spk, prompt_settings=p_settings))
    fmt_ledger = roll_ledger_formatter or format_roll_ledger

    persona = (p_settings.get("system_persona") or "").strip() or _DEFAULT_NARRATOR_PERSONA
    style_key = str(eff_settings.get("gm_style") or "grounded")
    length_key = str(eff_settings.get("narrator_length") or "standard")
    pacing_key = str(eff_settings.get("narrator_pacing") or "balanced")
    style_hint = _GM_STYLE_HINTS.get(style_key, _GM_STYLE_HINTS["grounded"])
    length_hint = _LENGTH_HINTS.get(length_key, _LENGTH_HINTS["standard"])
    pacing_hint = _PACING_HINTS.get(pacing_key, _PACING_HINTS["balanced"])
    saved_npcs = saved_npcs or []
    saved_npcs_line = f"\n- Saved Campaign NPCs (recallable): {json.dumps(saved_npcs)}" if saved_npcs else ""
    world_prefix = (p_settings.get("world_rules_prefix") or "").strip()
    dialogue_rules = (p_settings.get("player_dialogue_rules") or "").strip()
    player_narration_rules = (p_settings.get("player_narration_rules") or "").strip()
    multiplayer_rules = (p_settings.get("multiplayer_rules") or "").strip()
    narrator_extra = (p_settings.get("narrator_extra") or "").strip()
    narrator_core = (p_settings.get("narrator_core_rules") or "").strip()
    enable_highlights = bool(eff_settings.get("enable_highlights", True))
    sz_meta_block = _format_session_zero_and_meta_block(ctx["campaign"]["state"])
    custom_sections = f"\n{sz_meta_block}" if sz_meta_block else ""
    if world_prefix:
        custom_sections += f"\nTable World Rules:\n{world_prefix}\n"
    if dialogue_rules:
        custom_sections += f"\nHow Player Dialogue & Actions Are Sent:\n{dialogue_rules}\n"
    if player_narration_rules:
        custom_sections += f"\nPlayer Narration & Agency:\n{player_narration_rules}\n"
    if multiplayer_rules:
        custom_sections += f"\nMulti-Player / Co-op Handling:\n{multiplayer_rules}\n"
    if narrator_extra:
        custom_sections += f"\nCustom Narrator Instructions:\n{narrator_extra}\n"
    core_block = f"\n{narrator_core}\n" if narrator_core else "\n"
    flair_line = (
        "- Visual UI flair: highlight 2–5 short key terms per reply using inline color tags, e.g. [[cyan:Kiroshi Tower]], [[rose:Trauma Team]], [[amber:500eb]], [[emerald:Conversation]], or [[violet:NetWatch]]. Keep highlighted spans short (1–4 words) and never wrap whole sentences.\n"
        if enable_highlights
        else "- Clean plain Markdown only: do NOT use [[color:...]] inline highlight tags.\n"
    )
    system_prompt = (
        f"{persona}\n"
        f"Style: {style_hint}\n"
        f"Length: {length_hint}\n"
        f"Pacing: {pacing_hint}"
        f"{custom_sections}"
        f"{core_block}"
        f"{flair_line}"
        f"- Narrative State: {json.dumps(state)}\n"
        f"- NPC Identities (Respect real_name_hidden, personality & speech_style): {json.dumps(npc_profiles)}"
        f"{saved_npcs_line}\n"
        f"- Party Grouping & Locations: {grouping.get('prompt_summary')}\n"
        f"- Solo Engine State: {json.dumps(solo_summary)}\n"
        f"- Active Clocks (secret clocks are GM eyes only): {json.dumps(clocks)}\n"
        f"- Hidden GM Secrets (GM eyes only—NEVER leak unobservably or give away for free): {json.dumps(gm_secrets)}\n"
        f"- Characters: {json.dumps(narrator_chars)}"
        f"{party_line}"
        f"{speaker_line}"
        f"{guidance_line}\n"
        f"- Rulebook Library Context: {json.dumps(cards)}\n"
        f"- Authoritative Dice Roll Ledger:\n{fmt_ledger(executed, tagged_single_pass=tagged_single_pass)}\n"
        f"- Locked Engine Outcomes: {json.dumps(executed['outcomes'])}"
    )
    if tagged_single_pass:
        system_prompt += (
            "\nAt the very end of your reply, if rules checks, state updates, or homebrew additions are needed, "
            "append <gm_ops>{...JSON plan...}</gm_ops>."
        )
    hist_win = max(4, min(500, int(t_settings.get("history_window", 14))))
    msgs = [{"role": "system", "content": system_prompt}]
    main_tail = prep.get("main_tail") or []
    if chan != "main" and main_tail and not prep["branch"]:
        tail_lines = [
            f"{(m.get('metadata') or {}).get('speaker_name') or m['role']}: {m['content'][:320]}"
            for m in main_tail
        ]
        msgs.append({"role": "system", "content": "Prior Main Table context before party split:\n" + "\n".join(tail_lines)})
    for item in prep["branch"][-hist_win:]:
        meta = item.get("metadata") or {}
        if item["role"] == "system" and (meta.get("session_started") or meta.get("party_transition")):
            continue
        item_speaker = meta.get("speaker_name")
        content = fmt_player(item["content"], item_speaker) if item["role"] == "user" else item["content"]
        msgs.append({"role": item["role"], "content": content})
    msgs.append({"role": "user", "content": fmt_player(user_text, speaker_name)})
    return msgs


def build_chronicler_messages(
    prep: dict[str, Any],
    user_text: str,
    narrated_text: str,
    executed: dict[str, Any],
    *,
    speaker: dict[str, str] | None = None,
    turn_settings: dict[str, Any] | None = None,
    prompt_settings: dict[str, str] | None = None,
    solo_summary: dict[str, Any] | None = None,
    saved_npcs: list[dict[str, Any]] | None = None,
    player_message_formatter: Callable[[str, str | None], str] | None = None,
) -> list[dict[str, str]]:
    ctx = prep["context"]
    state = _visible_state_for_prompt(ctx["campaign"]["state"])
    chan = str(prep.get("channel_id") or "main")
    grouping = compute_party_grouping(ctx["characters"], ctx["campaign"]["state"], active_channel_id=chan)
    solo_summary = solo_summary if solo_summary is not None else {}
    gm_secrets = executed.get("gm_secrets", prep.get("gm_secrets") or {})
    npc_profiles = build_npc_profiles(ctx["campaign"]["state"], gm_secrets, include_hidden=True)
    clocks = executed.get("clocks", prep.get("clocks") or [])
    t_settings = turn_settings or {}
    p_settings = prompt_settings or {}
    fmt_player = player_message_formatter or (lambda txt, spk=None: format_player_message(txt, spk, prompt_settings=p_settings))

    chron_extra = (p_settings.get("chronicler_extra") or "").strip()
    chron_core = (p_settings.get("chronicler_core_rules") or "").strip()
    extra_block = f"\nCustom Chronicler Instructions:\n{chron_extra}\n" if chron_extra else "\n"
    core_block = f"Rules:\n{chron_core}\n" if chron_core else ""
    homebrew_note = "" if t_settings.get("allow_ai_homebrew", True) else "- Leave `new_homebrew` empty (`[]`).\n"
    speaker_name = speaker["name"] if speaker and speaker.get("name") else None
    formatted_user = fmt_player(user_text, speaker_name)
    saved_npcs = saved_npcs or []
    saved_npcs_line = f"Saved Campaign NPCs: {json.dumps(saved_npcs)}\n" if saved_npcs else ""
    system_prompt = (
        "You are the Cyberpunk RED Post-Turn Chronicler. Compare the player turn and the actual narrated GM prose against the current state, "
        "and record ONLY facts, NPCs, clues, scene transitions, or time elapsed that appeared in the narrated prose and are NOT yet captured.\n"
        f"{extra_block}"
        "Return ONLY a single valid JSON object with no markdown:\n"
        "{\n"
        '  "time_elapsed_minutes": 0,\n'
        '  "state_ops": [{"type": "update_campaign", "changes": {"scene": "...", "npcs": {"Handle": "Role, location — Disposition (Neutral 0); tie-in"}, "npc_identities": {"Handle": {"real_name": "Optional legal name", "real_name_hidden": true, "personality": "temperament/traits", "speech_style": "cadence/verbal quirks"}}, "pc_locations": {"PC Handle": "Location if split"}, "all_together": "Shared location if reunited", "discoveries": {"Topic": "PC-observed clue"}, "objectives": {"Obj": "Active|Completed"}, "unresolved": {"Thread": "..."}}, "reason": "..."}],\n'
        '  "clock_ops": [{"id": "...", "name": "...", "delta": 0, "segments": 4, "category": "heat|obligation|deadline|faction|recovery", "visibility": "public|secret", "note": "..."}],\n'
        '  "gm_secrets": {"secret_key": "unrevealed off-screen motive/consequence or null if revealed in prose"},\n'
        '  "new_homebrew": [{"name": "...", "category": "npc|location|faction|gear|program|rule|ammo|attachment|vehicle|drug|service|housing|mook|encounter|streetslang|screamsheet", "summary": "1-sentence player-known summary", "description": "concise factual entry", "stats": {"role": "...", "disposition": "Neutral (0)", "personality": "...", "speech_style": "..."}}]\n'
        "}\n"
        f"{core_block}"
        f"{homebrew_note}"
        f"Party Grouping & Locations: {grouping.get('prompt_summary')}\n"
        f"NPC Identities: {json.dumps(npc_profiles)}\n"
        f"{saved_npcs_line}"
        f"Current Narrative State: {json.dumps(state)}\n"
        f"Solo Engine State: {json.dumps(solo_summary)}\n"
        f"Active Clocks: {json.dumps(clocks)}\n"
        f"Private GM Secrets: {json.dumps(gm_secrets)}\n"
        f"Already Applied This Turn: {json.dumps(executed.get('patches') or [])}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Player Action: {formatted_user}\n\nGM Narration:\n{narrated_text}"},
    ]


def build_think_planner_messages(
    prep: dict[str, Any],
    user_text: str,
    **kwargs: Any,
) -> list[dict[str, str]]:
    """Hook for inner-thought (/think) observation Planner prompts."""
    return build_planner_messages(prep, user_text, **kwargs)


def build_think_narrator_messages(
    prep: dict[str, Any],
    user_text: str,
    executed: dict[str, Any],
    **kwargs: Any,
) -> list[dict[str, str]]:
    """Hook for inner-thought (/think) observation Narrator prompts."""
    return build_narrator_messages(prep, user_text, executed, **kwargs)
