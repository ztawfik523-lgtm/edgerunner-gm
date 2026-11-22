"""Smart-GM turn intervention router."""
from __future__ import annotations

import re
from typing import Any

_OOC_PARENS_RE = re.compile(r"\(\(.*?\)\)", re.S)
_OOC_BRACKET_RE = re.compile(r"\[ooc(?:\s*:[^\]]*|\s+[^\]]*)?\]", re.I | re.S)
_OOC_LINE_RE = re.compile(r"(?m)^\s*//.*$")
_THINK_PREFIX_RE = re.compile(r"^/think(?:\s+.*)?$", re.I | re.S)
_WORLD_ACTION_RE = re.compile(
    r"\b(shoot|fire|attack|aim|draw|hack|jack in|breach|scan|search|inspect|open|kick|unlock|pick|sneak|hide|run|drive|walk|enter|climb|grab|take|throw|reload|heal|stabilize|roll|check|look around|ask the|tell the)\b",
    re.I,
)


def _strip_ooc_blocks(text: str) -> str:
    """Remove all OOC annotations (`((...))`, `[OOC: ...]`, `// ...`) leaving only IC content."""
    ic = _OOC_PARENS_RE.sub(" ", text or "")
    ic = _OOC_BRACKET_RE.sub(" ", ic)
    ic = _OOC_LINE_RE.sub("", ic)
    return " ".join(ic.split()).strip()


def should_gm_intervene(
    user_text: str,
    *,
    branch: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    npcs: dict[str, Any],
    speaker: dict[str, str],
    coop_player_count: int = 1,
    overclock: bool = False,
    luck_spend: int = 0,
    turn_intent: str = "action",
) -> tuple[bool, str]:
    """Decide if the AI GM should respond immediately or let party members reply first."""
    clean = (user_text or "").strip()
    if str(turn_intent or "action").strip().lower() == "think" or _THINK_PREFIX_RE.match(clean):
        return True, ""
    if not clean:
        return True, ""
    if overclock or luck_spend > 0:
        return True, ""

    # In 1-player solo play, always trigger GM on OOC directives and multi-PC dialogue unless explicitly in hold_gm.
    if coop_player_count <= 1:
        return True, ""

    # Strip all ((...)), [OOC:...], and // lines before checking pure OOC so mixed OOC+IC turns are never swallowed.
    ic_text = _strip_ooc_blocks(clean)
    if not ic_text:
        return False, "OOC table note — GM standing by"

    # Count consecutive IC user turns at the end of the branch without an assistant reply,
    # ignoring system dividers, pure OOC notes, and manual roll messages.
    consecutive_user_turns = 0
    for msg in reversed(branch):
        role = msg.get("role")
        meta = msg.get("metadata") or {}
        if role == "system":
            continue
        if role == "user":
            if meta.get("manual_roll"):
                continue
            if not _strip_ooc_blocks(str(msg.get("content") or "")):
                continue
            consecutive_user_turns += 1
        else:
            break

    # Never skip the GM twice in a row automatically
    if consecutive_user_turns >= 1:
        return True, ""

    # Check if the player is directly addressing a teammate PC by handle/name without world/NPC action
    speaker_id = speaker.get("id") or ""
    speaker_name = (speaker.get("name") or "").strip().lower()
    other_pc_names: set[str] = set()
    for c in characters:
        if c.get("id") == speaker_id:
            continue
        d = c.get("detail") or {}
        cname = str(c.get("name") or "").strip().lower()
        handle = str(d.get("handle") or "").strip().lower()
        hidden = bool(d.get("real_name_hidden", False))
        cands: list[str] = []
        if handle:
            cands.append(handle)
        if cname and (not hidden or not handle):
            cands.append(cname)
        for cand in cands:
            if cand != speaker_name:
                other_pc_names.add(cand)
            first_tok = cand.split()[0] if cand.split() else ""
            if len(first_tok) >= 2 and first_tok != speaker_name:
                other_pc_names.add(first_tok)

    lower_ic = ic_text.lower()
    addresses_teammate = any(
        re.search(rf"(?<!\w)@?{re.escape(pc_name)}(?!\w)", lower_ic)
        for pc_name in other_pc_names
        if len(pc_name) >= 2 or (len(pc_name) == 1 and pc_name not in {"a", "i"})
    )

    npc_terms: set[str] = set()
    for npc_name in (npcs or {}):
        base = str(npc_name).split("(", 1)[0].strip().lower()
        if len(base) >= 3:
            npc_terms.add(base)
            first_tok = base.split()[0] if base.split() else ""
            if len(first_tok) >= 3:
                npc_terms.add(first_tok)
    mentions_npc = any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lower_ic)
        for term in npc_terms
    )
    has_world_action = bool(_WORLD_ACTION_RE.search(ic_text))

    if addresses_teammate and not mentions_npc and not has_world_action:
        return False, "Party conversation — waiting for teammate reply (or click 'Resolve GM Turn')"

    return True, ""
