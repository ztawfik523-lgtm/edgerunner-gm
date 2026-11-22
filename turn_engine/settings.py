"""Atomic settings persistence, validation, and prompt template defaults."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit

from index_lock import index_lock

_GM_THINKING_MODES = frozenset({"quality", "balanced"})
_COMPRESSION_MESSAGE_THRESHOLD = 14

DEFAULT_SETTINGS_PATH = Path(
    os.environ.get("REDGM_SETTINGS_FILE", Path.home() / ".local/share/cyberpunk-red-gm/settings.json")
)
_SETTINGS_LOCK = threading.RLock()


def default_settings_path() -> Path:
    env_override = os.environ.get("REDGM_SETTINGS_FILE", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    facade = sys.modules.get("turnloop")
    if facade is not None:
        facade_path = getattr(facade, "DEFAULT_SETTINGS_PATH", None)
        if facade_path is not None and facade_path != DEFAULT_SETTINGS_PATH:
            return Path(facade_path).expanduser()
    return DEFAULT_SETTINGS_PATH.expanduser()


_DEFAULT_NARRATOR_PERSONA = (
    "You are the Cyberpunk RED Game Master. Run responsive, grounded scenes driven by player choices, "
    "character sheets, and dice outcomes."
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
    "- Each turn arrives tagged with its active speaker (`[Character]: ...` and `Active Player / Speaker`). Resolve checks, LUCK, Overclock, and direct NPC replies primarily for that speaker unless multiple players acted in sequence.\n"
    "- When multiple consecutive `[Speaker]: ...` player turns appear since your last reply, resolve all of those players' declared actions and dialogue together in one cohesive scene response.\n"
    "- Protect teammate agency: NEVER invent dialogue, movement, or decisions for other player characters in the party while resolving a turn—leave idle or off-spotlight PCs free to jump in on their own turn.\n"
    "- Respect Party Grouping & Split Scenes: check `Party Grouping & Locations` carefully. If the party is SPLIT, only characters at the active scene/location can see, hear, fight, or hand over items here—never pull off-site PCs into this scene unless they physically travel or use an Agent/comms.\n"
    "- Keep party members distinct: honor each PC's separate HP, ammo, cyberware, location, and NPC disposition from `Characters`, and do not merge their inventory or private knowledge unless they are together and share it.\n"
    "- Handle vs Real Name Privacy: Always refer to and have NPCs address player characters AND NPCs by their Street Handle (`handle` / `name`). If a PC or NPC has `real_name_hidden: true`, the world DOES NOT know their real/legal name unless explicitly revealed in play."
)

_DEFAULT_NARRATOR_CORE_RULES = (
    "Information Fog-of-War & Earned Intel:\n"
    "- Keep Player Knowledge (`Narrative State` + observed facts) separate from Private GM Truth (`Hidden GM Secrets` and `secret` clocks). Never reveal unspotted traps, hidden motives, secret employers, or secret clocks.\n"
    "- Gate sensitive answers behind rolls, leverage, payment, or legwork: if a check failed or no check/leverage unlocked it, have the NPC deflect, lie plausibly, or name a price.\n"
    "- Handle vs Real Name Privacy: For PCs and NPCs with `real_name_hidden: true`, NPCs and public terminals only know their street `handle` unless revealed in play.\n"
    "Continuity, Cast & World:\n"
    "- Continue in media res from the previous beat: do not re-describe an already-established location or weather unless the crew moves or time shifts, and vary how each turn opens.\n"
    "- Persistent NPC cast & voice: Keep NPCs in `Narrative State -> npcs` and `NPC Identities` consistent in role, disposition, `personality`, and `speech_style`, without forcing off-screen contacts into unrelated scenes.\n"
    "- Deliver full clock consequences naturally when any clock in `Active Clocks` reaches `filled == segments`.\n"
    "- Respect Cyberpunk RED's street economy (typical gigs pay 500–2,000eb, rare high-risk jobs ~5,000eb).\n"
    "Strict Grounding & Formatting:\n"
    "- Never alter or contradict any dice roll total, stat, pass/fail, critical, HP/Humanity/eb change, or citation in the Engine Roll Ledger. Never offer retroactive LUCK.\n"
    "- Never fabricate unapplied numeric HP, Humanity, or eb changes in prose, and do not print raw stat-formula blocks (the UI renders dice cards separately).\n"
    "- On a failed check, the attempted action fails (at most a costly partial hint on a narrow miss); if the ledger says `NONE (0 rolls executed)`, never invent dice numbers or pass/fail lines.\n"
    "- Treat `Characters` JSON as canonical truth for stats, skills, money, inventory, and detail. Use `equipped_weapon` as the default weapon when a PC attacks without naming one (equipping does not mean drawn in public, and they can use any other weapon in `inventory` by name), and use `equipped_armor` (Body) / `equipped_head_armor` (Head) for worn SP protection.\n"
    '- Clean Markdown only: write spoken dialogue in normal quotes (e.g. "Step away from the case."), never wrapped in `**...**`, and never nest `**bold**`.'
)

_DEFAULT_CHRONICLER_CORE_RULES = (
    "- Only record NPCs, locations, clues, or discoveries explicitly observed by the PC in the GM prose.\n"
    "- Whenever a new named NPC with dialogue or a recurring role appears, save them in `new_homebrew` (`category: \"npc\"` with `stats`: `role`, `disposition`, `personality`, `speech_style`) AND in `state.npcs` + `npc_identities` (`personality`, `speech_style`) if not already stored.\n"
    "- Also capture newly introduced custom locations/factions or unique datashards/items in `new_homebrew` when recurring/significant; leave `new_homebrew` empty (`[]`) if nothing new appeared.\n"
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

_STATIC_INTRO_PRIMER = (
    "### WELCOME TO CYBERPUNK RED (NIGHT CITY, 2045)\n"
    "**The Setting:** In the Time of the Red, the Fourth Corporate War has shattered global supply chains, orbital debris stains the sky crimson at dawn, and megacorporations rebuild behind private walls while edgerunners survive on street gigs, scavenged chrome, and Fixer-brokered Night Markets.\n\n"
    "### HOW THE RULES & STATS WORK\n"
    "- **10 Core STATs (2–8):** `INT`, `REF`, `DEX`, `TECH`, `COOL`, `WILL`, `LUCK`, `MOVE`, `BODY`, `EMP`.\n"
    "- **Skill Checks:** Roll **`1d10 + STAT + Skill`** and beat the **Difficulty Value (DV)** — `DV 13` Everyday, `DV 15` Difficult, `DV 17` Professional, `DV 21` Heroic. A natural **10** explodes (`+1d10`); a natural **1** fumbles (`-1d10`).\n"
    "- **LUCK & Overclock:** Commit **LUCK** points *before* rolling (`+1` each, refills every session) or toggle **Overclock** (`-2 Humanity` for `+2` on a check) in the chat bar.\n"
    "- **Wounds, Armor & Humanity:** Armor **Stopping Power (SP)** absorbs damage before **HP** drops; below half HP you are **Seriously Wounded** (`-2` to all checks). Installing cyberware costs **Humanity**.\n\n"
    "### PLAYABLE ROLES\n"
    "- **Solo** *(Combat Awareness)*: Tactical edge, initiative boost, and precision damage.\n"
    "- **Netrunner** *(Interface)*: Breach local NET architectures, fight Black ICE, and hijack systems.\n"
    "- **Tech** *(Maker)*: Repair, upgrade, fabricate, and invent gear and weapons.\n"
    "- **Medtech** *(Medicine)*: Trauma surgery, combat pharmaceuticals, and cryotanks.\n"
    "- **Rockerboy** *(Charismatic Impact)*: Sway crowds, fans, and street venues.\n"
    "- **Media** *(Credibility)*: Dig up rumors, expose coverups, and shape public truth.\n"
    "- **Exec** *(Teamwork)*: Corporate perks, housing, and a loyal specialist teammate.\n"
    "- **Lawman** *(Backup)*: Call armed patrol or tactical response when heat rises.\n"
    "- **Fixer** *(Operator)*: Source scarce Night Market gear, haggle prices, and broker deals.\n"
    "- **Nomad** *(Moto)*: Access clan vehicles, armored upgrades, and highway networks."
)

_DEFAULT_INTRO_PROMPT = (
    "The player has just been shown the static Cyberpunk RED rules, stats, and 10 playable roles primer.\n"
    "DO NOT repeat the general Cyberpunk RED rules, dice formulas, or list of 10 roles.\n"
    "Write ONLY a tight, grounded **Campaign Welcome & Table Tie-In** (under 180 words, zero emojis, zero cheesy sign-offs):\n"
    "1. Briefly welcome the player to the active campaign's district, tone, and immediate stakes using `Campaign Scene`, `Campaign Summary`, and `Known NPCs`.\n"
    "2. Note any attached `Party Characters Attached` by Street Handle and Role (never expose hidden `real_name`s); if none are attached yet, tell them to open the **Character** tab to build or claim their Edgerunner.\n"
    "3. End with 2–3 concrete ways they can jump straight into the opening scene once ready."
)

DEFAULT_PROMPT_TEMPLATES: dict[str, str] = {
    "system_persona": _DEFAULT_NARRATOR_PERSONA,
    "intro_prompt": _DEFAULT_INTRO_PROMPT,
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
    "grounded": "Grounded street-level realism: keep pay, threats, and NPC reactions believable and consequential.",
    "cinematic": "Cinematic framing: heightened dramatic momentum and punchy visual beats while respecting dice outcomes.",
    "grit_dark": "Gritty and dark: bleak, visceral street survival, moral grayness, and harsh fallout.",
    "spy_thriller": "Spy thriller & espionage: tradecraft, paranoia, surveillance, double-crosses, and tense leverage.",
    "full_action": "Full action & adrenaline: fast kinetic momentum, gunfights, chases, and immediate escalation.",
    "lethal": "Lethal combat zone: ruthless tactical opposition, scarce ammo/meds, and unforgiving consequences.",
    "noir_mystery": "Hardboiled investigation: clues, alibis, interviews, and slow-burn intrigue.",
    "sandbox": "Open Night City sandbox: ambient neighborhood leads, fixer gigs, and player-driven exploration.",
}

_LENGTH_HINTS = {
    "auto": "Match reply length naturally to the moment: a crisp sentence or two for quick banter or checks, longer when a new scene or major beat earns it.",
    "concise": "Keep replies crisp (1-2 tight paragraphs) so turns play fast.",
    "standard": "Write balanced scenes (2-4 paragraphs) with room for dialogue and action.",
    "detailed": "Write rich, textured scenes (4-6 paragraphs) when exploring locales or tense confrontations.",
    "novel": "Write expansive, novelistic prose (5+ paragraphs) with unhurried character moments and scene texture.",
}

_PACING_HINTS = {
    "balanced": "Balanced pacing: natural mix of dialogue, action, and world reaction.",
    "reactive": "Fast and reactive: punchy back-and-forth, immediate NPC responses, minimal exposition.",
    "tactical": "Tactical and crunch-forward: clear distances, cover, threat cues, and mechanical clarity.",
    "roleplay": "Roleplay and character-heavy: linger on NPC personalities, subtext, relationships, and dialogue.",
    "slow_burn": "Slow burn and tension: deliberate buildup, lingering suspense, and quiet dread before things pop off.",
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


def _update_settings_doc(settings_path: Path | None, mutator) -> Any:
    """Atomically read, mutate, and write settings.json under both thread and file locks."""
    path = (settings_path or default_settings_path()).expanduser()
    with _SETTINGS_LOCK:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with index_lock(path):
            doc = read_settings_doc(path)
            result = mutator(path, doc)
            write_settings_doc(doc, path)
            return result


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
        "max_tokens": 2400,
        "intro_max_tokens": 4096,
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
        "narrator_pacing": "balanced",
        "default_time_step_minutes": 0,
        "gm_thinking_mode": "quality",
        "require_character_to_speak": True,
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
    if "intro_max_tokens" in raw and raw["intro_max_tokens"] is not None:
        imt = int(raw["intro_max_tokens"])
        if not 256 <= imt <= 65536:
            raise ValueError("intro_max_tokens must be between 256 and 65536")
        base["intro_max_tokens"] = imt
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
            raise ValueError(f"gm_style must be one of {', '.join(_GM_STYLE_HINTS)}")
        base["gm_style"] = style
    if "narrator_length" in raw and raw["narrator_length"] is not None:
        nl = str(raw["narrator_length"]).strip()
        if nl not in _LENGTH_HINTS:
            raise ValueError(f"narrator_length must be one of {', '.join(_LENGTH_HINTS)}")
        base["narrator_length"] = nl
    if "narrator_pacing" in raw and raw["narrator_pacing"] is not None:
        np_val = str(raw["narrator_pacing"]).strip()
        if np_val not in _PACING_HINTS:
            raise ValueError(f"narrator_pacing must be one of {', '.join(_PACING_HINTS)}")
        base["narrator_pacing"] = np_val
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
    if "require_character_to_speak" in raw and raw["require_character_to_speak"] is not None:
        base["require_character_to_speak"] = bool(raw["require_character_to_speak"])
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

    def _mutate(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
        current = load_llm_settings(path)
        merged = _validate_llm_settings(updates, current)
        for key in _default_llm_dict():
            doc[key] = merged[key]
        return merged

    return _update_settings_doc(settings_path, _mutate)


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
        "intro_max_tokens": int(settings.get("intro_max_tokens", 4096)),
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
        "narrator_pacing": settings.get("narrator_pacing", "balanced"),
        "default_time_step_minutes": int(settings.get("default_time_step_minutes", 0)),
        "gm_thinking_mode": settings.get("gm_thinking_mode", "quality"),
        "require_character_to_speak": bool(settings.get("require_character_to_speak", True)),
    }


_MAX_PROMPT_CHARS = 16000
_NON_EMPTY_PROMPT_KEYS = frozenset({"system_persona", "intro_prompt", "creation_assist_persona", "player_message_template"})


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

    def _mutate(path: Path, doc: dict[str, Any]) -> dict[str, str]:
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
        return next_prompts

    return _update_settings_doc(settings_path, _mutate)


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

    def _mutate(path: Path, doc: dict[str, Any]) -> dict[str, Any]:
        current = load_server_settings(path)
        merged = _validate_server_settings(updates, current)
        doc["server"] = merged
        return merged

    return _update_settings_doc(settings_path, _mutate)
