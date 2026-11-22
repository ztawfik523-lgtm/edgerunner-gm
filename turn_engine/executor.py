"""Deterministic GM plan execution (checks, state_ops, solo_ops, clocks, secrets)."""
from __future__ import annotations

from contextlib import closing
import re
from typing import Any

from campaign import STAT_NAMES, _json
from gameplay import GameplayService, _resolve_role_ability_rank
from library import CampaignLibrary, normalize_category, search_library
from mechanics import skill_check as _mechanics_skill_check
from rules_eval import sync_emp_from_humanity
import sourcecatalog
from turn_engine.chat_tree import BranchPrivateStateStore
from turn_engine.state_normalization import (
    _CANONICAL_ROLE_CHECKS,
    _format_clock_label,
    _normalize_campaign_changes,
    _normalize_character_changes,
    _parse_clock_minutes,
    _resolve_character,
)

_MAX_HOMEBREW_PER_TURN = 6
_MAX_CHECKS_PER_TURN = 8
_MAX_OPS_PER_TURN = 12
_ATTACK_MODES = frozenset({"ranged", "single", "autofire", "melee", "brawling", "aimed", "martial_arts", "suppressive"})
_SPECIALIZABLE_SKILL_BASES = frozenset({"language", "local expert", "science", "play instrument", "martial arts"})

_STATIC_CANONICAL_SKILL_STATS: dict[str, tuple[str, str]] = {
    sourcecatalog._normalize(name): (name, stat)
    for name, stat in (
        # Awareness
        ("Concentration", "WILL"),
        ("Conceal/Reveal Object", "INT"),
        ("Lip Reading", "INT"),
        ("Perception", "INT"),
        ("Tracking", "INT"),
        # Body
        ("Athletics", "DEX"),
        ("Contortionist", "DEX"),
        ("Dance", "DEX"),
        ("Endurance", "WILL"),
        ("Resist Torture/Drugs", "WILL"),
        ("Stealth", "DEX"),
        # Control
        ("Drive Land Vehicle", "REF"),
        ("Pilot Air Vehicle", "REF"),
        ("Pilot Sea Vehicle", "REF"),
        ("Riding", "REF"),
        # Education
        ("Accounting", "INT"),
        ("Animal Handling", "INT"),
        ("Bureaucracy", "INT"),
        ("Business", "INT"),
        ("Composition", "INT"),
        ("Criminology", "INT"),
        ("Cryptography", "INT"),
        ("Deduction", "INT"),
        ("Education", "INT"),
        ("Gamble", "INT"),
        ("Language", "INT"),
        ("Library Search", "INT"),
        ("Local Expert", "INT"),
        ("Science", "INT"),
        ("Stock Market", "INT"),
        ("Tactics", "INT"),
        ("Wilderness Survival", "INT"),
        # Fighting
        ("Brawling", "DEX"),
        ("Evasion", "DEX"),
        ("Martial Arts", "DEX"),
        ("Melee Weapon", "DEX"),
        # Performance
        ("Acting", "COOL"),
        ("Play Instrument", "COOL"),
        # Ranged
        ("Archery", "REF"),
        ("Autofire", "REF"),
        ("Handgun", "REF"),
        ("Heavy Weapons", "REF"),
        ("Shoulder Arms", "REF"),
        # Social
        ("Bribery", "COOL"),
        ("Conversation", "EMP"),
        ("Human Perception", "EMP"),
        ("Interrogation", "COOL"),
        ("Persuasion", "COOL"),
        ("Personal Grooming", "COOL"),
        ("Streetwise", "COOL"),
        ("Trading", "COOL"),
        ("Wardrobe & Style", "COOL"),
        # Technique
        ("Air Vehicle Tech", "TECH"),
        ("Basic Tech", "TECH"),
        ("Cybertech", "TECH"),
        ("Demolitions", "TECH"),
        ("Electronics/Security Tech", "TECH"),
        ("First Aid", "TECH"),
        ("Forgery", "TECH"),
        ("Land Vehicle Tech", "TECH"),
        ("Paint/Draw/Sculpt", "TECH"),
        ("Paramedic", "TECH"),
        ("Photography/Film", "TECH"),
        ("Pick Lock", "TECH"),
        ("Pick Pocket", "TECH"),
        ("Sea Vehicle Tech", "TECH"),
        ("Weaponstech", "TECH"),
    )
}


def _char_handle(char: dict[str, Any]) -> str:
    d = char.get("detail") or {}
    return str(d.get("handle") or char.get("name") or "Edgerunner").strip()


def _sanitize_roll_payload(
    res: dict[str, Any],
    *,
    actor: str,
    character_id: str | None,
    stat: str | None,
    skill: str | None,
    dv: int | None,
    modifier: int = 0,
    luck: int = 0,
    overclock: bool = False,
    complementary: bool = False,
    extra_time: bool = False,
    reason: str = "",
    npc: bool = False,
    success_override: bool | None = None,
) -> dict[str, Any]:
    """Build a safe, whitelisted dice-roll payload without leaking full character sheets."""
    dice_vals = list(res.get("dice") or [])
    crit_adj = int(res.get("critical_adjustment") or 0)
    total_val = res.get("total")
    eff_dv = res.get("dv") if dv is None else dv
    success_val = bool(res.get("success")) if success_override is None else bool(success_override)
    margin_val = (int(total_val) - int(eff_dv)) if isinstance(total_val, int) and isinstance(eff_dv, int) else None
    die_val = dice_vals[0] if dice_vals else res.get("die")
    out: dict[str, Any] = {
        "actor": actor,
        "character_id": character_id,
        "stat": stat,
        "skill": skill,
        "base": res.get("base"),
        "die": die_val,
        "dice": dice_vals,
        "explosion": crit_adj,
        "critical_adjustment": crit_adj,
        "modifier": int(modifier or 0),
        "luck": int(luck or 0),
        "luck_spent": int(luck or 0),
        "wound_modifier": int(res.get("wound_modifier") or 0),
        "total": total_val,
        "dv": eff_dv,
        "success": success_val,
        "margin": margin_val,
        "critical_success": bool(die_val == 10),
        "critical_failure": bool(die_val == 1),
        "overclock": bool(overclock),
        "complementary": bool(complementary),
        "extra_time": bool(extra_time),
        "reason": str(res.get("reason") or reason or "").strip(),
        "npc": bool(npc),
    }
    if res.get("stat_value") is not None:
        out["stat_value"] = res.get("stat_value")
    if res.get("skill_value") is not None:
        out["skill_value"] = res.get("skill_value")
    if res.get("breakdown") is not None:
        out["breakdown"] = res.get("breakdown")
    return out


