"""Server-side player redaction helpers for chat, SSE events, state patches, and campaign/character state."""
from __future__ import annotations

import copy
from typing import Any

_GM_ONLY_MESSAGE_META_KEYS = (
    "model",
    "generation_stats",
    "guidance",
    "citation_cards",
    "citations",
    "warnings",
    "library_added",
)

_GM_ONLY_SSE_EVENTS = frozenset({"rule_citation", "warning", "library_added"})


def _redact_hidden_npc_identities(mapping: dict[str, Any]) -> None:
    """Strip hidden NPC real names from npc_identities maps or __npc_real:* keys."""
    for key in [k for k in mapping if str(k).startswith("__npc_real:")]:
        mapping.pop(key, None)
    npc_ids = mapping.get("npc_identities")
    if isinstance(npc_ids, dict):
        for entry in npc_ids.values():
            if isinstance(entry, dict) and entry.get("real_name_hidden"):
                entry.pop("real_name", None)


def _redact_patch_section(section: dict[str, Any]) -> dict[str, Any]:
    sec = copy.deepcopy(section)
    sec.pop("gm_secrets", None)
    sec.pop("unresolved", None)
    if isinstance(sec.get("discoveries"), dict):
        sec["discoveries"] = {
            k: v for k, v in sec["discoveries"].items() if not str(k).startswith("__")
        }
    if sec.get("real_name_hidden") and "real_name" in sec:
        sec["real_name"] = ""
    if isinstance(sec.get("detail"), dict) and sec["detail"].get("real_name_hidden") and "real_name" in sec["detail"]:
        sec["detail"]["real_name"] = ""
    _redact_hidden_npc_identities(sec)
    return sec


