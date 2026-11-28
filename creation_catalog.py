"""AI co-writer for character backstory, contacts and campaign setup, grounded in the indexed Corebook."""
from __future__ import annotations

import asyncio
import inspect
import json
import random
import re
from pathlib import Path
from typing import Any

from creation_reference import campaign_presets

_THINK_XML_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.S | re.I)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
_LOCALE_STOPWORDS = frozenset({"the", "of", "and", "in", "at", "a", "an", "for", "on", "to"})


def _extract_balanced_json(text: str) -> str | None:
    """Scan `text` using `JSONDecoder.raw_decode` and return the last valid JSON object substring."""
    decoder = json.JSONDecoder()
    last_slice: str | None = None
    pos = 0
    while pos < len(text):
        brace = text.find("{", pos)
        if brace == -1:
            break
        try:
            obj, end_pos = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            pos = brace + 1
            continue
        if isinstance(obj, dict):
            last_slice = text[brace:end_pos]
        pos = max(end_pos, brace + 1)
    return last_slice


def _strip_json_fences(raw: str) -> str:
    """Strip `<think>` reasoning blocks and extract balanced JSON from fenced or raw LLM replies."""
    text = _THINK_XML_RE.sub("", raw or "")
    text = re.sub(r"<think\b.*$", "", text, flags=re.S | re.I).strip()
    if not text:
        return ""
    fences = list(_FENCED_JSON_RE.finditer(text))
    for match in reversed(fences):
        inner = match.group(1).strip()
        extracted = _extract_balanced_json(inner)
        if extracted is not None:
            return extracted
    if fences:
        return fences[-1].group(1).strip()
    extracted = _extract_balanced_json(text)
    if extracted is not None:
        return extracted
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _supports_enable_thinking(fn: Any) -> bool:
    """Return True if `fn` accepts an `enable_thinking` keyword argument."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return "enable_thinking" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )


def _normalize_kv_entry(entry: Any) -> dict[str, Any]:
    """Normalize `{key, val}`, `{name, description}`, or `{handle, summary}` entry shapes."""
    if not isinstance(entry, dict):
        return {"key": "", "val": str(entry or "")}
    out = dict(entry)
    if "key" in entry or "val" in entry:
        out["key"] = str(entry.get("key") or "")
        out["val"] = str(entry.get("val") or "")
        return out
    if "name" in entry or "description" in entry:
        out["key"] = str(entry.get("name") or "")
        out["val"] = str(entry.get("description") or "")
        return out
    if "handle" in entry or "summary" in entry:
        out["key"] = str(entry.get("handle") or "")
        out["val"] = str(entry.get("summary") or "")
        return out
    for k, v in entry.items():
        out["key"] = str(k)
        out["val"] = str(v or "")
        return out
    return {"key": "", "val": ""}


def _gather_creation_lore(
    rules_path: Path,
    query_terms: list[str],
    query_seed: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Run synchronous library & page searches off the event loop."""
    from library import search_library
    from redkb import search_pages

    lore_snippets: list[str] = []
    citations: list[dict[str, Any]] = []
    for q_term in query_terms:
        term = q_term.strip()
        if not term:
            continue
        try:
            hits = search_library(rules_path, q=term, limit=2)
            for h in hits:
                lore_snippets.append(f"[Library: {h['name']}] {h.get('summary') or h.get('description', '')[:220]}")
        except Exception:
            pass
    if query_seed:
        try:
            pages = search_pages(rules_path, query_seed, limit=2)
            for pg in pages:
                excerpt = str(pg.get("excerpt") or "").strip()
                if excerpt:
                    lore_snippets.append(f"[Corebook p.{pg.get('printed_page') or pg.get('pdf_page')}] {excerpt[:280]}")
                    citations.append({
                        "printed_page": pg.get("printed_page"),
                        "pdf_page": pg.get("pdf_page"),
                    })
        except Exception:
            pass
    return lore_snippets, citations


_RNG = random.SystemRandom()

_SCRATCH_LOCALES = [
    "Little China ramen-stall alleyways and overcrowded megabuilding stairwells",
    "Santo Domingo Rancho Coronado scrapyard garages and diesel-fumed workshops",
    "Heywood Glen bodega basements and neighborhood block-party rooftops",
    "Watson Northside Industrial rusting shipping containers and flooded docks",
    "Pacifica half-sunken arcade piers and squatters' solar micro-grids",
    "Westbrook Japantown capsule hotels, pachinko basements, and rooftop gardens",
    "South Night City Combat Zone bombed-out transit hubs and barter markets",
    "Badlands Red Chrome border motels, dust-choked wind farms, and water cisterns",
    "University District cramped grad-lab sublets and black-market textbook printers",
    "Upper Marina cargo-barge houseboats and salt-corroded crane catwalks",
]

_SCRATCH_CONFLICTS = [
    "a courier run for grey-market water-purifier filters that turned out to be tagged with corp trackers",
    "covering a sibling's gambling tab at an illegal rooftop fight club",
    "salvaging a wrecked Continental Brands delivery van before scavengers stripped the cold-chain crates",
    "an unpaid ripperdoc installment plan after emergency street surgery",
    "a forged Night City resident permit that got flagged during a routine NCPD sweep",
    "a crooked landlord threatening to cut the block's pirated power tap unless paid in hard eddies",
    "a stolen braindance master tape featuring an embarrassing exec cameo",
    "moonlighting security on a black-market Night Market pop-up that got hit by rival boosters",
    "a Nomad clan barter deal that left half a shipment of Synthcoke-laced meds unaccounted for",
    "a botched data-wipe on a secondhand Cyberdeck that still held someone's blackmail ledger",
]

