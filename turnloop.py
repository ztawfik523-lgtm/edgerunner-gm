"""Improved AI Turn Loop, OpenAI-compatible LLM adapter, and branching chat tree."""
from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import inspect
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from typing import Any, AsyncIterator
from urllib.parse import urlsplit
import uuid

import httpx

from campaign import STAT_NAMES, _json
from combat import wound_state
from gameplay import GameplayService
from library import ALLOWED_CATEGORIES, CampaignLibrary, normalize_category, search_library
import sourcecatalog

_GM_TAG_RE = re.compile(r"\[\[GM_STATE\s*:\s*(\{.*?\})\s*\]\]", re.S)
_GM_XML_RE = re.compile(r"<gm_ops>\s*(\{.*?\})\s*</gm_ops>", re.S | re.I)
_TRAILING_PARTIAL_TAG_RE = re.compile(r"(?:\[\[GM_STATE\b.*|<gm_ops\b.*)$", re.S | re.I)
_LIB_REF_RE = re.compile(r"\[([a-zA-Z]+)\s*:\s*([^\]\n]+)\]")
_CLOCK_CATEGORIES = frozenset({"heat", "obligation", "deadline", "faction", "recovery"})
_GM_THINKING_MODES = frozenset({"quality", "balanced"})
_COMPRESSION_MESSAGE_THRESHOLD = 14


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
}


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
DEFAULT_SETTINGS_PATH = Path(
    os.environ.get("REDGM_SETTINGS_FILE", Path.home() / ".local/share/cyberpunk-red-gm/settings.json")
)
_SETTINGS_LOCK = threading.RLock()


def default_settings_path() -> Path:
    env_override = os.environ.get("REDGM_SETTINGS_FILE", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return DEFAULT_SETTINGS_PATH.expanduser()

_DEFAULT_NARRATOR_PERSONA = (
    "You are the Cyberpunk RED Game Master. Write grounded, street-level Night City fiction "
    "driven by human friction, distinct character voices, and real consequences."
)

_DEFAULT_CREATION_ASSIST_PERSONA = (
    "You are a Cyberpunk RED (Year 2045, Time of the Red) Narrative Co-Writer.\n"
    "STRICT RULES:\n"
    "1. Adhere faithfully to the player's actual character sheet (Role Rank 4, STAT scores, trained Skills, installed Cyberware, Weapons/Armor, and Lifepath) or campaign setup.\n"
    "2. Never contradict the sheet (e.g., don't claim a low-TECH character is an elite surgeon, or give a character cyberware/stats they do not have).\n"
    "3. Stay grounded in official Cyberpunk RED Night City 2045 lore (Time of the Red scarcity, Night Markets, Fixers, Continental Brands, local gangs, Watson/Heywood/Westbrook/Santo Domingo/Pacifica/Combat Zone/Badlands)."
)

_DEFAULT_PLANNER_CORE_RULES = (
    "- Ground everything in each Character's actual stats, skills, money, inventory, detail, and wound_state. If inventory is {} and detail is {}, they carry NO confirmed gear or cyberware—do not invent unowned cyberarms or weapons.\n"
    "- Respect player agency: only schedule checks or character changes for actions the player actually declared or external hazards/attacks inflicted on them—never assume decisions or habits the player didn't choose.\n"
    "- Checks & Role Abilities: use canonical Cyberpunk RED skills or Role Abilities (`Interface`, `Charismatic Impact`, `Credibility`, `Operator`, `Moto`, `Maker`, `Medicine`, `Surgery`, `Medical Tech`). For pure role checks like `Interface`, set `stat` to `\"ROLE\"` (or omit `stat` so the engine resolves `ROLE`).\n"
    "- Playstyle IP Awards: award 10–80 IP per scene/session based on Group Playstyle + Roleplay (never award hundreds at once; use solo_ops role_action award_ip with actor, amount, and reason).\n"
    "- Beat Chart & Combat Cliffhanger Pacing: alternate Action, Investigation, and Character-Interaction beats; scale Cliffhangers per Corebook pp. 412–416 (1 Mook per PC, 1 Lieutenant per 2 PCs, 1 Boss per 4 PCs); EMP drops per tens digit of Humanity lost.\n"
    "- Pre-roll player stakes: if `Overclock` or `Pre-committed LUCK` is > 0, apply it only if a check is genuinely warranted by the player's action (never invent a pointless roll just to burn LUCK/Humanity).\n"
    "- Information Fog-of-War & Earned Intel:\n"
    "  * Keep player-visible Narrative Memory (`state.npcs`, `state.discoveries`, `state.summary`) spoiler-free—record only what the player character has directly seen, heard, or confirmed in play.\n"
    "  * Store hidden NPC motives, true employers, framed evidence, unspotted traps, or behind-the-scenes truths in `gm_secrets` instead (set a key to null once genuinely uncovered and move the revealed fact into `discoveries`).\n"
    "  * Treat sensitive information as earned, never free: if the player asks an NPC for hidden reasons, motives, names, or secrets, schedule a fitting check (`Conversation`, `Human Perception`, `Interrogation`, `Streetwise`, `Bribery`, `Library Search`, `Electronics/Security Tech`) or require leverage/payment/legwork.\n"
    "- Clocks & Pressure (`clock_ops`): when an active gig timer, site alert, faction pursuit, or looming deadline enters play (or when the player requests a tracked threat clock), create 1-2 tracked clocks (`segments` 4-8; use `visibility: \"public\"` for player-visible or requested threat timers, patrol sweeps, alerts, and deadlines, and `visibility: \"secret\"` ONLY for hidden off-screen GM plots) and tick `+1`/`-1` only when real pressure shifts—never tick blindly every turn.\n"
    "- Time Management (`start_time` & `time_elapsed_minutes`): check `Solo Engine State.clock_minutes` and `clock_label`. If `clock_minutes == 0` at campaign start and the opening sets a specific time of day (e.g. `22:15`), emit `\"start_time\": \"HH:MM\"` once. Emit `time_elapsed_minutes` (`0` for combat/rapid dialogue, `5`-`15` for quick searches/bandaging, `30`-`90` for district transit/stakeouts, `480` for overnight sleep) whenever narrative time meaningfully passes (skip if a `solo_ops` `rest`/`treat_injury`/`therapy`/`hustle` already advances time).\n"
    "- Solo Engine (`solo_ops`) & `state_ops` (`update_character`): use `solo_ops` for gig payouts (`economy_action` `job_reward` with `amount` and `contract_reason`), monthly rent/lifestyle (`pay_month`), canonical buying/equipping (`gear_action` `buy`/`equip_weapon`/`equip_armor`), recovery (`health_action` `rest`/`stabilize`/`treat_injury`), and tactical `start_encounter` for attached PCs only (omit unattached NPC enemies from `character_ids` and resolve their attacks via normal `checks`); put starting cash/ad-hoc gear or direct HP/money/inventory changes in `state_ops` as `{\"type\": \"update_character\", \"actor\": \"name\", \"changes\": {\"money\": 120, \"inventory\": {...}}, \"reason\": \"...\"}`.\n"
    "- ALWAYS keep Narrative Memory synced: if state.scene or state.summary is empty, or if the location, newly introduced/changed NPCs (including any named NPCs mentioned in recent messages not yet in state.npcs—format each as `Role, location — Disposition (Hostile -2 / Wary -1 / Neutral 0 / Warm +1 / Trusted +2); latest tie-in` using realistic, culturally varied everyday names, never cliché names like Jax, Vex, Kael, Vane, Vance, Razor, or Keres), objectives, discoveries, or unresolved hooks change in the current scene, emit an update_campaign state_op using ONLY top-level keys from {scene, summary, npcs, objectives, discoveries, unresolved} (nest any extracted lore/map notes inside `discoveries`, never as custom top-level keys).\n"
    "- Keep existing state.npcs natural: only plan around off-screen NPCs when location, faction, or the player's choices naturally involve them—never force stored NPCs into every scene.\n"
    "- For update_character state_ops, only use changes keys: hp (int), money (int), humanity (int), inventory ({item_name: quantity_int})."
)

_DEFAULT_PLAYER_MESSAGE_TEMPLATE = "[{speaker}]: {message}"

_DEFAULT_PLAYER_DIALOGUE_RULES = (
    "- Treat text in \"quotes\" as spoken in-character dialogue that nearby NPCs hear and react to directly.\n"
    "- Treat unquoted narration or *asterisk actions* as the character's declared physical actions, intent, or positioning.\n"
    "- Treat ((double parentheses)) or [OOC: ...] as out-of-character table notes for the GM; follow the intent without having NPCs hear it in-world.\n"
    "- Honor [Rolled ...] tags as player-supplied dice context when relevant, while trusting the Authoritative Dice Roll Ledger for official checks."
)

_DEFAULT_PLAYER_NARRATION_RULES = (
    "- NEVER control, decide, or narrate the player character's own actions, dialogue, habits (drinking, smoking, leaning), inner thoughts, emotions, or unstated backstory. You run the world, NPCs, external events, and hazards/injuries inflicted ON the character (backed by the rolls/outcomes below)—never puppet what the player decides to do.\n"
    "- Address the active player character naturally (second person \"you\" in solo/focused moments, or by character name when multiple PCs share a scene) and stop before deciding their reaction.\n"
    "- When the player gives an open prompt, bring an outside situation or NPC to them where they stand and leave their choice and reaction completely open.\n"
    "- Reflect physical consequences: if the active character's `wound_state` is `serious` or `mortal` (or they carry an injury/armor penalty), reflect the pain, sluggishness, and wound penalty in play without overriding their choices."
)

_DEFAULT_MULTIPLAYER_RULES = (
    "- Each turn arrives tagged with its active speaker (`[Character]: ...` and `Active Player / Speaker`). Resolve checks, LUCK, Overclock, and direct NPC replies primarily for that speaker unless they explicitly act together with a teammate.\n"
    "- Protect teammate agency: NEVER invent dialogue, movement, or decisions for other player characters in the party while resolving one player's turn—leave idle or off-spotlight PCs free to jump in on their own turn.\n"
    "- Keep party members distinct: honor each PC's separate HP, ammo, cyberware, location, and NPC disposition from `Characters`, and do not merge their inventory or private knowledge unless they are together and share it."
)

_DEFAULT_NARRATOR_CORE_RULES = (
    "Information Fog-of-War & Earned Intel:\n"
    "- Strictly separate Player Knowledge (`Narrative State` + established scene facts) from Private GM Truth (`Hidden GM Secrets` and `secret` clocks). NEVER narrate NPC inner motives, secret employers, unspotted traps, hidden clock ticks, or conspiracies the player character has no observable way to know.\n"
    "- Gate sensitive answers behind rolls, leverage, money, or legwork: if the player asks why they're targeted, who is behind something, or what an NPC knows—and a check FAILED or no check/leverage unlocked it—have the NPC deflect, lie plausibly, push back, or name a price instead of monologuing the answer. Even on a success, give only the grounded fragment that person or clue can realistically reveal.\n"
    "Character voice, naming & grounded realism:\n"
    "- Keep the tone gritty, everyday, and street-level—transactional, awkward, tense, and worn down—NOT witty action-movie banter, snappy one-liners, or fantastical heroics. People care about rent, cheap food, NCPD heat, and getting home alive.\n"
    "- Write NPCs as ordinary, flawed people first (tired, defensive, irritated, blunt, hesitant, or quietly worried), each with a distinct rhythm and speech pattern rather than stoic thriller stereotypes.\n"
    "- Ground emotion in mundane human behavior and subtext (rubbing a sore wrist, counting change, looking past your shoulder) rather than clinical scanner clichés ('pupil dilation', 'micro-servos whining', 'heart rate spike').\n"
    "- Give NPCs realistic, culturally varied everyday names, surnames, or understated street handles (diverse working-class names rather than cartoon nicknames). NEVER use repetitive stock AI names like Jax, Vex, Kael, Nyx, Vane, Vance, Razor, Keres, Rook, Sable, or Varela.\n"
    "- Persistent NPC cast & disposition: Keep any NPCs listed in Narrative State -> npcs consistent in role, voice, disposition/trust, and past slights or favors (and honor names already set in Locked Engine Outcomes), but do NOT force off-screen contacts into unrelated scenes just because they are in the list.\n"
    "- If any clock in Active Clocks reaches full (`filled == segments`), deliver its world consequence naturally in the scene.\n"
    "- Write full, natural sentences with varied rhythm. Avoid clipped subjectless fragments ('Not a question.', 'Doesn't glance up.', 'Slow. Deliberate.'), heavy em-dash interruptions in every paragraph, and AI tics like 'doesn't flinch', 'voice flat', or 'a pause'.\n"
    "- Respect Cyberpunk RED's gritty street economy: typical edgerunner gigs pay 500–2,000eb (rare high-risk jobs reach ~5,000eb), never tens or hundreds of thousands of eurobucks.\n"
    "Strict grounding & formatting rules:\n"
    "- Never alter or contradict any dice roll total, stat, dice value, pass/fail, critical fumble/success, HP/Humanity/eb change, or rulebook citation listed in the Engine Roll Ledger below. Never offer to spend LUCK retroactively on an already-rolled check—in Cyberpunk RED, LUCK must be committed before rolling.\n"
    "- NEVER fabricate unapplied numeric HP, Humanity, or eb damage/changes in prose unless an executed patch or Engine Roll Ledger outcome applied them (describe shock/strain qualitatively if HP wasn't reduced), and do NOT print raw stat-formula blocks like '**Roll: ... Dice: [...]**' inside story prose (the UI shows dice cards separately).\n"
    "- Honor roll pass/fail mechanically: on a FAILURE, the attempted action FAILS—it is denied, jammed, spotted, or misses its mark (at most a partial hint at a steep cost on a narrow miss by 1–2; NEVER grant full lock bypasses, full NET data extraction, or target objective completion when a check failed).\n"
    "- If the Engine Roll Ledger says `NONE (0 rolls executed)`, NO skill check or attack roll ran this turn—NEVER invent, simulate, or print any dice numbers, d10 result, total, or 'vs DV' pass/fail line in your prose.\n"
    "- Treat the Characters JSON below as canonical truth for stats, skills, money, inventory, and detail. If a character has `inventory: {}` and `detail: {}`, they own NO confirmed weapons, items, or cyberware—do NOT attribute cyberarms, weapons, or loadouts to them even if earlier chat messages mentioned them.\n"
    '- Clean Markdown only: write spoken dialogue in normal quotes (e.g. "Step away from the case."), NOT wrapped inside `**...**`, and NEVER nest `**bold**` markers inside already-bolded spans.'
)

_DEFAULT_CHRONICLER_CORE_RULES = (
    "- Only record NPCs, locations, clues, or discoveries explicitly observed by the PC in the GM prose.\n"
    "- Selectively capture up to 1-2 newly introduced major recurring named NPCs, custom locations/nodes, or unique datashards/items in `new_homebrew` ONLY if they are player-observed, recurring, and not already stored; leave `new_homebrew` empty (`[]`) on routine turns.\n"
    "- Never invent unmentioned cyberware/gear or modify character HP/money.\n"
    "- Never copy `gm_secrets` or `secret` clocks into `state_ops`.\n"
    "- If time clearly passed in the narrated prose (e.g. 'twenty minutes later', 'by dawn') and `Solo Engine State` has not yet advanced for it, set `time_elapsed_minutes` accordingly; otherwise 0.\n"
    "- If everything from the narration is already synced, return empty lists and 0."
)

_DEFAULT_ARCHIVIST_CORE_RULES = (
    "1. Information Fog-of-War: `library_entries` and `campaign_updates` are PLAYER-VISIBLE. NEVER leak `gm_secrets`, unrevealed employers, unseen traps, or secret clocks into `library_entries`, `summary`, `npcs`, or `discoveries`.\n"
    "2. Put repeatable details (NPC dossiers/dispositions, gang/corp faction profiles, recurring venues/locations, custom datashards/gear/house rules) into `library_entries` with structured `stats` fields so `campaign_updates.summary` stays short and points to them via `[Category: Name]`.\n"
    "3. Preserve established names, eddies/gear facts, and unresolved obligations accurately."
)

DEFAULT_PROMPT_TEMPLATES: dict[str, str] = {
    "system_persona": _DEFAULT_NARRATOR_PERSONA,
    "world_rules_prefix": "",
    "player_message_template": _DEFAULT_PLAYER_MESSAGE_TEMPLATE,
    "player_dialogue_rules": _DEFAULT_PLAYER_DIALOGUE_RULES,
    "player_narration_rules": _DEFAULT_PLAYER_NARRATION_RULES,
    "multiplayer_rules": _DEFAULT_MULTIPLAYER_RULES,
    "planner_extra": "",
    "narrator_extra": "",
    "chronicler_extra": "",
    "archivist_extra": "",
    "creation_assist_persona": _DEFAULT_CREATION_ASSIST_PERSONA,
    "creation_assist_extra": "",
    "narrator_core_rules": _DEFAULT_NARRATOR_CORE_RULES,
    "planner_core_rules": _DEFAULT_PLANNER_CORE_RULES,
    "chronicler_core_rules": _DEFAULT_CHRONICLER_CORE_RULES,
    "archivist_core_rules": _DEFAULT_ARCHIVIST_CORE_RULES,
}

_GM_STYLE_HINTS = {
    "grounded": "Grounded street realism: keep pay, threat, and reactions gritty, everyday, and consequential.",
    "cinematic": "Cinematic neon noir: heightened atmosphere and tense dramatic pacing while still respecting dice outcomes.",
    "lethal": "Lethal combat zone: ruthless tactical opposition, scarce ammo/meds, and unforgiving consequences for mistakes.",
    "sandbox": "Open Night City sandbox: lean into ambient neighborhood leads, fixer gigs, and player-driven exploration.",
}

_LENGTH_HINTS = {
    "concise": "Keep replies crisp (1-2 tight paragraphs) so turns play fast.",
    "standard": "Write focused, vivid scenes (2-4 paragraphs) with breathing room for dialogue.",
    "detailed": "Write immersive, textured scenes (4-6 paragraphs) when exploring locales or tense confrontations.",
}


def read_settings_doc(settings_path: Path | None = None) -> dict[str, Any]:
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return dict(data) if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}


