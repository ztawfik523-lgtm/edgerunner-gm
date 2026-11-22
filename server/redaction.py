"""Server-side player redaction helpers for chat, SSE events, state patches, and campaign/character state."""
from __future__ import annotations

from typing import Any


def redact_chat_message(msg: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a chat message formatted for the caller's visibility level."""
    if is_gm or not isinstance(msg, dict):
        return msg
    return dict(msg)


def redact_chat_tree(tree: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a chat tree payload formatted for the caller's visibility level."""
    if is_gm or not isinstance(tree, dict):
        return tree
    return dict(tree)


def redact_state_patch(patch: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return a state_patch diff formatted for the caller's visibility level."""
    if is_gm or not isinstance(patch, dict):
        return patch
    return dict(patch)


def redact_sse_event(event: str, data: dict[str, Any], *, is_gm: bool) -> dict[str, Any]:
    """Return an SSE event data dict formatted for the caller's visibility level."""
    if is_gm or not isinstance(data, dict):
        return data
    return dict(data)


def redact_character(char: dict[str, Any], *, is_gm: bool, viewer_username: str = "") -> dict[str, Any]:
    """Return a character dict formatted for the caller's visibility level."""
    if is_gm or not isinstance(char, dict):
        return char
    return dict(char)


def redact_campaign_context(ctx: dict[str, Any], *, is_gm: bool, viewer_username: str = "") -> dict[str, Any]:
    """Return a campaign_context payload with GM-only fields stripped when not authorized."""
    if not isinstance(ctx, dict):
        return ctx
    if is_gm:
        return ctx
    out = dict(ctx)
    out.pop("gm_secrets", None)
    return out