def redact_state_patch(patch: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a state_patch diff formatted for the caller's visibility level."""
    if is_gm or not isinstance(patch, dict):
        return patch
    out = copy.deepcopy(patch)
    out.pop("gm_secrets", None)
    out.pop("unresolved", None)
    for key in ("before", "after", "changes"):
        if isinstance(out.get(key), dict):
            out[key] = _redact_patch_section(out[key])
    return out


def redact_chat_message(msg: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a chat message formatted for the caller's visibility level."""
    if is_gm or not isinstance(msg, dict):
        return msg
    out = copy.deepcopy(msg)
    out.pop("raw_content", None)
    out.pop("model", None)
    meta = out.get("metadata")
    if isinstance(meta, dict):
        for key in _GM_ONLY_MESSAGE_META_KEYS:
            meta.pop(key, None)
        if isinstance(meta.get("patches"), list):
            meta["patches"] = [
                redact_state_patch(p, is_gm=False) if isinstance(p, dict) else p
                for p in meta["patches"]
            ]
    return out


def redact_chat_tree(
    tree: dict[str, Any],
    *,
    is_gm: bool,
    allowed_channels: set[str] | None = None,
) -> dict[str, Any]:
    """Return a chat tree payload formatted for the caller's visibility level."""
    if is_gm or not isinstance(tree, dict):
        return tree
    out = copy.deepcopy(tree)
    allowed = {str(c or "main") for c in allowed_channels} if allowed_channels is not None else None
    for list_key in ("nodes", "messages", "active_branch"):
        if isinstance(out.get(list_key), list):
            items = out[list_key]
            if allowed is not None:
                items = [
                    m for m in items
                    if isinstance(m, dict) and str(m.get("channel_id") or "main") in allowed
                ]
            out[list_key] = [redact_chat_message(m, is_gm=False) for m in items]
    if allowed is not None:
        if isinstance(out.get("channels"), list):
            out["channels"] = [c for c in out["channels"] if str(c or "main") in allowed]
        if str(out.get("channel_id") or "main") not in allowed:
            out["active_leaf_id"] = None
    return out


def redact_sse_event(event: str, data: dict[str, Any], *, is_gm: bool) -> dict[str, Any] | None:
    """Return an SSE event data dict formatted for the caller's visibility level, or None to suppress."""
    if is_gm or not isinstance(data, dict):
        return data
    if event in _GM_ONLY_SSE_EVENTS:
        return None
    if event == "state_patch":
        return redact_state_patch(data, is_gm=False)
    if event in {"turn_done", "peer_turn_done"}:
        out = copy.deepcopy(data)
        if isinstance(out.get("user_message"), dict):
            out["user_message"] = redact_chat_message(out["user_message"], is_gm=False)
        if isinstance(out.get("assistant_message"), dict):
            out["assistant_message"] = redact_chat_message(out["assistant_message"], is_gm=False)
        for key in ("citations", "warnings", "library_added", "generation_stats"):
            out.pop(key, None)
        for patch_key in ("state_patches", "patches"):
            if isinstance(out.get(patch_key), list):
                out[patch_key] = [
                    redact_state_patch(p, is_gm=False) if isinstance(p, dict) else p
                    for p in out[patch_key]
                ]
        return out
    if event == "peer_user_message":
        out = copy.deepcopy(data)
        if isinstance(out.get("message"), dict):
            out["message"] = redact_chat_message(out["message"], is_gm=False)
        return out
    if event == "peer_stream":
        inner_ev = str(data.get("event") or "")
        inner_data = data.get("data")
        if isinstance(inner_data, dict):
            redacted_inner = redact_sse_event(inner_ev, inner_data, is_gm=False)
            if redacted_inner is None:
                return None
            out = copy.deepcopy(data)
            out["data"] = redacted_inner
            return out
    return copy.deepcopy(data)


def redact_character(char: dict[str, Any], *, is_gm: bool, viewer_username: str = "") -> dict[str, Any]:
    """Return a character dict formatted for the caller's visibility level."""
    if is_gm or not isinstance(char, dict):
        return char
    out = copy.deepcopy(char)
    detail = out.get("detail")
    if isinstance(detail, dict):
        owner = str(detail.get("owner_username") or "").strip()
        viewer = (viewer_username or "").strip()
        is_owner = bool(viewer and owner and owner.lower() == viewer.lower())
        if not is_owner:
            if detail.get("real_name_hidden"):
                hidden_real = str(detail.get("real_name") or "").strip()
                detail["real_name"] = ""
                handle = str(detail.get("handle") or "").strip()
                if handle and (not out.get("name") or (hidden_real and str(out.get("name") or "").strip() == hidden_real)):
                    out["name"] = handle
            bs = detail.get("backstory")
            bs_private = bool(detail.get("backstory_hidden")) or (isinstance(bs, dict) and bool(bs.get("private")))
            if bs_private:
                if isinstance(bs, dict):
                    public_bs = {k: v for k, v in bs.items() if k in {"appearance", "gender", "pronouns"}}
                    if public_bs:
                        detail["backstory"] = public_bs
                    else:
                        detail.pop("backstory", None)
                else:
                    detail.pop("backstory", None)
    return out


def redact_campaign(camp: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a campaign dict with GM-only unresolved threads and __* discovery blobs stripped."""
    if is_gm or not isinstance(camp, dict):
        return camp
    out = copy.deepcopy(camp)
    state = out.get("state")
    if isinstance(state, dict):
        state["unresolved"] = {}
        if isinstance(state.get("discoveries"), dict):
            state["discoveries"] = {
                k: v for k, v in state["discoveries"].items() if not str(k).startswith("__")
            }
    return out


def redact_campaign_context(ctx: dict[str, Any], *, is_gm: bool, viewer_username: str = "") -> dict[str, Any]:
    """Return a campaign_context payload with GM-only fields stripped when not authorized."""
    if is_gm or not isinstance(ctx, dict):
        return ctx
    out = copy.deepcopy(ctx)
    out.pop("gm_secrets", None)
    if isinstance(out.get("campaign"), dict):
        out["campaign"] = redact_campaign(out["campaign"], is_gm=False)
    if isinstance(out.get("characters"), list):
        out["characters"] = [
            redact_character(c, is_gm=False, viewer_username=viewer_username)
            for c in out["characters"]
        ]
    if isinstance(out.get("solo"), dict):
        out["solo"] = _redact_solo_characters(out["solo"], viewer_username)
    if isinstance(out.get("clocks"), list):
        out["clocks"] = [
            c for c in out["clocks"] if isinstance(c, dict) and c.get("visibility") != "secret"
        ]
    if isinstance(out.get("npc_profiles"), dict):
        for prof in out["npc_profiles"].values():
            if isinstance(prof, dict) and prof.get("real_name_hidden"):
                prof.pop("real_name", None)
    return out


def _redact_solo_characters(payload: dict[str, Any], viewer_username: str) -> dict[str, Any]:
    """Redact the ``characters`` list (solo action responses) or id map (solo_context)."""
    out = dict(payload)
    chars = out.get("characters")
    if isinstance(chars, list):
        out["characters"] = [redact_character(c, is_gm=False, viewer_username=viewer_username) for c in chars]
    elif isinstance(chars, dict):
        out["characters"] = {
            k: redact_character(c, is_gm=False, viewer_username=viewer_username) for k, c in chars.items()
        }
    return out


def _redact_campaign_event(event: Any) -> Any:
    if not isinstance(event, dict):
        return event
    out = dict(event)
    for key in ("result", "before", "after"):
        if isinstance(out.get(key), dict):
            out[key] = redact_campaign(out[key], is_gm=False)
    payload = out.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("changes"), dict):
        out["payload"] = {**payload, "changes": _redact_patch_section(payload["changes"])}
    return out


def _redact_character_event(event: Any, viewer_username: str) -> Any:
    if not isinstance(event, dict):
        return event
    out = dict(event)
    for key in ("before", "after"):
        if isinstance(out.get(key), dict):
            out[key] = redact_character(out[key], is_gm=False, viewer_username=viewer_username)
    return out


def redact_game_result(action: str, result: Any, *, solo_actions: frozenset[str] | set[str], viewer_username: str = "") -> Any:
    """Strip GM-only campaign/character data from a non-GM ``/v1/game`` result (campaign_context excluded)."""
    if action in solo_actions:
        return _redact_solo_characters(result, viewer_username) if isinstance(result, dict) else result
    if action == "get_campaign" and isinstance(result, dict):
        return redact_campaign(result, is_gm=False)
    if action == "list_campaigns" and isinstance(result, list):
        return [redact_campaign(c, is_gm=False) for c in result]
    if action == "campaign_history" and isinstance(result, list):
        return [_redact_campaign_event(e) for e in result]
    if action == "get_character" and isinstance(result, dict):
        return redact_character(result, is_gm=False, viewer_username=viewer_username)
    if action == "list_characters" and isinstance(result, list):
        return [redact_character(c, is_gm=False, viewer_username=viewer_username) for c in result]
    if action == "history" and isinstance(result, list):
        return [_redact_character_event(e, viewer_username) for e in result]
    return result
