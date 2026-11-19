"""Private, persistent campaign character state (separate from the rules index).

Derived starting HP and humanity follow Cyberpunk RED Corebook pp. 79–80.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(os.environ.get("REDGM_CAMPAIGN_DB", Path.home() / ".local/share/cyberpunk-red-gm/campaign.sqlite"))
STAT_NAMES = ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def _mapping(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


class CampaignStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        existed = self.path.exists()
        if not existed:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and not {"characters", "audit"}.issubset(tables):
                raise ValueError("existing database is not an empty campaign database")
            if tables & {"pages", "metadata", "passages"}:
                raise ValueError("Campaign storage cannot use the rules index")
            os.chmod(self.path, self.path.stat().st_mode & 0o600)
            conn.execute("""CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, stats TEXT NOT NULL,
                    skills TEXT NOT NULL, hp INTEGER NOT NULL, max_hp INTEGER NOT NULL,
                    humanity INTEGER NOT NULL, luck_remaining INTEGER NOT NULL,
                    money INTEGER NOT NULL, inventory TEXT NOT NULL, revision INTEGER NOT NULL
                )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
                    reason TEXT NOT NULL, operation_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL
                )""")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(characters)")}
            if "detail" not in columns:
                conn.execute("ALTER TABLE characters ADD COLUMN detail TEXT NOT NULL DEFAULT '{}'")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _validate_stats(stats):
        stats = _mapping(stats, "stats")
        if set(stats) != set(STAT_NAMES):
            raise ValueError(f"stats must contain exactly: {', '.join(STAT_NAMES)}")
        return {key: _integer(stats[key], f"stat {key}", 0, 100) for key in STAT_NAMES}

    @staticmethod
    def _validate_skills(skills):
        skills = _mapping(skills, "skills")
        result = {}
        for name, value in skills.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError("skill names must be nonempty strings of at most 100 characters")
            result[name] = _integer(value, f"skill {name}", 0, 100)
        return result

    @staticmethod
    def _record(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("stats", "skills", "inventory", "detail"):
            result[key] = json.loads(result[key])
        return result

    @staticmethod
    def _reject_roll_id(conn, operation_id):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gameplay_events'").fetchone():
            if conn.execute("SELECT 1 FROM gameplay_events WHERE operation_id=?", (operation_id,)).fetchone():
                raise ValueError("operation_id was already used for a gameplay action")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_events'").fetchone():
            if conn.execute("SELECT 1 FROM campaign_events WHERE operation_id=?", (operation_id,)).fetchone():
                raise ValueError("operation_id was already used for a campaign change")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rolls'").fetchone():
            if conn.execute("SELECT 1 FROM rolls WHERE operation_id=?", (operation_id,)).fetchone():
                raise ValueError("operation_id was already used for a roll")

    def create_character(
        self,
        name,
        stats,
        skills=None,
        operation_id=None,
        *,
        money=0,
        inventory=None,
        detail=None,
        humanity=None,
    ):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a nonempty string")
        stats = self._validate_stats(stats)
        skills = self._validate_skills({} if skills is None else skills)
        money = _integer(money, "money", 0, 2**63 - 1)
        inv = {} if inventory is None else _mapping(inventory, "inventory")
        validated_inv = {}
        for item, count in inv.items():
            if not isinstance(item, str) or not item.strip():
                raise ValueError("inventory item names must be nonempty strings")
            validated_inv[item] = _integer(count, f"inventory count for {item}", 0, 2**63 - 1)
        validated_detail = {} if detail is None else dict(_mapping(detail, "detail"))
        if humanity is None:
            resolved_humanity = stats["EMP"] * 10
        else:
            resolved_humanity = _integer(humanity, "humanity", 0, max(100, stats["EMP"] * 10))
        if operation_id is not None and (not isinstance(operation_id, str) or not operation_id):
            raise ValueError("operation_id must be a nonempty string")
        creation_det = validated_detail.get("creation") if isinstance(validated_detail.get("creation"), dict) else {}
        eff_body = creation_det.get("effective_body")
        body_for_hp = eff_body if isinstance(eff_body, int) and eff_body >= stats["BODY"] else stats["BODY"]
        max_hp = 10 + 5 * ((body_for_hp + stats["WILL"] + 1) // 2)
        character_id = str(uuid.uuid4())
        record = dict(
            id=character_id,
            name=name,
            stats=stats,
            skills=skills,
            hp=max_hp,
            max_hp=max_hp,
            humanity=resolved_humanity,
            luck_remaining=stats["LUCK"],
            money=money,
            inventory=validated_inv,
            revision=1,
            detail=validated_detail,
        )
        payload_data: dict[str, Any] = {"action": "create_character", "name": name, "stats": stats, "skills": skills}
        if money:
            payload_data["money"] = money
        if validated_inv:
            payload_data["inventory"] = validated_inv
        if validated_detail:
            payload_data["detail"] = validated_detail
        if humanity is not None:
            payload_data["humanity"] = resolved_humanity
        payload = _json(payload_data)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if operation_id is not None:
                self._reject_roll_id(conn, operation_id)
                prior = conn.execute("SELECT payload,after_json FROM audit WHERE operation_id=?", (operation_id,)).fetchone()
                if prior:
                    if prior["payload"] != payload:
                        raise ValueError("operation_id was already used for a different create")
                    return json.loads(prior["after_json"])
            conn.execute(
                "INSERT INTO characters(id,name,stats,skills,hp,max_hp,humanity,luck_remaining,money,inventory,revision,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    character_id,
                    name,
                    _json(stats),
                    _json(skills),
                    max_hp,
                    max_hp,
                    record["humanity"],
                    record["luck_remaining"],
                    money,
                    _json(validated_inv),
                    1,
                    _json(validated_detail),
                ),
            )
            conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                          (character_id, 1, None, _json(record), "character created", operation_id or "create:" + character_id, payload))
        return record

    def delete_character(self, character_id):
        cid = str(character_id)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            before = self._record(row)
            has_members = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_members'"
            ).fetchone()
            if has_members:
                conn.execute("DELETE FROM campaign_members WHERE character_id=?", (cid,))
            conn.execute("DELETE FROM audit WHERE character_id=?", (cid,))
            conn.execute("DELETE FROM characters WHERE id=?", (cid,))
            return {"deleted": True, "id": cid, "name": before["name"]}

    def get_character(self, character_id):
        with closing(self._connect()) as conn:
            return self._record(conn.execute("SELECT * FROM characters WHERE id=?", (str(character_id),)).fetchone())

    def list_characters(self):
        with closing(self._connect()) as conn:
            return [self._record(row) for row in conn.execute("SELECT * FROM characters ORDER BY name COLLATE NOCASE,id")]

    def update_character(self, character_id, expected_revision, changes, reason, operation_id):
        changes = _mapping(changes, "changes")
        if not changes or set(changes) - {"hp", "money", "inventory", "humanity"}:
            raise ValueError("changes may contain only hp, money, inventory, and humanity")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a nonempty string")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("operation_id must be a nonempty string")
        payload = _json({"action": "update_character", "character_id": str(character_id), "expected_revision": expected_revision,
                         "changes": changes, "reason": reason})
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reject_roll_id(conn, operation_id)
            prior = conn.execute("SELECT payload,after_json FROM audit WHERE operation_id=?", (operation_id,)).fetchone()
            if prior:
                if prior["payload"] != payload:
                    raise ValueError("operation_id was already used for a different update")
                return json.loads(prior["after_json"])
            row = conn.execute("SELECT * FROM characters WHERE id=?", (str(character_id),)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or row["revision"] != expected_revision:
                raise ValueError(f"revision conflict: expected {expected_revision}, current {row['revision']}")
            before = self._record(row)
            updated = dict(before)
            if "hp" in changes:
                updated["hp"] = _integer(changes["hp"], "hp", -1_000_000, before["max_hp"])
            if "money" in changes:
                updated["money"] = _integer(changes["money"], "money", 0, 2**63 - 1)
            if "humanity" in changes:
                max_hum = max(100, int(before["stats"].get("EMP", 10)) * 10)
                updated["humanity"] = _integer(changes["humanity"], "humanity", 0, max_hum)
            if "inventory" in changes:
                inv = _mapping(changes["inventory"], "inventory")
                for item, count in inv.items():
                    if not isinstance(item, str) or not item.strip():
                        raise ValueError("inventory item names must be nonempty strings")
                    _integer(count, f"inventory count for {item}", 0, 2**63 - 1)
                updated["inventory"] = inv
            updated["revision"] += 1
            conn.execute("UPDATE characters SET hp=?,money=?,humanity=?,inventory=?,revision=? WHERE id=?",
                         (updated["hp"], updated["money"], updated["humanity"], _json(updated["inventory"]), updated["revision"], str(character_id)))
            conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                         (str(character_id), updated["revision"], _json(before), _json(updated), reason, operation_id, payload))
            return updated

    def update_character_profile(self, character_id, expected_revision, profile, reason, operation_id):
        profile = _mapping(profile, "profile")
        allowed_keys = {
            "backstory",
            "lifepath",
            "appearance",
            "roles",
            "handle",
            "real_name",
            "real_name_hidden",
            "gender",
            "pronouns",
            "portrait_url",
            "color",
            "owner_username",
            "equipped_weapon",
            "equipped_armor",
            "equipped_head_armor",
            "housing",
            "lifestyle",
            "trauma_team",
            "reputation",
            "reputation_note",
        }
        if not profile or set(profile) - allowed_keys:
            raise ValueError(
                "profile may contain only backstory, lifepath, appearance, roles, handle, real_name, "
                "real_name_hidden, gender, pronouns, portrait_url, color, owner_username, "
                "equipped_weapon, equipped_armor, equipped_head_armor, housing, lifestyle, "
                "trauma_team, reputation, and reputation_note"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a nonempty string")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("operation_id must be a nonempty string")
        payload = _json({
            "action": "update_character_profile",
            "character_id": str(character_id),
            "expected_revision": expected_revision,
            "profile": profile,
            "reason": reason,
        })
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reject_roll_id(conn, operation_id)
            prior = conn.execute("SELECT payload,after_json FROM audit WHERE operation_id=?", (operation_id,)).fetchone()
            if prior:
                if prior["payload"] != payload:
                    raise ValueError("operation_id was already used for a different profile update")
                return json.loads(prior["after_json"])
            row = conn.execute("SELECT * FROM characters WHERE id=?", (str(character_id),)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or row["revision"] != expected_revision:
                raise ValueError(f"revision conflict: expected {expected_revision}, current {row['revision']}")
            before = self._record(row)
            updated = dict(before)
            new_detail = dict(before.get("detail") or {})
            string_detail_keys = {
                "handle",
                "real_name",
                "gender",
                "pronouns",
                "portrait_url",
                "color",
                "owner_username",
                "equipped_weapon",
                "housing",
                "lifestyle",
                "trauma_team",
                "reputation_note",
            }
            armor_detail_keys = {"equipped_armor", "equipped_head_armor"}
            for key, val in profile.items():
                if key == "roles":
                    if not isinstance(val, list):
                        raise ValueError("profile roles must be a list")
                    new_detail["roles"] = val
                elif key == "reputation":
                    new_detail["reputation"] = _integer(val, "profile reputation", 0, 10)
                elif key == "appearance":
                    if not isinstance(val, (str, dict)):
                        raise ValueError("profile appearance must be a string or object")
                    new_detail["appearance"] = val
                elif key == "real_name_hidden":
                    if not isinstance(val, bool):
                        raise ValueError("profile real_name_hidden must be a boolean")
                    new_detail["real_name_hidden"] = val
                elif key in armor_detail_keys:
                    if val is None or val == "":
                        new_detail.pop(key, None)
                    elif isinstance(val, dict):
                        armor_name = str(val.get("name") or "").strip()
                        if not armor_name:
                            raise ValueError(f"profile {key} name must be a nonempty string")
                        armor_obj: dict[str, Any] = {"name": armor_name}
                        if "sp" in val and val["sp"] is not None:
                            armor_obj["sp"] = _integer(val["sp"], f"profile {key} sp", 0, 100)
                        new_detail[key] = armor_obj
                    else:
                        raise ValueError(f"profile {key} must be an object or null")
                elif key in string_detail_keys:
                    if val is None or val == "":
                        new_detail.pop(key, None)
                    elif isinstance(val, str):
                        new_detail[key] = val.strip()
                    else:
                        raise ValueError(f"profile {key} must be a string or null")
                else:
                    if not isinstance(val, dict):
                        raise ValueError(f"profile {key} must be an object")
                    new_detail[key] = val
            if isinstance(new_detail.get("handle"), str) and new_detail["handle"].strip():
                updated["name"] = new_detail["handle"].strip()
            elif isinstance(new_detail.get("real_name"), str) and new_detail["real_name"].strip() and not new_detail.get("handle"):
                updated["name"] = new_detail["real_name"].strip()
            updated["detail"] = new_detail
            updated["revision"] += 1
            conn.execute("UPDATE characters SET name=?,detail=?,revision=? WHERE id=?",
                         (updated["name"], _json(new_detail), updated["revision"], str(character_id)))
            conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                         (str(character_id), updated["revision"], _json(before), _json(updated), reason, operation_id, payload))
            return updated

    def audit_events(self, character_id):
        with closing(self._connect()) as conn:
            return [dict(sequence=r[0], character_id=r[1], revision=r[2], before=json.loads(r[3]) if r[3] else None,
                         after=json.loads(r[4]), reason=r[5], operation_id=r[6])
                     for r in conn.execute("SELECT sequence,character_id,revision,before_json,after_json,reason,operation_id FROM audit WHERE character_id=? ORDER BY sequence", (str(character_id),))]

    def undo_last(self, character_id, expected_revision, reason, operation_id):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a nonempty string")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("operation_id must be a nonempty string")
        payload = _json({"action": "undo", "character_id": str(character_id), "expected_revision": expected_revision,
                         "reason": reason})
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reject_roll_id(conn, operation_id)
            prior = conn.execute("SELECT payload,after_json FROM audit WHERE operation_id=?", (operation_id,)).fetchone()
            if prior:
                if prior["payload"] != payload:
                    raise ValueError("operation_id was already used for a different undo")
                return json.loads(prior["after_json"])
            row = conn.execute("SELECT * FROM characters WHERE id=?", (str(character_id),)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or row["revision"] != expected_revision:
                raise ValueError(f"revision conflict: expected {expected_revision}, current {row['revision']}")
            latest = conn.execute("SELECT before_json FROM audit WHERE character_id=? ORDER BY sequence DESC LIMIT 1",
                                  (str(character_id),)).fetchone()
            if latest is None or latest["before_json"] is None:
                raise ValueError("latest character event is creation and cannot be undone")
            before = self._record(row)
            restored = json.loads(latest["before_json"])
            updated = dict(before, hp=restored["hp"], money=restored["money"],
                           inventory=restored["inventory"], luck_remaining=restored["luck_remaining"],
                           revision=before["revision"] + 1)
            conn.execute("UPDATE characters SET hp=?,money=?,inventory=?,luck_remaining=?,revision=? WHERE id=?",
                         (updated["hp"], updated["money"], _json(updated["inventory"]), updated["luck_remaining"], updated["revision"], str(character_id)))
            conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                         (str(character_id), updated["revision"], _json(before), _json(updated), reason, operation_id, payload))
            return updated

    def rename_owner_username(self, old_username: str, new_username: str) -> list[str]:
        """Update detail.owner_username on all characters owned by old_username; return affected campaign IDs."""
        old_clean = (old_username or "").strip().lower()
        new_clean = (new_username or "").strip()
        if not old_clean or not new_clean:
            return []
        changed_char_ids: set[str] = set()
        affected_campaigns: list[str] = []
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT id, detail, revision FROM characters").fetchall()
            for row in rows:
                detail = json.loads(row["detail"] or "{}")
                owner = str(detail.get("owner_username") or "").strip()
                if owner.lower() == old_clean:
                    detail["owner_username"] = new_clean
                    conn.execute(
                        "UPDATE characters SET detail=?, revision=? WHERE id=?",
                        (_json(detail), int(row["revision"]) + 1, row["id"]),
                    )
                    changed_char_ids.add(str(row["id"]))
            if changed_char_ids:
                has_members = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campaign_members'"
                ).fetchone()
                if has_members:
                    placeholders = ",".join("?" for _ in changed_char_ids)
                    for crow in conn.execute(
                        f"SELECT DISTINCT campaign_id FROM campaign_members WHERE character_id IN ({placeholders})",
                        tuple(changed_char_ids),
                    ).fetchall():
                        affected_campaigns.append(str(crow["campaign_id"]))
        return affected_campaigns
