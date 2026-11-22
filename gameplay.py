"""Shared local gameplay operations; adapters never invent rolls or state."""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from campaign import CampaignStore, DEFAULT_DB, _json, _integer
from mechanics import roll_dice, skill_check
from memory import CampaignMemory
import rules_eval

_ROLE_ABILITY_TO_ROLE = {
    "interface": "Netrunner",
    "charismatic impact": "Rockerboy",
    "credibility": "Media",
    "operator": "Fixer",
    "moto": "Nomad",
    "combat awareness": "Solo",
    "backup": "Lawman",
    "teamwork": "Exec",
    "maker": "Tech",
    "medicine": "Medtech",
}


def _resolve_role_ability_rank(character: dict, skill: str | None) -> int | None:
    """Resolve a canonical Role Ability rank from detail.roles and/or stored skills."""
    if not isinstance(skill, str) or not skill.strip():
        return None
    norm = " ".join(skill.strip().casefold().split())
    target_role = _ROLE_ABILITY_TO_ROLE.get(norm)
    if target_role is None:
        return None
    best = 0
    for key, val in (character.get("skills") or {}).items():
        if isinstance(key, str) and " ".join(key.strip().casefold().split()) == norm and isinstance(val, int):
            best = max(best, val)
    roles = (character.get("detail") or {}).get("roles") or []
    if isinstance(roles, list):
        for entry in roles:
            if isinstance(entry, dict) and str(entry.get("role") or "").strip() == target_role:
                rank = entry.get("rank")
                if isinstance(rank, int):
                    best = max(best, rank)
    return best