def write_settings_doc(doc: dict[str, Any], settings_path: Path | None = None) -> dict[str, Any]:
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    return doc


def _default_llm_dict() -> dict[str, Any]:
    return {
        "base_url": os.environ.get("REDGM_LLM_URL", "http://127.0.0.1:11434/v1"),
        "model": os.environ.get("REDGM_LLM_MODEL", "llama3"),
        "api_key": os.environ.get("REDGM_LLM_API_KEY", ""),
        "temperature": 0.75,
        "planner_temperature": 0.1,
        "creation_temperature": 0.85,
        "top_p": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "max_tokens": 1200,
        "timeout_s": 60.0,
        "mode": "two_pass",
        "enable_chronicler": True,
        "enable_highlights": True,
        "allow_ai_homebrew": True,
        "auto_compress_prompt": True,
        "retry_attempts": 2,
        "history_window": 14,
        "compression_threshold": _COMPRESSION_MESSAGE_THRESHOLD,
        "citation_limit": 4,
        "gm_style": "grounded",
        "narrator_length": "standard",
        "default_time_step_minutes": 0,
        "gm_thinking_mode": "quality",
    }


def _validate_llm_settings(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or _default_llm_dict())
    if "base_url" in raw and raw["base_url"] is not None:
        url = str(raw["base_url"]).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("base_url must start with http:// or https://")
        base["base_url"] = url.rstrip("/")
    if "model" in raw and raw["model"] is not None:
        model = str(raw["model"]).strip()
        if not model:
            raise ValueError("model must be a nonempty string")
        base["model"] = model
    if raw.get("clear_api_key"):
        base["api_key"] = ""
    elif "api_key" in raw and raw["api_key"] is not None:
        base["api_key"] = str(raw["api_key"]).strip()
    if "temperature" in raw and raw["temperature"] is not None:
        temp = float(raw["temperature"])
        if not 0.0 <= temp <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        base["temperature"] = temp
    if "planner_temperature" in raw and raw["planner_temperature"] is not None:
        ptemp = float(raw["planner_temperature"])
        if not 0.0 <= ptemp <= 1.5:
            raise ValueError("planner_temperature must be between 0.0 and 1.5")
        base["planner_temperature"] = ptemp
    if "creation_temperature" in raw and raw["creation_temperature"] is not None:
        ctemp = float(raw["creation_temperature"])
        if not 0.0 <= ctemp <= 1.5:
            raise ValueError("creation_temperature must be between 0.0 and 1.5")
        base["creation_temperature"] = ctemp
    if "top_p" in raw and raw["top_p"] is not None:
        tp = float(raw["top_p"])
        if not 0.05 <= tp <= 1.0:
            raise ValueError("top_p must be between 0.05 and 1.0")
        base["top_p"] = tp
    if "presence_penalty" in raw and raw["presence_penalty"] is not None:
        pp = float(raw["presence_penalty"])
        if not -2.0 <= pp <= 2.0:
            raise ValueError("presence_penalty must be between -2.0 and 2.0")
        base["presence_penalty"] = pp
    if "frequency_penalty" in raw and raw["frequency_penalty"] is not None:
        fp = float(raw["frequency_penalty"])
        if not -2.0 <= fp <= 2.0:
            raise ValueError("frequency_penalty must be between -2.0 and 2.0")
        base["frequency_penalty"] = fp
    if "max_tokens" in raw and raw["max_tokens"] is not None:
        mt = int(raw["max_tokens"])
        if not 64 <= mt <= 65536:
            raise ValueError("max_tokens must be between 64 and 65536")
        base["max_tokens"] = mt
    if "timeout_s" in raw and raw["timeout_s"] is not None:
        ts = float(raw["timeout_s"])
        if not 5.0 <= ts <= 600.0:
            raise ValueError("timeout_s must be between 5 and 600")
        base["timeout_s"] = ts
    if "mode" in raw and raw["mode"] is not None:
        mode = str(raw["mode"]).strip()
        if mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError("mode must be 'two_pass' or 'single_pass_tagged'")
        base["mode"] = mode
    if "enable_chronicler" in raw and raw["enable_chronicler"] is not None:
        base["enable_chronicler"] = bool(raw["enable_chronicler"])
    if "enable_highlights" in raw and raw["enable_highlights"] is not None:
        base["enable_highlights"] = bool(raw["enable_highlights"])
    if "allow_ai_homebrew" in raw and raw["allow_ai_homebrew"] is not None:
        base["allow_ai_homebrew"] = bool(raw["allow_ai_homebrew"])
    if "auto_compress_prompt" in raw and raw["auto_compress_prompt"] is not None:
        base["auto_compress_prompt"] = bool(raw["auto_compress_prompt"])
    if "retry_attempts" in raw and raw["retry_attempts"] is not None:
        ra = int(raw["retry_attempts"])
        if not 0 <= ra <= 5:
            raise ValueError("retry_attempts must be between 0 and 5")
        base["retry_attempts"] = ra
    if "history_window" in raw and raw["history_window"] is not None:
        hw = int(raw["history_window"])
        if not 4 <= hw <= 500:
            raise ValueError("history_window must be between 4 and 500")
        base["history_window"] = hw
    if "compression_threshold" in raw and raw["compression_threshold"] is not None:
        ct = int(raw["compression_threshold"])
        if not 6 <= ct <= 1000:
            raise ValueError("compression_threshold must be between 6 and 1000")
        base["compression_threshold"] = ct
    if "citation_limit" in raw and raw["citation_limit"] is not None:
        cl = int(raw["citation_limit"])
        if not 1 <= cl <= 30:
            raise ValueError("citation_limit must be between 1 and 30")
        base["citation_limit"] = cl
    if "gm_style" in raw and raw["gm_style"] is not None:
        style = str(raw["gm_style"]).strip()
        if style not in _GM_STYLE_HINTS:
            raise ValueError("gm_style must be one of grounded, cinematic, lethal, sandbox")
        base["gm_style"] = style
    if "narrator_length" in raw and raw["narrator_length"] is not None:
        nl = str(raw["narrator_length"]).strip()
        if nl not in _LENGTH_HINTS:
            raise ValueError("narrator_length must be one of concise, standard, detailed")
        base["narrator_length"] = nl
    if "default_time_step_minutes" in raw and raw["default_time_step_minutes"] is not None:
        dt = int(raw["default_time_step_minutes"])
        if not 0 <= dt <= 1440:
            raise ValueError("default_time_step_minutes must be between 0 and 1440")
        base["default_time_step_minutes"] = dt
    if "gm_thinking_mode" in raw and raw["gm_thinking_mode"] is not None:
        tm = str(raw["gm_thinking_mode"]).strip()
        if tm not in _GM_THINKING_MODES:
            raise ValueError("gm_thinking_mode must be 'quality' or 'balanced'")
        base["gm_thinking_mode"] = tm
    return base


def load_llm_settings(settings_path: Path | None = None) -> dict[str, Any]:
    defaults = _default_llm_dict()
    data = read_settings_doc(settings_path)
    if not data:
        return defaults
    try:
        return _validate_llm_settings(data, defaults)
    except (TypeError, ValueError):
        return defaults


def save_llm_settings(updates: dict[str, Any], settings_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValueError("settings payload must be an object")
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        doc = read_settings_doc(path)
        current = load_llm_settings(path)
        merged = _validate_llm_settings(updates, current)
        for key in _default_llm_dict():
            doc[key] = merged[key]
        write_settings_doc(doc, path)
    return merged


def masked_llm_settings(settings: dict[str, Any]) -> dict[str, Any]:
    key = str(settings.get("api_key") or "")
    if not key:
        masked = ""
    elif len(key) <= 8:
        masked = "*" * len(key)
    else:
        masked = f"{key[:4]}...{key[-4:]}"
    return {
        "base_url": settings["base_url"],
        "model": settings["model"],
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "temperature": settings["temperature"],
        "planner_temperature": float(settings.get("planner_temperature", 0.1)),
        "creation_temperature": float(settings.get("creation_temperature", 0.85)),
        "top_p": settings.get("top_p", 1.0),
        "presence_penalty": settings.get("presence_penalty", 0.0),
        "frequency_penalty": settings.get("frequency_penalty", 0.0),
        "max_tokens": settings["max_tokens"],
        "timeout_s": settings["timeout_s"],
        "mode": settings["mode"],
        "enable_chronicler": bool(settings.get("enable_chronicler", True)),
        "enable_highlights": bool(settings.get("enable_highlights", True)),
        "allow_ai_homebrew": bool(settings.get("allow_ai_homebrew", True)),
        "auto_compress_prompt": bool(settings.get("auto_compress_prompt", True)),
        "retry_attempts": int(settings.get("retry_attempts", 2)),
        "history_window": int(settings.get("history_window", 14)),
        "compression_threshold": int(settings.get("compression_threshold", _COMPRESSION_MESSAGE_THRESHOLD)),
        "citation_limit": int(settings.get("citation_limit", 4)),
        "gm_style": settings.get("gm_style", "grounded"),
        "narrator_length": settings.get("narrator_length", "standard"),
        "default_time_step_minutes": int(settings.get("default_time_step_minutes", 0)),
        "gm_thinking_mode": settings.get("gm_thinking_mode", "quality"),
    }


_MAX_PROMPT_CHARS = 16000
_NON_EMPTY_PROMPT_KEYS = frozenset({"system_persona", "creation_assist_persona", "player_message_template"})


def load_prompt_settings(settings_path: Path | None = None) -> dict[str, str]:
    defaults = dict(DEFAULT_PROMPT_TEMPLATES)
    doc = read_settings_doc(settings_path)
    raw = doc.get("prompts")
    if not isinstance(raw, dict):
        return defaults
    out = dict(defaults)
    for key in defaults:
        val = raw.get(key)
        if isinstance(val, str):
            trimmed = val.strip()[:_MAX_PROMPT_CHARS]
            out[key] = trimmed if (trimmed or key not in _NON_EMPTY_PROMPT_KEYS) else defaults[key]
    return out


def save_prompt_settings(updates: dict[str, Any], settings_path: Path | None = None) -> dict[str, str]:
    if not isinstance(updates, dict):
        raise ValueError("prompt settings payload must be an object")
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        doc = read_settings_doc(path)
        if updates.get("reset"):
            next_prompts = dict(DEFAULT_PROMPT_TEMPLATES)
        else:
            next_prompts = load_prompt_settings(path)
            for key in DEFAULT_PROMPT_TEMPLATES:
                if key in updates and updates[key] is not None:
                    text = str(updates[key]).strip()
                    if len(text) > _MAX_PROMPT_CHARS:
                        raise ValueError(f"Prompt field {key} exceeds {_MAX_PROMPT_CHARS} characters")
                    if key in _NON_EMPTY_PROMPT_KEYS and not text:
                        next_prompts[key] = DEFAULT_PROMPT_TEMPLATES[key]
                    else:
                        next_prompts[key] = text
        doc["prompts"] = next_prompts
        write_settings_doc(doc, path)
    return next_prompts


def _default_server_dict() -> dict[str, Any]:
    raw_port = os.environ.get("REDGM_PORT", "8765").strip() or "8765"
    try:
        env_port = max(1, min(65535, int(raw_port)))
    except ValueError:
        env_port = 8765
    raw_origins = os.environ.get("REDGM_ALLOWED_ORIGINS", "")
    env_origins = [o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()]
    return {
        "bind_host": (os.environ.get("REDGM_HOST", "127.0.0.1") or "127.0.0.1").strip(),
        "port": env_port,
        "allowed_origins": env_origins,
        "public_url": (os.environ.get("REDGM_PUBLIC_URL", "") or "").strip().rstrip("/"),
    }


def _validate_origin_url(origin: str) -> str:
    cleaned = str(origin).strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "*" in cleaned
    ):
        raise ValueError(f"Invalid origin (must be exact http(s)://host[:port]): {origin!r}")
    return cleaned


