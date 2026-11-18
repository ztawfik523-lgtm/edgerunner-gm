"""Audited narrative campaign memory and explicit session lifecycle."""
from __future__ import annotations

import json
import uuid
from contextlib import closing

from campaign import _json, _integer

_SECTIONS = ("npcs", "objectives", "discoveries", "unresolved")
_INITIAL = {"scene": "", "summary": "", **{key: {} for key in _SECTIONS}}


class CampaignMemory:
    """Persist campaign narrative using the private SQLite database of CampaignStore."""

    def __init__(self, store):
        self.store = store
        with closing(store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
                state_json TEXT NOT NULL, session_number INTEGER NOT NULL DEFAULT 0,
                is_primary INTEGER NOT NULL DEFAULT 0)""")
            camp_cols = {r[1] for r in conn.execute("PRAGMA table_info(campaigns)")}
            if "is_primary" not in camp_cols:
                conn.execute("ALTER TABLE campaigns ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
            conn.execute("""CREATE TABLE IF NOT EXISTS campaign_members (
                campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                character_id TEXT UNIQUE NOT NULL REFERENCES characters(id),
                PRIMARY KEY(campaign_id, character_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS campaign_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL,
                operation_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL,
                before_json TEXT, after_json TEXT, reason TEXT NOT NULL)""")

    def _check_operation(self, operation_id):
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 160:
            raise ValueError("operation_id must be a nonempty string of at most 160 characters")

    @staticmethod
    def _reason(reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a nonempty string")

    @staticmethod
    def _record(conn, row):
        if row is None:
            return None
        result = dict(id=row["id"], name=row["name"], revision=row["revision"],
                      state=json.loads(row["state_json"]), session_number=row["session_number"],
                      is_primary=bool(row["is_primary"]) if "is_primary" in row.keys() else False)
        result["character_ids"] = [r[0] for r in conn.execute(
            "SELECT character_id FROM campaign_members WHERE campaign_id=? ORDER BY character_id", (row["id"],))]
        return result

    def _find_prior(self, conn, operation_id, payload):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gameplay_events'").fetchone():
            if conn.execute("SELECT 1 FROM gameplay_events WHERE operation_id=?", (operation_id,)).fetchone():
                raise ValueError("operation_id was already used for a solo action")
        if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a character change")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rolls'").fetchone():
            if conn.execute("SELECT 1 FROM rolls WHERE operation_id=?", (operation_id,)).fetchone():
                raise ValueError("operation_id was already used for a roll")
        prior = conn.execute("SELECT payload,result FROM campaign_events WHERE operation_id=?", (operation_id,)).fetchone()
        if prior:
            if prior["payload"] != payload:
                raise ValueError("operation_id was already used for a different campaign operation")
            return json.loads(prior["result"])
        return None

    @staticmethod
    def _campaign(conn, campaign_id):
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (str(campaign_id),)).fetchone()
        if row is None:
            raise ValueError(f"campaign not found: {campaign_id}")
        return CampaignMemory._record(conn, row)

    def create_campaign(self, name, operation_id):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("name must be a nonempty string of at most 100 characters")
        self._check_operation(operation_id)
        payload = _json(dict(action="create_campaign", name=name))
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = self._find_prior(conn, operation_id, payload)
            if prior is not None: return prior
            result = dict(id=str(uuid.uuid4()), name=name, revision=1, state=_INITIAL.copy(), session_number=0, is_primary=False, character_ids=[])
            conn.execute("INSERT INTO campaigns(id,name,revision,state_json,session_number,is_primary) VALUES(?,?,?,?,?,?)",
                         (result["id"], name, 1, _json(_INITIAL), 0, 0))
            conn.execute("INSERT INTO campaign_events(campaign_id,operation_id,payload,result,before_json,after_json,reason) VALUES(?,?,?,?,?,?,?)",
                         (result["id"], operation_id, payload, _json(result), None, _json(result), "campaign created"))
            return result

    def list_campaigns(self):
        with closing(self.store._connect()) as conn:
            return [self._record(conn, row) for row in conn.execute("SELECT * FROM campaigns ORDER BY is_primary DESC, name COLLATE NOCASE, id")]

    def set_primary_campaign(self, campaign_id):
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._campaign(conn, campaign_id)
            conn.execute("UPDATE campaigns SET is_primary=0")
            conn.execute("UPDATE campaigns SET is_primary=1 WHERE id=?", (str(campaign_id),))
            return self._campaign(conn, campaign_id)

    def delete_campaign(self, campaign_id):
        cid = str(campaign_id)
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._campaign(conn, cid)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for tbl in (
                "campaign_members",
                "campaign_events",
                "solo_state",
                "gameplay_events",
                "chat_messages",
                "gm_secrets",
                "campaign_clocks",
                "turn_gm_snapshots",
                "campaign_compressions",
                "campaign_library",
            ):
                if tbl in tables:
                    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
                    if "campaign_id" in cols:
                        conn.execute(f"DELETE FROM {tbl} WHERE campaign_id=?", (cid,))
            conn.execute("DELETE FROM campaigns WHERE id=?", (cid,))
            return {"deleted": True, "id": cid, "name": before["name"]}

    def get_campaign(self, campaign_id):
        with closing(self.store._connect()) as conn:
            row = conn.execute("SELECT * FROM campaigns WHERE id=?", (str(campaign_id),)).fetchone()
            return self._record(conn, row)

    def _mutate(self, campaign_id, expected_revision, reason, operation_id, payload, action):
        self._check_operation(operation_id); self._reason(reason)
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = self._find_prior(conn, operation_id, payload)
            if prior is not None: return prior
            before = self._campaign(conn, campaign_id)
            _integer(expected_revision, "expected_revision", 1, 2**63 - 1)
            if before["revision"] != expected_revision:
                raise ValueError(f"revision conflict: expected {expected_revision}, current {before['revision']}")
            result = action(conn, before)
            conn.execute("UPDATE campaigns SET revision=?,state_json=?,session_number=? WHERE id=?",
                         (result["revision"], _json(result["state"]), result["session_number"], result["id"]))
            conn.execute("INSERT INTO campaign_events(campaign_id,operation_id,payload,result,before_json,after_json,reason) VALUES(?,?,?,?,?,?,?)",
                         (result["id"], operation_id, payload, _json(result), _json(before), _json(result), reason))
            return result

    @staticmethod
    def _validate_state(state):
        if not isinstance(state, dict) or set(state) != set(_INITIAL):
            raise ValueError("state must contain scene, summary, npcs, objectives, discoveries, unresolved")
        result = {}
        for key in ("scene", "summary"):
            value = state[key]
            if not isinstance(value, str) or len(value) > 4000: raise ValueError(f"{key} must be a string of at most 4000 characters")
            result[key] = value
        for section in _SECTIONS:
            mapping = state[section]
            if not isinstance(mapping, dict) or len(mapping) > 40: raise ValueError(f"{section} must be a mapping of at most 40 entries")
            for k, v in mapping.items():
                if not isinstance(k, str) or not k.strip() or len(k) > 100: raise ValueError("state keys must be nonempty strings of at most 100 characters")
                if not isinstance(v, str) or len(v) > 2000: raise ValueError("state values must be strings of at most 2000 characters")
            result[section] = dict(mapping)
        if len(_json(result)) > 24000: raise ValueError("serialized campaign state exceeds 24000 characters")
        return result

    def update_campaign(self, campaign_id, expected_revision, changes, reason, operation_id):
        if not isinstance(changes, dict) or not changes or set(changes) - set(_INITIAL):
            raise ValueError("changes must contain one or more narrative state fields")
        payload = _json(dict(action="update_campaign", campaign_id=str(campaign_id), expected_revision=expected_revision, changes=changes, reason=reason))
        def apply(conn, before):
            state = dict(before["state"]); state.update(changes)
            return dict(before, revision=before["revision"] + 1, state=self._validate_state(state))
        return self._mutate(campaign_id, expected_revision, reason, operation_id, payload, apply)

    def attach_character(self, campaign_id, character_id, expected_revision, reason, operation_id):
        payload = _json(dict(action="attach_character", campaign_id=str(campaign_id), character_id=str(character_id), expected_revision=expected_revision, reason=reason))
        def apply(conn, before):
            char = conn.execute("SELECT id FROM characters WHERE id=?", (str(character_id),)).fetchone()
            if not char: raise ValueError(f"character not found: {character_id}")
            member = conn.execute("SELECT campaign_id FROM campaign_members WHERE character_id=?", (str(character_id),)).fetchone()
            if member and member[0] != str(campaign_id): raise ValueError("character belongs to another campaign")
            conn.execute("INSERT OR IGNORE INTO campaign_members VALUES(?,?)", (str(campaign_id), str(character_id)))
            return dict(before, revision=before["revision"] + 1,
                        character_ids=sorted(set(before["character_ids"]) | {str(character_id)}))
        return self._mutate(campaign_id, expected_revision, reason, operation_id, payload, apply)

    def start_session(self, campaign_id, expected_revision, reason, operation_id):
        payload = _json(dict(action="start_session", campaign_id=str(campaign_id), expected_revision=expected_revision, reason=reason))
        def apply(conn, before):
            ids = before["character_ids"]
            for char_id in ids:
                row = conn.execute("SELECT * FROM characters WHERE id=?", (char_id,)).fetchone()
                char_before = self.store._record(row)
                char_after = dict(char_before, luck_remaining=char_before["stats"]["LUCK"], revision=char_before["revision"] + 1)
                op = f"{operation_id}:character:{char_id}"
                self.store._reject_roll_id(conn, op)
                if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (op,)).fetchone(): raise ValueError("derived character operation_id already exists")
                conn.execute("UPDATE characters SET luck_remaining=?,revision=? WHERE id=?", (char_after["luck_remaining"], char_after["revision"], char_id))
                char_payload = _json(dict(action="session_start", campaign_operation_id=operation_id, campaign_id=str(campaign_id), character_id=char_id, reason=reason))
                conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                             (char_id, char_after["revision"], _json(char_before), _json(char_after), "session start: " + reason, op, char_payload))
            return dict(before, revision=before["revision"] + 1, session_number=before["session_number"] + 1)
        return self._mutate(campaign_id, expected_revision, reason, operation_id, payload, apply)

    def history(self, campaign_id):
        with closing(self.store._connect()) as conn:
            return [dict(sequence=r[0], campaign_id=r[1], operation_id=r[2], payload=json.loads(r[3]), result=json.loads(r[4]), before=json.loads(r[5]) if r[5] else None, after=json.loads(r[6]) if r[6] else None, reason=r[7])
                    for r in conn.execute("SELECT sequence,campaign_id,operation_id,payload,result,before_json,after_json,reason FROM campaign_events WHERE campaign_id=? ORDER BY sequence", (str(campaign_id),))]

    def undo_campaign(self, campaign_id, expected_revision, reason, operation_id):
        payload = _json(dict(action="undo_campaign", campaign_id=str(campaign_id), expected_revision=expected_revision, reason=reason))
        def apply(conn, before):
            latest = conn.execute("SELECT payload,before_json FROM campaign_events WHERE campaign_id=? ORDER BY sequence DESC LIMIT 1", (str(campaign_id),)).fetchone()
            action = json.loads(latest["payload"])["action"]
            if action not in ("update_campaign", "undo_campaign"):
                raise ValueError(f"latest campaign event ({action}) is not narrative and cannot be undone")
            if latest["before_json"] is None: raise ValueError("campaign creation cannot be undone")
            restored = json.loads(latest["before_json"])
            return dict(before, revision=before["revision"] + 1, state=restored["state"])
        return self._mutate(campaign_id, expected_revision, reason, operation_id, payload, apply)