_SCRATCH_TONES = [
    "gritty blue-collar survivalism — messy debts, worn-out gear, fierce neighborhood loyalty",
    "dry streetwise gallows humor — cynical pragmatism, oddball associates, sharp banter",
    "tense hardboiled noir — quiet betrayals, half-truths, and tight-lipped favors",
    "scrappy up-and-comer hustle — ambitious, resourceful, always three days ahead of rent",
    "ramshackle found-family warmth — fiercely protective of a tiny circle in a brutal city",
]

_CAMPAIGN_TWISTS = [
    "a mid-level Continental Brands logistics clerk trying to defect with contaminated Kibble batch manifests",
    "a flooded sub-basement server vault under Rancho Coronado humming with pre-DataKrash firmware",
    "a stolen Trauma Team cryo-pod whose occupant is a witness everyone thinks is already dead",
    "a neighborhood Night Market co-op being squeezed by two rival gangs over a clean water main",
    "a disgraced Zhirafa drone rigger hiring local street talent to steal back their own prototype rig",
    "a phantom Screamsheet pirate broadcast hijacking local Data Pool feeds from an abandoned maglev tunnel",
    "a Nomad pack stranded outside the city wall with medical supplies the Combat Zone desperately needs",
    "an underground combat-cab syndicate fixing races to launder dirty Petrochem scrip",
]

_ANTI_CLICHE_RULE = (
    "CREATIVE VARIETY & ANTI-CLICHE RULES (CRITICAL):\n"
    "- Invent fresh, grounded, culturally varied Night City 2045 names (everyday names + street handles like 'Marek', 'Tala', 'DeShawn', 'Piotr', 'Sadia', 'Nori', 'Rafa', 'Bex', 'Oskar', 'Yuna' — NEVER use overused sci-fi cliché names like Vex, Nyx, Kael, Jax, Raven, Kira, Viktor, Zero, Razor, Ghost, Nova, or Thorne unless the user explicitly wrote them).\n"
    "- Do NOT default to 'ex-Trauma Team EMT', 'ex-Arasaka operative', 'Afterlife booth meeting', 'Maelstrom ambush', or 'rain-slicked neon alley' unless the user's guidance or character sheet explicitly asks for it.\n"
    "- Write vivid, specific, concrete 2045 details (rent in cargo containers, Kibble/Synthcoke/Smash, specific neighborhoods, real skill/gear hooks) instead of vague purple prose."
)

_BIO_FIELDS = {
    "concept",
    "summary",
    "established_history",
    "appearance",
    "reputation_note",
    "trauma_hook",
    "addiction_hook",
    "debt_hook",
}
_CONTACT_FIELDS = {"friends", "enemies", "tragic_love_affairs"}
_CAMPAIGN_FIELDS = {
    "name",
    "summary",
    "opening_scene",
    "beat_chart",
    "beat_hook",
    "beat_developments",
    "beat_cliffhanger",
    "beat_climax",
    "beat_resolution",
    "npcs",
    "objectives",
    "discoveries",
    "locations",
    "gig",
    "gig_title",
    "gig_client",
    "gig_target",
    "gig_deadline",
    "gig_notes",
    "gm_secrets",
    "opening_clock",
    "clock_name",
    "clock_note",
}

_BEAT_KEY_TO_FIELD = {
    "beat_hook": ("hook", "Inciting job / Screamsheet lead"),
    "beat_developments": ("developments", "1-2 mid-run complications or reveals"),
    "beat_cliffhanger": ("cliffhanger", "Major twist raising the stakes"),
    "beat_climax": ("climax", "Showdown or extraction payoff"),
    "beat_resolution": ("resolution", "Fallout, eddie payout, Rep & IP aftermath"),
}

_CAMPAIGN_GIG_FIELDS = {
    "gig_title": ("title", "Contract title"),
    "gig_client": ("client", "Patron / Fixer"),
    "gig_target": ("target", "Objective site or asset"),
    "gig_deadline": ("deadline", "Contract deadline (e.g. 48 hours)"),
    "gig_notes": ("notes", "Contract terms or twist"),
}

_CAMPAIGN_CLOCK_FIELDS = {
    "clock_name": ("name", "Countdown name (e.g. Corp Response / Gang Heat)"),
    "clock_note": ("note", "What happens when the clock fills"),
}


def _sample_scratch_seed(target: str, cultural_origin: str = "") -> dict[str, str]:
    locale = _RNG.choice(_SCRATCH_LOCALES)
    conflict = _RNG.choice(_SCRATCH_CONFLICTS)
    tone = _RNG.choice(_SCRATCH_TONES)
    seed: dict[str, str] = {
        "suggested_locale": locale,
        "suggested_hook_angle": conflict,
        "tone_lens": tone,
    }
    if cultural_origin.strip():
        seed["naming_heritage_cue"] = f"Draw realistic NPC/handle inspiration from {cultural_origin.strip()} or diverse Night City street culture."
    if target == "campaign":
        seed["suggested_premise_spark"] = _RNG.choice(_CAMPAIGN_TWISTS)
    return seed