def _validate_server_settings(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or _default_server_dict())
    if "bind_host" in raw and raw["bind_host"] is not None:
        host = str(raw["bind_host"]).strip()
        if not host or any(c in host for c in " \t\n\r/\\"):
            raise ValueError("bind_host must be a valid IP address or hostname")
        if host not in {"localhost", "0.0.0.0", "::"}:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
                    raise ValueError(f"Invalid bind_host: {host!r}") from None
        base["bind_host"] = host
    if "port" in raw and raw["port"] is not None:
        if isinstance(raw["port"], bool):
            raise ValueError("port must be an integer")
        try:
            port = int(raw["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        base["port"] = port
    if "allowed_origins" in raw and raw["allowed_origins"] is not None:
        origins_raw = raw["allowed_origins"]
        if isinstance(origins_raw, str):
            origins_list = [x.strip() for x in re.split(r"[\n,]+", origins_raw) if x.strip()]
        elif isinstance(origins_raw, list):
            origins_list = [str(x).strip() for x in origins_raw if str(x).strip()]
        else:
            raise ValueError("allowed_origins must be a list or comma-separated string")
        base["allowed_origins"] = [_validate_origin_url(o) for o in origins_list[:32]]
    if "public_url" in raw and raw["public_url"] is not None:
        pub = str(raw["public_url"]).strip().rstrip("/")
        if pub:
            parsed = urlsplit(pub)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("public_url must start with http:// or https://")
        base["public_url"] = pub
    return base


def load_server_settings(settings_path: Path | None = None) -> dict[str, Any]:
    defaults = _default_server_dict()
    doc = read_settings_doc(settings_path)
    raw = doc.get("server")
    if not isinstance(raw, dict):
        return defaults
    try:
        return _validate_server_settings(raw, defaults)
    except (TypeError, ValueError):
        return defaults


def save_server_settings(updates: dict[str, Any], settings_path: Path | None = None) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValueError("server settings payload must be an object")
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        doc = read_settings_doc(path)
        current = load_server_settings(path)
        merged = _validate_server_settings(updates, current)
        doc["server"] = merged
        write_settings_doc(doc, path)
    return merged


@dataclass(slots=True)
class LLMConfig:
    """Model-agnostic connection settings for any OpenAI-compatible chat API."""

    base_url: str = os.environ.get("REDGM_LLM_URL", "http://127.0.0.1:11434/v1")
    model: str = os.environ.get("REDGM_LLM_MODEL", "llama3")
    api_key: str = os.environ.get("REDGM_LLM_API_KEY", "")
    temperature: float = 0.75
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    max_tokens: int = 1200
    timeout_s: float = 60.0
    mode: str = "two_pass"  # "two_pass" or "single_pass_tagged"
    retry_attempts: int = 2


class OpenAICompatibleLLM:
    """Async OpenAI-compatible /chat/completions client usable with local or cloud models."""

    def __init__(self, config: LLMConfig | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config or LLMConfig()
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        return f"{base}/chat/completions" if not base.endswith("/chat/completions") else base

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        ra = resp.headers.get("retry-after")
        if ra:
            try:
                return max(0.5, min(10.0, float(ra)))
            except ValueError:
                pass
        return 1.5 * (attempt + 1)

    def _sampling_extras(self) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        top_p = float(getattr(self.config, "top_p", 1.0))
        if top_p < 0.999:
            extras["top_p"] = top_p
        pp = float(getattr(self.config, "presence_penalty", 0.0))
        if abs(pp) > 1e-6:
            extras["presence_penalty"] = pp
        fp = float(getattr(self.config, "frequency_penalty", 0.0))
        if abs(fp) > 1e-6:
            extras["frequency_penalty"] = fp
        return extras

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
    ) -> str:
        effective_max = self.config.max_tokens if max_tokens is None else max_tokens
        if json_mode and max_tokens is None:
            # Reasoning models count thinking tokens against max_tokens; give structured JSON passes headroom.
            effective_max = max(int(effective_max), 4096)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": effective_max,
            "stream": False,
            **self._sampling_extras(),
        }
        if enable_thinking is False:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        max_attempts = max(1, 1 + int(getattr(self.config, "retry_attempts", 2)))
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                resp = await client.post(self._endpoint(), headers=self._headers(), json=payload)
                if resp.status_code == 400 and ("response_format" in payload or "chat_template_kwargs" in payload):
                    payload.pop("response_format", None)
                    payload.pop("chat_template_kwargs", None)
                    resp = await client.post(self._endpoint(), headers=self._headers(), json=payload)
                if resp.status_code in {429, 503} and attempt < max_attempts - 1:
                    await asyncio.sleep(self._retry_delay(resp, attempt))
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        return str(msg.get("content") or "")

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
            **self._sampling_extras(),
        }
        if enable_thinking is False:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        max_attempts = max(1, 1 + int(getattr(self.config, "retry_attempts", 2)))
        async with httpx.AsyncClient(timeout=self.config.timeout_s, transport=self.transport) as client:
            for attempt in range(max_attempts):
                retry_delay: float | None = None
                stripped_kwargs = False
                while True:
                    async with client.stream("POST", self._endpoint(), headers=self._headers(), json=payload) as resp:
                        if resp.status_code == 400 and "chat_template_kwargs" in payload and not stripped_kwargs:
                            payload.pop("chat_template_kwargs", None)
                            stripped_kwargs = True
                            continue
                        if resp.status_code in {429, 503} and attempt < max_attempts - 1:
                            retry_delay = self._retry_delay(resp, attempt)
                            break
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            body = line[5:].strip()
                            if body == "[DONE]":
                                break
                            try:
                                chunk = json.loads(body)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0].get("delta") or {}).get("content")
                            if isinstance(delta, str) and delta:
                                yield delta
                        return
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)