class PlanExecutor:
    """Executes structured GM plans deterministically against GameplayService and CampaignLibrary."""

    def __init__(
        self,
        gameplay: GameplayService,
        library: CampaignLibrary,
        private_state: BranchPrivateStateStore,
        turn_settings: dict[str, Any] | None = None,
    ):
        self.gameplay = gameplay
        self.library = library
        self.private_state = private_state
        self.turn_settings = turn_settings if turn_settings is not None else {}
        self._skill_cache: dict[str, dict[str, Any]] | None = None
        self._item_cache: dict[str, dict[str, Any]] | None = None

    def catalog_items(self) -> dict[str, dict[str, Any]]:
        if self._item_cache is not None:
            return self._item_cache
        if self.gameplay.rules_path and self.gameplay.rules_path.is_file():
            try:
                self._item_cache = sourcecatalog.items(self.gameplay.rules_path)
                return self._item_cache
            except ValueError:
                pass
        self._item_cache = {}
        return self._item_cache

    def corebook_skills(self) -> dict[str, dict[str, Any]]:
        if self._skill_cache is not None:
            return self._skill_cache
        if self.gameplay.rules_path and self.gameplay.rules_path.is_file():
            try:
                self._skill_cache = sourcecatalog.skills(self.gameplay.rules_path)
                return self._skill_cache
            except ValueError:
                pass
        self._skill_cache = {}
        return self._skill_cache

    def verify_skill(
        self,
        campaign_id: str,
        skill_name: Any,
        requested_stat: str | None,
        *,
        character: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None, str | None, dict[str, Any] | None]:
        """Validate proposed skill against Corebook, character sheet, or campaign homebrew skill entries."""
        if skill_name is None or (isinstance(skill_name, str) and not skill_name.strip()):
            stat = requested_stat.upper() if isinstance(requested_stat, str) and requested_stat.upper() in STAT_NAMES else None
            return (stat is not None, None, stat, None)
        if not isinstance(skill_name, str):
            return (False, None, None, None)

        norm_req = sourcecatalog._normalize(skill_name)
        role_hit = _CANONICAL_ROLE_CHECKS.get(norm_req)
        if role_hit is not None:
            canonical_role, role_stat = role_hit
            return (True, canonical_role, role_stat, {"source": "corebook", "name": canonical_role, "stat": role_stat})

        core = self.corebook_skills()
        hit = sourcecatalog.lookup_skill(core, skill_name) if core else None
        if hit is not None:
            canonical = next(
                (k for k in core if sourcecatalog._normalize(k) == norm_req),
                None,
            )
            if canonical is None:
                m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", skill_name.strip())
                if m:
                    base_norm = sourcecatalog._normalize(m.group(1))
                    base_canon = next((k for k in core if sourcecatalog._normalize(k) == base_norm), m.group(1).strip())
                    canonical = f"{base_canon} ({m.group(2).strip()})"
                else:
                    canonical = skill_name.strip()
            return (True, canonical, hit["stat"], {"source": "corebook", "name": canonical, **hit})

        # Check character's own skills case-insensitively before falling back.
        if isinstance(character, dict):
            char_skills = character.get("skills") or {}
            char_skill_key = next(
                (k for k in char_skills if isinstance(k, str) and sourcecatalog._normalize(k) == norm_req),
                None,
            )
            if char_skill_key is not None:
                static_hit = self._lookup_static_skill(char_skill_key)
                req_s = requested_stat.upper() if isinstance(requested_stat, str) and requested_stat.upper() in STAT_NAMES else None
                core_hit = sourcecatalog.lookup_skill(core, char_skill_key) if core else None
                stat_resolved = (
                    (core_hit["stat"] if core_hit else None)
                    or (static_hit[1] if static_hit else None)
                    or req_s
                )
                if stat_resolved:
                    return (True, char_skill_key, stat_resolved, {"source": "character", "name": char_skill_key, "stat": stat_resolved})

        homebrew_hits = search_library(
            self.gameplay.rules_path,
            q=skill_name,
            category="skill",
            campaign_path=self.gameplay.store.path,
            campaign_id=campaign_id,
            limit=10,
        )
        exact = next(
            (e for e in homebrew_hits if sourcecatalog._normalize(e["name"]) == norm_req),
            None,
        )
        if exact is not None:
            entry_stat = str((exact.get("stats") or {}).get("stat") or requested_stat or "").upper()
            stat = entry_stat if entry_stat in STAT_NAMES else None
            return (stat is not None, exact["name"], stat, exact)

        # Fall back to the static canonical Cyberpunk RED skill->STAT table when Corebook DB is absent or omits a standard skill.
        static_hit = self._lookup_static_skill(skill_name)
        if static_hit is not None:
            canon_name, canon_stat = static_hit
            return (True, canon_name, canon_stat, {"source": "corebook_static", "name": canon_name, "stat": canon_stat})

        return (False, skill_name, None, None)

    @staticmethod
    def _lookup_static_skill(skill_name: str) -> tuple[str, str] | None:
        norm_req = sourcecatalog._normalize(skill_name)
        hit = _STATIC_CANONICAL_SKILL_STATS.get(norm_req)
        if hit is not None:
            return hit
        m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", norm_req)
        if m and m.group(1).strip() in _SPECIALIZABLE_SKILL_BASES:
            base_hit = _STATIC_CANONICAL_SKILL_STATS.get(m.group(1).strip())
            if base_hit is not None:
                orig_m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", skill_name.strip())
                spec = orig_m.group(2).strip() if orig_m else m.group(2).strip()
                return (f"{base_hit[0]} ({spec})", base_hit[1])
        return None

    def deduct_humanity(self, character_id: str, amount: int, reason: str, operation_id: str) -> dict[str, Any]:
        payload = _json({"action": "overclock_humanity", "character_id": character_id, "amount": amount, "reason": reason})
        with closing(self.gameplay.store._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self.gameplay.store._reject_roll_id(conn, operation_id)
            row = conn.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
            if row is None:
                raise ValueError(f"character not found: {character_id}")
            before = self.gameplay.store._record(row)
            if before["humanity"] < amount:
                raise ValueError(f"{_char_handle(before)} lacks Humanity for Overclock (has {before['humanity']}, needs {amount})")
            after = dict(before, humanity=before["humanity"] - amount, revision=before["revision"] + 1)
            after["stats"] = dict(before.get("stats") or {})
            sync_emp_from_humanity(after)
            conn.execute(
                "UPDATE characters SET humanity=?, stats=?, revision=? WHERE id=?",
                (after["humanity"], _json(after["stats"]), after["revision"], character_id),
            )
            conn.execute(
                "INSERT INTO audit(character_id,revision,before_json,after_json,reason,operation_id,payload) VALUES(?,?,?,?,?,?,?)",
                (character_id, after["revision"], _json(before), _json(after), reason, operation_id, payload),
            )
            return {"before": before["humanity"], "after": after["humanity"], "revision": after["revision"], "character": after}

    def apply_character_update_op(
        self,
        campaign_id: str,
        actor_hint: Any,
        raw_changes: Any,
        reason: str,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Normalize and apply a character state patch via GameplayService."""
        ctx = self.gameplay.campaign_context(campaign_id)
        live_chars = ctx["characters"]
        known_npcs = (ctx.get("campaign") or {}).get("state", {}).get("npcs")
        char = _resolve_character(actor_hint, live_chars, known_npcs=known_npcs)
        if char is None:
            return [], [f"Unknown character for state update: {actor_hint!r}"]
        if not isinstance(raw_changes, dict) or not raw_changes:
            return [], []

        raw_changes = dict(raw_changes)
        ip_entry = raw_changes.pop("ip", None)
        patches: list[dict[str, Any]] = []
        warnings: list[str] = []
        char_label = _char_handle(char)

        if ip_entry is not None:
            d = char.get("detail") or {}
            current_ip = int(((d.get("role_ext") or {}).get("ip")) or d.get("ip") or 0)
            try:
                if isinstance(ip_entry, dict):
                    delta = int(ip_entry.get("delta", ip_entry.get("amount", 0)))
                    if "target" in ip_entry:
                        delta = int(ip_entry["target"]) - current_ip
                else:
                    raw_ip = int(ip_entry)
                    if raw_ip > current_ip and current_ip > 0:
                        delta = raw_ip - current_ip
                    else:
                        delta = raw_ip
                if delta > 0:
                    solo_rev = int(ctx["solo"]["revision"])
                    self.gameplay.execute(
                        "role_action",
                        {
                            "character_id": char["id"],
                            "action": "award_ip",
                            "arguments": {"amount": delta, "reason": reason},
                            "expected_revision": solo_rev,
                            "reason": reason,
                            "operation_id": f"{operation_id}:ip",
                        },
                        campaign_id=campaign_id,
                    )
                    after_ip = current_ip + delta
                    patches.append(
                        {
                            "target": "character",
                            "character_id": char["id"],
                            "name": char_label,
                            "before": {"ip": current_ip},
                            "after": {"ip": after_ip},
                            "reason": reason,
                        }
                    )
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped IP update: {exc}")

        changes, norm_notes = _normalize_character_changes(raw_changes, char)
        warnings.extend(norm_notes)
        if not changes:
            return patches, warnings

        if patches:
            refreshed_chars = self.gameplay.campaign_context(campaign_id)["characters"]
            refreshed = next((c for c in refreshed_chars if c["id"] == char["id"]), None)
            if refreshed:
                char = refreshed

        before_vals = {k: char.get(k) for k in changes}
        update_op_id = f"{operation_id}:state" if patches else operation_id
        try:
            updated = self.gameplay.execute(
                "update_character",
                {
                    "character_id": char["id"],
                    "expected_revision": char["revision"],
                    "changes": changes,
                    "reason": reason,
                    "operation_id": update_op_id,
                },
                campaign_id=campaign_id,
            )["result"]
            patches.append(
                {
                    "target": "character",
                    "character_id": char["id"],
                    "name": char_label,
                    "before": before_vals,
                    "after": {k: updated.get(k) for k in changes},
                    "reason": reason,
                }
            )
            return patches, warnings
        except (TypeError, ValueError) as exc:
            warnings.append(f"Skipped character update: {exc}")
            return patches, warnings

    @staticmethod
    def _resolve_encounter_npc(hint: Any, encounter_npcs: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any] | None:
        """Resolve an active ephemeral encounter NPC sheet by id, name, handle, or unique first token."""
        if not encounter_npcs or not isinstance(hint, str) or not hint.strip():
            return None
        items: list[dict[str, Any]] = []
        if isinstance(encounter_npcs, dict):
            for k, v in encounter_npcs.items():
                if isinstance(v, dict):
                    items.append({"id": v.get("id") or k, **v})
        elif isinstance(encounter_npcs, list):
            items = [v for v in encounter_npcs if isinstance(v, dict)]
        if not items:
            return None
        raw = hint.strip()
        needle = raw.casefold()
        for npc in items:
            d = npc.get("detail") or {}
            handle = str(d.get("handle") or "").strip()
            name = str(npc.get("name") or "").strip()
            if npc.get("id") == raw or name.casefold() == needle or (handle and handle.casefold() == needle):
                return npc
        tok_matches: list[dict[str, Any]] = []
        for npc in items:
            d = npc.get("detail") or {}
            for cand in (str(d.get("handle") or "").strip(), str(npc.get("name") or "").strip()):
                parts = cand.split()
                if parts and parts[0].casefold() == needle:
                    tok_matches.append(npc)
                    break
        return tok_matches[0] if len(tok_matches) == 1 else None

    def execute_npc_check(
        self,
        campaign_id: str,
        chk: dict[str, Any],
        *,
        encounter_npcs: dict[str, Any] | list[dict[str, Any]] | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a deterministic NPC or environmental skill check backed by mechanics.skill_check."""
        del operation_id
        actor_label = str(chk.get("actor") or "NPC").strip() or "NPC"
        raw_skill = chk.get("skill")
        raw_stat = chk.get("stat")
        explicit_base = chk.get("base")
        if raw_skill is not None or raw_stat is not None:
            skill_ok, resolved_skill, resolved_stat, _ = self.verify_skill(campaign_id, raw_skill, raw_stat)
            if not skill_ok or not resolved_stat:
                if isinstance(explicit_base, int) and not isinstance(explicit_base, bool) and not raw_skill:
                    resolved_skill = None
                    resolved_stat = str(raw_stat or "NPC").upper()
                else:
                    raise ValueError(f"Blocked unverified skill/stat in check: {raw_skill!r}")
        elif isinstance(explicit_base, int) and not isinstance(explicit_base, bool):
            resolved_skill = None
            resolved_stat = "NPC"
        else:
            raise ValueError("Blocked unverified skill/stat in check: None")

        dv_raw = chk.get("dv", 13)
        mod_raw = chk.get("modifier", 0)
        comp = chk.get("complementary", False)
        extra_t = chk.get("extra_time", False)
        if isinstance(dv_raw, bool) or isinstance(mod_raw, bool):
            raise ValueError("Invalid numeric parameters in NPC check")
        dv = int(dv_raw)
        modifier = int(mod_raw)
        if not isinstance(comp, bool) or not isinstance(extra_t, bool):
            raise ValueError("complementary and extra_time must be booleans")

        npc_sheet = self._resolve_encounter_npc(actor_label, encounter_npcs)
        wound_modifier = 0
        npc_id: str | None = None
        if npc_sheet is not None:
            npc_id = str(npc_sheet.get("id") or "") or None
            actor_label = _char_handle(npc_sheet)
            npc_stats = npc_sheet.get("stats") or {}
            npc_skills = npc_sheet.get("skills") or {}
            stat_val = int(npc_stats.get(resolved_stat, 6)) if resolved_stat in npc_stats else 6
            skill_val = 0
            if resolved_skill:
                norm_sk = sourcecatalog._normalize(resolved_skill)
                for sk_k, sk_v in npc_skills.items():
                    if isinstance(sk_k, str) and sourcecatalog._normalize(sk_k) == norm_sk and isinstance(sk_v, int):
                        skill_val = sk_v
                        break
            hp = npc_sheet.get("hp")
            max_hp = npc_sheet.get("max_hp")
            if isinstance(hp, int) and isinstance(max_hp, int) and max_hp > 0:
                thresh = (max_hp + 1) // 2
                wound_modifier = -4 if hp < 1 else (-2 if hp < thresh else 0)
        elif isinstance(explicit_base, int) and not isinstance(explicit_base, bool):
            stat_val = max(0, int(explicit_base))
            skill_val = 0
        elif isinstance(chk.get("stat_value"), int) or isinstance(chk.get("skill_value"), int):
            sv = chk.get("stat_value", 0)
            kv = chk.get("skill_value", 0)
            if isinstance(sv, bool) or isinstance(kv, bool):
                raise ValueError("Invalid stat_value/skill_value")
            stat_val = max(0, int(sv))
            skill_val = max(0, int(kv))
        else:
            tier = str(chk.get("tier") or "").strip().lower()
            stat_val = 12 if tier in {"lieutenant", "boss", "elite"} else 10
            skill_val = 0

        res = _mechanics_skill_check(
            stat_val,
            skill_val,
            dv,
            modifier=modifier,
            luck=0,
            complementary=comp,
            extra_time=extra_t,
        )
        res["wound_modifier"] = wound_modifier
        res["total"] = int(res["total"]) + wound_modifier
        res["success"] = res["total"] > dv
        reason_str = str(chk.get("reason") or f"{resolved_skill or resolved_stat} check").strip()
        return _sanitize_roll_payload(
            res,
            actor=actor_label,
            character_id=npc_id,
            stat=resolved_stat,
            skill=resolved_skill,
            dv=dv,
            modifier=modifier,
            luck=0,
            overclock=False,
            complementary=comp,
            extra_time=extra_t,
            reason=reason_str,
            npc=True,
        )

    def _resolve_actor_or_npc_id(
        self,
        hint: Any,
        live_chars: list[dict[str, Any]],
        encounter_npcs: dict[str, Any] | list[dict[str, Any]] | None,
        known_npcs: dict[str, Any] | None = None,
    ) -> tuple[str | None, dict[str, Any] | None, bool]:
        """Resolve an ID or name/handle across attached PCs and active encounter NPCs."""
        pc = _resolve_character(hint, live_chars, known_npcs=known_npcs)
        if pc is not None:
            return pc["id"], pc, False
        npc = self._resolve_encounter_npc(hint, encounter_npcs)
        if npc is not None:
            return str(npc.get("id") or ""), npc, True
        return None, None, False

    def _extract_solo_outcomes_and_rolls(
        self,
        action: str,
        raw_args: dict[str, Any],
        res: Any,
        *,
        actor_label: str,
        actor_id: str | None,
        actor_is_npc: bool,
        target_label: str | None,
        target_id: str | None,
        name_lookup: dict[str, tuple[str, bool]],
        before_target_armor: list[dict[str, Any]] | None,
        reason: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Extract sanitized dice rolls and structured outcomes from SoloService res['result']."""
        solo_rolls: list[dict[str, Any]] = []
        solo_outcomes: list[dict[str, Any]] = []
        if not isinstance(res, dict):
            return solo_rolls, solo_outcomes
        inner = res.get("result")
        if not isinstance(inner, dict):
            return solo_rolls, solo_outcomes

        def _name_and_npc(cid: Any, fallback: str = "Combatant") -> tuple[str, bool]:
            if cid is not None and str(cid) in name_lookup:
                return name_lookup[str(cid)]
            return fallback, False

        if action == "start_encounter":
            order = inner.get("queue") or []
            init_rolls = inner.get("initiative") or {}
            init_summary: list[dict[str, Any]] = []
            combatants: list[str] = []
            for cid in order:
                cname, c_is_npc = _name_and_npc(cid, str(cid))
                combatants.append(cname)
                r = init_rolls.get(cid)
                if isinstance(r, dict) and isinstance(r.get("dice"), list):
                    dice_vals = list(r["dice"])
                    total = r.get("total")
                    base = (int(total) - int(dice_vals[0])) if isinstance(total, int) and dice_vals else None
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            {**r, "base": base, "dv": 0, "success": True},
                            actor=cname,
                            character_id=str(cid),
                            stat="REF",
                            skill="Initiative",
                            dv=0,
                            reason="Encounter initiative",
                            npc=c_is_npc,
                            success_override=True,
                        )
                    )
                    init_summary.append({"actor": cname, "total": total, "dice": dice_vals})
            solo_outcomes.append(
                {
                    "action": "start_encounter",
                    "round": inner.get("round", 1),
                    "queue": combatants,
                    "combatants": combatants,
                    "initiative": init_summary,
                }
            )
            return solo_rolls, solo_outcomes

        if action == "encounter_action":
            sub = str(raw_args.get("action") or "")
            if sub == "attack":
                attacks_out: list[dict[str, Any]] = []
                for item in inner.get("attacks") or []:
                    if not isinstance(item, dict):
                        continue
                    chk = item.get("check") or {}
                    hit = bool(item.get("hit"))
                    defense = chk.get("defense") if isinstance(chk.get("defense"), dict) else None
                    eff_dv = defense.get("total") if defense else chk.get("dv")
                    atk_skill = (raw_args.get("arguments") or {}).get("mode") or "Attack"
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            chk,
                            actor=actor_label,
                            character_id=actor_id,
                            stat="DEX" if atk_skill in {"melee", "brawling", "martial_arts"} else "REF",
                            skill=str(atk_skill),
                            dv=eff_dv if isinstance(eff_dv, int) else 0,
                            modifier=int(chk.get("modifier") or 0),
                            luck=int(chk.get("luck_bonus") or 0),
                            reason=reason or f"Attack vs {target_label or 'target'}",
                            npc=actor_is_npc,
                            success_override=hit,
                        )
                    )
                    if defense and target_label:
                        t_name, t_npc = _name_and_npc(target_id, target_label)
                        solo_rolls.append(
                            _sanitize_roll_payload(
                                defense,
                                actor=t_name,
                                character_id=target_id,
                                stat="DEX",
                                skill="Evasion",
                                dv=chk.get("total") if isinstance(chk.get("total"), int) else 0,
                                modifier=int(defense.get("modifier") or 0),
                                reason=f"Evasion vs {actor_label}",
                                npc=t_npc,
                                success_override=not hit,
                            )
                        )
                    dmg = item.get("damage") if isinstance(item.get("damage"), dict) else None
                    dmg_summary = None
                    if dmg is not None:
                        ablation = dmg.get("sp_ablation")
                        if ablation is None:
                            before_sp = sum(int(a.get("sp") or 0) for a in (before_target_armor or []) if isinstance(a, dict))
                            after_armor = dmg.get("armor_after") or []
                            after_sp = sum(int(a.get("sp") or 0) for a in after_armor if isinstance(a, dict))
                            ablation = max(0, before_sp - after_sp) if before_target_armor else (1 if int(dmg.get("penetration") or 0) > 0 else 0)
                        dmg_summary = {
                            "raw": dmg.get("raw"),
                            "effective_sp": dmg.get("effective_sp"),
                            "penetration": dmg.get("penetration"),
                            "hp_damage": dmg.get("hp_damage"),
                            "sp_ablation": ablation,
                            "critical_trigger": bool(dmg.get("critical_trigger")),
                        }
                    crits = [
                        {"name": ci.get("name"), "effects": ci.get("effects")}
                        for ci in (item.get("critical_injuries") or [])
                        if isinstance(ci, dict) and ci.get("name")
                    ]
                    if not crits and isinstance(item.get("critical_injury"), dict) and item["critical_injury"].get("name"):
                        ci = item["critical_injury"]
                        crits.append({"name": ci.get("name"), "effects": ci.get("effects")})
                    attacks_out.append(
                        {
                            "attacker": actor_label,
                            "target": target_label or target_id,
                            "hit": hit,
                            "attack_total": chk.get("total"),
                            "dv": eff_dv,
                            "defense_total": defense.get("total") if defense else None,
                            **({"damage": dmg_summary} if dmg_summary is not None else {}),
                            **({"critical_injuries": crits} if crits else {}),
                        }
                    )
                solo_outcomes.append(
                    {
                        "action": "encounter_action",
                        "subaction": "attack",
                        "actor": actor_label,
                        "target": target_label or target_id,
                        "attacks": attacks_out,
                    }
                )
            elif sub in {"grab", "escape"}:
                won = bool(inner.get("won") if sub == "grab" else inner.get("escaped"))
                chk_a = inner.get("attacker")
                chk_b = inner.get("defender")
                if isinstance(chk_a, dict):
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            chk_a,
                            actor=actor_label,
                            character_id=actor_id,
                            stat="DEX",
                            skill="Brawling",
                            dv=chk_b.get("total") if isinstance(chk_b, dict) else 0,
                            modifier=int(chk_a.get("modifier") or 0),
                            reason=f"{sub.title()} vs {target_label or 'target'}",
                            npc=actor_is_npc,
                            success_override=won,
                        )
                    )
                if isinstance(chk_b, dict) and target_label:
                    t_name, t_npc = _name_and_npc(target_id, target_label)
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            chk_b,
                            actor=t_name,
                            character_id=target_id,
                            stat="DEX",
                            skill="Brawling",
                            dv=chk_a.get("total") if isinstance(chk_a, dict) else 0,
                            modifier=int(chk_b.get("modifier") or 0),
                            reason=f"Resist {sub} vs {actor_label}",
                            npc=t_npc,
                            success_override=not won,
                        )
                    )
                solo_outcomes.append(
                    {
                        "action": "encounter_action",
                        "subaction": sub,
                        "actor": actor_label,
                        "target": target_label or target_id,
                        "success": won,
                    }
                )
            elif sub == "suppressive_fire":
                atk_chk = inner.get("attack_check")
                if isinstance(atk_chk, dict):
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            atk_chk,
                            actor=actor_label,
                            character_id=actor_id,
                            stat="REF",
                            skill="Autofire",
                            dv=0,
                            modifier=int(atk_chk.get("modifier") or 0),
                            reason="Suppressive Fire",
                            npc=actor_is_npc,
                            success_override=True,
                        )
                    )
                targets_out = []
                for t_row in inner.get("targets") or []:
                    if not isinstance(t_row, dict):
                        continue
                    tid = t_row.get("target_id")
                    t_name, t_npc = _name_and_npc(tid, str(tid))
                    def_chk = t_row.get("check")
                    forced = bool(t_row.get("forced_to_cover"))
                    if isinstance(def_chk, dict):
                        solo_rolls.append(
                            _sanitize_roll_payload(
                                def_chk,
                                actor=t_name,
                                character_id=str(tid) if tid else None,
                                stat="WILL",
                                skill="Concentration",
                                dv=atk_chk.get("total") if isinstance(atk_chk, dict) else 0,
                                modifier=int(def_chk.get("modifier") or 0),
                                reason=f"Resist Suppressive Fire vs {actor_label}",
                                npc=t_npc,
                                success_override=not forced,
                            )
                        )
                    targets_out.append({"target": t_name, "forced_to_cover": forced})
                solo_outcomes.append(
                    {
                        "action": "encounter_action",
                        "subaction": "suppressive_fire",
                        "actor": actor_label,
                        "targets": targets_out,
                    }
                )
            elif sub == "next_turn":
                next_id = inner.get("actor_id")
                next_name, next_npc = _name_and_npc(next_id, str(next_id or ""))
                ds = inner.get("death_save")
                if isinstance(ds, dict) and isinstance(ds.get("dice"), list):
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            {"dice": ds["dice"], "total": ds["dice"][0], "base": 0},
                            actor=next_name,
                            character_id=str(next_id) if next_id else None,
                            stat="BODY",
                            skill="Death Save",
                            dv=0,
                            reason="Death Save",
                            npc=next_npc,
                            success_override=bool(ds.get("survived")),
                        )
                    )
                solo_outcomes.append(
                    {
                        "action": "encounter_action",
                        "subaction": "next_turn",
                        "next_actor": next_name,
                        "round": inner.get("round"),
                        **({"death_save": ds} if ds is not None else {}),
                        **({"end_of_turn_effects": inner["end_of_turn_effects"]} if inner.get("end_of_turn_effects") else {}),
                        **({"ended": inner["ended"], "reason": inner.get("reason")} if inner.get("ended") else {}),
                    }
                )
            else:
                solo_outcomes.append(
                    {
                        "action": "encounter_action",
                        "subaction": sub,
                        "actor": actor_label,
                        **({"target": target_label or target_id} if (target_label or target_id) else {}),
                        **{k: v for k, v in inner.items() if k != "source"},
                    }
                )
            return solo_rolls, solo_outcomes

        if action == "health_action":
            sub = str(raw_args.get("action") or "")
            chk = inner.get("check")
            if isinstance(chk, dict):
                skill_lbl = str(inner.get("skill") or chk.get("skill") or ("Medical Tech" if sub == "therapy" else "First Aid/Paramedic"))
                solo_rolls.append(
                    _sanitize_roll_payload(
                        chk,
                        actor=actor_label,
                        character_id=actor_id,
                        stat="TECH",
                        skill=skill_lbl,
                        dv=chk.get("dv"),
                        modifier=int(chk.get("modifier") or 0),
                        reason=reason or f"Health: {sub}",
                        npc=actor_is_npc,
                    )
                )
            elif sub == "death_save" and "survived" in inner and isinstance(inner.get("dice"), list):
                t_name = target_label or actor_label
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": inner["dice"], "total": inner["dice"][0], "base": 0},
                        actor=t_name,
                        character_id=target_id or actor_id,
                        stat="BODY",
                        skill="Death Save",
                        dv=0,
                        reason=reason or "Death Save",
                        npc=False,
                        success_override=bool(inner.get("survived")),
                    )
                )
            solo_outcomes.append(
                {
                    "action": "health_action",
                    "subaction": sub,
                    "actor": actor_label,
                    **({"target": target_label} if target_label else {}),
                    **{k: v for k, v in inner.items() if k not in {"source", "check"}},
                    **({"check_total": chk.get("total"), "check_dv": chk.get("dv")} if isinstance(chk, dict) else {}),
                }
            )
            return solo_rolls, solo_outcomes

        if action == "role_action":
            sub = str(raw_args.get("action") or "")
            if isinstance(inner.get("check"), dict):
                chk = inner["check"]
                solo_rolls.append(
                    _sanitize_roll_payload(
                        chk,
                        actor=actor_label,
                        character_id=actor_id,
                        stat="TECH",
                        skill=str(inner.get("recipe") or inner.get("project_id") or sub),
                        dv=chk.get("dv"),
                        reason=reason or f"Role action: {sub}",
                        npc=actor_is_npc,
                    )
                )
            if isinstance(inner.get("fixer_check"), dict):
                fc = inner["fixer_check"]
                oc = inner.get("opponent_check") or {}
                solo_rolls.append(
                    _sanitize_roll_payload(
                        fc,
                        actor=actor_label,
                        character_id=actor_id,
                        stat="COOL",
                        skill="Trading",
                        dv=oc.get("total") if isinstance(oc, dict) else 0,
                        modifier=int(fc.get("modifier") or 0),
                        reason="Fixer Haggle",
                        npc=actor_is_npc,
                        success_override=bool(inner.get("success")),
                    )
                )
            if sub in {"rocker_favor", "rocker_convert"} and isinstance(inner.get("dice"), list):
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": inner["dice"], "total": inner.get("total"), "base": (inner.get("total", 0) - inner["dice"][0]) if inner["dice"] else 0},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill="Charismatic Impact",
                        dv=inner.get("dv"),
                        reason=reason or sub,
                        npc=actor_is_npc,
                        success_override=bool(inner.get("success")),
                    )
                )
            elif sub == "media_rumor" and "total" in inner:
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": [], "total": inner.get("total"), "base": None},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill="Credibility",
                        dv=inner.get("passive_dv"),
                        reason=reason or "Media Rumor",
                        npc=actor_is_npc,
                        success_override=inner.get("rumor") is not None,
                    )
                )
            elif sub == "lawman_backup" and "call_die" in inner:
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": [inner["call_die"]], "total": inner["call_die"], "base": 0},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill="Backup",
                        dv=0,
                        reason=reason or "Lawman Backup",
                        npc=actor_is_npc,
                        success_override=bool(inner.get("success")),
                    )
                )
            elif sub == "exec_team" and "die" in inner:
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": [inner["die"]], "total": inner["die"], "base": 0},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill="Teamwork",
                        dv=inner.get("loyalty") or 0,
                        reason=str(inner.get("task") or "Exec Team"),
                        npc=actor_is_npc,
                        success_override=bool(inner.get("success")),
                    )
                )
            elif sub == "media_publish" and "die" in inner:
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": [inner["die"]], "total": inner["die"], "base": 0},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill="Credibility",
                        dv=inner.get("chance_out_of_10") or 0,
                        reason=reason or "Media Publish",
                        npc=actor_is_npc,
                        success_override=bool(inner.get("believed")),
                    )
                )
            solo_outcomes.append(
                {
                    "action": "role_action",
                    "subaction": sub,
                    "actor": actor_label,
                    **{k: v for k, v in inner.items() if k not in {"source", "check", "fixer_check", "opponent_check"}},
                }
            )
            return solo_rolls, solo_outcomes

        if action == "economy_action":
            sub = str(raw_args.get("action") or "")
            if sub == "hustle" and isinstance(inner.get("dice"), list) and inner["dice"]:
                role_lbl = str((raw_args.get("arguments") or {}).get("role") or "Hustle")
                solo_rolls.append(
                    _sanitize_roll_payload(
                        {"dice": inner["dice"], "total": inner["dice"][0], "base": 0},
                        actor=actor_label,
                        character_id=actor_id,
                        stat="ROLE",
                        skill=f"Hustle ({role_lbl})",
                        dv=0,
                        reason=str(inner.get("label") or "Weekly Hustle"),
                        npc=actor_is_npc,
                        success_override=True,
                    )
                )
            solo_outcomes.append(
                {
                    "action": "economy_action",
                    "subaction": sub,
                    "actor": actor_label,
                    **{k: v for k, v in inner.items() if k != "source"},
                }
            )
            return solo_rolls, solo_outcomes

        if action == "substance_action":
            sub = str(raw_args.get("action") or "")
            for dc in inner.get("expired_drug_checks") or []:
                if isinstance(dc, dict) and isinstance(dc.get("dice"), list):
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            dc,
                            actor=target_label or actor_label,
                            character_id=target_id or actor_id,
                            stat="WILL",
                            skill="Resist Torture/Drugs",
                            dv=dc.get("dv"),
                            reason=f"Drug expiration ({dc.get('drug', 'substance')})",
                            npc=False,
                        )
                    )
            solo_outcomes.append(
                {
                    "action": "substance_action",
                    "subaction": sub,
                    "actor": actor_label,
                    **({"target": target_label} if target_label else {}),
                    **{k: v for k, v in inner.items() if k != "source"},
                }
            )
            return solo_rolls, solo_outcomes

        if action in {"net_action", "create_architecture", "start_netrun"}:
            sub = str(raw_args.get("action") or "") if action == "net_action" else ""
            chk = inner.get("check")
            if isinstance(chk, dict):
                if isinstance(chk.get("attacker"), dict):
                    atk = chk["attacker"]
                    dfd = chk.get("defender") or {}
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            atk,
                            actor=actor_label,
                            character_id=actor_id,
                            stat="ROLE",
                            skill="Interface",
                            dv=dfd.get("total") if isinstance(dfd, dict) else 0,
                            reason=f"NET {sub or action}",
                            npc=False,
                            success_override=bool(chk.get("attacker_wins")),
                        )
                    )
                elif isinstance(chk.get("dice"), list):
                    solo_rolls.append(
                        _sanitize_roll_payload(
                            chk,
                            actor=actor_label,
                            character_id=actor_id,
                            stat="ROLE",
                            skill="Interface",
                            dv=chk.get("dv"),
                            reason=f"NET {sub or action}",
                            npc=False,
                        )
                    )
            solo_outcomes.append(
                {
                    "action": action,
                    **({"subaction": sub} if sub else {}),
                    **({"actor": actor_label} if actor_label else {}),
                    **{k: v for k, v in inner.items() if k not in {"source", "check"}},
                }
            )
            return solo_rolls, solo_outcomes

        if action not in {"advance_time"}:
            sub_val = raw_args.get("action")
            solo_outcomes.append(
                {
                    "action": action,
                    **({"subaction": str(sub_val)} if sub_val else {}),
                    **({"actor": actor_label} if actor_label else {}),
                    **{k: v for k, v in inner.items() if k != "source"},
                }
            )
        return solo_rolls, solo_outcomes

    def execute_solo_op(
        self,
        campaign_id: str,
        op: dict[str, Any],
        default_actor: str | None,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        action = str(op.get("action") or op.get("type") or "").strip()
        if action == "update_character":
            raw_changes = op.get("changes")
            if not isinstance(raw_changes, dict):
                raw_changes = op.get("arguments") if isinstance(op.get("arguments"), dict) else {
                    k: v for k, v in op.items()
                    if k not in {"action", "type", "subaction", "mode", "actor", "reason", "_kind"}
                }
            c_patches, c_warns = self.apply_character_update_op(
                campaign_id,
                op.get("actor") or default_actor,
                raw_changes,
                str(op.get("reason") or "GM turn state update"),
                operation_id,
            )
            return c_patches, c_warns, [], []
        allowed = {
            "advance_time",
            "health_action",
            "economy_action",
            "gear_action",
            "role_action",
            "substance_action",
            "start_encounter",
            "encounter_action",
            "end_encounter",
            "create_architecture",
            "start_netrun",
            "net_action",
        }
        if action not in allowed:
            return [], [f"Ignored unsupported solo_op action: {action!r}"], [], []

        ctx = self.gameplay.campaign_context(campaign_id)
        live_chars = ctx["characters"]
        known_npcs = (ctx.get("campaign") or {}).get("state", {}).get("npcs")
        runtime = ctx["solo"].get("runtime") or {}
        cur_enc = runtime.get("encounter")
        encounter_npcs = cur_enc.get("npcs") if isinstance(cur_enc, dict) else None
        solo_rev = int(ctx["solo"]["revision"])
        is_start_time = op.get("_kind") == "start_time" or operation_id.endswith(":start_time")

        if isinstance(op.get("arguments"), dict):
            raw_args = dict(op["arguments"])
        else:
            raw_args = {
                k: v
                for k, v in op.items()
                if k not in {"action", "type", "subaction", "mode", "actor", "reason", "_kind"}
            }
        reason = str(op.get("reason") or f"GM solo action: {action}").strip()
        actor_hint = op.get("actor") or raw_args.pop("actor", None) or default_actor
        actor_id_res, actor_rec, actor_is_npc = self._resolve_actor_or_npc_id(
            actor_hint, live_chars, encounter_npcs, known_npcs=known_npcs
        )

        # Build id -> (display_handle, is_npc) lookup across PCs and active encounter NPCs.
        name_lookup: dict[str, tuple[str, bool]] = {c["id"]: (_char_handle(c), False) for c in live_chars}
        if isinstance(encounter_npcs, dict):
            for k, v in encounter_npcs.items():
                if isinstance(v, dict):
                    nid = str(v.get("id") or k)
                    name_lookup[nid] = (_char_handle(v), True)
        elif isinstance(encounter_npcs, list):
            for v in encounter_npcs:
                if isinstance(v, dict) and v.get("id"):
                    name_lookup[str(v["id"])] = (_char_handle(v), True)

        target_label: str | None = None
        resolved_target_id: str | None = None
        before_target_armor: list[dict[str, Any]] | None = None
        before_clock = int(runtime.get("clock_minutes") or 0)
        elapsed_val = 0

        if action == "start_encounter":
            if isinstance(cur_enc, dict) and cur_enc.get("active"):
                return [], [], [], []
            raw_candidates = raw_args.get("character_ids") or op.get("actors") or raw_args.get("actors")
            ids: list[str] = []
            seen_ids: set[str] = set()
            valid_ids = {c["id"] for c in live_chars}
            if isinstance(raw_candidates, list):
                for entry in raw_candidates:
                    if isinstance(entry, str) and entry in valid_ids and entry not in seen_ids:
                        ids.append(entry)
                        seen_ids.add(entry)
                    else:
                        matched = _resolve_character(entry, live_chars, known_npcs=known_npcs)
                        if matched is not None and matched["id"] not in seen_ids:
                            ids.append(matched["id"])
                            seen_ids.add(matched["id"])
            if not ids:
                if actor_rec is not None and not actor_is_npc and actor_id_res:
                    ids = [actor_id_res]
                else:
                    ids = [c["id"] for c in live_chars]
            if not ids:
                return [], ["Skipped solo action (start_encounter): no campaign members attached"], [], []
            raw_args = {"character_ids": ids}
        elif action == "advance_time":
            elapsed_raw = op.get("elapsed_minutes", raw_args.get("elapsed_minutes", 0))
            try:
                if isinstance(elapsed_raw, bool):
                    raise ValueError("bool")
                elapsed_val = int(elapsed_raw)
            except (TypeError, ValueError):
                return [], [f"Invalid elapsed_minutes for advance_time: {elapsed_raw!r}"], [], []
            raw_args = {"elapsed_minutes": elapsed_val}
        elif action == "end_encounter":
            raw_args = {}
        elif action == "create_architecture":
            raw_args = {
                k: v
                for k, v in raw_args.items()
                if k in {"floors", "access_points"}
            }
        elif action == "start_netrun":
            if isinstance(raw_args.get("arguments"), dict):
                inner_net = dict(raw_args["arguments"])
                for k, v in inner_net.items():
                    raw_args.setdefault(k, v)
            cid_hint = raw_args.get("character_id") or actor_hint
            cid_res, cid_rec, cid_is_npc = self._resolve_actor_or_npc_id(
                cid_hint, live_chars, encounter_npcs, known_npcs=known_npcs
            )
            if cid_rec is None or cid_is_npc or not cid_res:
                return [], [f"Unknown character for start_netrun: {cid_hint!r}"], [], []
            raw_args["character_id"] = cid_res
            actor_id_res, actor_rec, actor_is_npc = cid_res, cid_rec, False
        elif action == "net_action":
            subaction = op.get("subaction") or op.get("action_type") or raw_args.get("action") or op.get("mode")
            nested_args = dict(raw_args.get("arguments")) if isinstance(raw_args.get("arguments"), dict) else None
            if nested_args is None:
                envelope_keys = {"run_id", "action", "subaction", "action_type", "character_id", "actor_id", "arguments"}
                nested_args = {k: v for k, v in raw_args.items() if k not in envelope_keys}
            run_id = raw_args.get("run_id") or op.get("run_id")
            if not run_id:
                runs = runtime.get("runs") or {}
                connected_runs = [
                    (rid, r) for rid, r in runs.items()
                    if isinstance(r, dict) and (r.get("connected") or (r.get("run") or {}).get("connected"))
                ]
                if actor_id_res:
                    matching_runs = [
                        rid for rid, r in connected_runs
                        if (r.get("character_id") or (r.get("run") or {}).get("character_id")) == actor_id_res
                    ]
                    if len(matching_runs) == 1:
                        run_id = matching_runs[0]
                if not run_id and len(connected_runs) == 1:
                    run_id = connected_runs[0][0]
            raw_args = {
                **({"run_id": run_id} if run_id else {}),
                **({"action": str(subaction)} if subaction else {}),
                "arguments": nested_args,
            }
        else:
            # Resolve character_id / actor_id (supporting PCs and active encounter NPCs, even when passed as names/handles).
            if action in {"economy_action", "gear_action", "role_action"}:
                if "character_id" in raw_args and raw_args["character_id"] is not None:
                    c_res, c_rec, c_npc = self._resolve_actor_or_npc_id(
                        raw_args["character_id"], live_chars, encounter_npcs, known_npcs=known_npcs
                    )
                    if c_res:
                        raw_args["character_id"] = c_res
                        actor_id_res, actor_rec, actor_is_npc = c_res, c_rec, c_npc
                else:
                    if actor_rec is None or not actor_id_res:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"], [], []
                    raw_args["character_id"] = actor_id_res
            else:
                if "actor_id" in raw_args and raw_args["actor_id"] is not None:
                    a_res, a_rec, a_npc = self._resolve_actor_or_npc_id(
                        raw_args["actor_id"], live_chars, encounter_npcs, known_npcs=known_npcs
                    )
                    if a_res:
                        raw_args["actor_id"] = a_res
                        actor_id_res, actor_rec, actor_is_npc = a_res, a_rec, a_npc
                else:
                    if actor_rec is None or not actor_id_res:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"], [], []
                    raw_args["actor_id"] = actor_id_res

            # Resolve subaction vs attack firing mode carefully.
            explicit_sub = op.get("subaction") or op.get("action_type") or raw_args.get("subaction") or raw_args.get("action_type") or raw_args.get("action")
            op_mode = op.get("mode")
            mode_norm = str(op_mode).strip().lower() if isinstance(op_mode, str) else ""
            if explicit_sub:
                subaction = explicit_sub
            elif op_mode:
                if action == "encounter_action" and mode_norm in _ATTACK_MODES:
                    subaction = "suppressive_fire" if mode_norm == "suppressive" else "attack"
                else:
                    subaction = op_mode
            else:
                subaction = None

            nested_args = dict(raw_args.get("arguments")) if isinstance(raw_args.get("arguments"), dict) else None
            if nested_args is None:
                envelope_keys = {"character_id", "actor_id", "action", "subaction", "action_type", "arguments"}
                nested_args = {k: v for k, v in raw_args.items() if k not in envelope_keys}
                raw_args = {k: v for k, v in raw_args.items() if k in {"character_id", "actor_id"}}
                raw_args["arguments"] = nested_args

            if op_mode is not None and action == "encounter_action" and str(subaction or "").strip().lower() == "attack":
                if "mode" not in nested_args and mode_norm != "suppressive":
                    nested_args["mode"] = op_mode

            if subaction:
                raw_args["action"] = str(subaction)

            # Resolve target / target_id across top-level and nested arguments (PCs + encounter NPCs).
            top_target = raw_args.pop("target", None) or raw_args.pop("target_id", None)
            if top_target is not None:
                nested_args.setdefault("target_id", top_target)
            raw_tgt = nested_args.pop("target", None)
            if raw_tgt is not None and not nested_args.get("target_id"):
                nested_args["target_id"] = raw_tgt
            if nested_args.get("target_id") is not None:
                t_res, t_rec, _ = self._resolve_actor_or_npc_id(
                    nested_args["target_id"], live_chars, encounter_npcs, known_npcs=known_npcs
                )
                if t_res:
                    nested_args["target_id"] = t_res
                    resolved_target_id = t_res
                    target_label = _char_handle(t_rec) if t_rec else str(t_res)
                    if t_rec:
                        before_target_armor = list((t_rec.get("detail") or {}).get("equipment", {}).get("armor") or [])

            # Resolve suppressive_fire targets list entries.
            if action == "encounter_action" and raw_args.get("action") == "suppressive_fire" and isinstance(nested_args.get("targets"), list):
                for trow in nested_args["targets"]:
                    if isinstance(trow, dict):
                        t_hint = trow.pop("target", None) or trow.get("target_id")
                        if t_hint is not None:
                            tr_id, _, _ = self._resolve_actor_or_npc_id(
                                t_hint, live_chars, encounter_npcs, known_npcs=known_npcs
                            )
                            if tr_id:
                                trow["target_id"] = tr_id

            if action == "economy_action" and raw_args.get("action") == "job_reward":
                e_args = raw_args.setdefault("arguments", {})
                if not isinstance(e_args.get("contract_reason"), str) or not e_args["contract_reason"].strip():
                    e_args["contract_reason"] = reason

            if action == "role_action" and raw_args.get("action") == "award_ip":
                r_args = raw_args.setdefault("arguments", {})
                if "amount" not in r_args and "ip" in r_args:
                    try:
                        r_args["amount"] = int(r_args["ip"])
                    except (TypeError, ValueError):
                        pass
                if not isinstance(r_args.get("reason"), str) or not r_args["reason"].strip():
                    r_args["reason"] = reason

            if action == "gear_action":
                g_args = raw_args.setdefault("arguments", {})
                wanted_item = g_args.pop("item", None) or g_args.get("item_id")
                if isinstance(wanted_item, str) and wanted_item:
                    catalog = self.catalog_items()
                    if wanted_item in catalog:
                        g_args["item_id"] = wanted_item
                    else:
                        norm_w = sourcecatalog._normalize(wanted_item)
                        matched = next(
                            (item_id for item_id, item in catalog.items() if sourcecatalog._normalize(item.get("name", "")) == norm_w),
                            None,
                        )
                        g_args["item_id"] = matched or wanted_item

        before_map = {c["id"]: c for c in live_chars}
        payload_args = {**raw_args, "expected_revision": solo_rev, "reason": reason, "operation_id": operation_id}
        try:
            res = self.gameplay.execute(action, payload_args, campaign_id=campaign_id)["result"]
        except (TypeError, ValueError, KeyError) as exc:
            return [], [f"Skipped solo action ({action}): {exc}"], [], []

        if isinstance(res, dict) and res.get("committed") is False:
            ruling_reason = (res.get("result") or {}).get("reason") or "Requires manual tabletop ruling."
            return [], [f"Solo action ({action}) deferred: {ruling_reason}"], [], []

        actor_label = _char_handle(actor_rec) if actor_rec is not None else str(actor_hint or "")
        solo_rolls, solo_outcomes = self._extract_solo_outcomes_and_rolls(
            action,
            raw_args,
            res,
            actor_label=actor_label,
            actor_id=actor_id_res,
            actor_is_npc=actor_is_npc,
            target_label=target_label,
            target_id=resolved_target_id,
            name_lookup=name_lookup,
            before_target_armor=before_target_armor,
            reason=reason,
        )

        patches: list[dict[str, Any]] = []
        after_chars = (res.get("characters") if isinstance(res, dict) else None) or []
        for after_c in after_chars:
            cid = after_c.get("id")
            before_c = before_map.get(cid)
            if not before_c:
                continue
            b_diff: dict[str, Any] = {}
            a_diff: dict[str, Any] = {}
            for fld in ("hp", "money", "humanity", "luck_remaining", "inventory"):
                if before_c.get(fld) != after_c.get(fld):
                    b_diff[fld] = before_c.get(fld)
                    a_diff[fld] = after_c.get(fld)
            b_d = before_c.get("detail") or {}
            a_d = after_c.get("detail") or {}
            b_ip = int(((b_d.get("role_ext") or {}).get("ip")) or b_d.get("ip") or 0)
            a_ip = int(((a_d.get("role_ext") or {}).get("ip")) or a_d.get("ip") or 0)
            if b_ip != a_ip:
                b_diff["ip"] = b_ip
                a_diff["ip"] = a_ip
            if b_diff:
                patches.append(
                    {
                        "target": "character",
                        "character_id": cid,
                        "name": _char_handle(after_c),
                        "before": b_diff,
                        "after": a_diff,
                        "reason": reason,
                    }
                )
        if action == "advance_time" and isinstance(res, dict):
            time_res = res.get("result") if isinstance(res.get("result"), dict) else res
            b_m = int(time_res["before_minutes"]) if time_res.get("before_minutes") is not None else before_clock
            a_m = int(time_res["after_minutes"]) if time_res.get("after_minutes") is not None else (b_m + elapsed_val)
            time_patch: dict[str, Any] = {
                "target": "solo",
                "before": {"time": _format_clock_label(b_m)},
                "after": {"time": _format_clock_label(a_m)},
                "reason": reason,
            }
            if is_start_time:
                time_patch["kind"] = "start_time"
            patches.append(time_patch)
        elif action in {"health_action", "economy_action", "substance_action"}:
            after_clock = int(self.gameplay.campaign_context(campaign_id)["solo"]["runtime"].get("clock_minutes") or 0)
            if after_clock > before_clock:
                patches.append(
                    {
                        "target": "solo",
                        "before": {"time": _format_clock_label(before_clock)},
                        "after": {"time": _format_clock_label(after_clock)},
                        "reason": reason,
                    }
                )
        if not patches:
            patches.append(
                {
                    "target": "solo",
                    "before": {"solo_revision": solo_rev},
                    "after": {"solo_revision": res.get("revision", solo_rev + 1) if isinstance(res, dict) else solo_rev + 1, "action": action},
                    "reason": reason,
                }
            )
        return patches, [], solo_rolls, solo_outcomes

    def execute_plan(
        self,
        campaign_id: str,
        plan: dict[str, Any] | None,
        prep: dict[str, Any],
        *,
        overclock: bool = False,
        luck_spend: int = 0,
        default_actor: str | None = None,
        op_prefix: str | None = None,
        allow_checks: bool = True,
        allow_solo: bool = True,
        allow_character_updates: bool = True,
    ) -> dict[str, Any]:
        plan = plan if isinstance(plan, dict) else {}
        turn_id = op_prefix or prep["turn_id"]
        rolls: list[dict[str, Any]] = []
        solo_outcomes: list[dict[str, Any]] = []
        blocked_checks: list[str] = []
        patches: list[dict[str, Any]] = []
        added_library: list[dict[str, Any]] = []
        warnings: list[str] = []

        # 1. Create/update any AI-proposed campaign homebrew entries first so skill checks can reference new skills.
        raw_homebrew = (plan.get("new_homebrew") or []) if self.turn_settings.get("allow_ai_homebrew", True) else []
        if isinstance(raw_homebrew, list) and len(raw_homebrew) > _MAX_HOMEBREW_PER_TURN:
            warnings.append(f"Capped new_homebrew from {len(raw_homebrew)} to {_MAX_HOMEBREW_PER_TURN} entries.")
            raw_homebrew = raw_homebrew[:_MAX_HOMEBREW_PER_TURN]
        for idx, hb in enumerate(raw_homebrew):
            if not isinstance(hb, dict):
                continue
            try:
                raw_cat = hb.get("category")
                norm_cat = normalize_category(str(raw_cat)) if raw_cat else "gear"
                upsert_fn = getattr(self.library, "upsert_entry", None)
                if callable(upsert_fn):
                    entry = upsert_fn(
                        campaign_id,
                        name=str(hb.get("name") or ""),
                        category=norm_cat or "gear",
                        summary=str(hb.get("summary") or ""),
                        description=str(hb.get("description") or ""),
                        stats=hb.get("stats") if isinstance(hb.get("stats"), dict) else {},
                        tags=hb.get("tags") if isinstance(hb.get("tags"), list) else [],
                        created_by="ai",
                        allow_variant=False,
                        operation_id=f"{turn_id}:hb:{idx}",
                    )
                else:
                    entry = self.library.add_entry(
                        campaign_id,
                        name=str(hb.get("name") or ""),
                        category=norm_cat or "gear",
                        summary=str(hb.get("summary") or ""),
                        description=str(hb.get("description") or ""),
                        stats=hb.get("stats") if isinstance(hb.get("stats"), dict) else {},
                        tags=hb.get("tags") if isinstance(hb.get("tags"), list) else [],
                        created_by="ai",
                        operation_id=f"{turn_id}:hb:{idx}",
                    )
                added_library.append(entry)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped invalid homebrew '{hb.get('name', '?')}': {exc}")

        # 2. Resolve checks (PC checks + non-encounter NPC checks) with Overclock & pre-roll LUCK targeting.
        raw_checks = [chk for chk in (plan.get("checks") or []) if isinstance(chk, dict)] if allow_checks else []
        if len(raw_checks) > _MAX_CHECKS_PER_TURN:
            warnings.append(f"Capped planned checks from {len(raw_checks)} to {_MAX_CHECKS_PER_TURN}.")
            raw_checks = raw_checks[:_MAX_CHECKS_PER_TURN]

        pre_ctx = self.gameplay.campaign_context(campaign_id)
        pre_chars = pre_ctx["characters"]
        known_npcs = (pre_ctx.get("campaign") or {}).get("state", {}).get("npcs")
        pre_enc = (pre_ctx.get("solo") or {}).get("runtime", {}).get("encounter")
        encounter_npcs = pre_enc.get("npcs") if isinstance(pre_enc, dict) and pre_enc.get("active") else None

        default_char = _resolve_character(default_actor, pre_chars, known_npcs=known_npcs) if default_actor else None
        first_pc_idx: int | None = None
        default_pc_idx: int | None = None
        for pre_idx, chk in enumerate(raw_checks):
            if chk.get("npc"):
                continue
            pc = _resolve_character(chk.get("actor") or default_actor, pre_chars, known_npcs=known_npcs)
            if pc is None:
                continue
            sk_ok, _, sk_stat, _ = self.verify_skill(campaign_id, chk.get("skill"), chk.get("stat"), character=pc)
            if not sk_ok or not sk_stat:
                continue
            if first_pc_idx is None:
                first_pc_idx = pre_idx
            if default_char is not None and pc["id"] == default_char["id"] and default_pc_idx is None:
                default_pc_idx = pre_idx
        target_pc_idx = default_pc_idx if default_pc_idx is not None else first_pc_idx

        requested_luck = max(0, int(luck_spend or 0))
        luck_applied = False
        overclock_applied = False

        for idx, chk in enumerate(raw_checks):
            live_ctx = self.gameplay.campaign_context(campaign_id)
            live_chars = live_ctx["characters"]
            live_known_npcs = (live_ctx.get("campaign") or {}).get("state", {}).get("npcs")
            raw_actor = chk.get("actor")
            is_npc_flag = bool(chk.get("npc"))

            char = None if is_npc_flag else _resolve_character(raw_actor or default_actor, live_chars, known_npcs=live_known_npcs)
            if char is None:
                # Route explicitly marked NPCs or unattached non-empty actor names to NPC/environmental check runner.
                if is_npc_flag or (isinstance(raw_actor, str) and raw_actor.strip()):
                    try:
                        npc_roll = self.execute_npc_check(
                            campaign_id,
                            chk,
                            encounter_npcs=encounter_npcs,
                            operation_id=f"{turn_id}:npc:{idx}",
                        )
                        rolls.append(npc_roll)
                    except (TypeError, ValueError) as exc:
                        msg = str(exc)
                        warnings.append(msg)
                        blocked_checks.append(msg)
                    continue
                msg = f"Unknown character for check: {raw_actor!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue

            skill_ok, resolved_skill, resolved_stat, _ = self.verify_skill(
                campaign_id, chk.get("skill"), chk.get("stat"), character=char
            )
            if not skill_ok or not resolved_stat:
                msg = f"Blocked unverified skill/stat in check: {chk.get('skill')!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue

            raw_dv = chk.get("dv", 13)
            raw_mod = chk.get("modifier", 0)
            raw_chk_luck = chk.get("luck", 0)
            comp_flag = chk.get("complementary", False)
            extra_flag = chk.get("extra_time", False)
            if (
                isinstance(raw_dv, bool)
                or isinstance(raw_mod, bool)
                or isinstance(raw_chk_luck, bool)
                or not isinstance(comp_flag, bool)
                or not isinstance(extra_flag, bool)
            ):
                warnings.append("Invalid parameter types in planned skill check")
                continue
            try:
                dv = int(raw_dv)
                modifier = int(raw_mod)
                luck = max(0, int(raw_chk_luck))
            except (TypeError, ValueError):
                warnings.append("Invalid numeric parameters in planned skill check")
                continue
            if dv < 0 or not (-100 <= modifier <= 100):
                warnings.append("Out-of-range dv or modifier in planned skill check")
                continue

            # Pre-validate stat resolution before any Overclock Humanity deduction.
            if resolved_stat == "ROLE":
                if _resolve_role_ability_rank(char, resolved_skill) is None:
                    msg = f"Blocked check: {_char_handle(char)} lacks Role Ability for {resolved_skill!r}"
                    warnings.append(msg)
                    blocked_checks.append(msg)
                    continue
            elif resolved_stat not in (char.get("stats") or {}):
                msg = f"Blocked check: unknown stat {resolved_stat!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue

            avail_luck = int(char.get("luck_remaining", 0))
            if requested_luck > 0 and not luck_applied and idx == target_pc_idx:
                applied = min(max(luck, requested_luck), avail_luck)
                if applied < requested_luck:
                    warnings.append(f"Clamped committed LUCK for {_char_handle(char)} to available pool ({avail_luck}).")
                luck = applied
                luck_applied = True
            elif luck > avail_luck:
                luck = avail_luck

            want_overclock = bool(chk.get("overclock")) or (overclock and not overclock_applied and idx == target_pc_idx)
            overclock_applied_this_check = False
            expected_rev = int(char["revision"])
            if want_overclock:
                if not (-100 <= modifier + 2 <= 100):
                    warnings.append("Skipped Overclock: resulting modifier out of range")
                else:
                    try:
                        oc = self.deduct_humanity(
                            char["id"],
                            2,
                            reason=f"Overclock bonus for {resolved_skill or resolved_stat}",
                            operation_id=f"{turn_id}:oc:{idx}",
                        )
                        expected_rev = int(oc["revision"])
                        modifier += 2
                        overclock_applied_this_check = True
                        if overclock and idx == target_pc_idx:
                            overclock_applied = True
                        patches.append(
                            {
                                "target": "character",
                                "character_id": char["id"],
                                "name": _char_handle(char),
                                "before": {"humanity": oc["before"]},
                                "after": {"humanity": oc["after"]},
                                "reason": "Overclock (-2 Humanity for +2 Check Bonus)",
                            }
                        )
                    except ValueError as exc:
                        warnings.append(str(exc))

            reason_str = str(chk.get("reason") or f"{resolved_skill or resolved_stat} check").strip()
            try:
                res = self.gameplay.execute(
                    "skill_check",
                    {
                        "character_id": char["id"],
                        "expected_revision": expected_rev,
                        "stat": resolved_stat,
                        "skill": resolved_skill,
                        "dv": dv,
                        "modifier": modifier,
                        "luck": luck,
                        "complementary": comp_flag,
                        "extra_time": extra_flag,
                        "reason": reason_str,
                        "operation_id": f"{turn_id}:chk:{idx}",
                    },
                    campaign_id=campaign_id,
                )["result"]
                rolls.append(
                    _sanitize_roll_payload(
                        res,
                        actor=_char_handle(char),
                        character_id=char["id"],
                        stat=resolved_stat,
                        skill=resolved_skill,
                        dv=dv,
                        modifier=modifier,
                        luck=luck,
                        overclock=overclock_applied_this_check,
                        complementary=comp_flag,
                        extra_time=extra_flag,
                        reason=reason_str,
                        npc=False,
                    )
                )
            except ValueError as exc:
                warnings.append(f"Check failed validation: {exc}")

        # 3. Execute explicit state_ops through GameplayService with before/after snapshot capture.
        raw_state_ops = [op for op in (plan.get("state_ops") or []) if isinstance(op, dict)]
        if len(raw_state_ops) > _MAX_OPS_PER_TURN:
            warnings.append(f"Capped state_ops from {len(raw_state_ops)} to {_MAX_OPS_PER_TURN}.")
            raw_state_ops = raw_state_ops[:_MAX_OPS_PER_TURN]
        for idx, op in enumerate(raw_state_ops):
            op_type = op.get("type")
            reason = str(op.get("reason") or "GM turn state update")
            if op_type == "update_character":
                if not allow_character_updates:
                    warnings.append("Blocked disallowed update_character in post-turn chronicler pass.")
                    continue
                c_patches, c_warns = self.apply_character_update_op(
                    campaign_id,
                    op.get("actor") or default_actor,
                    op.get("changes"),
                    reason,
                    f"{turn_id}:char:{idx}",
                )
                patches.extend(c_patches)
                warnings.extend(c_warns)
            elif op_type == "update_campaign":
                raw_changes = op.get("changes")
                if not isinstance(raw_changes, dict) or not raw_changes:
                    continue
                live_ctx = self.gameplay.campaign_context(campaign_id)
                live_camp = live_ctx["campaign"]
                changes, norm_notes = _normalize_campaign_changes(
                    raw_changes,
                    live_camp["state"],
                    characters=live_ctx["characters"],
                    existing_secrets=prep.get("gm_secrets") or {},
                )
                # Mirror hidden NPC legal names into secret gm_secrets updates so players cannot inspect them
                if isinstance(raw_changes.get("npc_identities"), dict):
                    sec_up = dict(plan.get("gm_secrets") or {}) if isinstance(plan.get("gm_secrets"), dict) else {}
                    for raw_h, raw_m in raw_changes["npc_identities"].items():
                        h = str(raw_h or "").strip()
                        if not h:
                            continue
                        if raw_m is None:
                            sec_up[f"__npc_real:{h}"] = None
                        elif isinstance(raw_m, dict):
                            hidden = bool(raw_m.get("real_name_hidden", True))
                            rname = str(raw_m.get("real_name") or "").strip()
                            if hidden and rname:
                                sec_up[f"__npc_real:{h}"] = rname
                            elif not hidden:
                                sec_up[f"__npc_real:{h}"] = None
                    plan["gm_secrets"] = sec_up
                warnings.extend(norm_notes)
                if not changes:
                    continue
                before_vals = {k: live_camp["state"].get(k) for k in changes}
                try:
                    updated = self.gameplay.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": live_camp["revision"],
                            "changes": changes,
                            "reason": reason,
                            "operation_id": f"{turn_id}:camp:{idx}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                    patches.append(
                        {
                            "target": "campaign",
                            "campaign_id": campaign_id,
                            "before": before_vals,
                            "after": {k: updated["state"].get(k) for k in changes},
                            "reason": reason,
                        }
                    )
                except (TypeError, ValueError) as exc:
                    warnings.append(f"Skipped campaign update: {exc}")

        # 4. Execute deterministic SoloService operations (economy, gear, health, encounter, net).
        solo_time_advanced = False
        if allow_solo:
            raw_solo_ops = [sop for sop in (plan.get("solo_ops") or []) if isinstance(sop, dict)]
            if len(raw_solo_ops) > _MAX_OPS_PER_TURN:
                warnings.append(f"Capped solo_ops from {len(raw_solo_ops)} to {_MAX_OPS_PER_TURN}.")
                raw_solo_ops = raw_solo_ops[:_MAX_OPS_PER_TURN]
            for idx, sop in enumerate(raw_solo_ops):
                if not allow_character_updates and str(sop.get("action") or sop.get("type") or "").strip() == "update_character":
                    warnings.append("Blocked disallowed update_character in post-turn chronicler pass.")
                    continue
                s_patches, s_warns, s_rolls, s_outcomes = self.execute_solo_op(
                    campaign_id, sop, default_actor, operation_id=f"{turn_id}:solo:{idx}"
                )
                patches.extend(s_patches)
                warnings.extend(s_warns)
                rolls.extend(s_rolls)
                solo_outcomes.extend(s_outcomes)
                if any(
                    p.get("target") == "solo"
                    and p.get("kind") != "start_time"
                    and isinstance(p.get("after"), dict)
                    and "time" in p["after"]
                    for p in s_patches
                ):
                    solo_time_advanced = True

        # 4b. Sync opening wall-clock time when clock_minutes == 0 and Planner parsed a start_time (e.g. "22:15").
        if allow_solo and plan.get("start_time"):
            cur_clock = int(self.gameplay.campaign_context(campaign_id)["solo"]["runtime"].get("clock_minutes") or 0)
            start_mins = _parse_clock_minutes(plan.get("start_time"))
            if cur_clock == 0 and start_mins is not None and start_mins > 0:
                st_patches, st_warns, _, _ = self.execute_solo_op(
                    campaign_id,
                    {
                        "action": "advance_time",
                        "_kind": "start_time",
                        "elapsed_minutes": start_mins,
                        "reason": f"Scene opening time ({_format_clock_label(start_mins)})",
                    },
                    default_actor,
                    operation_id=f"{turn_id}:start_time",
                )
                patches.extend(st_patches)
                warnings.extend(st_warns)

        # 4c. Advance campaign clock when time_elapsed_minutes is explicitly specified (default fallback runs after Chronicler in engine.py).
        raw_elapsed = plan.get("time_elapsed_minutes")
        if (
            not solo_time_advanced
            and not isinstance(raw_elapsed, bool)
            and isinstance(raw_elapsed, (int, float))
            and int(raw_elapsed) > 0
        ):
            mins = min(43200, int(raw_elapsed))
            t_patches, t_warns, _, _ = self.execute_solo_op(
                campaign_id,
                {"action": "advance_time", "elapsed_minutes": mins, "reason": f"Scene time elapsed (+{mins}m)"},
                default_actor,
                operation_id=f"{turn_id}:time",
            )
            patches.extend(t_patches)
            warnings.extend(t_warns)

        # 5. Advance branch-scoped GM secrets & world clocks without exposing private data in patches.
        next_secrets = self.private_state.merge_gm_secrets(prep.get("gm_secrets") or {}, plan.get("gm_secrets"))
        next_clocks, public_clock_changes = self.private_state.apply_clock_ops(
            prep.get("clocks") or [], plan.get("clock_ops"), allow_secret=True
        )
        for c_diff in public_clock_changes:
            patches.append(
                {
                    "target": "campaign",
                    "campaign_id": campaign_id,
                    "before": {f"Clock ({c_diff['clock']})": c_diff["before"]},
                    "after": {f"Clock ({c_diff['clock']})": c_diff["after"]},
                    "reason": f"Updated clock {c_diff['clock']}",
                }
            )

        return {
            "rolls": rolls,
            "patches": patches,
            "library_added": added_library,
            "warnings": warnings,
            "gm_secrets": next_secrets,
            "clocks": next_clocks,
            "outcomes": {
                "rolls": [
                    {
                        "actor": r["actor"],
                        "skill": r["skill"],
                        "stat": r["stat"],
                        "reason": r.get("reason"),
                        "base": r.get("base"),
                        "dice": r.get("dice"),
                        "die": r.get("die"),
                        "explosion": r.get("explosion", 0),
                        "modifier": r.get("modifier", 0),
                        "total": r.get("total"),
                        "dv": r["dv"],
                        "wound_modifier": r.get("wound_modifier", 0),
                        "luck": r.get("luck", r.get("luck_spent", 0)),
                        "luck_spent": r.get("luck_spent", r.get("luck", 0)),
                        "overclock": bool(r.get("overclock", False)),
                        "npc": bool(r.get("npc", False)),
                        "success": r.get("success"),
                        "critical": (
                            "critical_success"
                            if (r.get("explosion") or 0) > 0
                            else ("fumble" if (r.get("explosion") or 0) < 0 else None)
                        ),
                    }
                    for r in rolls
                ],
                "solo_results": solo_outcomes,
                "blocked_checks": blocked_checks,
                "unspent_luck_requested": requested_luck if (requested_luck > 0 and not luck_applied) else 0,
                "patches": patches,
                "library_added": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in added_library],
                "gm_notes": str(plan.get("gm_notes") or ""),
            },
        }