async def generate_creation_ai_assist(
    rules_path: str | Path | None,
    llm: Any,
    payload: dict[str, Any],
    *,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate or expand character Backstory, Contacts, or Campaign setup grounded in sheet & Corebook lore."""
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    target = str(payload.get("target") or "bio").strip().lower()
    if target not in {"bio", "contacts", "campaign"}:
        raise ValueError("target must be 'bio', 'contacts', or 'campaign'")

    mode = str(payload.get("mode") or "scratch").strip().lower()
    if mode not in {"scratch", "expand"}:
        raise ValueError("mode must be 'scratch' or 'expand'")

    raw_field = payload.get("field")
    field: str | None = str(raw_field).strip().lower() if isinstance(raw_field, str) and raw_field.strip() else None
    if field == "all":
        field = None
    if field is not None:
        allowed = (
            _BIO_FIELDS
            if target == "bio"
            else _CONTACT_FIELDS
            if target == "contacts"
            else _CAMPAIGN_FIELDS
        )
        if field not in allowed:
            raise ValueError(f"Unsupported field {field!r} for target {target!r}")

    raw_entry_index = payload.get("entry_index")
    entry_index: int | None = (
        int(raw_entry_index)
        if isinstance(raw_entry_index, (int, float)) and not isinstance(raw_entry_index, bool) and int(raw_entry_index) >= 0
        else None
    )
    raw_sub_field = payload.get("sub_field")
    sub_field: str | None = (
        str(raw_sub_field).strip().lower()
        if isinstance(raw_sub_field, str) and raw_sub_field.strip()
        else None
    )

    char = payload.get("character") if isinstance(payload.get("character"), dict) else {}
    camp = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    guidance = str(payload.get("guidance") or "").strip()
    lock_choices = bool(camp.get("lock_choices", payload.get("lock_choices", False)))

    role_name = str(char.get("role") or "Edgerunner").strip()
    char_handle = str(char.get("handle") or "").strip()
    char_real_name = str(char.get("real_name") or "").strip()
    char_detail = char.get("detail") if isinstance(char.get("detail"), dict) else {}
    real_name_hidden = bool(
        char.get(
            "real_name_hidden",
            char_detail.get("real_name_hidden", True if (char_handle and char_real_name) else False),
        )
    )
    visible_real_name = "" if real_name_hidden else char_real_name
    char_name = str(char.get("name") or char_handle or visible_real_name or "Unnamed Edgerunner").strip()
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    skills = char.get("skills") if isinstance(char.get("skills"), dict) else {}
    lifepath = char.get("lifepath") if isinstance(char.get("lifepath"), dict) else {}
    starting_gear = char.get("starting_gear") if isinstance(char.get("starting_gear"), dict) else {}

    top_skills = sorted(
        [(str(k), int(v)) for k, v in skills.items() if isinstance(v, (int, float)) and v > 0],
        key=lambda kv: (-kv[1], kv[0]),
    )[:10]

    scratch_seed = (
        _sample_scratch_seed(target, str(lifepath.get("cultural_origin") or ""))
        if mode == "scratch"
        else None
    )

    if not rules_path or not Path(rules_path).expanduser().is_file():
        raise ValueError("The AI co-writer needs your indexed Cyberpunk RED Corebook PDF")
    lore_snippets: list[str] = []
    citations: list[dict[str, Any]] = []
    p = Path(rules_path).expanduser()
    camp_meta_for_lore = camp.get("campaign_meta") if isinstance(camp.get("campaign_meta"), dict) else {}
    camp_district = str(camp.get("district") or camp_meta_for_lore.get("district") or "").strip()
    camp_factions = camp.get("factions") or camp_meta_for_lore.get("factions") or []
    camp_caper_style = str(camp.get("caper_style") or camp_meta_for_lore.get("caper_style") or "").strip()
    if camp_district:
        locale_hint = camp_district
    elif scratch_seed and scratch_seed.get("suggested_locale"):
        raw_locale = str(scratch_seed.get("suggested_locale") or "").strip()
        locale_terms = [
            t for t in re.split(r"\s+", raw_locale)
            if t and t.lower() not in _LOCALE_STOPWORDS
        ]
        locale_hint = " ".join(locale_terms[:3]) if locale_terms else raw_locale
    else:
        locale_hint = ""
    use_camp_seed_for_lore = target == "campaign" and (mode != "scratch" or lock_choices or field is not None)
    query_terms = (
        (
            [
                camp_district,
                *(str(f) for f in camp_factions[:2]),
                camp_caper_style,
                locale_hint or "Night City",
            ]
            if use_camp_seed_for_lore
            else [guidance[:80], locale_hint or "Night City"]
        )
        if target == "campaign"
        else [role_name, locale_hint or "Night City", str(lifepath.get("cultural_origin") or "")]
    )
    query_seed = (
        " ".join([camp_district, camp_caper_style, guidance[:120]]).strip()
        if target == "campaign"
        else " ".join([role_name, guidance[:120] or locale_hint]).strip()
    )
    lore_snippets, citations = await asyncio.to_thread(
        _gather_creation_lore, p, query_terms, query_seed
    )

    sheet_brief = {
        "name": char_name,
        **({"handle": char_handle} if char_handle else {}),
        **({"real_name": char_real_name} if char_real_name and not real_name_hidden else {}),
        "real_name_hidden": real_name_hidden,
        "identity_rule": (
            f"Known on The Street strictly by Handle '{char_handle}'; real name is hidden/secret from the public."
            if (char_handle and char_real_name and real_name_hidden)
            else f"Goes exclusively by Street Handle '{char_handle}' (no public legal name)."
            if (char_handle and not char_real_name)
            else f"Known as '{char_handle}' (real name '{char_real_name}' is known)."
            if (char_handle and char_real_name)
            else "Identity is hidden/secret from the public."
            if real_name_hidden
            else f"Known as '{char_name}'."
        ),
        "gender": char.get("gender") or "",
        "pronouns": char.get("pronouns") or "",
        "age": char.get("age") or "",
        "role": f"{role_name} (Rank 4)",
        "method": char.get("method") or "streetrat",
        "stats": stats,
        "top_skills": [f"{k} +{v}" for k, v in top_skills],
        "equipped_weapon": starting_gear.get("equipped_weapon") or "",
        "equipped_armor": starting_gear.get("equipped_armor") or {},
        "cyberware": [
            c.get("name") if isinstance(c, dict) else str(c)
            for c in (starting_gear.get("cyberware") or [])
        ],
        "lifepath": {k: v for k, v in lifepath.items() if k not in {"friends", "enemies", "tragic_love_affairs"} and v},
    }

    from turn_engine import DEFAULT_PROMPT_TEMPLATES, load_llm_settings, load_prompt_settings

    resolved_settings = Path(settings_path) if settings_path else None
    prompt_cfg = load_prompt_settings(resolved_settings) if resolved_settings is not None else dict(DEFAULT_PROMPT_TEMPLATES)
    llm_cfg = load_llm_settings(resolved_settings) if resolved_settings is not None else {}
    assist_persona = (prompt_cfg.get("creation_assist_persona") or "").strip() or DEFAULT_PROMPT_TEMPLATES["creation_assist_persona"]
    world_prefix = (prompt_cfg.get("world_rules_prefix") or "").strip()
    assist_extra = (prompt_cfg.get("creation_assist_extra") or "").strip()
    extra_sections = ""
    if world_prefix:
        extra_sections += f"\nTable World Rules:\n{world_prefix}\n"
    if assist_extra:
        extra_sections += f"\nCustom Co-Writer Instructions:\n{assist_extra}\n"

    system_prompt = (
        f"{assist_persona}\n"
        f"{_ANTI_CLICHE_RULE}\n"
        f"{extra_sections}"
        "Return ONLY valid JSON matching the requested schema. No markdown prose outside the JSON."
    )

    lore_block = "\n".join(lore_snippets[:4]) if lore_snippets else "Setting: Night City 2045 (Time of the Red, post-4th Corporate War)."

    if target == "bio":
        core_bio_schema = {
            "concept": "Short punchy one-line character tagline",
            "summary": "2-3 vivid paragraphs about origins, upbringing, family crisis, and why they became an Edgerunner",
            "established_history": "Concrete pre-Session-1 Night City history: past jobs, Fixers/crews, favors owed, local turf, hooks for the GM",
            "appearance": "Concise visual description matching their outfit, Lifepath style, armor, and visible cyberware",
        }
        full_schema = {
            **core_bio_schema,
            "reputation_note": "Concise Night City street rumor or reason behind their starting Reputation",
            "trauma_hook": "Specific psychological scar, cyberpsychosis warning sign, or war/street trauma",
            "addiction_hook": "Specific Night City vice, chem habit, or compulsion (e.g. Synthcoke, Smash, BDs)",
            "debt_hook": "Concrete eddie debt, blood favor, or obligation owed to a Fixer, corp, or ripperdoc",
        }
        current_draft = {
            "concept": current.get("concept") or "",
            "summary": current.get("summary") or "",
            "established_history": current.get("established_history") or "",
            "appearance": current.get("appearance") or "",
            "reputation_note": current.get("reputation_note") or "",
            "trauma_hook": current.get("trauma_hook") or "",
            "addiction_hook": current.get("addiction_hook") or "",
            "debt_hook": current.get("debt_hook") or "",
        }
        if field is not None:
            requested_schema = {field: full_schema[field]}
            mode_rule = (
                f"Generate ONLY the '{field}' field from scratch, tailored to the character sheet and creative seed, keeping consistency with any other fields already filled in current_draft."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON THE '{field}' FIELD. Expand, enrich, and sharpen ONLY '{field}'—preserving every specific name, event, debt, and tone the player wrote in '{field}' (or drafting it to harmonize with their other fields in current_draft if '{field}' is currently brief/empty). Do NOT return other fields."
            )
        else:
            requested_schema = core_bio_schema
            mode_rule = (
                "Write an original Concept tagline, Personal Backstory (2-3 crisp paragraphs), Established Night City History & Ties (concrete gigs, debts, hangouts, local turf, NPC hooks), and Signature Look & Mannerisms from scratch. Use the creative_seed angle unless user_guidance steers elsewhere."
                if mode == "scratch"
                else "The player has written draft notes. EXPAND, ENRICH, and POLISH their draft—preserving EVERY specific event, NPC name, debt, faction, and tone they wrote while weaving in sharper 2045 sensory details and sheet-faithful hooks."
            )
        user_payload: dict[str, Any] = {
            "task": "character_bio",
            "mode": mode,
            **({"target_field": field} if field else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "sheet": sheet_brief,
            "current_draft": current_draft,
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            if field is not None and isinstance(current_draft.get(field), str) and current_draft[field].strip():
                user_payload["avoid_repeating"] = f"Write a completely fresh alternative for '{field}'; do NOT repeat or lightly rephrase: {current_draft[field][:260]}"
            else:
                prev_text = " | ".join(str(v)[:140] for v in current_draft.values() if isinstance(v, str) and v.strip())
                if prev_text:
                    user_payload["avoid_repeating"] = f"Do NOT reuse names, locations, or plot beats from this prior draft: {prev_text[:320]}"

    elif target == "contacts":
        full_schema = {
            "friends": [{"name": "NPC Name", "relationship": "How you know them", "note": "Shared history / what favor or help they offer"}],
            "enemies": [{"who": "Role/Archetype (e.g. Ex-friend, Boosterganger, Corporate exec)", "name": "NPC Name", "wronged": "They wronged me or I wronged them", "cause": "What happened", "backup": "What resources/gang/corp they can throw at you", "revenge": "What you/they plan next"}],
            "tragic_love_affairs": [{"name": "NPC Name", "outcome": "What tore you apart and current status"}],
        }
        current_contacts = {
            "friends": current.get("friends") or [],
            "enemies": current.get("enemies") or [],
            "tragic_love_affairs": current.get("tragic_love_affairs") or [],
        }
        targeted_entry: dict[str, Any] | None = None
        targeted_prev_val = ""
        if field is not None and entry_index is not None and sub_field is not None:
            cat_list = current_contacts.get(field) if isinstance(current_contacts.get(field), list) else []
            if 0 <= entry_index < len(cat_list) and isinstance(cat_list[entry_index], dict):
                targeted_entry = cat_list[entry_index]
                targeted_prev_val = str(targeted_entry.get(sub_field) or "")
            requested_schema = {"value": f"Concise updated text for '{field}[{entry_index}].{sub_field}'"}
            mode_rule = (
                f"FOCUS EXCLUSIVELY ON '{field}[{entry_index}].{sub_field}'. Generate a fresh, concrete Night City 2045 value from scratch consistent with the rest of this contact entry and the character sheet. Return ONLY {{\"value\": \"...\"}}."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON '{field}[{entry_index}].{sub_field}'. Expand, sharpen, and enrich ONLY this single field while preserving the contact's existing name/identity and staying consistent with the rest of the entry and character sheet. Return ONLY {{\"value\": \"...\"}}."
            )
        elif field is not None:
            requested_schema = {field: full_schema[field]}
            mode_rule = (
                f"Generate ONLY the '{field}' list from scratch anchored in this character's Lifepath, Role, Skills, and existing bio."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON '{field}'. PRESERVE all existing NPCs/names/relationships the player entered in '{field}', EXPAND thin or placeholder entries (like 'Ally #1' or 'Rival #1') into vivid Night City 2045 NPCs tied to their sheet & other contacts, and add 1 fitting entry only if '{field}' is currently empty. Do NOT return other contact categories."
            )
        else:
            requested_schema = full_schema
            mode_rule = (
                "Generate an original set of pre-campaign NPCs from scratch anchored in this character's Lifepath, Role, Skills, and Night City 2045: 2 Friends, 2 Enemies, and 1 Tragic Love Affair. Give every NPC a distinctive everyday/street name and concrete hook."
                if mode == "scratch"
                else "The player already has draft Friends, Enemies, and/or Tragic Love Affairs. PRESERVE all existing NPCs/names/relationships they entered, EXPAND thin/generic entries into memorable Night City 2045 NPCs tied to their sheet & Lifepath, and add 1 missing ally/rival/ex only if a category is empty."
            )
        user_payload = {
            "task": "character_contacts",
            "mode": mode,
            **({"target_field": field} if field else {}),
            **({"target_entry_index": entry_index} if entry_index is not None else {}),
            **({"target_sub_field": sub_field} if sub_field else {}),
            **({"target_entry": targeted_entry} if targeted_entry is not None else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "sheet": sheet_brief,
            "current_contacts": current_contacts,
            "existing_bio": {
                "summary": current.get("summary") or "",
                "established_history": current.get("established_history") or "",
            },
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            if targeted_prev_val.strip():
                user_payload["avoid_repeating"] = f"Write a completely fresh alternative; do NOT repeat: {targeted_prev_val[:220]}"
            else:
                existing_names = [
                    str(e.get("name"))
                    for lst in current_contacts.values()
                    for e in (lst if isinstance(lst, list) else [])
                    if isinstance(e, dict) and e.get("name")
                ]
                if existing_names:
                    user_payload["avoid_repeating"] = f"Use completely new NPCs and dynamics; do NOT repeat these names: {', '.join(existing_names[:8])}"

    else:
        camp_brief = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
        presets = await asyncio.to_thread(campaign_presets, p)
        available_districts = [d["name"] for d in presets["districts"]]
        available_factions = [f["name"] for f in presets["factions"]]

        raw_npc_count = camp_brief.get("npc_count")
        raw_obj_count = camp_brief.get("objective_count")
        npc_count = max(1, min(8, int(raw_npc_count))) if isinstance(raw_npc_count, (int, float)) and not isinstance(raw_npc_count, bool) and int(raw_npc_count) > 0 else None
        obj_count = max(1, min(8, int(raw_obj_count))) if isinstance(raw_obj_count, (int, float)) and not isinstance(raw_obj_count, bool) and int(raw_obj_count) > 0 else None

        full_schema: dict[str, Any] = {
            "name": "Evocative campaign title",
            "summary": "2 concise paragraphs: campaign premise, district mood, central conflict, and stakes",
            "opening_scene": "1 playable in-media-res opening moment right before Turn 1: what is actively happening, where the crew is, and the immediate hook",
            "npcs": {"NPC Name (Faction/Role)": "Who they are, motive, and immediate offer or threat"},
            "objectives": {"Objective Title": "What the crew needs to accomplish first"},
            "discoveries": {"Starting Lead": "Concrete clue or intel the crew already holds at Session 1"},
            "locations": [{"name": "Venue or Block Name", "district": "Neighborhood", "notes": "Layout, security, or atmosphere"}],
            "gig": {"title": "Contract Title", "client": "Patron/Fixer", "target": "Objective site or asset", "payout_eb": 2000, "deadline": "48 hours", "notes": "Contract terms"},
            "beat_chart": {
                "hook": "Inciting job/Screamsheet lead",
                "developments": "1-2 complications or reveals mid-run",
                "cliffhanger": "Major twist raising the stakes",
                "climax": "Showdown or heist extraction payoff",
                "resolution": "Fallout, eddie payout, Reputation & IP aftermath",
            },
            "gm_secrets": "Hidden truth behind the patron, double-cross, or corporate agenda for the AI GM only",
            "opening_clock": {"name": "Countdown name (e.g. Corp Response / Gang Heat)", "segments": 4, "note": "What happens when the clock fills"},
        }
        camp_meta = camp_brief.get("campaign_meta") if isinstance(camp_brief.get("campaign_meta"), dict) else {}
        current_draft = {
            "name": camp_brief.get("name") or current.get("name") or "",
            "summary": current.get("summary") or "",
            "opening_scene": current.get("opening_scene") or "",
            "gm_secrets": current.get("gm_secrets") or "",
            "secret_entries": current.get("secret_entries") or [],
            "beats": current.get("beats") or {},
            "npcs": current.get("npcs") or camp_brief.get("npcs") or {},
            "objectives": current.get("objectives") or camp_brief.get("objectives") or {},
            "discoveries": current.get("discoveries") or camp_brief.get("discoveries") or {},
            "locations": current.get("locations") or [],
            "gig": current.get("gig") or {},
            "opening_clock": current.get("opening_clock") or {},
        }
        targeted_camp_entry: Any = None
        if field is not None:
            if field in _BEAT_KEY_TO_FIELD:
                beat_key, beat_desc = _BEAT_KEY_TO_FIELD[field]
                requested_schema = {"beat_chart": {beat_key: beat_desc}}
                target_label = f"beat_chart.{beat_key}"
                prev_field_val = (current_draft.get("beats") or {}).get(beat_key, "")
            elif field in _CAMPAIGN_GIG_FIELDS:
                gig_key, gig_desc = _CAMPAIGN_GIG_FIELDS[field]
                requested_schema = {field: gig_desc}
                target_label = f"gig.{gig_key}"
                prev_field_val = (current_draft.get("gig") or {}).get(gig_key, "")
            elif field in _CAMPAIGN_CLOCK_FIELDS:
                clock_key, clock_desc = _CAMPAIGN_CLOCK_FIELDS[field]
                requested_schema = {field: clock_desc}
                target_label = f"opening_clock.{clock_key}"
                prev_field_val = (current_draft.get("opening_clock") or {}).get(clock_key, "")
            elif entry_index is not None and sub_field is not None and field in {"npcs", "objectives", "discoveries", "locations", "gm_secrets"}:
                if field == "locations":
                    locs_list = current_draft.get("locations") if isinstance(current_draft.get("locations"), list) else []
                    targeted_camp_entry = locs_list[entry_index] if 0 <= entry_index < len(locs_list) else {}
                    prev_field_val = targeted_camp_entry.get(sub_field, "") if isinstance(targeted_camp_entry, dict) else ""
                elif field == "gm_secrets":
                    sec_list = current_draft.get("secret_entries") if isinstance(current_draft.get("secret_entries"), list) else []
                    raw_entry = sec_list[entry_index] if 0 <= entry_index < len(sec_list) else None
                    targeted_camp_entry = _normalize_kv_entry(raw_entry) if raw_entry is not None else {}
                    prev_field_val = targeted_camp_entry.get(sub_field, "") if isinstance(targeted_camp_entry, dict) else ""
                else:
                    raw_map = current_draft.get(field)
                    if isinstance(raw_map, dict):
                        items = [{"key": k, "val": v} for k, v in raw_map.items()]
                        targeted_camp_entry = items[entry_index] if 0 <= entry_index < len(items) else {}
                    elif isinstance(raw_map, list):
                        raw_entry = raw_map[entry_index] if 0 <= entry_index < len(raw_map) else None
                        targeted_camp_entry = _normalize_kv_entry(raw_entry) if raw_entry is not None else {}
                    prev_field_val = targeted_camp_entry.get(sub_field, "") if isinstance(targeted_camp_entry, dict) else ""
                requested_schema = {"value": f"Concise updated text for '{field}[{entry_index}].{sub_field}'"}
                target_label = f"{field}[{entry_index}].{sub_field}"
            else:
                requested_schema = {field: full_schema[field]}
                target_label = field
                prev_field_val = current_draft.get(field)
            mode_rule = (
                f"FOCUS EXCLUSIVELY ON '{target_label}'. Generate a completely fresh '{target_label}' from scratch consistent with the rest of current_draft and campaign_seed, using creative_seed unless user_guidance steers elsewhere. Return ONLY the requested schema key."
                if mode == "scratch"
                else f"FOCUS EXCLUSIVELY ON '{target_label}'. Expand, sharpen, and enrich ONLY '{target_label}'—preserving every specific plot thread, NPC, faction, and tone the user supplied while staying consistent with the rest of current_draft and campaign_seed. Return ONLY the requested schema key."
            )
        else:
            prev_field_val = None
            if mode == "scratch" and not lock_choices:
                requested_schema = {
                    "district": "Pick 1 district name from available_options.districts",
                    "caper_style": "Short label for the kind of caper this campaign runs",
                    "factions": ["1 to 4 active factions: corporations from available_options.factions or fitting Night City 2045 gangs"],
                    **full_schema,
                }
                mode_rule = (
                    "Design a fresh, ready-to-play Cyberpunk RED Night City 2045 campaign starter from scratch. "
                    "YOU decide the best Starting District (pick from available_options.districts), Campaign/Caper Style (a short label you write), "
                    "1-4 active Gangs/Factions (pick from available_options.factions or fitting Night City gangs), and choose an organic number of starting NPCs (2-5) "
                    "and starting Objectives (2-4) tailored to the premise. Follow the Corebook Beat Chart structure (Hook -> Developments -> Cliffhangers -> Climax -> Resolution) "
                    "and draw on creative_seed unless user_guidance overrides it."
                )
            elif mode == "scratch":
                requested_schema = full_schema
                count_parts: list[str] = []
                if npc_count is not None:
                    count_parts.append(f"Generate EXACTLY {npc_count} entries in 'npcs'.")
                if obj_count is not None:
                    count_parts.append(f"Generate EXACTLY {obj_count} entries in 'objectives'.")
                count_note = " ".join(count_parts)
                mode_rule = (
                    "Design a fresh, ready-to-play Cyberpunk RED Night City 2045 campaign starter strictly adhering to Corebook lore and Beat Chart structure. "
                    f"LOCKED CONSTRAINTS: Build the entire campaign AROUND the user's locked campaign_seed (district, caper_style, factions). Do NOT change or ignore those locked choices. {count_note}"
                ).strip()
            else:
                requested_schema = full_schema
                mode_rule = (
                    "The GM/player already wrote campaign notes/ideas. EXPAND, SHARPEN, and STRUCTURE their draft—preserving every specific plot thread, district, NPC, and faction they supplied while fleshing out Corebook-faithful hooks, Beat Chart stages, Fixer patrons, and GM secrets."
                )
        effective_seed = (
            {
                "name": camp_brief.get("name") or "",
                "lock_choices": lock_choices,
                **(
                    {
                        "district": camp_brief.get("district") or camp_meta.get("district") or "",
                        "caper_style": camp_brief.get("caper_style") or camp_meta.get("caper_style") or "",
                        "factions": camp_brief.get("factions") or camp_meta.get("factions") or [],
                        **({"campaign_meta": camp_meta} if camp_meta else {}),
                        **({"target_npc_count": npc_count} if npc_count is not None else {}),
                        **({"target_objective_count": obj_count} if obj_count is not None else {}),
                    }
                    if (lock_choices or mode != "scratch" or field is not None)
                    else {"screamsheet_hook": camp_brief.get("screamsheet_hook") or camp_meta.get("screamsheet_hook") or ""}
                ),
            }
        )
        user_payload = {
            "task": "campaign_setup",
            "mode": mode,
            **({"target_field": field} if field else {}),
            **({"target_entry_index": entry_index} if entry_index is not None else {}),
            **({"target_sub_field": sub_field} if sub_field else {}),
            **({"target_entry": targeted_camp_entry} if targeted_camp_entry is not None else {}),
            "instruction": mode_rule,
            "user_guidance": guidance or "(none)",
            "campaign_seed": effective_seed,
            **(
                {
                    "available_options": {
                        "districts": available_districts,
                        "factions": available_factions,
                    }
                }
                if (mode == "scratch" and field is None and not lock_choices)
                else {}
            ),
            "current_draft": current_draft,
            "corebook_context": lore_block,
            "required_json_schema": requested_schema,
        }
        if scratch_seed:
            user_payload["creative_seed"] = scratch_seed
            if field is not None and prev_field_val:
                prev_str = json.dumps(prev_field_val, ensure_ascii=False) if isinstance(prev_field_val, (dict, list)) else str(prev_field_val)
                if prev_str.strip():
                    user_payload["avoid_repeating"] = f"Generate a completely fresh alternative for '{field}'; avoid repeating: {prev_str[:300]}"
            else:
                prev_camp = " | ".join(
                    str(current_draft.get(k) or "")[:120]
                    for k in ("name", "summary", "opening_scene")
                    if str(current_draft.get(k) or "").strip()
                )
                if prev_camp:
                    user_payload["avoid_repeating"] = f"Generate a completely fresh premise, cast, and hook; avoid repeating: {prev_camp[:320]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    base_temp = float(llm_cfg.get("creation_temperature", 0.85))
    effective_temp = min(1.5, base_temp + 0.1) if mode == "scratch" else max(0.0, base_temp - 0.15)
    thinking_kwargs = (
        {"enable_thinking": False}
        if llm_cfg.get("gm_thinking_mode", "quality") == "balanced" and _supports_enable_thinking(llm.complete)
        else {}
    )
    raw_reply = await llm.complete(
        messages,
        json_mode=True,
        temperature=effective_temp,
        **thinking_kwargs,
    )
    cleaned = _strip_json_fences(raw_reply)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as first_err:
        repair_messages = [
            *messages,
            {"role": "assistant", "content": str(raw_reply)[:4000]},
            {
                "role": "user",
                "content": (
                    f"Your previous reply was not valid JSON ({first_err}). "
                    "Return ONLY a single valid JSON object matching required_json_schema, with no markdown fences, commentary, or <think> tags."
                ),
            },
        ]
        raw_reply = await llm.complete(
            repair_messages,
            json_mode=True,
            temperature=0.0,
            **thinking_kwargs,
        )
        cleaned = _strip_json_fences(raw_reply)
        parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned non-object JSON for creation AI assist")

    if target == "bio":
        out: dict[str, Any] = {"target": "bio", "mode": mode, "citations": citations}
        if field:
            out["field"] = field
            out[field] = str(parsed.get(field) or "").strip()
        else:
            out["concept"] = str(parsed.get("concept") or "").strip()
            out["summary"] = str(parsed.get("summary") or "").strip()
            out["established_history"] = str(parsed.get("established_history") or "").strip()
            out["appearance"] = str(parsed.get("appearance") or "").strip()
        return out

    if target == "campaign":
        raw_npcs = parsed.get("npcs") if isinstance(parsed.get("npcs"), dict) else {}
        npcs_out = {
            str(k).strip(): str(v).strip()
            for k, v in raw_npcs.items()
            if str(k).strip() and str(v).strip()
        }
        raw_obj = parsed.get("objectives") if isinstance(parsed.get("objectives"), dict) else {}
        obj_out = {
            str(k).strip(): str(v).strip()
            for k, v in raw_obj.items()
            if str(k).strip() and str(v).strip()
        }
        raw_disc = parsed.get("discoveries") if isinstance(parsed.get("discoveries"), dict) else {}
        disc_out = {
            str(k).strip(): str(v).strip()
            for k, v in raw_disc.items()
            if str(k).strip() and str(v).strip()
        }
        raw_locs = parsed.get("locations") if isinstance(parsed.get("locations"), list) else []
        locs_out = [
            {
                "name": str(loc.get("name")).strip(),
                "district": str(loc.get("district") or "").strip(),
                "notes": str(loc.get("notes") or "").strip(),
            }
            for loc in raw_locs[:6]
            if isinstance(loc, dict) and str(loc.get("name") or "").strip()
        ]
        raw_gig = parsed.get("gig") if isinstance(parsed.get("gig"), dict) else {}
        gig_out = (
            {
                "title": str(raw_gig.get("title") or "").strip(),
                "client": str(raw_gig.get("client") or "").strip(),
                "target": str(raw_gig.get("target") or "").strip(),
                "payout_eb": int(raw_gig["payout_eb"]) if isinstance(raw_gig.get("payout_eb"), (int, float)) else 2000,
                "deadline": str(raw_gig.get("deadline") or "").strip(),
                "notes": str(raw_gig.get("notes") or "").strip(),
            }
            if any(str(raw_gig.get(k) or "").strip() for k in ("title", "client", "target", "notes"))
            else None
        )
        raw_beats = parsed.get("beat_chart") if isinstance(parsed.get("beat_chart"), dict) else {}
        beat_chart_out = {
            "hook": str(raw_beats.get("hook") or "").strip(),
            "developments": str(raw_beats.get("developments") or "").strip(),
            "cliffhanger": str(raw_beats.get("cliffhanger") or "").strip(),
            "climax": str(raw_beats.get("climax") or "").strip(),
            "resolution": str(raw_beats.get("resolution") or "").strip(),
        }
        raw_clock = parsed.get("opening_clock") if isinstance(parsed.get("opening_clock"), dict) else {}
        seg_val = raw_clock.get("segments", 4)
        segments = seg_val if isinstance(seg_val, int) and 2 <= seg_val <= 12 else 4
        opening_clock_out = (
            {
                "name": str(raw_clock.get("name")).strip(),
                "segments": segments,
                "note": str(raw_clock.get("note") or "").strip(),
            }
            if str(raw_clock.get("name") or "").strip()
            else None
        )
        if field:
            out = {"target": "campaign", "mode": mode, "field": field, "citations": citations}
            if entry_index is not None and sub_field is not None:
                out["entry_index"] = entry_index
                out["sub_field"] = sub_field
                out["value"] = str(parsed.get("value") or parsed.get(sub_field) or "").strip()
            elif field in _BEAT_KEY_TO_FIELD:
                beat_key = _BEAT_KEY_TO_FIELD[field][0]
                val = str(raw_beats.get(beat_key) or parsed.get(beat_key) or parsed.get(field) or "").strip()
                out["beat_chart"] = {beat_key: val}
            elif field in _CAMPAIGN_GIG_FIELDS:
                gig_key = _CAMPAIGN_GIG_FIELDS[field][0]
                out[field] = str(parsed.get(field) or raw_gig.get(gig_key) or "").strip()
            elif field in _CAMPAIGN_CLOCK_FIELDS:
                clock_key = _CAMPAIGN_CLOCK_FIELDS[field][0]
                out[field] = str(parsed.get(field) or raw_clock.get(clock_key) or "").strip()
            elif field == "beat_chart":
                out["beat_chart"] = beat_chart_out
            elif field == "npcs":
                out["npcs"] = npcs_out
            elif field == "objectives":
                out["objectives"] = obj_out
            elif field == "discoveries":
                out["discoveries"] = disc_out
            elif field == "locations":
                out["locations"] = locs_out
            elif field == "gig":
                out["gig"] = gig_out
            elif field == "opening_clock":
                out["opening_clock"] = opening_clock_out
            else:
                out[field] = str(parsed.get(field) or "").strip()
            return out
        raw_factions = parsed.get("factions") if isinstance(parsed.get("factions"), list) else []
        factions_out = [str(f).strip() for f in raw_factions if str(f).strip()][:4]
        district_out = str(parsed.get("district") or "").strip()
        style_out = str(parsed.get("caper_style") or "").strip()
        return {
            "target": "campaign",
            "mode": mode,
            "name": str(parsed.get("name") or "").strip(),
            **({"district": district_out} if district_out and not lock_choices else {}),
            **({"caper_style": style_out} if style_out and not lock_choices else {}),
            **({"factions": factions_out} if factions_out and not lock_choices else {}),
            "summary": str(parsed.get("summary") or "").strip(),
            "opening_scene": str(parsed.get("opening_scene") or "").strip(),
            "npcs": npcs_out,
            "objectives": obj_out,
            **({"discoveries": disc_out} if disc_out else {}),
            **({"locations": locs_out} if locs_out else {}),
            **({"gig": gig_out} if gig_out else {}),
            "beat_chart": beat_chart_out,
            "gm_secrets": str(parsed.get("gm_secrets") or "").strip(),
            "opening_clock": opening_clock_out,
            "citations": citations,
        }

    friends_out = []
    for entry in parsed.get("friends") or []:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            friends_out.append({
                "name": str(entry.get("name")).strip(),
                "relationship": str(entry.get("relationship") or "Night City contact").strip(),
                "note": str(entry.get("note") or "").strip(),
            })
    enemies_out = []
    for entry in parsed.get("enemies") or []:
        if isinstance(entry, dict) and (str(entry.get("name") or "").strip() or str(entry.get("who") or "").strip()):
            raw_wronged = str(entry.get("wronged") or "They wronged me").strip()
            wronged = "I wronged them" if "i wronged" in raw_wronged.lower() else "They wronged me"
            enemies_out.append({
                "who": str(entry.get("who") or "Rival").strip(),
                "name": str(entry.get("name") or "Unnamed Rival").strip(),
                "wronged": wronged,
                "cause": str(entry.get("cause") or "Old score in Night City").strip(),
                "backup": str(entry.get("backup") or "Just themselves").strip(),
                "revenge": str(entry.get("revenge") or "Waiting for payback").strip(),
            })
    loves_out = []
    for entry in parsed.get("tragic_love_affairs") or []:
        if isinstance(entry, dict) and str(entry.get("name") or "").strip():
            loves_out.append({
                "name": str(entry.get("name")).strip(),
                "outcome": str(entry.get("outcome") or "Lost in Night City").strip(),
            })
    if field:
        out = {"target": "contacts", "mode": mode, "field": field, "citations": citations}
        if entry_index is not None and sub_field is not None:
            out["entry_index"] = entry_index
            out["sub_field"] = sub_field
            out["value"] = str(parsed.get("value") or parsed.get(sub_field) or "").strip()
        elif field == "friends":
            out["friends"] = friends_out
        elif field == "enemies":
            out["enemies"] = enemies_out
        else:
            out["tragic_love_affairs"] = loves_out
        return out
    return {
        "target": "contacts",
        "mode": mode,
        "friends": friends_out,
        "enemies": enemies_out,
        "tragic_love_affairs": loves_out,
        "citations": citations,
    }