class ChatTreeStore:
    """Persistent message-tree storage in campaign.sqlite with revision sync tracking."""

    def __init__(self, gameplay: GameplayService):
        self.gameplay = gameplay
        self.store = gameplay.store
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    parent_id TEXT REFERENCES chat_messages(id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    campaign_revision INTEGER NOT NULL,
                    solo_revision INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_camp_parent ON chat_messages(campaign_id, parent_id, created_at)"
            )

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "parent_id": row["parent_id"],
            "role": row["role"],
            "content": row["content"],
            "raw_content": row["raw_content"],
            "model": row["model"],
            "campaign_revision": int(row["campaign_revision"]),
            "solo_revision": int(row["solo_revision"]),
            "metadata": json.loads(row["metadata_json"]),
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
        }

    def get_message(self, campaign_id: str, message_id: str) -> dict[str, Any] | None:
        with closing(self.store._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            return self._row_dict(row) if row else None

    def append_message(
        self,
        campaign_id: str,
        *,
        parent_id: str | None,
        role: str,
        content: str,
        raw_content: str | None = None,
        model: str = "",
        campaign_revision: int,
        solo_revision: int,
        metadata: dict[str, Any] | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("role must be user, assistant, or system")
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        raw = content if raw_content is None else raw_content
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise ValueError(f"campaign not found: {campaign_id}")
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT 1 FROM chat_messages WHERE campaign_id=? AND id=?",
                    (campaign_id, parent_id),
                ).fetchone()
                if not parent:
                    raise ValueError(f"parent message not found in campaign: {parent_id}")
            if activate:
                if parent_id is None:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND parent_id IS NULL",
                        (campaign_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND parent_id=?",
                        (campaign_id, parent_id),
                    )
            conn.execute(
                """
                INSERT INTO chat_messages(
                    id, campaign_id, parent_id, role, content, raw_content, model,
                    campaign_revision, solo_revision, metadata_json, is_active, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    msg_id,
                    campaign_id,
                    parent_id,
                    role,
                    content,
                    raw,
                    model,
                    int(campaign_revision),
                    int(solo_revision),
                    _json(metadata or {}),
                    1 if activate else 0,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM chat_messages WHERE id=?", (msg_id,)).fetchone()
            return self._row_dict(row)

    def _current_revisions(self, campaign_id: str) -> dict[str, int]:
        ctx = self.gameplay.campaign_context(campaign_id)
        return {
            "campaign_revision": int(ctx["campaign"]["revision"]),
            "solo_revision": int(ctx["solo"]["revision"]),
        }

    def get_tree(self, campaign_id: str) -> dict[str, Any]:
        revs = self._current_revisions(campaign_id)
        with closing(self.store._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? ORDER BY created_at, id",
                (campaign_id,),
            ).fetchall()
        nodes = [self._row_dict(r) for r in rows]
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for node in nodes:
            by_parent.setdefault(node["parent_id"], []).append(node)
        for siblings in by_parent.values():
            for idx, node in enumerate(siblings):
                node["sibling_index"] = idx
                node["sibling_count"] = len(siblings)
                node["sibling_ids"] = [s["id"] for s in siblings]

        active_branch: list[dict[str, Any]] = []
        parent_key: str | None = None
        seen: set[str] = set()
        while True:
            children = by_parent.get(parent_key, [])
            active = next((c for c in children if c["is_active"]), None)
            if active is None or active["id"] in seen:
                break
            seen.add(active["id"])
            active_branch.append(active)
            parent_key = active["id"]

        leaf = active_branch[-1] if active_branch else None
        revision_mismatch = bool(
            leaf
            and (
                leaf["campaign_revision"] != revs["campaign_revision"]
                or leaf["solo_revision"] != revs["solo_revision"]
            )
        )
        return {
            "campaign_id": campaign_id,
            "nodes": nodes,
            "active_branch": active_branch,
            "active_leaf_id": leaf["id"] if leaf else None,
            "current_revisions": revs,
            "revision_mismatch": revision_mismatch,
        }

    def get_branch_to(self, campaign_id: str, leaf_id: str | None) -> list[dict[str, Any]]:
        if leaf_id is None:
            return []
        with closing(self.store._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=?",
                (campaign_id,),
            ).fetchall()
        by_id = {r["id"]: self._row_dict(r) for r in rows}
        chain: list[dict[str, Any]] = []
        cur = by_id.get(leaf_id)
        if cur is None:
            raise ValueError(f"message not found in campaign: {leaf_id}")
        while cur is not None:
            chain.append(cur)
            cur = by_id.get(cur["parent_id"]) if cur["parent_id"] else None
        chain.reverse()
        return chain

    def _activate_descendant_chain(
        self,
        conn: sqlite3.Connection,
        campaign_id: str,
        start_id: str,
        children: dict[str | None, list[sqlite3.Row]],
        excluded: set[str],
    ) -> None:
        """Walk downward from start_id, keeping exactly one active child per parent."""
        cur_id: str | None = start_id
        seen: set[str] = set()
        while cur_id is not None and cur_id not in seen:
            seen.add(cur_id)
            conn.execute("UPDATE chat_messages SET is_active=1 WHERE campaign_id=? AND id=?", (campaign_id, cur_id))
            next_children = [r for r in children.get(cur_id, []) if r["id"] not in excluded]
            if not next_children:
                break
            cur_active = next((c for c in next_children if c["is_active"]), next_children[0])
            for ch in next_children:
                if ch["id"] != cur_active["id"] and ch["is_active"]:
                    conn.execute("UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND id=?", (campaign_id, ch["id"]))
            cur_id = cur_active["id"]

    def switch_branch(self, campaign_id: str, message_id: str) -> dict[str, Any]:
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? ORDER BY created_at, id",
                (campaign_id,),
            ).fetchall()
            by_id = {r["id"]: r for r in rows}
            if message_id not in by_id:
                raise ValueError(f"message not found in campaign: {message_id}")
            children: dict[str | None, list[sqlite3.Row]] = {}
            for r in rows:
                children.setdefault(r["parent_id"], []).append(r)
            cur_id: str | None = message_id
            while cur_id is not None:
                row = by_id[cur_id]
                parent_id = row["parent_id"]
                if parent_id is None:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND parent_id IS NULL",
                        (campaign_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND parent_id=?",
                        (campaign_id, parent_id),
                    )
                conn.execute("UPDATE chat_messages SET is_active=1 WHERE id=?", (cur_id,))
                cur_id = parent_id
            # Ensure the selected node's downward active chain has no duplicate active siblings.
            self._activate_descendant_chain(conn, campaign_id, message_id, children, set())
        return self.get_tree(campaign_id)

    def delete_message(
        self, campaign_id: str, message_id: str, *, scope: str = "branch"
    ) -> dict[str, Any]:
        """Delete either a single message (re-parenting children) or the entire subtree below it."""
        if scope not in {"branch", "single"}:
            raise ValueError("scope must be 'branch' or 'single'")
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, parent_id, is_active, created_at FROM chat_messages WHERE campaign_id=? ORDER BY created_at, id",
                (campaign_id,),
            ).fetchall()
            by_id = {r["id"]: r for r in rows}
            if message_id not in by_id:
                raise ValueError(f"message not found in campaign: {message_id}")
            children: dict[str | None, list[sqlite3.Row]] = {}
            for r in rows:
                children.setdefault(r["parent_id"], []).append(r)

            target_row = by_id[message_id]
            parent_id = target_row["parent_id"]
            was_active = bool(target_row["is_active"])
            has_snapshots = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_gm_snapshots'"
                ).fetchone()
            )
            has_compressions = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_compressions'"
                ).fetchone()
            )

            if scope == "single":
                direct_children = children.get(message_id, [])
                if direct_children:
                    conn.execute(
                        "UPDATE chat_messages SET parent_id=? WHERE campaign_id=? AND parent_id=?",
                        (parent_id, campaign_id, message_id),
                    )
                    if not was_active:
                        # Re-parented children from an inactive branch must not compete with the active sibling.
                        for ch in direct_children:
                            if ch["is_active"]:
                                conn.execute(
                                    "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND id=?",
                                    (campaign_id, ch["id"]),
                                )
                    if has_snapshots:
                        conn.execute(
                            "UPDATE turn_gm_snapshots SET parent_id=? WHERE campaign_id=? AND parent_id=?",
                            (parent_id, campaign_id, message_id),
                        )
                conn.execute("DELETE FROM chat_messages WHERE campaign_id=? AND id=?", (campaign_id, message_id))
                if has_snapshots:
                    conn.execute(
                        "DELETE FROM turn_gm_snapshots WHERE campaign_id=? AND message_id=?",
                        (campaign_id, message_id),
                    )
                if has_compressions:
                    conn.execute(
                        "UPDATE campaign_compressions SET leaf_id=? WHERE campaign_id=? AND leaf_id=?",
                        (parent_id, campaign_id, message_id),
                    )
                excluded = {message_id}
                if was_active:
                    # Deactivate all remaining original siblings under parent_id first.
                    for sib in children.get(parent_id, []):
                        if sib["id"] != message_id and sib["is_active"]:
                            conn.execute(
                                "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND id=?",
                                (campaign_id, sib["id"]),
                            )
                    if direct_children:
                        chosen_child = next((c for c in direct_children if c["is_active"]), direct_children[0])
                        for ch in direct_children:
                            if ch["id"] != chosen_child["id"] and ch["is_active"]:
                                conn.execute(
                                    "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND id=?",
                                    (campaign_id, ch["id"]),
                                )
                        self._activate_descendant_chain(conn, campaign_id, chosen_child["id"], children, excluded)
                        reactivate = False
                    else:
                        reactivate = True
                else:
                    reactivate = False
            else:
                to_delete: list[str] = []
                queue = [message_id]
                while queue:
                    cur = queue.pop(0)
                    to_delete.append(cur)
                    for ch in children.get(cur, []):
                        queue.append(ch["id"])
                excluded = set(to_delete)
                # Delete leaves first to satisfy self-referential foreign keys cleanly.
                for del_id in reversed(to_delete):
                    conn.execute("DELETE FROM chat_messages WHERE campaign_id=? AND id=?", (campaign_id, del_id))
                    if has_snapshots:
                        conn.execute(
                            "DELETE FROM turn_gm_snapshots WHERE campaign_id=? AND message_id=?",
                            (campaign_id, del_id),
                        )
                if has_compressions and to_delete:
                    placeholders = ",".join("?" for _ in to_delete)
                    conn.execute(
                        f"UPDATE campaign_compressions SET leaf_id=? WHERE campaign_id=? AND leaf_id IN ({placeholders})",
                        (parent_id, campaign_id, *to_delete),
                    )
                reactivate = was_active

            if reactivate:
                siblings = [r for r in children.get(parent_id, []) if r["id"] not in excluded]
                if siblings:
                    orig_siblings = [r["id"] for r in children.get(parent_id, [])]
                    old_idx = orig_siblings.index(message_id) if message_id in orig_siblings else 0
                    replacement = siblings[min(max(0, old_idx - 1), len(siblings) - 1)]
                    for sib in siblings:
                        if sib["id"] != replacement["id"] and sib["is_active"]:
                            conn.execute(
                                "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND id=?",
                                (campaign_id, sib["id"]),
                            )
                    self._activate_descendant_chain(conn, campaign_id, replacement["id"], children, excluded)
        return self.get_tree(campaign_id)

    def update_message(self, campaign_id: str, message_id: str, content: str) -> dict[str, Any]:
        """Update an existing message's text in place without spawning a new branch."""
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a nonempty string")
        cleaned = content.strip()
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT metadata_json FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            meta = json.loads(row["metadata_json"])
            meta["edited"] = True
            meta["edited_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE chat_messages SET content=?, raw_content=?, metadata_json=? WHERE campaign_id=? AND id=?",
                (cleaned, cleaned, _json(meta), campaign_id, message_id),
            )
        return self.get_tree(campaign_id)

    def export_branch(self, campaign_id: str, leaf_id: str | None = None) -> dict[str, Any]:
        """Return both structured JSON and Markdown transcript for the active or requested branch."""
        ctx = self.gameplay.campaign_context(campaign_id)
        tree = self.get_tree(campaign_id)
        branch = self.get_branch_to(campaign_id, leaf_id) if leaf_id else tree["active_branch"]
        lines = [
            f"# {ctx['campaign']['name']} — Session {ctx['campaign']['session_number']}",
            "",
        ]
        if ctx["campaign"]["state"].get("scene"):
            lines.append(f"**Scene:** {ctx['campaign']['state']['scene']}")
            lines.append("")
        for msg in branch:
            meta = msg.get("metadata") or {}
            speaker = meta.get("speaker_name") or ("Player" if msg["role"] == "user" else "Game Master")
            lines.append(f"## {speaker} ({msg['role']})")
            lines.append("")
            lines.append(msg["content"])
            for r in meta.get("rolls") or []:
                lines.append(f"- Roll ({r.get('actor', 'PC')}): {r.get('skill') or r.get('stat')} = {r.get('total')} vs DV {r.get('dv', '?')}")
            lines.append("")
        return {
            "campaign": ctx["campaign"],
            "branch": branch,
            "markdown": "\n".join(lines).strip() + "\n",
        }


def strip_gm_tags(text: str) -> str:
    """Remove structured GM control tags so user-visible narrative stays clean."""
    cleaned = _GM_TAG_RE.sub("", text)
    cleaned = _GM_XML_RE.sub("", cleaned)
    return cleaned.strip()


def extract_gm_plan(raw_text: str) -> dict[str, Any]:
    """Extract structured GM plan/operations from JSON, [[GM_STATE:...]], or <gm_ops>...</gm_ops>."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return {}
    for pattern in (_GM_XML_RE, _GM_TAG_RE):
        match = pattern.search(raw_text)
        if match:
            try:
                parsed = json.loads(match.group(1))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    stripped = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    candidate = fence.group(1) if fence else stripped
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _resolve_character(actor: str | None, characters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not characters:
        return None
    if not isinstance(actor, str) or not actor.strip():
        return characters[0] if len(characters) == 1 else None
    needle = actor.strip().casefold()
    for char in characters:
        if char["name"].strip().casefold() == needle or char["id"] == actor.strip():
            return char
    for char in characters:
        cname = char["name"].strip().casefold()
        if cname.startswith(needle) or needle in cname:
            return char
    names = {c["name"].strip().casefold(): c for c in characters}
    close = difflib.get_close_matches(needle, list(names), n=1, cutoff=0.6)
    return names[close[0]] if close else None


def _summarize_character(char: dict[str, Any]) -> dict[str, Any]:
    """Render canonical snapshot of character state for rules planning and narration."""
    max_h = int(char.get("max_hp") or 0)
    body_stat = int((char.get("stats") or {}).get("BODY", 0))
    move_stat = int((char.get("stats") or {}).get("MOVE", 0))
    d = char.get("detail") or {}
    role_ext = d.get("role_ext") or {}
    char_ip = int(role_ext.get("ip") or d.get("ip") or 0)
    return {
        "id": char["id"],
        "name": char["name"],
        "hp": char["hp"],
        "max_hp": char["max_hp"],
        "seriously_wounded": (max_h + 1) // 2,
        "death_save": body_stat,
        "wound_state": wound_state(max(0, char["hp"]), char["max_hp"], move_stat),
        "humanity": char["humanity"],
        "luck_remaining": char["luck_remaining"],
        "money": char["money"],
        "ip": char_ip,
        "stats": char["stats"],
        "skills": char["skills"],
        "inventory": char.get("inventory") or {},
        "detail": char.get("detail") or {},
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


def _normalize_campaign_changes(
    raw_changes: dict[str, Any], current_state: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    mapped = dict(raw_changes)
    if "location" in mapped and "scene" not in mapped:
        mapped["scene"] = mapped.pop("location")
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
            merged = dict(list(merged.items())[-40:])
        clean[section] = merged
    return clean, notes


class TurnEngine:
    """Hybrid 3-phase / 2-pass GM turn orchestrator backed by deterministic Cyberpunk RED tools."""

    def __init__(
        self,
        gameplay: GameplayService,
        llm: Any | None = None,
        *,
        library: CampaignLibrary | None = None,
        tree: ChatTreeStore | None = None,
        settings_path: Path | None = None,
        turn_settings: dict[str, Any] | None = None,
        prompt_settings: dict[str, str] | None = None,
    ):
        self.gameplay = gameplay
        self.llm = llm or OpenAICompatibleLLM()
        self.library = library or CampaignLibrary(gameplay.store, rules_path=gameplay.rules_path)
        self.tree = tree or ChatTreeStore(gameplay)
        self.settings_path = settings_path
        base_turn = load_llm_settings(settings_path) if settings_path is not None else _default_llm_dict()
        if isinstance(turn_settings, dict):
            base_turn = _validate_llm_settings(turn_settings, base_turn)
        self.turn_settings = base_turn
        base_prompts = load_prompt_settings(settings_path) if settings_path is not None else dict(DEFAULT_PROMPT_TEMPLATES)
        if isinstance(prompt_settings, dict):
            for k in DEFAULT_PROMPT_TEMPLATES:
                if isinstance(prompt_settings.get(k), str):
                    val = prompt_settings[k].strip()
                    base_prompts[k] = val if (val or k not in _NON_EMPTY_PROMPT_KEYS) else DEFAULT_PROMPT_TEMPLATES[k]
        self.prompt_settings = base_prompts
        self._skill_cache: dict[str, dict[str, Any]] | None = None
        self._item_cache: dict[str, dict[str, Any]] | None = None
        self._ensure_private_tables()

    @staticmethod
    def _supports_enable_thinking(fn: Any) -> bool:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        return "enable_thinking" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )

    def _thinking_kwargs_for_pass(self, fn: Any, *, disable_in_balanced: bool) -> dict[str, Any]:
        if not disable_in_balanced:
            return {}
        if self.turn_settings.get("gm_thinking_mode", "quality") != "balanced":
            return {}
        return {"enable_thinking": False} if self._supports_enable_thinking(fn) else {}

    def _ensure_private_tables(self) -> None:
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gm_secrets (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                    secrets_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_clocks (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                    clocks_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_gm_snapshots (
                    message_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    parent_id TEXT,
                    secrets_json TEXT NOT NULL DEFAULT '{}',
                    clocks_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_compressions (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                    leaf_id TEXT,
                    compressed_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )

    @staticmethod
    def _clean_secrets_dict(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for k, v in raw.items():
            key = str(k).strip()[:120]
            if not key or v is None:
                continue
            if isinstance(v, str):
                if not v.strip():
                    continue
                out[key] = v.strip()[:600]
            elif isinstance(v, (int, float, bool)):
                out[key] = str(v)
        return out

    @staticmethod
    def _merge_gm_secrets(current: dict[str, str], updates: Any) -> dict[str, str]:
        merged = dict(current)
        if not isinstance(updates, dict) or not updates:
            return merged
        for raw_k, raw_v in updates.items():
            key = str(raw_k).strip()[:120]
            if not key:
                continue
            if raw_v is None or (isinstance(raw_v, str) and not raw_v.strip()):
                merged.pop(key, None)
            else:
                val = raw_v if isinstance(raw_v, str) else json.dumps(raw_v, ensure_ascii=False)
                merged[key] = val.strip()[:600]
        while len(merged) > 30:
            merged.pop(next(iter(merged)), None)
        serialized = json.dumps(merged, ensure_ascii=False)
        while len(serialized) > 8000 and merged:
            merged.pop(next(iter(merged)), None)
            serialized = json.dumps(merged, ensure_ascii=False)
        return merged

    @staticmethod
    def _normalize_clock_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        cleaned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = re.sub(r"[^a-z0-9_-]+", "-", str(item.get("id") or item.get("name") or "").strip().lower()).strip("-")[:64]
            name = str(item.get("name") or cid or "").strip()[:80]
            if not cid or not name or cid in seen:
                continue
            seen.add(cid)
            try:
                segments = max(2, min(12, int(item.get("segments", 4))))
            except (TypeError, ValueError):
                segments = 4
            try:
                filled = max(0, min(segments, int(item.get("filled", 0))))
            except (TypeError, ValueError):
                filled = 0
            cat = str(item.get("category") or "heat").strip().lower()
            if cat not in _CLOCK_CATEGORIES:
                cat = "heat"
            vis = "secret" if str(item.get("visibility") or "public").strip().lower() == "secret" else "public"
            note = str(item.get("note") or "").strip()[:240]
            cleaned.append(
                {
                    "id": cid,
                    "name": name,
                    "filled": filled,
                    "segments": segments,
                    "category": cat,
                    "visibility": vis,
                    "note": note,
                }
            )
            if len(cleaned) >= 20:
                break
        return cleaned

    @classmethod
    def _apply_clock_ops(
        cls,
        current: list[dict[str, Any]],
        ops: Any,
        *,
        allow_secret: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        clocks = [dict(c) for c in cls._normalize_clock_list(current)]
        if not isinstance(ops, list) or not ops:
            return clocks, []
        by_id = {c["id"]: idx for idx, c in enumerate(clocks)}
        public_changes: list[dict[str, Any]] = []

        for raw_op in ops:
            if not isinstance(raw_op, dict):
                continue
            raw_ident = str(raw_op.get("id") or raw_op.get("name") or "").strip()
            if not raw_ident:
                continue
            cid = re.sub(r"[^a-z0-9_-]+", "-", raw_ident.lower()).strip("-")[:64]
            if not cid:
                continue
            idx = by_id.get(cid)
            existing = dict(clocks[idx]) if idx is not None else None

            if raw_op.get("delete") is True:
                if existing is None:
                    continue
                if not allow_secret and existing.get("visibility") == "secret":
                    continue
                clocks.pop(idx)  # type: ignore[arg-type]
                by_id = {c["id"]: i for i, c in enumerate(clocks)}
                if existing.get("visibility") != "secret":
                    public_changes.append({"clock": existing["name"], "before": f"{existing['filled']}/{existing['segments']}", "after": "removed"})
                continue

            vis_raw = str(raw_op.get("visibility") or (existing["visibility"] if existing else "public")).strip().lower()
            vis = "secret" if (allow_secret and vis_raw == "secret") else "public"
            if existing is not None and not allow_secret and existing.get("visibility") == "secret":
                continue

            name = str(raw_op.get("name") or (existing["name"] if existing else raw_ident)).strip()[:80]
            try:
                segments = max(2, min(12, int(raw_op.get("segments", existing["segments"] if existing else 4))))
            except (TypeError, ValueError):
                segments = existing["segments"] if existing else 4
            base_filled = existing["filled"] if existing else 0
            if "filled" in raw_op and raw_op["filled"] is not None:
                try:
                    filled = int(raw_op["filled"])
                except (TypeError, ValueError):
                    filled = base_filled
            elif "delta" in raw_op and raw_op["delta"] is not None:
                try:
                    filled = base_filled + int(raw_op["delta"])
                except (TypeError, ValueError):
                    filled = base_filled
            else:
                filled = base_filled
            filled = max(0, min(segments, filled))

            cat = str(raw_op.get("category") or (existing["category"] if existing else "heat")).strip().lower()
            if cat not in _CLOCK_CATEGORIES:
                cat = existing["category"] if existing else "heat"
            note = str(raw_op.get("note") if "note" in raw_op and raw_op["note"] is not None else (existing["note"] if existing else "")).strip()[:240]

            updated_clock = {
                "id": cid,
                "name": name,
                "filled": filled,
                "segments": segments,
                "category": cat,
                "visibility": vis,
                "note": note,
            }
            if existing is not None:
                clocks[idx] = updated_clock  # type: ignore[index]
            elif len(clocks) < 20:
                clocks.append(updated_clock)
                by_id[cid] = len(clocks) - 1
            if vis != "secret" and (
                existing is None
                or existing["filled"] != filled
                or existing["segments"] != segments
                or existing["name"] != name
            ):
                prev_lbl = f"{existing['filled']}/{existing['segments']}" if existing else "new"
                public_changes.append({"clock": name, "before": prev_lbl, "after": f"{filled}/{segments}"})

        return clocks, public_changes

    def _load_branch_private_state(
        self, campaign_id: str, parent_id: str | None
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        with closing(self.gameplay.store._connect()) as conn:
            cursor_id = parent_id
            for _ in range(500):
                if not cursor_id:
                    break
                snap = conn.execute(
                    "SELECT secrets_json, clocks_json FROM turn_gm_snapshots WHERE campaign_id=? AND message_id=?",
                    (campaign_id, cursor_id),
                ).fetchone()
                if snap is not None:
                    try:
                        s = self._clean_secrets_dict(json.loads(snap["secrets_json"]))
                    except (TypeError, json.JSONDecodeError):
                        s = {}
                    try:
                        c = self._normalize_clock_list(json.loads(snap["clocks_json"]))
                    except (TypeError, json.JSONDecodeError):
                        c = []
                    return s, c
                msg = conn.execute(
                    "SELECT parent_id FROM chat_messages WHERE campaign_id=? AND id=?",
                    (campaign_id, cursor_id),
                ).fetchone()
                cursor_id = msg["parent_id"] if msg else None

            sec_row = conn.execute("SELECT secrets_json FROM gm_secrets WHERE campaign_id=?", (campaign_id,)).fetchone()
            clk_row = conn.execute("SELECT clocks_json FROM campaign_clocks WHERE campaign_id=?", (campaign_id,)).fetchone()
        secrets: dict[str, str] = {}
        clocks: list[dict[str, Any]] = []
        if sec_row:
            try:
                secrets = self._clean_secrets_dict(json.loads(sec_row["secrets_json"]))
            except (TypeError, json.JSONDecodeError):
                secrets = {}
        if clk_row:
            try:
                clocks = self._normalize_clock_list(json.loads(clk_row["clocks_json"]))
            except (TypeError, json.JSONDecodeError):
                clocks = []
        return secrets, clocks

    def _save_branch_private_state(
        self,
        campaign_id: str,
        message_id: str | None,
        parent_id: str | None,
        secrets: dict[str, str],
        clocks: list[dict[str, Any]],
    ) -> None:
        sec_json = json.dumps(self._clean_secrets_dict(secrets), ensure_ascii=False)
        clk_json = json.dumps(self._normalize_clock_list(clocks), ensure_ascii=False)
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if message_id:
                conn.execute(
                    """
                    INSERT INTO turn_gm_snapshots (message_id, campaign_id, parent_id, secrets_json, clocks_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        secrets_json=excluded.secrets_json,
                        clocks_json=excluded.clocks_json
                    """,
                    (message_id, campaign_id, parent_id, sec_json, clk_json),
                )
            else:
                conn.execute(
                    "INSERT INTO gm_secrets (campaign_id, secrets_json) VALUES (?, ?) "
                    "ON CONFLICT(campaign_id) DO UPDATE SET secrets_json=excluded.secrets_json",
                    (campaign_id, sec_json),
                )
                conn.execute(
                    "INSERT INTO campaign_clocks (campaign_id, clocks_json) VALUES (?, ?) "
                    "ON CONFLICT(campaign_id) DO UPDATE SET clocks_json=excluded.clocks_json",
                    (campaign_id, clk_json),
                )

    def _get_gm_secrets(self, campaign_id: str) -> dict[str, str]:
        leaf_id = self.tree.get_tree(campaign_id).get("active_leaf_id")
        secrets, _ = self._load_branch_private_state(campaign_id, leaf_id)
        return secrets

    def list_public_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        self.gameplay.campaign_context(campaign_id)
        target_leaf = leaf_id if leaf_id is not None else self.tree.get_tree(campaign_id).get("active_leaf_id")
        _, clocks = self._load_branch_private_state(campaign_id, target_leaf)
        return [c for c in clocks if c.get("visibility") != "secret"]

    def mutate_public_clock(self, campaign_id: str, body: dict[str, Any], leaf_id: str | None = None) -> list[dict[str, Any]]:
        self.gameplay.campaign_context(campaign_id)
        tree = self.tree.get_tree(campaign_id)
        target_leaf = leaf_id if leaf_id is not None else tree.get("active_leaf_id")
        secrets, clocks = self._load_branch_private_state(campaign_id, target_leaf)
        action = str(body.get("action") or "upsert").strip().lower()
        op: dict[str, Any]
        if action == "delete":
            op = {"id": body.get("id") or body.get("name"), "delete": True}
        elif action == "tick":
            op = {
                "id": body.get("id") or body.get("name"),
                "name": body.get("name"),
                "delta": body.get("delta", 1),
            }
        elif action == "upsert":
            op = {
                "id": body.get("id") or body.get("name"),
                "name": body.get("name"),
                "segments": body.get("segments", 4),
                "filled": body.get("filled", 0),
                "category": body.get("category", "heat"),
                "note": body.get("note", ""),
                "visibility": "public",
            }
        else:
            raise ValueError(f"Unsupported clock action: {action!r}")
        if not op.get("id") and not op.get("name"):
            raise ValueError("clock id or name is required")
        next_clocks, _ = self._apply_clock_ops(clocks, [op], allow_secret=False)
        parent_id = None
        if target_leaf:
            msg = self.tree.get_message(campaign_id, target_leaf)
            parent_id = msg["parent_id"] if msg else None
        self._save_branch_private_state(campaign_id, target_leaf, parent_id, secrets, next_clocks)
        if not target_leaf:
            self._save_branch_private_state(campaign_id, None, None, secrets, next_clocks)
        return [c for c in next_clocks if c.get("visibility") != "secret"]

    def seed_initial_gm_state(
        self,
        campaign_id: str,
        *,
        secrets: dict[str, str] | None = None,
        opening_clock: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Seed initial hidden GM secrets and/or opening public clock for a newly created campaign."""
        self.gameplay.campaign_context(campaign_id)
        cur_secrets, cur_clocks = self._load_branch_private_state(campaign_id, None)
        merged_secrets = self._merge_gm_secrets(cur_secrets, secrets or {})
        next_clocks = list(cur_clocks)
        if isinstance(opening_clock, dict) and str(opening_clock.get("name") or "").strip():
            op = {
                "id": opening_clock.get("id") or opening_clock.get("name"),
                "name": str(opening_clock["name"]).strip(),
                "segments": opening_clock.get("segments", 4),
                "filled": opening_clock.get("filled", 0),
                "category": opening_clock.get("category", "heat"),
                "note": str(opening_clock.get("note") or "").strip(),
                "visibility": "public",
            }
            next_clocks, _ = self._apply_clock_ops(next_clocks, [op], allow_secret=False)
        self._save_branch_private_state(campaign_id, None, None, merged_secrets, next_clocks)
        return {
            "clocks": [c for c in next_clocks if c.get("visibility") != "secret"],
            "secrets_count": len(merged_secrets),
        }

    def _get_compressed_count(self, campaign_id: str) -> int:
        with closing(self.gameplay.store._connect()) as conn:
            row = conn.execute(
                "SELECT compressed_count FROM campaign_compressions WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        return int(row["compressed_count"]) if row else 0

    def _set_compressed_count(self, campaign_id: str, leaf_id: str | None, count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO campaign_compressions (campaign_id, leaf_id, compressed_count, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    leaf_id=excluded.leaf_id,
                    compressed_count=excluded.compressed_count,
                    updated_at=excluded.updated_at
                """,
                (campaign_id, leaf_id, max(0, int(count)), now),
            )

    def _catalog_items(self) -> dict[str, dict[str, Any]]:
        if self._item_cache is not None:
            return self._item_cache
        if self.gameplay.rules_path and self.gameplay.rules_path.is_file():
            try:
                self._item_cache = sourcecatalog.items(self.gameplay.rules_path)
                return self._item_cache
            except ValueError:
                pass
        self._item_cache = {}
        return self._item_cache

    def _corebook_skills(self) -> dict[str, dict[str, Any]]:
        if self._skill_cache is not None:
            return self._skill_cache
        if self.gameplay.rules_path and self.gameplay.rules_path.is_file():
            try:
                self._skill_cache = sourcecatalog.skills(self.gameplay.rules_path)
                return self._skill_cache
            except ValueError:
                pass
        self._skill_cache = {}
        return self._skill_cache

    def _verify_skill(
        self, campaign_id: str, skill_name: str | None, requested_stat: str | None
    ) -> tuple[bool, str | None, str | None, dict[str, Any] | None]:
        """Validate proposed skill against Corebook or campaign homebrew skill entries."""
        if not skill_name:
            stat = requested_stat.upper() if isinstance(requested_stat, str) and requested_stat.upper() in STAT_NAMES else None
            return (stat is not None, None, stat, None)

        role_hit = _CANONICAL_ROLE_CHECKS.get(sourcecatalog._normalize(skill_name))
        if role_hit is not None:
            canonical_role, role_stat = role_hit
            return (True, canonical_role, role_stat, {"source": "corebook", "name": canonical_role, "stat": role_stat})

        core = self._corebook_skills()
        hit = sourcecatalog.lookup_skill(core, skill_name)
        if hit is not None:
            canonical = next(
                (k for k in core if sourcecatalog._normalize(k) == sourcecatalog._normalize(skill_name)),
                skill_name,
            )
            return (True, canonical, hit["stat"], {"source": "corebook", "name": canonical, **hit})

        homebrew_hits = search_library(
            self.gameplay.rules_path,
            q=skill_name,
            category="skill",
            campaign_path=self.gameplay.store.path,
            campaign_id=campaign_id,
            limit=10,
        )
        exact = next(
            (e for e in homebrew_hits if sourcecatalog._normalize(e["name"]) == sourcecatalog._normalize(skill_name)),
            None,
        )
        if exact is not None:
            entry_stat = str((exact.get("stats") or {}).get("stat") or requested_stat or "").upper()
            stat = entry_stat if entry_stat in STAT_NAMES else None
            return (stat is not None, exact["name"], stat, exact)
        return (False, skill_name, None, None)

    def _deduct_humanity(self, character_id: str, amount: int, reason: str, operation_id: str) -> dict[str, Any]:
        payload = _json({"action": "overclock_humanity", "character_id": character_id, "amount": amount, "reason": reason})
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self.gameplay.store._reject_roll_id(conn, operation_id)
            row = conn.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            before = self.gameplay.store._record(row)
            if before["humanity"] < amount:
                raise ValueError(f"{before['name']} lacks Humanity for Overclock (has {before['humanity']}, needs {amount})")
            after = dict(before, humanity=before["humanity"] - amount, revision=before["revision"] + 1)
            conn.execute(
                "UPDATE characters SET humanity=?, revision=? WHERE id=?",
                (after["humanity"], after["revision"], character_id),
            )
            conn.execute(
                "INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                (character_id, after["revision"], _json(before), _json(after), reason, operation_id, payload),
            )
            return {"before": before["humanity"], "after": after["humanity"], "revision": after["revision"], "character": after}

    def _solo_summary(self, ctx: dict[str, Any]) -> dict[str, Any]:
        runtime = (ctx.get("solo") or {}).get("runtime") or {}
        enc = runtime.get("encounter")
        chars_by_id = {c["id"]: c["name"] for c in ctx.get("characters") or []}
        enc_view = None
        if isinstance(enc, dict) and enc.get("active"):
            q = enc.get("queue") or []
            idx = enc.get("turn_index", 0)
            cur_id = q[idx] if isinstance(idx, int) and 0 <= idx < len(q) else None
            enc_view = {
                "active": True,
                "round": enc.get("round", 1),
                "current_actor": chars_by_id.get(cur_id, cur_id),
                "queue": [chars_by_id.get(cid, cid) for cid in q],
            }
        runs_view = {
            rid: {"connected": bool(r.get("connected")), "floor": r.get("current_floor_id"), "actions_remaining": r.get("actions_remaining")}
            for rid, r in (runtime.get("runs") or {}).items()
            if isinstance(r, dict) and r.get("connected")
        }
        clock_mins = int(runtime.get("clock_minutes") or 0)
        return {
            "clock_minutes": clock_mins,
            "clock_label": _format_clock_label(clock_mins),
            "encounter": enc_view,
            "active_runs": runs_view,
        }

    def _collect_citations(
        self,
        campaign_id: str,
        user_text: str,
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cit_limit = max(1, min(30, int(self.turn_settings.get("citation_limit", 4))))
        total_cap = max(8, cit_limit + 4)
        citations = search_library(
            self.gameplay.rules_path,
            q=user_text.strip()[:200],
            campaign_path=self.gameplay.store.path,
            campaign_id=campaign_id,
            strict_names=True,
            limit=cit_limit,
        )
        seen_ids = {c["id"] for c in citations}
        # Also resolve explicit [Category: Name] tags or campaign dossier names mentioned in state/summary.
        state_blob = "\n".join(
            [
                str(state.get("scene") or ""),
                str(state.get("summary") or ""),
                *(f"{k} {v}" for k, v in (state.get("npcs") or {}).items()),
                *(f"{k} {v}" for k, v in (state.get("discoveries") or {}).items()),
            ]
        )
        if state_blob.strip() or user_text.strip():
            ref_names = {sourcecatalog._normalize(m.group(2)) for m in _LIB_REF_RE.finditer(state_blob)}
            hay_norm = sourcecatalog._normalize(f"{user_text}\n{state.get('scene', '')}\n{state.get('summary', '')}")
            try:
                camp_entries = self.library.list_entries(campaign_id)
            except ValueError:
                camp_entries = []
            for entry in camp_entries:
                if entry["id"] in seen_ids:
                    continue
                norm_n = sourcecatalog._normalize(entry["name"])
                if norm_n in ref_names or (len(norm_n) >= 4 and norm_n in hay_norm):
                    citations.append(entry)
                    seen_ids.add(entry["id"])
                    if len(citations) >= total_cap:
                        break
        return citations[:total_cap]

    def _apply_character_update_op(
        self,
        campaign_id: str,
        actor_hint: Any,
        raw_changes: Any,
        reason: str,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Normalize and apply a character state patch via GameplayService."""
        live_chars = self.gameplay.campaign_context(campaign_id)["characters"]
        char = _resolve_character(actor_hint, live_chars)
        if char is None:
            return [], [f"Unknown character for state update: {actor_hint!r}"]
        if not isinstance(raw_changes, dict) or not raw_changes:
            return [], []

        raw_changes = dict(raw_changes)
        ip_entry = raw_changes.pop("ip", None)
        patches: list[dict[str, Any]] = []
        warnings: list[str] = []

        if ip_entry is not None:
            d = char.get("detail") or {}
            current_ip = int(((d.get("role_ext") or {}).get("ip")) or d.get("ip") or 0)
            try:
                if isinstance(ip_entry, dict):
                    delta = int(ip_entry.get("delta", ip_entry.get("amount", 0)))
                    if "target" in ip_entry:
                        delta = int(ip_entry["target"]) - current_ip
                else:
                    raw_ip = int(ip_entry)
                    if raw_ip > current_ip and current_ip > 0:
                        delta = raw_ip - current_ip
                    else:
                        delta = raw_ip
                if delta > 0:
                    ctx = self.gameplay.campaign_context(campaign_id)
                    solo_rev = int(ctx["solo"]["revision"])
                    self.gameplay.execute(
                        "role_action",
                        {
                            "character_id": char["id"],
                            "action": "award_ip",
                            "arguments": {"amount": delta, "reason": reason},
                            "expected_revision": solo_rev,
                            "reason": reason,
                            "operation_id": f"{operation_id}:ip",
                        },
                        campaign_id=campaign_id,
                    )
                    after_ip = current_ip + delta
                    patches.append(
                        {
                            "target": "character",
                            "character_id": char["id"],
                            "name": char["name"],
                            "before": {"ip": current_ip},
                            "after": {"ip": after_ip},
                            "reason": reason,
                        }
                    )
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped IP update: {exc}")

        changes, norm_notes = _normalize_character_changes(raw_changes, char)
        warnings.extend(norm_notes)
        if not changes:
            return patches, warnings

        if patches:
            refreshed_chars = self.gameplay.campaign_context(campaign_id)["characters"]
            refreshed = next((c for c in refreshed_chars if c["id"] == char["id"]), None)
            if refreshed:
                char = refreshed

        before_vals = {k: char.get(k) for k in changes}
        update_op_id = f"{operation_id}:state" if patches else operation_id
        try:
            updated = self.gameplay.execute(
                "update_character",
                {
                    "character_id": char["id"],
                    "expected_revision": char["revision"],
                    "changes": changes,
                    "reason": reason,
                    "operation_id": update_op_id,
                },
                campaign_id=campaign_id,
            )["result"]
            patches.append(
                {
                    "target": "character",
                    "character_id": char["id"],
                    "name": char["name"],
                    "before": before_vals,
                    "after": {k: updated.get(k) for k in changes},
                    "reason": reason,
                }
            )
            return patches, warnings
        except (TypeError, ValueError) as exc:
            warnings.append(f"Skipped character update: {exc}")
            return patches, warnings

    def _execute_solo_op(
        self,
        campaign_id: str,
        op: dict[str, Any],
        default_actor: str | None,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        action = str(op.get("action") or op.get("type") or "").strip()
        if action == "update_character":
            raw_changes = op.get("changes")
            if not isinstance(raw_changes, dict):
                raw_changes = op.get("arguments") if isinstance(op.get("arguments"), dict) else {
                    k: v for k, v in op.items()
                    if k not in {"action", "type", "subaction", "mode", "actor", "reason"}
                }
            return self._apply_character_update_op(
                campaign_id,
                op.get("actor") or default_actor,
                raw_changes,
                str(op.get("reason") or "GM turn state update"),
                operation_id,
            )
        allowed = {
            "advance_time",
            "health_action",
            "economy_action",
            "gear_action",
            "role_action",
            "substance_action",
            "start_encounter",
            "encounter_action",
            "end_encounter",
        }
        if action not in allowed:
            return [], [f"Ignored unsupported solo_op action: {action!r}"]

        ctx = self.gameplay.campaign_context(campaign_id)
        live_chars = ctx["characters"]
        solo_rev = int(ctx["solo"]["revision"])
        if isinstance(op.get("arguments"), dict):
            raw_args = dict(op["arguments"])
        else:
            raw_args = {
                k: v
                for k, v in op.items()
                if k not in {"action", "type", "subaction", "mode", "actor", "reason"}
            }
        reason = str(op.get("reason") or f"GM solo action: {action}").strip()
        actor_hint = op.get("actor") or raw_args.pop("actor", None) or default_actor
        actor_char = _resolve_character(actor_hint, live_chars)

        before_clock = int(ctx["solo"]["runtime"].get("clock_minutes") or 0)
        if action == "start_encounter":
            cur_enc = ctx["solo"]["runtime"].get("encounter")
            if isinstance(cur_enc, dict) and cur_enc.get("active"):
                return [], []
            raw_candidates = raw_args.get("character_ids") or op.get("actors") or raw_args.get("actors")
            ids: list[str] = []
            seen_ids: set[str] = set()
            valid_ids = {c["id"] for c in live_chars}
            if isinstance(raw_candidates, list):
                for entry in raw_candidates:
                    if isinstance(entry, str) and entry in valid_ids and entry not in seen_ids:
                        ids.append(entry)
                        seen_ids.add(entry)
                    else:
                        matched = _resolve_character(entry, live_chars)
                        if matched is not None and matched["id"] not in seen_ids:
                            ids.append(matched["id"])
                            seen_ids.add(matched["id"])
            if not ids:
                ids = [actor_char["id"]] if actor_char is not None else [c["id"] for c in live_chars]
            if not ids:
                return [], ["Skipped solo action (start_encounter): no campaign members attached"]
            raw_args = {"character_ids": ids}
        elif action == "advance_time":
            elapsed_raw = op.get("elapsed_minutes", raw_args.get("elapsed_minutes", 0))
            try:
                elapsed_val = int(elapsed_raw)
            except (TypeError, ValueError):
                return [], [f"Invalid elapsed_minutes for advance_time: {elapsed_raw!r}"]
            raw_args = {"elapsed_minutes": elapsed_val}
        elif action == "end_encounter":
            raw_args = {}
        else:
            if action in {"economy_action", "gear_action", "role_action"}:
                if "character_id" not in raw_args:
                    if actor_char is None:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"]
                    raw_args["character_id"] = actor_char["id"]
            else:
                if "actor_id" not in raw_args:
                    if actor_char is None:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"]
                    raw_args["actor_id"] = actor_char["id"]

            if "target" in raw_args and "target_id" not in raw_args:
                tgt = _resolve_character(raw_args.pop("target"), live_chars)
                if tgt is not None:
                    raw_args["target_id"] = tgt["id"]

            subaction = op.get("subaction") or op.get("mode") or raw_args.get("action")
            nested_args = dict(raw_args.get("arguments")) if isinstance(raw_args.get("arguments"), dict) else None
            if nested_args is None:
                # Support flat arguments from model JSON by nesting remaining non-envelope keys.
                envelope_keys = {"character_id", "actor_id", "action", "subaction", "arguments"}
                nested_args = {k: v for k, v in raw_args.items() if k not in envelope_keys}
                raw_args = {k: v for k, v in raw_args.items() if k in {"character_id", "actor_id"}}
                raw_args["arguments"] = nested_args
            if subaction:
                raw_args["action"] = str(subaction)

            if action == "economy_action" and raw_args.get("action") == "job_reward":
                e_args = raw_args.setdefault("arguments", {})
                if not isinstance(e_args.get("contract_reason"), str) or not e_args["contract_reason"].strip():
                    e_args["contract_reason"] = reason

            if action == "role_action" and raw_args.get("action") == "award_ip":
                r_args = raw_args.setdefault("arguments", {})
                if "amount" not in r_args and "ip" in r_args:
                    try:
                        r_args["amount"] = int(r_args["ip"])
                    except (TypeError, ValueError):
                        pass
                if not isinstance(r_args.get("reason"), str) or not r_args["reason"].strip():
                    r_args["reason"] = reason

            if action == "gear_action":
                g_args = raw_args.setdefault("arguments", {})
                wanted_item = g_args.pop("item", None) or g_args.get("item_id")
                catalog = self._catalog_items()
                if isinstance(wanted_item, str) and wanted_item and wanted_item not in catalog:
                    norm_w = sourcecatalog._normalize(wanted_item)
                    matched = next(
                        (item_id for item_id, item in catalog.items() if sourcecatalog._normalize(item.get("name", "")) == norm_w),
                        None,
                    )
                    if matched:
                        g_args["item_id"] = matched

        before_map = {c["id"]: c for c in live_chars}
        payload_args = {**raw_args, "expected_revision": solo_rev, "reason": reason, "operation_id": operation_id}
        try:
            res = self.gameplay.execute(action, payload_args, campaign_id=campaign_id)["result"]
        except (TypeError, ValueError, KeyError) as exc:
            return [], [f"Skipped solo action ({action}): {exc}"]

        if isinstance(res, dict) and res.get("committed") is False:
            ruling_reason = (res.get("result") or {}).get("reason") or "Requires manual tabletop ruling."
            return [], [f"Solo action ({action}) deferred: {ruling_reason}"]

        patches: list[dict[str, Any]] = []
        after_chars = (res.get("characters") if isinstance(res, dict) else None) or []
        for after_c in after_chars:
            cid = after_c.get("id")
            before_c = before_map.get(cid)
            if not before_c:
                continue
            b_diff: dict[str, Any] = {}
            a_diff: dict[str, Any] = {}
            for fld in ("hp", "money", "humanity", "luck_remaining", "inventory"):
                if before_c.get(fld) != after_c.get(fld):
                    b_diff[fld] = before_c.get(fld)
                    a_diff[fld] = after_c.get(fld)
            b_d = before_c.get("detail") or {}
            a_d = after_c.get("detail") or {}
            b_ip = int(((b_d.get("role_ext") or {}).get("ip")) or b_d.get("ip") or 0)
            a_ip = int(((a_d.get("role_ext") or {}).get("ip")) or a_d.get("ip") or 0)
            if b_ip != a_ip:
                b_diff["ip"] = b_ip
                a_diff["ip"] = a_ip
            if b_diff:
                patches.append(
                    {
                        "target": "character",
                        "character_id": cid,
                        "name": after_c.get("name"),
                        "before": b_diff,
                        "after": a_diff,
                        "reason": reason,
                    }
                )
        if action == "advance_time" and isinstance(res, dict):
            time_res = res.get("result") if isinstance(res.get("result"), dict) else res
            b_m = int(time_res["before_minutes"]) if time_res.get("before_minutes") is not None else before_clock
            a_m = int(time_res["after_minutes"]) if time_res.get("after_minutes") is not None else (b_m + elapsed_val)
            patches.append(
                {
                    "target": "solo",
                    "before": {"time": _format_clock_label(b_m)},
                    "after": {"time": _format_clock_label(a_m)},
                    "reason": reason,
                }
            )
        elif action in {"health_action", "economy_action"}:
            after_clock = int(self.gameplay.campaign_context(campaign_id)["solo"]["runtime"].get("clock_minutes") or 0)
            if after_clock > before_clock:
                patches.append(
                    {
                        "target": "solo",
                        "before": {"time": _format_clock_label(before_clock)},
                        "after": {"time": _format_clock_label(after_clock)},
                        "reason": reason,
                    }
                )
        if not patches:
            patches.append(
                {
                    "target": "solo",
                    "before": {"solo_revision": solo_rev},
                    "after": {"solo_revision": res.get("revision", solo_rev + 1) if isinstance(res, dict) else solo_rev + 1, "action": action},
                    "reason": reason,
                }
            )
        return patches, []

    def preprocess(
        self,
        campaign_id: str,
        user_text: str,
        *,
        parent_id: str | None = None,
        branch_from_root: bool = False,
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        """Gather dual memory, branch secrets/clocks, pre-rolled server dice pool, rulebook cards, and branch history."""
        op_base = turn_id or uuid.uuid4().hex[:12]
        context = self.gameplay.campaign_context(campaign_id)
        tree_state = self.tree.get_tree(campaign_id)
        if branch_from_root:
            branch_parent = None
            branch = []
        elif parent_id is None and tree_state["active_leaf_id"] is not None:
            branch_parent = tree_state["active_leaf_id"]
            branch = list(tree_state["active_branch"])
        elif parent_id is not None:
            branch_parent = parent_id
            branch = self.tree.get_branch_to(campaign_id, parent_id)
        else:
            branch_parent = None
            branch = []

        branch_secrets, branch_clocks = self._load_branch_private_state(campaign_id, branch_parent)

        d10_pool = self.gameplay.execute(
            "roll_dice",
            {"count": 3, "sides": 10, "operation_id": f"{op_base}:pool:d10", "reason": "Turn server d10 entropy pool"},
            campaign_id=campaign_id,
        )["result"]
        d6_pool = self.gameplay.execute(
            "roll_dice",
            {"count": 4, "sides": 6, "operation_id": f"{op_base}:pool:d6", "reason": "Turn server d6 entropy pool"},
            campaign_id=campaign_id,
        )["result"]

        citations = self._collect_citations(campaign_id, user_text, context["campaign"]["state"])
        compressed_count = self._get_compressed_count(campaign_id)
        turns_since_compress = max(0, len(branch) - compressed_count)
        threshold = max(4, int(self.turn_settings.get("compression_threshold", _COMPRESSION_MESSAGE_THRESHOLD)))
        return {
            "turn_id": op_base,
            "context": context,
            "parent_id": branch_parent,
            "branch": branch,
            "gm_secrets": branch_secrets,
            "clocks": branch_clocks,
            "dice_pool": {"d10": d10_pool["dice"], "d6": d6_pool["dice"]},
            "citations": citations,
            "compression_recommended": bool(self.turn_settings.get("auto_compress_prompt", True)) and turns_since_compress >= threshold,
        }

    def _build_planner_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        *,
        overclock: bool,
        luck_spend: int = 0,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = prep["context"]
        state = ctx["campaign"]["state"]
        chars_summary = [_summarize_character(c) for c in ctx["characters"]]
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
        solo_summary = self._solo_summary(ctx)
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
        style_key = str(self.turn_settings.get("gm_style") or "grounded")
        style_hint = _GM_STYLE_HINTS.get(style_key, _GM_STYLE_HINTS["grounded"])
        default_step = int(self.turn_settings.get("default_time_step_minutes") or 0)
        world_prefix = (self.prompt_settings.get("world_rules_prefix") or "").strip()
        dialogue_rules = (self.prompt_settings.get("player_dialogue_rules") or "").strip()
        multiplayer_rules = (self.prompt_settings.get("multiplayer_rules") or "").strip()
        planner_extra = (self.prompt_settings.get("planner_extra") or "").strip()
        planner_core = (self.prompt_settings.get("planner_core_rules") or "").strip()
        allow_homebrew = bool(self.turn_settings.get("allow_ai_homebrew", True))
        custom_lines = ""
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
            '  "state_ops": [{"type": "update_campaign", "changes": {"scene": "5th & Main, Rain-slicked street", "summary": "...", "npcs": {"NPC Name": "Role, location — Disposition (Neutral 0); tie-in"}, "objectives": {"Clear your name": "Active"}, "discoveries": {"Topic": "Observed clue"}}, "reason": "..."}],\n'
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
            f"{speaker_line}"
            f"{guidance_line}"
            f"Overclock requested by player: {overclock}.\n"
            f"Pre-committed LUCK by player: {max(0, int(luck_spend))}.\n"
            f"Pre-rolled server dice pool available if needed: {json.dumps(prep['dice_pool'])}.\n"
            f"Narrative Memory: {json.dumps(state)}\n"
            f"Solo Engine State: {json.dumps(solo_summary)}\n"
            f"Active Clocks (secret clocks are GM-only): {json.dumps(clocks)}\n"
            f"Hidden GM Secrets (NEVER expose in state_ops unless earned): {json.dumps(gm_secrets)}\n"
            f"Characters: {json.dumps(chars_summary)}\n"
            f"Retrieved Library Entries: {json.dumps(cards)}"
        )
        hist_win = max(4, min(200, int(self.turn_settings.get("history_window", 14))))
        msgs = [{"role": "system", "content": system_prompt}]
        for item in prep["branch"][-hist_win:]:
            item_speaker = (item.get("metadata") or {}).get("speaker_name")
            content = self._format_player_message(item["content"], item_speaker) if item["role"] == "user" else item["content"]
            msgs.append({"role": item["role"], "content": content})
        msgs.append({"role": "user", "content": self._format_player_message(user_text, speaker_name)})
        return msgs

    def _format_player_message(self, text: str, speaker_name: str | None = None) -> str:
        clean_text = text.strip() if isinstance(text, str) else ""
        speaker = speaker_name.strip() if isinstance(speaker_name, str) and speaker_name.strip() else ""
        if not speaker:
            return clean_text
        tpl = (self.prompt_settings.get("player_message_template") or "").strip() or _DEFAULT_PLAYER_MESSAGE_TEMPLATE
        if "{message}" not in tpl:
            tpl = f"{tpl} {{message}}".strip()
        return tpl.replace("{speaker}", speaker).replace("{message}", clean_text)

    @staticmethod
    def _format_roll_ledger(executed: dict[str, Any], *, tagged_single_pass: bool = False) -> str:
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

    def _build_narrator_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        executed: dict[str, Any],
        *,
        tagged_single_pass: bool = False,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = self.gameplay.campaign_context(prep["context"]["campaign"]["id"])
        state = ctx["campaign"]["state"]
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
        gm_secrets = executed.get("gm_secrets", prep.get("gm_secrets") or {})
        clocks = executed.get("clocks", prep.get("clocks") or [])
        solo_summary = self._solo_summary(ctx)
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
        persona = (self.prompt_settings.get("system_persona") or "").strip() or _DEFAULT_NARRATOR_PERSONA
        style_key = str(self.turn_settings.get("gm_style") or "grounded")
        length_key = str(self.turn_settings.get("narrator_length") or "standard")
        style_hint = _GM_STYLE_HINTS.get(style_key, _GM_STYLE_HINTS["grounded"])
        length_hint = _LENGTH_HINTS.get(length_key, _LENGTH_HINTS["standard"])
        world_prefix = (self.prompt_settings.get("world_rules_prefix") or "").strip()
        dialogue_rules = (self.prompt_settings.get("player_dialogue_rules") or "").strip()
        player_narration_rules = (self.prompt_settings.get("player_narration_rules") or "").strip()
        multiplayer_rules = (self.prompt_settings.get("multiplayer_rules") or "").strip()
        narrator_extra = (self.prompt_settings.get("narrator_extra") or "").strip()
        narrator_core = (self.prompt_settings.get("narrator_core_rules") or "").strip()
        enable_highlights = bool(self.turn_settings.get("enable_highlights", True))
        custom_sections = ""
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
            f"Tone & Pacing: {style_hint} {length_hint}"
            f"{custom_sections}"
            f"{core_block}"
            f"{flair_line}"
            f"- Narrative State: {json.dumps(state)}\n"
            f"- Solo Engine State: {json.dumps(solo_summary)}\n"
            f"- Active Clocks (secret clocks are GM eyes only): {json.dumps(clocks)}\n"
            f"- Hidden GM Secrets (GM eyes only—NEVER leak unobservably or give away for free): {json.dumps(gm_secrets)}\n"
            f"- Characters: {json.dumps(narrator_chars)}"
            f"{party_line}"
            f"{speaker_line}"
            f"{guidance_line}\n"
            f"- Rulebook Library Context: {json.dumps(cards)}\n"
            f"- Authoritative Dice Roll Ledger:\n{self._format_roll_ledger(executed, tagged_single_pass=tagged_single_pass)}\n"
            f"- Locked Engine Outcomes: {json.dumps(executed['outcomes'])}"
        )
        if tagged_single_pass:
            system_prompt += (
                "\nAt the very end of your reply, if rules checks, state updates, or homebrew additions are needed, "
                "append <gm_ops>{...JSON plan...}</gm_ops>."
            )
        hist_win = max(4, min(500, int(self.turn_settings.get("history_window", 14))))
        msgs = [{"role": "system", "content": system_prompt}]
        for item in prep["branch"][-hist_win:]:
            item_speaker = (item.get("metadata") or {}).get("speaker_name")
            content = self._format_player_message(item["content"], item_speaker) if item["role"] == "user" else item["content"]
            msgs.append({"role": item["role"], "content": content})
        msgs.append({"role": "user", "content": self._format_player_message(user_text, speaker_name)})
        return msgs

    def _build_chronicler_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        narrated_text: str,
        executed: dict[str, Any],
        *,
        speaker: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        ctx = prep["context"]
        state = ctx["campaign"]["state"]
        solo_summary = self._solo_summary(ctx)
        gm_secrets = executed.get("gm_secrets", prep.get("gm_secrets") or {})
        clocks = executed.get("clocks", prep.get("clocks") or [])
        chron_extra = (self.prompt_settings.get("chronicler_extra") or "").strip()
        chron_core = (self.prompt_settings.get("chronicler_core_rules") or "").strip()
        extra_block = f"\nCustom Chronicler Instructions:\n{chron_extra}\n" if chron_extra else "\n"
        core_block = f"Rules:\n{chron_core}\n" if chron_core else ""
        homebrew_note = "" if self.turn_settings.get("allow_ai_homebrew", True) else "- Leave `new_homebrew` empty (`[]`).\n"
        speaker_name = speaker["name"] if speaker and speaker.get("name") else None
        formatted_user = self._format_player_message(user_text, speaker_name)
        system_prompt = (
            "You are the Cyberpunk RED Post-Turn Chronicler. Compare the player turn and the actual narrated GM prose against the current state, "
            "and record ONLY facts, NPCs, clues, scene transitions, or time elapsed that appeared in the narrated prose and are NOT yet captured.\n"
            f"{extra_block}"
            "Return ONLY a single valid JSON object with no markdown:\n"
            "{\n"
            '  "time_elapsed_minutes": 0,\n'
            '  "state_ops": [{"type": "update_campaign", "changes": {"scene": "...", "npcs": {"Name": "Role, location — Disposition (Neutral 0); tie-in"}, "discoveries": {"Topic": "PC-observed clue"}, "objectives": {"Obj": "Active|Completed"}, "unresolved": {"Thread": "..."}}, "reason": "..."}],\n'
            '  "clock_ops": [{"id": "...", "name": "...", "delta": 0, "segments": 4, "category": "heat|obligation|deadline|faction|recovery", "visibility": "public|secret", "note": "..."}],\n'
            '  "gm_secrets": {"secret_key": "unrevealed off-screen motive/consequence or null if revealed in prose"},\n'
            '  "new_homebrew": [{"name": "...", "category": "npc|location|faction|gear|program|rule|ammo|attachment|vehicle|drug|service|housing|mook|encounter|streetslang|screamsheet", "summary": "1-sentence player-known summary", "description": "concise factual entry", "stats": {...}}]\n'
            "}\n"
            f"{core_block}"
            f"{homebrew_note}"
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

    def _execute_plan(
        self,
        campaign_id: str,
        plan: dict[str, Any],
        prep: dict[str, Any],
        *,
        overclock: bool = False,
        luck_spend: int = 0,
        default_actor: str | None = None,
        op_prefix: str | None = None,
        allow_checks: bool = True,
        allow_solo: bool = True,
    ) -> dict[str, Any]:
        turn_id = op_prefix or prep["turn_id"]
        rolls: list[dict[str, Any]] = []
        blocked_checks: list[str] = []
        patches: list[dict[str, Any]] = []
        added_library: list[dict[str, Any]] = []
        warnings: list[str] = []

        # 1. Create any AI-proposed campaign homebrew entries first so skill checks can reference new skills.
        raw_homebrew = (plan.get("new_homebrew") or []) if self.turn_settings.get("allow_ai_homebrew", True) else []
        for idx, hb in enumerate(raw_homebrew):
            if not isinstance(hb, dict):
                continue
            try:
                raw_cat = hb.get("category")
                norm_cat = normalize_category(str(raw_cat)) if raw_cat else "gear"
                entry = self.library.add_entry(
                    campaign_id,
                    name=str(hb.get("name") or ""),
                    category=norm_cat or "gear",
                    summary=str(hb.get("summary") or ""),
                    description=str(hb.get("description") or ""),
                    stats=hb.get("stats") if isinstance(hb.get("stats"), dict) else {},
                    tags=hb.get("tags") if isinstance(hb.get("tags"), list) else [],
                    created_by="ai",
                    operation_id=f"{turn_id}:hb:{idx}",
                )
                added_library.append(entry)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped invalid homebrew '{hb.get('name', '?')}': {exc}")

        # Refresh characters snapshot helper
        def current_chars() -> list[dict[str, Any]]:
            return self.gameplay.campaign_context(campaign_id)["characters"]

        # 2. Resolve checks with fuzzy actor matching + entity hallucination guard + Overclock & pre-roll LUCK support.
        planned_checks = [chk for chk in (plan.get("checks") or []) if isinstance(chk, dict)] if allow_checks else []
        requested_luck = max(0, int(luck_spend or 0))
        luck_applied = False

        for idx, chk in enumerate(planned_checks):
            live_chars = current_chars()
            char = _resolve_character(chk.get("actor") or default_actor, live_chars)
            if char is None:
                msg = f"Unknown character for check: {chk.get('actor')!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue
            skill_ok, resolved_skill, resolved_stat, _ = self._verify_skill(
                campaign_id, chk.get("skill"), chk.get("stat")
            )
            if not skill_ok or not resolved_stat:
                msg = f"Blocked unverified skill/stat in check: {chk.get('skill')!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue
            try:
                dv = int(chk.get("dv", 13))
                modifier = int(chk.get("modifier", 0))
                luck = max(0, int(chk.get("luck", 0)))
            except (TypeError, ValueError):
                warnings.append("Invalid numeric parameters in planned skill check")
                continue

            if requested_luck > 0 and not luck_applied and (not default_actor or char["id"] == default_actor or char["name"] == default_actor or idx == 0):
                avail = int(char.get("luck_remaining", 0))
                applied = min(max(luck, requested_luck), avail)
                if applied < requested_luck:
                    warnings.append(f"Clamped committed LUCK for {char['name']} to available pool ({avail}).")
                luck = applied
                luck_applied = True

            use_overclock = bool(chk.get("overclock")) or (overclock and idx == 0)
            expected_rev = int(char["revision"])
            if use_overclock:
                try:
                    oc = self._deduct_humanity(
                        char["id"],
                        2,
                        reason=f"Overclock bonus for {resolved_skill or resolved_stat}",
                        operation_id=f"{turn_id}:oc:{idx}",
                    )
                    expected_rev = int(oc["revision"])
                    modifier += 2
                    patches.append(
                        {
                            "target": "character",
                            "character_id": char["id"],
                            "name": char["name"],
                            "before": {"humanity": oc["before"]},
                            "after": {"humanity": oc["after"]},
                            "reason": "Overclock (-2 Humanity for +2 Check Bonus)",
                        }
                    )
                except ValueError as exc:
                    warnings.append(str(exc))

            try:
                res = self.gameplay.execute(
                    "skill_check",
                    {
                        "character_id": char["id"],
                        "expected_revision": expected_rev,
                        "stat": resolved_stat,
                        "skill": resolved_skill,
                        "dv": dv,
                        "modifier": modifier,
                        "luck": luck,
                        "reason": str(chk.get("reason") or f"{resolved_skill or resolved_stat} check"),
                        "operation_id": f"{turn_id}:chk:{idx}",
                    },
                    campaign_id=campaign_id,
                )["result"]
                dice_vals = res.get("dice") or []
                rolls.append(
                    {
                        "actor": char["name"],
                        "character_id": char["id"],
                        "skill": resolved_skill,
                        "stat": resolved_stat,
                        "dv": dv,
                        "modifier": modifier,
                        "luck_spent": luck,
                        "overclock": use_overclock,
                        "die": dice_vals[0] if dice_vals else None,
                        "explosion": res.get("critical_adjustment", 0),
                        **res,
                    }
                )
            except ValueError as exc:
                warnings.append(f"Check failed validation: {exc}")

        # 3. Execute explicit state_ops through GameplayService with before/after snapshot capture.
        for idx, op in enumerate(plan.get("state_ops") or []):
            if not isinstance(op, dict):
                continue
            op_type = op.get("type")
            reason = str(op.get("reason") or "GM turn state update")
            if op_type == "update_character":
                c_patches, c_warns = self._apply_character_update_op(
                    campaign_id,
                    op.get("actor") or default_actor,
                    op.get("changes"),
                    reason,
                    f"{turn_id}:char:{idx}",
                )
                patches.extend(c_patches)
                warnings.extend(c_warns)
            elif op_type == "update_campaign":
                raw_changes = op.get("changes")
                if not isinstance(raw_changes, dict) or not raw_changes:
                    continue
                live_camp = self.gameplay.campaign_context(campaign_id)["campaign"]
                changes, norm_notes = _normalize_campaign_changes(raw_changes, live_camp["state"])
                warnings.extend(norm_notes)
                if not changes:
                    continue
                before_vals = {k: live_camp["state"].get(k) for k in changes}
                try:
                    updated = self.gameplay.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": live_camp["revision"],
                            "changes": changes,
                            "reason": reason,
                            "operation_id": f"{turn_id}:camp:{idx}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                    patches.append(
                        {
                            "target": "campaign",
                            "campaign_id": campaign_id,
                            "before": before_vals,
                            "after": {k: updated["state"].get(k) for k in changes},
                            "reason": reason,
                        }
                    )
                except (TypeError, ValueError) as exc:
                    warnings.append(f"Skipped campaign update: {exc}")

        # 4. Execute deterministic SoloService operations (economy, gear, health, encounter).
        solo_time_advanced = False
        if allow_solo:
            for idx, sop in enumerate(plan.get("solo_ops") or []):
                if not isinstance(sop, dict):
                    continue
                if str(sop.get("action") or sop.get("type") or "").strip() == "advance_time" or (
                    str(sop.get("subaction") or sop.get("mode") or sop.get("action") or "").strip()
                    in {"rest", "treat_injury", "therapy", "hustle"}
                ):
                    solo_time_advanced = True
                s_patches, s_warns = self._execute_solo_op(
                    campaign_id, sop, default_actor, operation_id=f"{turn_id}:solo:{idx}"
                )
                patches.extend(s_patches)
                warnings.extend(s_warns)

        # 4b. Sync opening wall-clock time when clock_minutes == 0 and Planner parsed a start_time (e.g. "22:15").
        if allow_solo and plan.get("start_time"):
            cur_clock = int(self.gameplay.campaign_context(campaign_id)["solo"]["runtime"].get("clock_minutes") or 0)
            start_mins = _parse_clock_minutes(plan.get("start_time"))
            if cur_clock == 0 and start_mins is not None and start_mins > 0:
                st_patches, st_warns = self._execute_solo_op(
                    campaign_id,
                    {"action": "advance_time", "elapsed_minutes": start_mins, "reason": f"Scene opening time ({_format_clock_label(start_mins)})"},
                    default_actor,
                    operation_id=f"{turn_id}:start_time",
                )
                patches.extend(st_patches)
                warnings.extend(st_warns)

        # 4c. Advance campaign clock when time_elapsed_minutes is specified (or default fallback configured).
        raw_elapsed = plan.get("time_elapsed_minutes")
        if (raw_elapsed is None or raw_elapsed == 0) and allow_solo:
            fallback_step = int(self.turn_settings.get("default_time_step_minutes") or 0)
            if fallback_step > 0:
                raw_elapsed = fallback_step
        if (
            not solo_time_advanced
            and not isinstance(raw_elapsed, bool)
            and isinstance(raw_elapsed, (int, float))
            and int(raw_elapsed) > 0
        ):
            mins = min(43200, int(raw_elapsed))
            t_patches, t_warns = self._execute_solo_op(
                campaign_id,
                {"action": "advance_time", "elapsed_minutes": mins, "reason": f"Scene time elapsed (+{mins}m)"},
                default_actor,
                operation_id=f"{turn_id}:time",
            )
            patches.extend(t_patches)
            warnings.extend(t_warns)

        # 5. Advance branch-scoped GM secrets & world clocks without exposing private data in patches.
        next_secrets = self._merge_gm_secrets(prep.get("gm_secrets") or {}, plan.get("gm_secrets"))
        next_clocks, public_clock_changes = self._apply_clock_ops(
            prep.get("clocks") or [], plan.get("clock_ops"), allow_secret=True
        )
        for c_diff in public_clock_changes:
            patches.append(
                {
                    "target": "campaign",
                    "campaign_id": campaign_id,
                    "before": {f"Clock ({c_diff['clock']})": c_diff["before"]},
                    "after": {f"Clock ({c_diff['clock']})": c_diff["after"]},
                    "reason": f"Updated clock {c_diff['clock']}",
                }
            )

        return {
            "rolls": rolls,
            "patches": patches,
            "library_added": added_library,
            "warnings": warnings,
            "gm_secrets": next_secrets,
            "clocks": next_clocks,
            "outcomes": {
                "rolls": [
                    {
                        "actor": r["actor"],
                        "skill": r["skill"],
                        "stat": r["stat"],
                        "reason": r.get("reason"),
                        "base": r.get("base"),
                        "dice": r.get("dice"),
                        "die": r.get("die"),
                        "explosion": r.get("explosion", 0),
                        "modifier": r.get("modifier", 0),
                        "total": r.get("total"),
                        "dv": r["dv"],
                        "wound_modifier": r.get("wound_modifier", 0),
                        "luck_spent": r.get("luck_spent", 0),
                        "success": r.get("success"),
                        "critical": (
                            "critical_success"
                            if (r.get("explosion") or 0) > 0
                            else ("fumble" if (r.get("explosion") or 0) < 0 else None)
                        ),
                    }
                    for r in rolls
                ],
                "blocked_checks": blocked_checks,
                "unspent_luck_requested": requested_luck if (requested_luck > 0 and not luck_applied) else 0,
                "patches": patches,
                "library_added": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in added_library],
                "gm_notes": str(plan.get("gm_notes") or ""),
            },
        }

    async def _stream_turn_from_user_msg(
        self,
        campaign_id: str,
        user_msg: dict[str, Any],
        prep: dict[str, Any],
        *,
        overclock: bool,
        luck_spend: int = 0,
        active_mode: str,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        user_text = user_msg["content"]
        default_actor = speaker.get("id") or speaker.get("name") if speaker else None
        yield {"event": "rule_citation", "data": {"entries": prep["citations"], "dice_pool": prep["dice_pool"]}}

        raw_chunks: list[str] = []
        if active_mode == "two_pass":
            planner_msgs = self._build_planner_messages(
                prep,
                user_text,
                overclock=overclock,
                luck_spend=luck_spend,
                speaker=speaker,
                guidance=guidance,
            )
            planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
            raw_plan = await self.llm.complete(planner_msgs, temperature=planner_temp, json_mode=True)
            plan = extract_gm_plan(raw_plan)
            executed = self._execute_plan(
                campaign_id,
                plan,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                default_actor=default_actor,
            )
            if not plan and (not isinstance(raw_plan, str) or raw_plan.strip() != "{}"):
                executed["warnings"].append("Planner pass returned empty or unparseable output; pre-turn operations were skipped.")

            for r in executed["rolls"]:
                yield {"event": "dice_roll", "data": r}
            for p in executed["patches"]:
                yield {"event": "state_patch", "data": p}
            for entry in executed["library_added"]:
                yield {"event": "library_added", "data": entry}
            for w in executed["warnings"]:
                yield {"event": "warning", "data": {"message": w}}

            narrator_msgs = self._build_narrator_messages(
                prep, user_text, executed, tagged_single_pass=False, speaker=speaker, guidance=guidance
            )
            narrator_kwargs = self._thinking_kwargs_for_pass(self.llm.stream, disable_in_balanced=True)
            async for delta in self.llm.stream(narrator_msgs, **narrator_kwargs):
                raw_chunks.append(delta)
                yield {"event": "text_delta", "data": {"delta": delta}}
            raw_text = "".join(raw_chunks)
            clean_text = strip_gm_tags(raw_text)
        else:
            empty_exec = {"rolls": [], "patches": [], "library_added": [], "warnings": [], "outcomes": {}}
            msgs = self._build_narrator_messages(
                prep, user_text, empty_exec, tagged_single_pass=True, speaker=speaker, guidance=guidance
            )
            emitted_len = 0
            async for delta in self.llm.stream(msgs):
                raw_chunks.append(delta)
                joined = "".join(raw_chunks)
                safe = _TRAILING_PARTIAL_TAG_RE.sub("", strip_gm_tags(joined))
                if len(safe) > emitted_len:
                    new_piece = safe[emitted_len:]
                    emitted_len = len(safe)
                    yield {"event": "text_delta", "data": {"delta": new_piece}}
            raw_text = "".join(raw_chunks)
            plan = extract_gm_plan(raw_text)
            executed = self._execute_plan(
                campaign_id,
                plan,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                default_actor=default_actor,
            )
            clean_text = strip_gm_tags(raw_text)
            if len(clean_text) > emitted_len:
                yield {"event": "text_delta", "data": {"delta": clean_text[emitted_len:]}}
            for r in executed["rolls"]:
                yield {"event": "dice_roll", "data": r}
            for p in executed["patches"]:
                yield {"event": "state_patch", "data": p}
            for entry in executed["library_added"]:
                yield {"event": "library_added", "data": entry}
            for w in executed["warnings"]:
                yield {"event": "warning", "data": {"message": w}}

        # Optional 3rd pass (Post-Turn Chronicler) when enabled and using OpenAI-compatible or opted-in multi-call adapters.
        chronicler_allowed = bool(self.turn_settings.get("enable_chronicler", True))
        use_chronicler = (
            chronicler_allowed
            and bool(getattr(self.llm, "enable_multi_call", isinstance(self.llm, OpenAICompatibleLLM)))
            and bool(clean_text.strip())
        )
        if use_chronicler:
            try:
                chron_ctx = self.gameplay.campaign_context(campaign_id)
                chron_prep = {
                    **prep,
                    "context": chron_ctx,
                    "gm_secrets": executed["gm_secrets"],
                    "clocks": executed["clocks"],
                }
                chron_msgs = self._build_chronicler_messages(chron_prep, user_text, clean_text, executed, speaker=speaker)
                chron_kwargs = self._thinking_kwargs_for_pass(self.llm.complete, disable_in_balanced=True)
                planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
                raw_chron = await self.llm.complete(chron_msgs, temperature=planner_temp, json_mode=True, **chron_kwargs)
                chron_plan = extract_gm_plan(raw_chron)
                if not chron_plan and (not isinstance(raw_chron, str) or raw_chron.strip() != "{}"):
                    warn_msg = "Post-turn chronicler returned empty or unparseable output; post-turn sync was skipped."
                    executed["warnings"].append(warn_msg)
                    yield {"event": "warning", "data": {"message": warn_msg}}
                if chron_plan:
                    already_timed = any(
                        p.get("target") == "solo" and isinstance(p.get("after"), dict) and "time" in p["after"]
                        for p in executed["patches"]
                    )
                    if already_timed:
                        chron_plan.pop("time_elapsed_minutes", None)
                    chron_exec = self._execute_plan(
                        campaign_id,
                        chron_plan,
                        chron_prep,
                        default_actor=default_actor,
                        op_prefix=f"{prep['turn_id']}:chron",
                        allow_checks=False,
                        allow_solo=False,
                    )
                    for p in chron_exec["patches"]:
                        executed["patches"].append(p)
                        yield {"event": "state_patch", "data": p}
                    for entry in chron_exec["library_added"]:
                        executed["library_added"].append(entry)
                        yield {"event": "library_added", "data": entry}
                    for w in chron_exec["warnings"]:
                        executed["warnings"].append(w)
                        yield {"event": "warning", "data": {"message": w}}
                    executed["gm_secrets"] = chron_exec["gm_secrets"]
                    executed["clocks"] = chron_exec["clocks"]
            except Exception as exc:
                warn_msg = f"Post-turn chronicler skipped: {exc}"
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}

        if prep["compression_recommended"]:
            msg = "Long conversation branch; update or compress the campaign summary when convenient."
            executed["warnings"].append(msg)
            yield {"event": "warning", "data": {"message": msg}}

        post_ctx = self.gameplay.campaign_context(campaign_id)
        model_name = getattr(getattr(self.llm, "config", None), "model", "")
        citation_cards = [
            {
                "id": c["id"],
                "name": c["name"],
                "category": c["category"],
                "summary": c["summary"],
                "source": c.get("source"),
                "printed_page": c.get("printed_page"),
                "pdf_page": c.get("pdf_page"),
            }
            for c in prep["citations"]
        ]
        assistant_msg = self.tree.append_message(
            campaign_id,
            parent_id=user_msg["id"],
            role="assistant",
            content=clean_text,
            raw_content=raw_text,
            model=model_name,
            campaign_revision=post_ctx["campaign"]["revision"],
            solo_revision=post_ctx["solo"]["revision"],
            metadata={
                "turn_id": prep["turn_id"],
                "mode": active_mode,
                "rolls": executed["rolls"],
                "patches": executed["patches"],
                "library_added": [e["id"] for e in executed["library_added"]],
                "citations": [c["id"] for c in prep["citations"]],
                "citation_cards": citation_cards,
                "warnings": executed["warnings"],
                **({"guidance": guidance.strip()} if isinstance(guidance, str) and guidance.strip() else {}),
            },
        )
        self._save_branch_private_state(
            campaign_id,
            assistant_msg["id"],
            user_msg["id"],
            executed["gm_secrets"],
            executed["clocks"],
        )
        yield {
            "event": "turn_done",
            "data": {
                "turn_id": prep["turn_id"],
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "citations": prep["citations"],
                "rolls": executed["rolls"],
                "state_patches": executed["patches"],
                "library_added": executed["library_added"],
                "warnings": executed["warnings"],
                "compression_recommended": prep["compression_recommended"],
            },
        }

    async def compress_memory(self, campaign_id: str, leaf_id: str | None = None) -> dict[str, Any]:
        """Distill branch history into structured Campaign Library dossiers + concise cross-referenced summary."""
        ctx = self.gameplay.campaign_context(campaign_id)
        tree = self.tree.get_tree(campaign_id)
        target_leaf = leaf_id or tree.get("active_leaf_id")
        branch = self.tree.get_branch_to(campaign_id, target_leaf) if target_leaf else list(tree.get("active_branch") or [])
        secrets, clocks = self._load_branch_private_state(campaign_id, target_leaf)
        existing_lib = [
            {
                "name": e["name"],
                "category": e["category"],
                "summary": e["summary"],
                "stats": e["stats"],
            }
            for e in self.library.list_entries(campaign_id)
        ]
        transcript_lines = [
            (
                f"[{((m.get('metadata') or {}).get('speaker_name') or 'USER').upper()}] {m['content'].strip()}"
                if m.get("role") == "user"
                else f"[{m['role'].upper()}] {m['content'].strip()}"
            )
            for m in branch[-60:]
            if isinstance(m.get("content"), str) and m["content"].strip()
        ]
        if not transcript_lines and not ctx["campaign"]["state"]["summary"].strip():
            raise ValueError("No conversation history or summary to compress yet")

        archivist_extra = (self.prompt_settings.get("archivist_extra") or "").strip()
        archivist_core = (self.prompt_settings.get("archivist_core_rules") or "").strip()
        arch_block = f"\nCustom Archivist Instructions:\n{archivist_extra}\n" if archivist_extra else "\n"
        core_block = f"Critical rules:\n{archivist_core}\n" if archivist_core else ""
        comp_prompt = (
            "You are the Cyberpunk RED Campaign Archivist. Compress the conversation history into clean, structured persistent records.\n"
            f"{arch_block}"
            "Return ONLY a single valid JSON object with no markdown:\n"
            "{\n"
            '  "library_entries": [\n'
            '    {"name": "...", "category": "npc|faction|location|weapon|armor|cyberware|program|hardware|gear|role|rule", "summary": "1-sentence player-known summary", "description": "concise factual dossier/lore/mechanics", "stats": {"role": "...", "district": "...", "disposition": "Wary (-1)", "cost_eb": 500}, "tags": ["..."]}\n'
            "  ],\n"
            '  "campaign_updates": {\n'
            '    "scene": "concise current location + active situation",\n'
            '    "summary": "crisp chronological recap <= 1400 chars referencing Library dossiers with [Category: Name] tags (e.g. [NPC: Mara Kovic], [Location: Dock 7], [Faction: Maelstrom]) instead of repeating bios/stats inline",\n'
            '    "npcs": {"NPC Name": "Role, location — Disposition (Hostile -2..Trusted +2); latest tie-in"},\n'
            '    "objectives": {"Objective": "Active|Completed|Blocked"},\n'
            '    "discoveries": {"Topic": "Verified PC-observed clue (can cite [Category: Name])"},\n'
            '    "unresolved": {"Thread": "Open hook or pending threat"}\n'
            "  },\n"
            '  "gm_secrets": {"secret_key": "private GM truth, hidden motive, or null to remove resolved secret"},\n'
            '  "clock_ops": [{"id": "...", "name": "...", "delta": 0, "filled": 0, "segments": 4, "category": "heat|obligation|deadline|faction|recovery", "visibility": "public|secret", "note": "..."}]\n'
            "}\n"
            f"{core_block}"
            f"Current Campaign State: {json.dumps(ctx['campaign']['state'])}\n"
            f"Existing Campaign Library Entries: {json.dumps(existing_lib)}\n"
            f"Current Private GM Secrets: {json.dumps(secrets)}\n"
            f"Current Clocks: {json.dumps(clocks)}"
        )
        planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
        raw = await self.llm.complete(
            [
                {"role": "system", "content": comp_prompt},
                {"role": "user", "content": "Branch Transcript:\n" + "\n\n".join(transcript_lines)},
            ],
            temperature=planner_temp,
            json_mode=True,
        )
        parsed = extract_gm_plan(raw)
        if not parsed:
            raise ValueError("Compression model returned empty or invalid JSON")

        op_base = f"compress:{uuid.uuid4().hex[:10]}"
        upserted_entries: list[dict[str, Any]] = []
        warnings: list[str] = []

        for idx, raw_entry in enumerate(parsed.get("library_entries") or []):
            if not isinstance(raw_entry, dict):
                continue
            try:
                raw_cat = raw_entry.get("category")
                norm_cat = normalize_category(str(raw_cat)) if raw_cat else "rule"
                upserted = self.library.upsert_entry(
                    campaign_id,
                    name=str(raw_entry.get("name") or ""),
                    category=norm_cat or "rule",
                    summary=str(raw_entry.get("summary") or ""),
                    description=str(raw_entry.get("description") or ""),
                    stats=raw_entry.get("stats") if isinstance(raw_entry.get("stats"), dict) else {},
                    tags=raw_entry.get("tags") if isinstance(raw_entry.get("tags"), list) else [],
                    created_by="ai",
                    allow_variant=False,
                    operation_id=f"{op_base}:lib:{idx}",
                )
                upserted_entries.append(upserted)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped library entry '{raw_entry.get('name', '?')}': {exc}")

        live_camp = self.gameplay.campaign_context(campaign_id)["campaign"]
        raw_updates = parsed.get("campaign_updates") if isinstance(parsed.get("campaign_updates"), dict) else {}
        updated_campaign = live_camp
        if raw_updates:
            changes, norm_notes = _normalize_campaign_changes(raw_updates, live_camp["state"])
            warnings.extend(norm_notes)
            if changes:
                updated_campaign = self.gameplay.execute(
                    "update_campaign",
                    {
                        "campaign_id": campaign_id,
                        "expected_revision": live_camp["revision"],
                        "changes": changes,
                        "reason": "Compress campaign memory & archive to Library",
                        "operation_id": f"{op_base}:camp",
                    },
                    campaign_id=campaign_id,
                )["result"]

        next_secrets = self._merge_gm_secrets(secrets, parsed.get("gm_secrets"))
        next_clocks, _ = self._apply_clock_ops(clocks, parsed.get("clock_ops"), allow_secret=True)
        parent_id = None
        if target_leaf:
            leaf_msg = self.tree.get_message(campaign_id, target_leaf)
            parent_id = leaf_msg["parent_id"] if leaf_msg else None
        self._save_branch_private_state(campaign_id, target_leaf, parent_id, next_secrets, next_clocks)
        if not target_leaf:
            self._save_branch_private_state(campaign_id, None, None, next_secrets, next_clocks)
        self._set_compressed_count(campaign_id, target_leaf, len(branch))

        return {
            "campaign": updated_campaign,
            "library_upserted": upserted_entries,
            "compressed_messages": len(branch),
            "clocks": [c for c in next_clocks if c.get("visibility") != "secret"],
            "warnings": warnings,
        }

    async def run_turn(
        self,
        campaign_id: str,
        user_text: str,
        *,
        parent_id: str | None = None,
        branch_from_root: bool = False,
        overclock: bool = False,
        luck_spend: int = 0,
        mode: str | None = None,
        speaker_character_id: str | None = None,
        speaker_name: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one complete AI GM turn and stream typed events for the frontend UI."""
        if not isinstance(user_text, str) or not user_text.strip():
            raise ValueError("user_text must be a nonempty string")
        if isinstance(luck_spend, bool) or not isinstance(luck_spend, int) or luck_spend < 0:
            raise ValueError("luck_spend must be a nonnegative integer")
        active_mode = mode or getattr(getattr(self.llm, "config", None), "mode", "two_pass")
        if active_mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError(f"Unsupported turn mode: {active_mode!r}")

        prep = self.preprocess(
            campaign_id,
            user_text.strip(),
            parent_id=parent_id,
            branch_from_root=branch_from_root,
        )
        pre_ctx = prep["context"]
        speaker = self._resolve_speaker(pre_ctx["characters"], speaker_character_id, speaker_name)
        meta: dict[str, Any] = {"overclock": overclock, "luck_spend": luck_spend}
        if speaker.get("id"):
            meta["speaker_character_id"] = speaker["id"]
        if speaker.get("name"):
            meta["speaker_name"] = speaker["name"]
        user_msg = self.tree.append_message(
            campaign_id,
            parent_id=prep["parent_id"],
            role="user",
            content=user_text.strip(),
            campaign_revision=pre_ctx["campaign"]["revision"],
            solo_revision=pre_ctx["solo"]["revision"],
            metadata=meta,
        )
        turn_completed = False
        try:
            async for ev in self._stream_turn_from_user_msg(
                campaign_id,
                user_msg,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                active_mode=active_mode,
                speaker=speaker,
            ):
                if ev.get("event") == "turn_done":
                    turn_completed = True
                yield ev
        finally:
            if not turn_completed:
                try:
                    self.tree.delete_message(campaign_id, user_msg["id"])
                except Exception:
                    pass

    @staticmethod
    def _resolve_speaker(
        characters: list[dict[str, Any]],
        speaker_character_id: str | None,
        speaker_name: str | None,
    ) -> dict[str, str]:
        if speaker_character_id:
            found = next((c for c in characters if c["id"] == speaker_character_id), None)
            if found:
                return {"id": found["id"], "name": found["name"]}
        if isinstance(speaker_name, str) and speaker_name.strip():
            return {"id": "", "name": speaker_name.strip()}
        return {}

    async def regenerate_turn(
        self,
        campaign_id: str,
        message_id: str,
        *,
        overclock: bool | None = None,
        luck_spend: int | None = None,
        mode: str | None = None,
        guidance: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Regenerate an assistant reply as a sibling branch without duplicating the user message."""
        active_mode = mode or getattr(getattr(self.llm, "config", None), "mode", "two_pass")
        if active_mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError(f"Unsupported turn mode: {active_mode!r}")
        target = self.tree.get_message(campaign_id, message_id)
        if target is None:
            raise ValueError(f"message not found in campaign: {message_id}")
        if target["role"] == "assistant":
            if not target["parent_id"]:
                raise ValueError("Assistant message has no parent user message")
            user_msg = self.tree.get_message(campaign_id, target["parent_id"])
            if user_msg is None or user_msg["role"] != "user":
                raise ValueError("Parent message is not a user turn")
        elif target["role"] == "user":
            user_msg = target
        else:
            raise ValueError("Only user or assistant messages can be regenerated")

        self.tree.switch_branch(campaign_id, user_msg["id"])
        use_overclock = bool(user_msg["metadata"].get("overclock", False)) if overclock is None else bool(overclock)
        use_luck = int(user_msg["metadata"].get("luck_spend", 0)) if luck_spend is None else int(luck_spend)
        if use_luck < 0:
            raise ValueError("luck_spend must be a nonnegative integer")
        prep = self.preprocess(
            campaign_id,
            user_msg["content"],
            parent_id=user_msg["parent_id"],
            branch_from_root=(user_msg["parent_id"] is None),
        )
        speaker = self._resolve_speaker(
            prep["context"]["characters"],
            user_msg["metadata"].get("speaker_character_id"),
            user_msg["metadata"].get("speaker_name"),
        )
        async for ev in self._stream_turn_from_user_msg(
            campaign_id,
            user_msg,
            prep,
            overclock=use_overclock,
            luck_spend=use_luck,
            active_mode=active_mode,
            speaker=speaker,
            guidance=guidance,
        ):
            yield ev
