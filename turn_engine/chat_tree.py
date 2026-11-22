"""Persistent branching chat tree and branch-scoped private GM state store."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import re
import sqlite3
from typing import Any
import uuid

from campaign import _json
from gameplay import GameplayService
from turn_engine.state_normalization import _CLOCK_CATEGORIES


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
                    channel_id TEXT NOT NULL DEFAULT 'main',
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
            cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_messages)")}
            if "channel_id" not in cols:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'main'")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_camp_parent ON chat_messages(campaign_id, parent_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_camp_chan ON chat_messages(campaign_id, channel_id, parent_id, created_at)"
            )

    @staticmethod
    def _norm_channel(channel_id: str | None) -> str:
        clean = str(channel_id or "main").strip()
        return clean[:80] if clean else "main"

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "channel_id": row["channel_id"] if "channel_id" in keys and row["channel_id"] else "main",
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

    def has_children(self, campaign_id: str, message_id: str) -> bool:
        with closing(self.store._connect()) as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM chat_messages WHERE campaign_id=? AND parent_id=? LIMIT 1",
                    (campaign_id, message_id),
                ).fetchone()
            )

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
        channel_id: str = "main",
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("role must be user, assistant, or system")
        chan = self._norm_channel(channel_id)
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        raw = content if raw_content is None else raw_content
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise ValueError(f"campaign not found: {campaign_id}")
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT channel_id FROM chat_messages WHERE campaign_id=? AND id=?",
                    (campaign_id, parent_id),
                ).fetchone()
                if not parent:
                    raise ValueError(f"parent message not found in campaign: {parent_id}")
                parent_chan = self._norm_channel(parent["channel_id"] if "channel_id" in parent.keys() else "main")
                if parent_chan != chan:
                    chan = parent_chan
            if activate:
                if parent_id is None:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND channel_id=? AND parent_id IS NULL",
                        (campaign_id, chan),
                    )
                else:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND channel_id=? AND parent_id=?",
                        (campaign_id, chan, parent_id),
                    )
            conn.execute(
                """
                INSERT INTO chat_messages(
                    id, campaign_id, channel_id, parent_id, role, content, raw_content, model,
                    campaign_revision, solo_revision, metadata_json, is_active, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    msg_id,
                    campaign_id,
                    chan,
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

    def get_tree(self, campaign_id: str, channel_id: str = "main") -> dict[str, Any]:
        chan = self._norm_channel(channel_id)
        revs = self._current_revisions(campaign_id)
        with closing(self.store._connect()) as conn:
            chan_rows = conn.execute(
                "SELECT DISTINCT channel_id FROM chat_messages WHERE campaign_id=? ORDER BY channel_id",
                (campaign_id,),
            ).fetchall()
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? AND channel_id=? ORDER BY created_at, id",
                (campaign_id, chan),
            ).fetchall()
        channels = sorted({"main", *(self._norm_channel(r["channel_id"]) for r in chan_rows)}, key=lambda c: (0 if c == "main" else 1, c))
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
            "channel_id": chan,
            "channels": channels,
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
        visited: set[str] = set()
        while cur is not None:
            if cur["id"] in visited:
                break
            visited.add(cur["id"])
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
        target_chan = "main"
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                "SELECT channel_id FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            if target is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            target_chan = self._norm_channel(target["channel_id"] if "channel_id" in target.keys() else "main")
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? AND channel_id=? ORDER BY created_at, id",
                (campaign_id, target_chan),
            ).fetchall()
            by_id = {r["id"]: r for r in rows}
            if message_id not in by_id:
                raise ValueError(f"message not found in campaign: {message_id}")
            children: dict[str | None, list[sqlite3.Row]] = {}
            for r in rows:
                children.setdefault(r["parent_id"], []).append(r)
            cur_id: str | None = message_id
            visited: set[str] = set()
            while cur_id is not None and cur_id not in visited:
                visited.add(cur_id)
                row = by_id.get(cur_id)
                if row is None:
                    break
                parent_id = row["parent_id"]
                if parent_id is None:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND channel_id=? AND parent_id IS NULL",
                        (campaign_id, target_chan),
                    )
                else:
                    conn.execute(
                        "UPDATE chat_messages SET is_active=0 WHERE campaign_id=? AND channel_id=? AND parent_id=?",
                        (campaign_id, target_chan, parent_id),
                    )
                conn.execute("UPDATE chat_messages SET is_active=1 WHERE id=?", (cur_id,))
                cur_id = parent_id
            # Ensure the selected node's downward active chain has no duplicate active siblings.
            self._activate_descendant_chain(conn, campaign_id, message_id, children, set())
            # Sync non-manual-roll user message rolls to match the active sibling assistant branch.
            active_rows = conn.execute(
                "SELECT id, parent_id, role, metadata_json, is_active FROM chat_messages WHERE campaign_id=? AND channel_id=? AND is_active=1",
                (campaign_id, target_chan),
            ).fetchall()
            active_assistant_by_parent: dict[str, dict[str, Any]] = {}
            for a_row in active_rows:
                if a_row["role"] == "assistant" and a_row["parent_id"]:
                    try:
                        active_assistant_by_parent[str(a_row["parent_id"])] = json.loads(a_row["metadata_json"])
                    except (TypeError, json.JSONDecodeError):
                        pass
            for u_row in active_rows:
                if u_row["role"] != "user":
                    continue
                a_meta = active_assistant_by_parent.get(str(u_row["id"]))
                if not isinstance(a_meta, dict) or "rolls" not in a_meta:
                    continue
                try:
                    u_meta = json.loads(u_row["metadata_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if u_meta.get("manual_roll"):
                    continue
                a_rolls = a_meta.get("rolls") or []
                if a_rolls:
                    if u_meta.get("rolls") != a_rolls:
                        u_meta["rolls"] = a_rolls
                        conn.execute(
                            "UPDATE chat_messages SET metadata_json=? WHERE campaign_id=? AND id=?",
                            (_json(u_meta), campaign_id, u_row["id"]),
                        )
                elif "rolls" in u_meta:
                    u_meta.pop("rolls", None)
                    conn.execute(
                        "UPDATE chat_messages SET metadata_json=? WHERE campaign_id=? AND id=?",
                        (_json(u_meta), campaign_id, u_row["id"]),
                    )
        return self.get_tree(campaign_id, channel_id=target_chan)

    def delete_message(
        self, campaign_id: str, message_id: str, *, scope: str = "branch"
    ) -> dict[str, Any]:
        """Delete either a single message (re-parenting children) or the entire subtree below it."""
        if scope not in {"branch", "single"}:
            raise ValueError("scope must be 'branch' or 'single'")
        target_chan = "main"
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            target_meta = conn.execute(
                "SELECT channel_id FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            if target_meta is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            target_chan = self._norm_channel(target_meta["channel_id"] if "channel_id" in target_meta.keys() else "main")
            rows = conn.execute(
                "SELECT id, parent_id, is_active, created_at FROM chat_messages WHERE campaign_id=? AND channel_id=? ORDER BY created_at, id",
                (campaign_id, target_chan),
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
            has_pre_snapshots = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_pre_snapshots'"
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
                if has_pre_snapshots:
                    conn.execute(
                        "DELETE FROM turn_pre_snapshots WHERE campaign_id=? AND user_message_id=?",
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
                seen_del: set[str] = set()
                while queue:
                    cur = queue.pop(0)
                    if cur in seen_del:
                        continue
                    seen_del.add(cur)
                    to_delete.append(cur)
                    for ch in children.get(cur, []):
                        if ch["id"] not in seen_del:
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
                    if has_pre_snapshots:
                        conn.execute(
                            "DELETE FROM turn_pre_snapshots WHERE campaign_id=? AND user_message_id=?",
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
        return self.get_tree(campaign_id, channel_id=target_chan)

    def update_message(self, campaign_id: str, message_id: str, content: str) -> dict[str, Any]:
        """Update an existing message's text in place without spawning a new branch."""
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a nonempty string")
        cleaned = content.strip()
        target_chan = "main"
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT metadata_json, channel_id FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            target_chan = self._norm_channel(row["channel_id"] if "channel_id" in row.keys() else "main")
            meta = json.loads(row["metadata_json"])
            meta["edited"] = True
            meta["edited_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE chat_messages SET content=?, raw_content=?, metadata_json=? WHERE campaign_id=? AND id=?",
                (cleaned, cleaned, _json(meta), campaign_id, message_id),
            )
        return self.get_tree(campaign_id, channel_id=target_chan)

    def update_message_metadata(
        self,
        campaign_id: str,
        message_id: str,
        metadata_updates: dict[str, Any],
        *,
        campaign_revision: int | None = None,
        solo_revision: int | None = None,
    ) -> dict[str, Any] | None:
        """Merge additional keys into a message's metadata_json and return the updated row dict."""
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            if row is None:
                return None
            meta = json.loads(row["metadata_json"])
            for k, v in metadata_updates.items():
                if v is None:
                    meta.pop(k, None)
                else:
                    meta[k] = v
            next_camp_rev = int(campaign_revision) if campaign_revision is not None else int(row["campaign_revision"])
            next_solo_rev = int(solo_revision) if solo_revision is not None else int(row["solo_revision"])
            conn.execute(
                "UPDATE chat_messages SET metadata_json=?, campaign_revision=?, solo_revision=? WHERE campaign_id=? AND id=?",
                (_json(meta), next_camp_rev, next_solo_rev, campaign_id, message_id),
            )
            updated = conn.execute(
                "SELECT * FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, message_id),
            ).fetchone()
            return self._row_dict(updated) if updated else None

    def sync_active_leaf_revisions(self, campaign_id: str, channel_id: str = "main") -> dict[str, Any]:
        """Sync the active branch leaf's stored revisions to current live campaign/solo revisions."""
        chan = self._norm_channel(channel_id)
        tree = self.get_tree(campaign_id, channel_id=chan)
        leaf_id = tree.get("active_leaf_id")
        revs = tree.get("current_revisions") or self._current_revisions(campaign_id)
        if leaf_id:
            with closing(self.store._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE chat_messages SET campaign_revision=?, solo_revision=? WHERE campaign_id=? AND id=?",
                    (int(revs["campaign_revision"]), int(revs["solo_revision"]), campaign_id, leaf_id),
                )
        return self.get_tree(campaign_id, channel_id=chan)

    def sync_all_active_leaf_revisions(self, campaign_id: str) -> dict[str, Any]:
        """Sync active branch leaf revisions across all channels of the campaign."""
        main_tree = self.get_tree(campaign_id, channel_id="main")
        revs = main_tree.get("current_revisions") or self._current_revisions(campaign_id)
        channels = list(main_tree.get("channels") or ["main"])
        leaf_ids: list[str] = []
        if main_tree.get("active_leaf_id"):
            leaf_ids.append(str(main_tree["active_leaf_id"]))
        for ch in channels:
            if ch == "main":
                continue
            ch_tree = self.get_tree(campaign_id, channel_id=ch)
            if ch_tree.get("active_leaf_id"):
                leaf_ids.append(str(ch_tree["active_leaf_id"]))
        if leaf_ids:
            with closing(self.store._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                for lid in leaf_ids:
                    conn.execute(
                        "UPDATE chat_messages SET campaign_revision=?, solo_revision=? WHERE campaign_id=? AND id=?",
                        (int(revs["campaign_revision"]), int(revs["solo_revision"]), campaign_id, lid),
                    )
        return self.get_tree(campaign_id, channel_id="main")

    def export_branch(self, campaign_id: str, leaf_id: str | None = None, channel_id: str = "main") -> dict[str, Any]:
        """Return both structured JSON and Markdown transcript for the active or requested branch."""
        ctx = self.gameplay.campaign_context(campaign_id)
        tree = self.get_tree(campaign_id, channel_id=channel_id)
        branch = self.get_branch_to(campaign_id, leaf_id) if leaf_id else tree["active_branch"]
        lines = [
            f"# {ctx['campaign']['name']} — Session {ctx['campaign']['session_number']}",
            "",
        ]
        if ctx["campaign"]["state"].get("scene"):
            lines.append(f"**Scene:** {ctx['campaign']['state']['scene']}")
            lines.append("")
        for idx, msg in enumerate(branch):
            meta = msg.get("metadata") or {}
            if msg["role"] == "system":
                lines.append("## System Notice")
            else:
                speaker = meta.get("speaker_name") or ("Player" if msg["role"] == "user" else "Game Master")
                lines.append(f"## {speaker} ({msg['role']})")
            lines.append("")
            lines.append(msg["content"])
            next_msg = branch[idx + 1] if idx + 1 < len(branch) else None
            next_meta = (next_msg.get("metadata") or {}) if next_msg else {}
            skip_user_rolls = (
                msg["role"] == "user"
                and next_msg is not None
                and next_msg.get("role") == "assistant"
                and next_msg.get("parent_id") == msg.get("id")
                and bool(next_meta.get("rolls"))
                and (not meta.get("manual_roll") or next_meta.get("rolls") == meta.get("rolls"))
            )
            if not skip_user_rolls:
                for r in meta.get("rolls") or []:
                    lines.append(f"- Roll ({r.get('actor', 'PC')}): {r.get('skill') or r.get('stat')} = {r.get('total')} vs DV {r.get('dv', '?')}")
            lines.append("")
        return {
            "campaign": ctx["campaign"],
            "branch": branch,
            "markdown": "\n".join(lines).strip() + "\n",
        }


class BranchPrivateStateStore:
    """Branch-scoped private GM secrets, world clocks, and compression watermarks."""

    def __init__(self, gameplay: GameplayService, tree: ChatTreeStore):
        self.gameplay = gameplay
        self.tree = tree
        self.ensure_private_tables()

    def ensure_private_tables(self) -> None:
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
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
                CREATE TABLE IF NOT EXISTS turn_pre_snapshots (
                    user_message_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    snapshot_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_compressions (
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                    channel_id TEXT NOT NULL DEFAULT 'main',
                    leaf_id TEXT,
                    compressed_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (campaign_id, channel_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_banners (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
                    banner_url TEXT NOT NULL DEFAULT ''
                )
                """
            )
            comp_cols = {r[1] for r in conn.execute("PRAGMA table_info(campaign_compressions)")}
            if "channel_id" not in comp_cols:
                conn.execute(
                    """
                    CREATE TABLE campaign_compressions_new (
                        campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                        channel_id TEXT NOT NULL DEFAULT 'main',
                        leaf_id TEXT,
                        compressed_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (campaign_id, channel_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO campaign_compressions_new (campaign_id, channel_id, leaf_id, compressed_count, updated_at)
                    SELECT campaign_id, 'main', leaf_id, compressed_count, updated_at FROM campaign_compressions
                    """
                )
                conn.execute("DROP TABLE campaign_compressions")
                conn.execute("ALTER TABLE campaign_compressions_new RENAME TO campaign_compressions")

    @staticmethod
    def clean_secrets_dict(raw: Any) -> dict[str, str]:
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
    def merge_gm_secrets(current: dict[str, str], updates: Any) -> dict[str, str]:
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
        while len(merged) > 50:
            evict_key = next((k for k in merged if not str(k).startswith("__npc_real:")), None)
            if evict_key is None:
                break
            merged.pop(evict_key, None)
        serialized = json.dumps(merged, ensure_ascii=False)
        while len(serialized) > 8000 and merged:
            evict_key = next((k for k in merged if not str(k).startswith("__npc_real:")), None)
            if evict_key is None:
                break
            merged.pop(evict_key, None)
            serialized = json.dumps(merged, ensure_ascii=False)
        return merged

    @staticmethod
    def normalize_clock_list(raw: Any) -> list[dict[str, Any]]:
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
    def apply_clock_ops(
        cls,
        current: list[dict[str, Any]],
        ops: Any,
        *,
        allow_secret: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        clocks = [dict(c) for c in cls.normalize_clock_list(current)]
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

    def _walk_snapshot_chain(
        self, conn: sqlite3.Connection, campaign_id: str, start_id: str | None
    ) -> tuple[dict[str, str] | None, list[dict[str, Any]] | None, str | None]:
        cursor_id = start_id
        visited: set[str] = set()
        inferred_channel: str | None = None
        while cursor_id and cursor_id not in visited:
            visited.add(cursor_id)
            snap = conn.execute(
                "SELECT secrets_json, clocks_json FROM turn_gm_snapshots WHERE campaign_id=? AND message_id=?",
                (campaign_id, cursor_id),
            ).fetchone()
            if snap is not None:
                try:
                    s = self.clean_secrets_dict(json.loads(snap["secrets_json"]))
                except (TypeError, json.JSONDecodeError):
                    s = {}
                try:
                    c = self.normalize_clock_list(json.loads(snap["clocks_json"]))
                except (TypeError, json.JSONDecodeError):
                    c = []
                return s, c, inferred_channel
            msg = conn.execute(
                "SELECT parent_id, channel_id FROM chat_messages WHERE campaign_id=? AND id=?",
                (campaign_id, cursor_id),
            ).fetchone()
            if msg is None:
                break
            if inferred_channel is None and msg["channel_id"]:
                inferred_channel = ChatTreeStore._norm_channel(msg["channel_id"])
            cursor_id = msg["parent_id"]
        return None, None, inferred_channel

    def load_branch_private_state(
        self, campaign_id: str, parent_id: str | None, *, channel_id: str | None = None
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        with closing(self.gameplay.store._connect()) as conn:
            s, c, inferred_channel = self._walk_snapshot_chain(conn, campaign_id, parent_id)
            if s is not None and c is not None:
                return s, c

            eff_channel = ChatTreeStore._norm_channel(channel_id or inferred_channel or "main")
            if eff_channel != "main":
                main_leaf = self.latest_snapshot_leaf(campaign_id, channel_id="main")
                if main_leaf:
                    ms, mc, _ = self._walk_snapshot_chain(conn, campaign_id, main_leaf)
                    if ms is not None and mc is not None:
                        return ms, mc

            sec_row = conn.execute("SELECT secrets_json FROM gm_secrets WHERE campaign_id=?", (campaign_id,)).fetchone()
            clk_row = conn.execute("SELECT clocks_json FROM campaign_clocks WHERE campaign_id=?", (campaign_id,)).fetchone()
        secrets: dict[str, str] = {}
        clocks: list[dict[str, Any]] = []
        if sec_row:
            try:
                secrets = self.clean_secrets_dict(json.loads(sec_row["secrets_json"]))
            except (TypeError, json.JSONDecodeError):
                secrets = {}
        if clk_row:
            try:
                clocks = self.normalize_clock_list(json.loads(clk_row["clocks_json"]))
            except (TypeError, json.JSONDecodeError):
                clocks = []
        return secrets, clocks

    def save_branch_private_state(
        self,
        campaign_id: str,
        message_id: str | None,
        parent_id: str | None,
        secrets: dict[str, str],
        clocks: list[dict[str, Any]],
    ) -> None:
        sec_json = json.dumps(self.clean_secrets_dict(secrets), ensure_ascii=False)
        clk_json = json.dumps(self.normalize_clock_list(clocks), ensure_ascii=False)
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

    def latest_snapshot_leaf(self, campaign_id: str, channel_id: str = "main") -> str | None:
        tree = self.tree.get_tree(campaign_id, channel_id=channel_id)
        active_branch = tree.get("active_branch") or []
        if active_branch:
            with closing(self.gameplay.store._connect()) as conn:
                rows = conn.execute(
                    "SELECT message_id FROM turn_gm_snapshots WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchall()
            snap_ids = {str(r["message_id"]) for r in rows}
            for msg in reversed(active_branch):
                mid = msg.get("id")
                if mid and str(mid) in snap_ids:
                    return str(mid)
        return tree.get("active_leaf_id")

    def active_channel_leaves(self, campaign_id: str) -> list[str]:
        main_tree = self.tree.get_tree(campaign_id, "main")
        leaves: list[str] = []
        seen: set[str] = set()
        for ch in main_tree.get("channels") or ["main"]:
            t = main_tree if ch == "main" else self.tree.get_tree(campaign_id, ch)
            lid = t.get("active_leaf_id")
            if lid and lid not in seen:
                seen.add(lid)
                leaves.append(lid)
        return leaves

    def get_gm_secrets(self, campaign_id: str) -> dict[str, str]:
        leaf_id = self.latest_snapshot_leaf(campaign_id)
        secrets, _ = self.load_branch_private_state(campaign_id, leaf_id)
        return secrets

    def update_gm_secrets(self, campaign_id: str, updates: dict[str, str | None]) -> dict[str, str]:
        """Persist secret updates across root gm_secrets AND all active channel branch snapshots."""
        self.gameplay.campaign_context(campaign_id)
        root_sec, root_clk = self.load_branch_private_state(campaign_id, None)
        merged_root = self.merge_gm_secrets(root_sec, updates)
        self.save_branch_private_state(campaign_id, None, None, merged_root, root_clk)

        latest_sec = merged_root
        for lid in self.active_channel_leaves(campaign_id):
            b_sec, b_clk = self.load_branch_private_state(campaign_id, lid)
            merged_b = self.merge_gm_secrets(b_sec, updates)
            msg = self.tree.get_message(campaign_id, lid)
            parent_id = msg["parent_id"] if msg else None
            self.save_branch_private_state(campaign_id, lid, parent_id, merged_b, b_clk)
            latest_sec = merged_b
        return latest_sec

    def get_banner(self, campaign_id: str) -> str:
        with closing(self.gameplay.store._connect()) as conn:
            row = conn.execute(
                "SELECT banner_url FROM campaign_banners WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            return str(row["banner_url"] or "") if row else ""

    def set_banner(self, campaign_id: str, banner_url: str) -> str:
        self.gameplay.campaign_context(campaign_id)
        cleaned = str(banner_url or "").strip()
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not cleaned:
                conn.execute("DELETE FROM campaign_banners WHERE campaign_id=?", (campaign_id,))
                return ""
            conn.execute(
                "INSERT INTO campaign_banners (campaign_id, banner_url) VALUES (?, ?) "
                "ON CONFLICT(campaign_id) DO UPDATE SET banner_url=excluded.banner_url",
                (campaign_id, cleaned),
            )
            return cleaned

    def list_public_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        self.gameplay.campaign_context(campaign_id)
        target_leaf = leaf_id if leaf_id is not None else self.latest_snapshot_leaf(campaign_id)
        _, clocks = self.load_branch_private_state(campaign_id, target_leaf)
        return [c for c in clocks if c.get("visibility") != "secret"]

    def list_all_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        self.gameplay.campaign_context(campaign_id)
        target_leaf = leaf_id if leaf_id is not None else self.latest_snapshot_leaf(campaign_id)
        _, clocks = self.load_branch_private_state(campaign_id, target_leaf)
        return list(clocks)

    def mutate_public_clock(
        self,
        campaign_id: str,
        body: dict[str, Any],
        leaf_id: str | None = None,
        *,
        allow_secret: bool = False,
    ) -> list[dict[str, Any]]:
        self.gameplay.campaign_context(campaign_id)
        target_leaf = leaf_id if leaf_id is not None else self.latest_snapshot_leaf(campaign_id)
        _, clocks = self.load_branch_private_state(campaign_id, target_leaf)
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
            vis_raw = str(body.get("visibility") or "public").strip().lower()
            op = {
                "id": body.get("id") or body.get("name"),
                "name": body.get("name"),
                "segments": body.get("segments", 4),
                "filled": body.get("filled", 0),
                "category": body.get("category", "heat"),
                "note": body.get("note", ""),
                "visibility": "secret" if (allow_secret and vis_raw == "secret") else "public",
            }
        else:
            raise ValueError(f"Unsupported clock action: {action!r}")
        if not op.get("id") and not op.get("name"):
            raise ValueError("clock id or name is required")
        next_clocks, _ = self.apply_clock_ops(clocks, [op], allow_secret=allow_secret)
        if not target_leaf:
            root_sec, _ = self.load_branch_private_state(campaign_id, None)
            self.save_branch_private_state(campaign_id, None, None, root_sec, next_clocks)
        synced_leaves = set(self.active_channel_leaves(campaign_id))
        if target_leaf:
            synced_leaves.add(target_leaf)
        for lid in synced_leaves:
            b_sec, _ = self.load_branch_private_state(campaign_id, lid)
            msg = self.tree.get_message(campaign_id, lid)
            parent_id = msg["parent_id"] if msg else None
            self.save_branch_private_state(campaign_id, lid, parent_id, b_sec, next_clocks)
        if allow_secret:
            return list(next_clocks)
        return [c for c in next_clocks if c.get("visibility") != "secret"]

    def seed_initial_gm_state(
        self,
        campaign_id: str,
        *,
        secrets: dict[str, str | None] | None = None,
        opening_clock: dict[str, Any] | None = None,
        clocks: list[dict[str, Any]] | None = None,
        replace_secrets: bool = False,
        replace_clocks: bool = False,
    ) -> dict[str, Any]:
        """Seed initial hidden GM secrets and/or starting clocks for a campaign."""
        self.gameplay.campaign_context(campaign_id)
        target_leaf = self.latest_snapshot_leaf(campaign_id)
        cur_secrets, cur_clocks = self.load_branch_private_state(campaign_id, target_leaf)

        if replace_secrets:
            preserved_internal = {k: v for k, v in cur_secrets.items() if str(k).startswith("__")}
            base_secrets = preserved_internal
        else:
            base_secrets = dict(cur_secrets)
        merged_secrets = self.merge_gm_secrets(base_secrets, secrets or {})

        clock_ops: list[dict[str, Any]] = []
        if isinstance(clocks, list):
            for entry in clocks:
                if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
                    continue
                vis_raw = str(entry.get("visibility") or "public").strip().lower()
                clock_ops.append({
                    "id": entry.get("id") or entry.get("name"),
                    "name": str(entry["name"]).strip(),
                    "segments": entry.get("segments", 4),
                    "filled": entry.get("filled", 0),
                    "category": entry.get("category", "heat"),
                    "note": str(entry.get("note") or "").strip(),
                    "visibility": "secret" if vis_raw == "secret" else "public",
                })
        elif isinstance(opening_clock, dict) and str(opening_clock.get("name") or "").strip():
            vis_raw = str(opening_clock.get("visibility") or "public").strip().lower()
            clock_ops.append({
                "id": opening_clock.get("id") or opening_clock.get("name"),
                "name": str(opening_clock["name"]).strip(),
                "segments": opening_clock.get("segments", 4),
                "filled": opening_clock.get("filled", 0),
                "category": opening_clock.get("category", "heat"),
                "note": str(opening_clock.get("note") or "").strip(),
                "visibility": "secret" if vis_raw == "secret" else "public",
            })

        base_clocks = [] if replace_clocks else list(cur_clocks)
        if clock_ops:
            next_clocks, _ = self.apply_clock_ops(base_clocks, clock_ops, allow_secret=True)
        else:
            next_clocks = base_clocks

        self.save_branch_private_state(campaign_id, None, None, merged_secrets, next_clocks)
        for lid in self.active_channel_leaves(campaign_id):
            msg = self.tree.get_message(campaign_id, lid)
            parent_id = msg["parent_id"] if msg else None
            self.save_branch_private_state(campaign_id, lid, parent_id, merged_secrets, next_clocks)
        return {
            "clocks": [c for c in next_clocks if c.get("visibility") != "secret"],
            "all_clocks": list(next_clocks),
            "secrets_count": len([k for k in merged_secrets if not str(k).startswith("__")]),
        }

    def get_compressed_count(self, campaign_id: str, channel_id: str = "main") -> int:
        chan = ChatTreeStore._norm_channel(channel_id)
        with closing(self.gameplay.store._connect()) as conn:
            row = conn.execute(
                "SELECT compressed_count FROM campaign_compressions WHERE campaign_id=? AND channel_id=?",
                (campaign_id, chan),
            ).fetchone()
        return int(row["compressed_count"]) if row else 0

    def set_compressed_count(
        self, campaign_id: str, leaf_id: str | None, count: int, channel_id: str | None = None
    ) -> None:
        if channel_id is None and leaf_id:
            leaf_msg = self.tree.get_message(campaign_id, leaf_id)
            chan = ChatTreeStore._norm_channel(leaf_msg.get("channel_id") if leaf_msg else "main")
        else:
            chan = ChatTreeStore._norm_channel(channel_id)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO campaign_compressions (campaign_id, channel_id, leaf_id, compressed_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, channel_id) DO UPDATE SET
                    leaf_id=excluded.leaf_id,
                    compressed_count=excluded.compressed_count,
                    updated_at=excluded.updated_at
                """,
                (campaign_id, chan, leaf_id, max(0, int(count)), now),
            )

    def has_pre_turn_snapshot(self, campaign_id: str, user_message_id: str) -> bool:
        with closing(self.gameplay.store._connect()) as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM turn_pre_snapshots WHERE campaign_id=? AND user_message_id=?",
                    (campaign_id, user_message_id),
                ).fetchone()
            )

    def save_pre_turn_snapshot(self, campaign_id: str, user_message_id: str) -> None:
        ctx = self.gameplay.campaign_context(campaign_id)
        camp = ctx.get("campaign") or {}
        solo_rt = (ctx.get("solo") or {}).get("runtime") or {}
        chars = [
            {
                "id": c["id"],
                "name": c["name"],
                "stats": c["stats"],
                "skills": c["skills"],
                "hp": int(c["hp"]),
                "max_hp": int(c["max_hp"]),
                "humanity": int(c["humanity"]),
                "luck_remaining": int(c["luck_remaining"]),
                "money": int(c["money"]),
                "inventory": c["inventory"],
                "detail": c["detail"],
            }
            for c in (ctx.get("characters") or [])
        ]
        snapshot = {
            "campaign": {
                "name": camp.get("name"),
                "state": camp.get("state"),
                "session_number": int(camp.get("session_number") or 0),
            },
            "solo": {"runtime": solo_rt},
            "characters": chars,
        }
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO turn_pre_snapshots (user_message_id, campaign_id, snapshot_json) VALUES (?, ?, ?)",
                (user_message_id, campaign_id, _json(snapshot)),
            )

    def restore_pre_turn_snapshot(self, campaign_id: str, user_message_id: str) -> bool:
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT snapshot_json FROM turn_pre_snapshots WHERE campaign_id=? AND user_message_id=?",
                (campaign_id, user_message_id),
            ).fetchone()
            if row is None:
                return False
            snap = json.loads(row["snapshot_json"])
            camp_snap = snap.get("campaign")
            if isinstance(camp_snap, dict):
                cur_camp = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
                if cur_camp is not None:
                    snap_state_json = _json(camp_snap["state"])
                    if (
                        cur_camp["name"] != camp_snap["name"]
                        or cur_camp["state_json"] != snap_state_json
                        or int(cur_camp["session_number"]) != int(camp_snap["session_number"])
                    ):
                        conn.execute(
                            "UPDATE campaigns SET name=?, state_json=?, session_number=?, revision=? WHERE id=?",
                            (
                                camp_snap["name"],
                                snap_state_json,
                                int(camp_snap["session_number"]),
                                int(cur_camp["revision"]) + 1,
                                campaign_id,
                            ),
                        )
            solo_snap = snap.get("solo")
            if isinstance(solo_snap, dict) and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='solo_state'"
            ).fetchone():
                cur_solo = conn.execute("SELECT * FROM solo_state WHERE campaign_id=?", (campaign_id,)).fetchone()
                if cur_solo is not None:
                    snap_rt_json = _json(solo_snap["runtime"])
                    if cur_solo["runtime_json"] != snap_rt_json:
                        conn.execute(
                            "UPDATE solo_state SET runtime_json=?, revision=? WHERE campaign_id=?",
                            (snap_rt_json, int(cur_solo["revision"]) + 1, campaign_id),
                        )
            for csnap in snap.get("characters") or []:
                if not isinstance(csnap, dict) or not csnap.get("id"):
                    continue
                cur_row = conn.execute("SELECT * FROM characters WHERE id=?", (csnap["id"],)).fetchone()
                if cur_row is None:
                    continue
                before = self.gameplay.store._record(cur_row)
                changed = any(
                    before.get(k) != csnap.get(k)
                    for k in ("name", "stats", "skills", "hp", "max_hp", "humanity", "luck_remaining", "money", "inventory", "detail")
                )
                if not changed:
                    continue
                after = {
                    "id": before["id"],
                    "name": csnap["name"],
                    "stats": csnap["stats"],
                    "skills": csnap["skills"],
                    "hp": int(csnap["hp"]),
                    "max_hp": int(csnap["max_hp"]),
                    "humanity": int(csnap["humanity"]),
                    "luck_remaining": int(csnap["luck_remaining"]),
                    "money": int(csnap["money"]),
                    "inventory": csnap["inventory"],
                    "detail": csnap["detail"],
                    "revision": int(before["revision"]) + 1,
                }
                conn.execute(
                    "UPDATE characters SET name=?,stats=?,skills=?,hp=?,max_hp=?,humanity=?,luck_remaining=?,money=?,inventory=?,detail=?,revision=? WHERE id=?",
                    (
                        after["name"],
                        _json(after["stats"]),
                        _json(after["skills"]),
                        after["hp"],
                        after["max_hp"],
                        after["humanity"],
                        after["luck_remaining"],
                        after["money"],
                        _json(after["inventory"]),
                        _json(after["detail"]),
                        after["revision"],
                        after["id"],
                    ),
                )
                op_id = f"regen-restore:{user_message_id[:16]}:{after['id'][:16]}:{uuid.uuid4().hex[:8]}"
                payload = _json({"action": "regenerate_restore", "user_message_id": user_message_id, "character_id": after["id"]})
                conn.execute(
                    "INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                    (after["id"], after["revision"], _json(before), _json(after), "Regenerate turn: restore pre-turn character state", op_id, payload),
                )
        return True