class GameplayService:
    def __init__(self, campaign_path=DEFAULT_DB, rules_path=None):
        self.rules_path = Path(rules_path) if rules_path else None
        if rules_path and Path(campaign_path).expanduser().resolve() == Path(rules_path).expanduser().resolve():
            raise ValueError("Campaign storage must be separate from the rules index")
        self.store = CampaignStore(campaign_path)
        self.memory = CampaignMemory(self.store)
        with closing(self.store._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS rolls (operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL)")
        from lifecycle import SoloService
        self.solo = SoloService(self)

    def execute(self, action: str, arguments: dict, *, campaign_id: str | None = None) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        arguments = dict(arguments)
        from lifecycle import SOLO_ACTIONS
        if action in SOLO_ACTIONS:
            return {"action": action, "result": self.solo.execute(action, arguments, campaign_id)}
        campaign_actions = {
            "create_campaign": self.memory.create_campaign,
            "list_campaigns": self.memory.list_campaigns,
            "get_campaign": self.memory.get_campaign,
            "set_primary_campaign": self.memory.set_primary_campaign,
            "delete_campaign": self.memory.delete_campaign,
            "campaign_context": self.campaign_context,
            "update_campaign": self.memory.update_campaign,
            "rename_campaign": self.memory.rename_campaign,
            "attach_character": self.memory.attach_character,
            "start_session": self.memory.start_session,
            "campaign_history": self.memory.history,
            "undo_campaign": self.memory.undo_campaign,
        }
        if campaign_id is not None:
            if not isinstance(campaign_id, str) or not campaign_id:
                raise ValueError("campaign_id must be a nonempty string")
            if action in campaign_actions:
                self._check_campaign_scope(campaign_id)
                if action in {"create_campaign", "list_campaigns"}:
                    raise ValueError("Create/list campaigns outside the selected campaign scope")
                if arguments.get("campaign_id", campaign_id) != campaign_id:
                    raise ValueError("Action targets another campaign")
                arguments["campaign_id"] = campaign_id
            elif action == "list_characters":
                if arguments:
                    raise ValueError("list_characters takes no arguments")
                return {"action": action, "result": self._check_campaign_scope(campaign_id, include_characters=True)}
            elif action not in {"create_character", "roll_dice"}:
                self._check_campaign_scope(campaign_id, character_id=arguments.get("character_id"), check_member=True)
            else:
                self._check_campaign_scope(campaign_id)
        methods = {
            "create_character": self.store.create_character,
            "get_character": self.store.get_character,
            "list_characters": self.store.list_characters,
            "update_character": self.store.update_character,
            "update_character_profile": self.store.update_character_profile,
            "delete_character": self.store.delete_character,
            "history": self.store.audit_events,
            "undo": self.store.undo_last,
            "roll_dice": self.roll,
            "skill_check": self.check,
            **campaign_actions,
        }
        if action not in methods:
            raise ValueError("Unknown gameplay action")
        result = methods[action](**arguments)
        if result is None:
            raise ValueError("Requested character or campaign not found")
        return {"action": action, "result": result}

    def _check_campaign_scope(self, campaign_id, *, character_id=None, check_member=False, include_characters=False):
        """Verify campaign existence (and optional membership) without building a full solo snapshot."""
        with closing(self.store._connect()) as conn:
            conn.execute("BEGIN")
            if not conn.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone():
                raise ValueError(f"campaign not found: {campaign_id}")
            if check_member:
                if not isinstance(character_id, str) or not conn.execute(
                    "SELECT 1 FROM campaign_members WHERE campaign_id=? AND character_id=?",
                    (campaign_id, character_id),
                ).fetchone():
                    raise ValueError("Character is not attached to the selected campaign")
            if include_characters:
                return [self.store._record(row) for row in conn.execute(
                    "SELECT c.* FROM characters c JOIN campaign_members m ON m.character_id=c.id "
                    "WHERE m.campaign_id=? ORDER BY c.name COLLATE NOCASE,c.id", (campaign_id,))]
        return None

    def campaign_context(self, campaign_id):
        """Read a consistent campaign/membership/character snapshot for ST context."""
        with closing(self.store._connect()) as conn:
            conn.execute("BEGIN")
            campaign = self.memory._campaign(conn, campaign_id)
            characters = [self.store._record(row) for row in conn.execute(
                "SELECT c.* FROM characters c JOIN campaign_members m ON m.character_id=c.id "
                "WHERE m.campaign_id=? ORDER BY c.name COLLATE NOCASE,c.id", (campaign_id,))]
            result = {"campaign": campaign, "characters": characters}
        result["solo"] = self.solo.context(campaign_id)
        return result

    @staticmethod
    def _operation(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError("operation_id must be a nonempty string of at most 200 characters")

    def _prior(self, conn, operation_id, payload):
        if conn.execute("SELECT 1 FROM gameplay_events WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a solo action")
        row = conn.execute("SELECT payload,result FROM rolls WHERE operation_id=?", (operation_id,)).fetchone()
        if row:
            if row["payload"] != payload:
                raise ValueError("operation_id was already used for another roll")
            return json.loads(row["result"])
        if conn.execute("SELECT 1 FROM audit WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a state change")
        if conn.execute("SELECT 1 FROM campaign_events WHERE operation_id=?", (operation_id,)).fetchone():
            raise ValueError("operation_id was already used for a campaign change")
        return None

    def roll(self, count, sides, operation_id, reason):
        self._operation(operation_id)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A roll reason is required")
        payload = _json(dict(action="roll_dice", count=count, sides=sides, reason=reason))
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = self._prior(conn, operation_id, payload)
            if prior is not None:
                return prior
            dice = roll_dice(count, sides)
            result = dict(operation_id=operation_id, dice=dice, total=sum(dice), reason=reason)
            conn.execute("INSERT INTO rolls VALUES(?,?,?)", (operation_id, payload, _json(result)))
            return result

    def check(self, character_id, expected_revision, stat, skill, dv, operation_id,
              reason, modifier=0, luck=0, complementary=False, extra_time=False):
        """Roll from stored values, deducting declared LUCK in the same transaction.

        The GM must establish the DV, modifiers and any improved retry circumstances
        from evidence before calling. This does not infer an action's governing skill.
        """
        self._operation(operation_id)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A check reason is required")
        payload = _json(dict(action="skill_check", character_id=character_id,
                            expected_revision=expected_revision, stat=stat, skill=skill, dv=dv,
                            reason=reason, modifier=modifier, luck=luck,
                            complementary=complementary, extra_time=extra_time))
        with closing(self.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = self._prior(conn, operation_id, payload)
            if prior is not None:
                return prior
            before = self.store._record(conn.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone())
            if before is None:
                raise ValueError("Character not found")
            _integer(expected_revision, "expected_revision", 1, 2**63 - 1)
            if before["revision"] != expected_revision:
                raise ValueError("revision conflict; read the character before rolling")
            if not isinstance(stat, str) or not stat.strip():
                raise ValueError("Unknown stat")
            stat_upper = stat.strip().upper()
            if stat_upper == "ROLE":
                role_rank = _resolve_role_ability_rank(before, skill)
                if role_rank is None:
                    raise ValueError("Unknown stat")
            else:
                canonical_stat = next(
                    (k for k in before["stats"] if isinstance(k, str) and k.strip().upper() == stat_upper),
                    None,
                )
                if canonical_stat is None:
                    raise ValueError("Unknown stat")
                if skill is not None and (not isinstance(skill, str) or not skill.strip()):
                    raise ValueError("skill must be a name or null for an untrained check")
            _integer(luck, "luck", 0, before["luck_remaining"])
            ctx = rules_eval.effective_check_context(before, stat_upper, skill)
            if stat_upper == "ROLE":
                stat_value, skill_value = ctx["skill_value"], 0
            else:
                stat_value, skill_value = ctx["stat_value"], ctx["skill_value"]
            result = skill_check(
                stat_value,
                skill_value,
                dv,
                modifier=modifier,
                luck=luck,
                complementary=complementary,
                extra_time=extra_time,
            )
            dice = list(result.get("dice") or [])
            initial_die = dice[0] if dice else None
            crit_adj = int(result.get("critical_adjustment", 0) or 0)
            if ctx["fumble_recovery"] and initial_die == 1:
                result["total"] -= crit_adj
                crit_adj = 0
                result["critical_adjustment"] = 0
                result["dice"] = [1]
                is_crit_failure = False
            else:
                is_crit_failure = initial_die == 1
            is_crit_success = initial_die == 10

            # Apply authoritative sheet/condition modifiers separately, keeping caller modifiers auditable.
            result["total"] += ctx["total_modifier"]
            result["success"] = result["total"] > dv
            result["margin"] = result["total"] - dv
            result["reason"] = reason
            result["die"] = initial_die
            result["explosion"] = crit_adj
            result["critical_success"] = is_crit_success
            result["critical_failure"] = is_crit_failure
            result["wound_modifier"] = ctx["wound_penalty"]
            result["armor_penalty"] = ctx["armor_penalty"]
            result["injury_penalty"] = ctx["injury_penalty"]
            result["solo_bonus"] = ctx["solo_bonus"]
            result["fumble_recovery"] = ctx["fumble_recovery"]
            result["modifier_breakdown"] = list(ctx["reasons"])
            result["stat_value"] = stat_value
            result["skill_value"] = skill_value
            result["operation_id"] = operation_id
            after = dict(before, luck_remaining=before["luck_remaining"] - luck,
                         revision=before["revision"] + 1)
            result["character"] = after
            conn.execute("UPDATE characters SET luck_remaining=?,revision=? WHERE id=?",
                         (after["luck_remaining"], after["revision"], character_id))
            conn.execute("INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                         (character_id, after["revision"], _json(before), _json(after), reason, operation_id, payload))
            conn.execute("INSERT INTO rolls VALUES(?,?,?)", (operation_id, payload, _json(result)))
            return result
