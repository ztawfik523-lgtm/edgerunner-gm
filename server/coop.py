"""In-memory per-campaign presence, per-channel turn locks, and SSE fanout for LAN co-op play."""
from __future__ import annotations

import asyncio
import time
from typing import Any


class _CoopHub:
    """In-memory per-campaign presence, per-channel turn locks, and SSE fanout for LAN co-op play."""

    def __init__(self, ttl_s: float = 45.0):
        self.ttl_s = ttl_s
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.presence: dict[str, dict[str, dict[str, Any]]] = {}
        self.active_turns: dict[tuple[str, str], dict[str, Any]] = {}
        self.sync_seq: dict[str, int] = {}

    @staticmethod
    def _norm_chan(channel_id: str | None) -> str:
        clean = str(channel_id or "main").strip()
        return clean[:80] if clean else "main"

    def current_seq(self, campaign_id: str) -> int:
        return int(self.sync_seq.get(campaign_id, 0))

    def bump_seq(self, campaign_id: str) -> int:
        nxt = int(self.sync_seq.get(campaign_id, 0)) + 1
        self.sync_seq[campaign_id] = nxt
        return nxt

    def _prune(self, campaign_id: str) -> None:
        cutoff = time.time() - self.ttl_s
        members = self.presence.get(campaign_id)
        if not members:
            return
        stale = [cid for cid, entry in members.items() if entry.get("ts", 0.0) < cutoff]
        for cid in stale:
            del members[cid]

    def roster(self, campaign_id: str) -> list[dict[str, Any]]:
        self._prune(campaign_id)
        members = list(self.presence.get(campaign_id, {}).values())
        members.sort(key=lambda m: (not bool(m.get("is_host")), str(m.get("player_name") or "").casefold(), str(m.get("client_id") or "")))
        return [{k: v for k, v in m.items() if k != "ts"} for m in members]

    def active_turn_for(self, campaign_id: str, channel_id: str = "main") -> dict[str, Any] | None:
        chan = self._norm_chan(channel_id)
        now = time.time()
        existing = self.active_turns.get((campaign_id, chan))
        if existing and now - float(existing.get("started_at", 0.0)) < 180.0:
            return existing
        if existing:
            self.active_turns.pop((campaign_id, chan), None)
        return None

    def all_active_turns(self, campaign_id: str) -> dict[str, dict[str, Any]]:
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        stale_keys: list[tuple[str, str]] = []
        for (cid, chan), info in self.active_turns.items():
            if cid != campaign_id:
                continue
            if now - float(info.get("started_at", 0.0)) < 180.0:
                out[chan] = info
            else:
                stale_keys.append((cid, chan))
        for k in stale_keys:
            self.active_turns.pop(k, None)
        return out

    def publish(self, campaign_id: str, event: str, data: dict[str, Any]) -> None:
        payload_data = dict(data)
        if event == "sync" and "sync_seq" not in payload_data:
            payload_data["sync_seq"] = self.bump_seq(campaign_id)
        queues = list(self.subscribers.get(campaign_id) or ())
        for q in queues:
            try:
                q.put_nowait({"event": event, "data": payload_data})
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait({"event": event, "data": payload_data})
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def update_presence(
        self,
        campaign_id: str,
        *,
        client_id: str,
        player_name: str,
        character_id: str | None = None,
        is_host: bool = False,
    ) -> list[dict[str, Any]]:
        self._prune(campaign_id)
        bucket = self.presence.setdefault(campaign_id, {})
        bucket[client_id] = {
            "client_id": client_id,
            "player_name": player_name[:40] or "Player",
            "character_id": character_id or None,
            "is_host": bool(is_host),
            "ts": time.time(),
        }
        roster = self.roster(campaign_id)
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "presence",
            {
                "campaign_id": campaign_id,
                "players": roster,
                "active_turn": turns.get("main") or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": self.current_seq(campaign_id),
            },
        )
        return roster

    def acquire_turn(self, campaign_id: str, *, client_id: str, player_name: str, channel_id: str = "main") -> dict[str, Any] | None:
        chan = self._norm_chan(channel_id)
        existing = self.active_turn_for(campaign_id, chan)
        if existing and existing.get("client_id") != client_id:
            return existing
        info = {"client_id": client_id, "player_name": player_name or "Player", "channel_id": chan, "started_at": time.time()}
        self.active_turns[(campaign_id, chan)] = info
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "turn_started",
            {
                "campaign_id": campaign_id,
                "channel_id": chan,
                "active_turn": info,
                "active_turns": turns,
            },
        )
        return None

    def touch_turn(self, campaign_id: str, client_id: str, channel_id: str = "main") -> None:
        """Refresh active turn lock timestamp while long-running turns stream."""
        chan = self._norm_chan(channel_id)
        existing = self.active_turns.get((campaign_id, chan))
        if existing and existing.get("client_id") == client_id:
            existing["started_at"] = time.time()

    def release_turn(self, campaign_id: str, client_id: str, channel_id: str = "main") -> None:
        chan = self._norm_chan(channel_id)
        existing = self.active_turns.get((campaign_id, chan))
        if existing and existing.get("client_id") == client_id:
            del self.active_turns[(campaign_id, chan)]
        turns = self.all_active_turns(campaign_id)
        self.publish(
            campaign_id,
            "turn_finished",
            {
                "campaign_id": campaign_id,
                "channel_id": chan,
                "active_turn": turns.get(chan) or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": self.current_seq(campaign_id),
            },
        )

    def clear_campaign(self, campaign_id: str) -> None:
        """Remove all in-memory presence, turn locks, and sync state for a deleted campaign."""
        self.presence.pop(campaign_id, None)
        self.sync_seq.pop(campaign_id, None)
        for key in [k for k in self.active_turns if k[0] == campaign_id]:
            self.active_turns.pop(key, None)
        self.subscribers.pop(campaign_id, None)
