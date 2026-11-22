"""Smart-GM turn intervention router."""
from __future__ import annotations

import re
from typing import Any


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
) -> tuple[bool, str]:
    """Decide if the AI GM should respond immediately or let party members reply first."""
    clean = (user_text or "").strip()
    if not clean:
        return True, ""
    if overclock or luck_spend > 0:
        return True, ""

    # Pure OOC table chatter: ((...)) or // ... or [OOC: ...]
    if (clean.startswith("((") and clean.endswith("))")) or clean.lower().startswith(("[ooc", "//")):
        return False, "OOC table note — GM standing by"

    # Count consecutive user turns at the end of the branch without an assistant reply
    consecutive_user_turns = 0
    for msg in reversed(branch):
        if msg.get("role") == "user":
            consecutive_user_turns += 1
        else:
            break

    # Never skip the GM twice in a row automatically
    if consecutive_user_turns >= 1:
        return True, ""

    # In solo play (only 1 player online), always let the GM respond to non-OOC turns
    if coop_player_count <= 1 and len(characters) <= 1:
        return True, ""

    # Check if the player is directly addressing a teammate PC by handle/name without world/NPC action
    speaker_id = speaker.get("id") or ""
    speaker_name = (speaker.get("name") or "").strip().lower()
    other_pc_names = set()
    for c in characters:
        if c.get("id") == speaker_id:
            continue
        cname = str(c.get("name") or "").strip().lower()
        handle = str((c.get("detail") or {}).get("handle") or "").strip().lower()
        if cname and cname != speaker_name:
            other_pc_names.add(cname)
        if handle and handle != speaker_name:
            other_pc_names.add(handle)

    lower_text = clean.lower()
    addresses_teammate = any(
        re.search(rf"(?:^|\b|@){re.escape(pc_name)}\b", lower_text)
        for pc_name in other_pc_names
        if len(pc_name) >= 2
    )
    mentions_npc = any(
        re.search(rf"\b{re.escape(npc_name.split('(')[0].strip().lower())}\b", lower_text)
        for npc_name in (npcs or {})
        if len(npc_name.split("(")[0].strip()) >= 3
    )
    world_action_re = re.compile(
        r"\b(shoot|fire|attack|aim|draw|hack|jack in|breach|scan|search|inspect|open|kick|unlock|pick|sneak|hide|run|drive|walk|enter|climb|grab|take|throw|reload|heal|stabilize|roll|check|look around|ask the|tell the)\b",
        re.I,
    )
    has_world_action = bool(world_action_re.search(clean))

    if addresses_teammate and not mentions_npc and not has_world_action:
        return False, "Party conversation — waiting for teammate reply (or click 'Resolve GM Turn')"

    return True, ""
