"""Deterministic GM plan execution (checks, state_ops, solo_ops, clocks, secrets)."""
from __future__ import annotations

from contextlib import closing
from typing import Any

from campaign import STAT_NAMES, _json
from gameplay import GameplayService
from library import CampaignLibrary, normalize_category, search_library
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
        self, campaign_id: str, skill_name: str | None, requested_stat: str | None
    ) -> tuple[bool, str | None, str | None, dict[str, Any] | None]:
        """Validate proposed skill against Corebook or campaign homebrew skill entries."""
        if not skill_name:
            stat = requested_stat.upper() if isinstance(requested_stat, str) and requested_stat.upper() in STAT_NAMES else None
            return (stat is not None, None, stat, None)

        role_hit = _CANONICAL_ROLE_CHECKS.get(sourcecatalog._normalize(skill_name))
        if role_hit is not None:
            canonical_role, role_stat = role_hit
            return (True, canonical_role, role_stat, {"source": "corebook", "name": canonical_role, "stat": role_stat})

        core = self.corebook_skills()
        hit = sourcecatalog.lookup_skill(core, skill_name)
        if hit is not None:
            canonical = next(
                (k for k in core if sourcecatalog._normalize(k) == sourcecatalog._normalize(skill_name)),
                skill_name,
            )
            return (True, canonical, hit["stat"], {"source": "corebook", "name": canonical, **hit})

        homebrew_hits = search_library(
            self.gameplay.rules_path,
            q=skill_name,
            category="skill",
            campaign_path=self.gameplay.store.path,
            campaign_id=campaign_id,
            limit=10,
        )
        exact = next(
            (e for e in homebrew_hits if sourcecatalog._normalize(e["name"]) == sourcecatalog._normalize(skill_name)),
            None,
        )
        if exact is not None:
            entry_stat = str((exact.get("stats") or {}).get("stat") or requested_stat or "").upper()
            stat = entry_stat if entry_stat in STAT_NAMES else None
            return (stat is not None, exact["name"], stat, exact)
        return (False, skill_name, None, None)

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
                raise ValueError(f"{before['name']} lacks Humanity for Overclock (has {before['humanity']}, needs {amount})")
            after = dict(before, humanity=before["humanity"] - amount, revision=before["revision"] + 1)
            conn.execute(
                "UPDATE characters SET humanity=?, revision=? WHERE id=?",
                (after["humanity"], after["revision"], character_id),
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
        live_chars = self.gameplay.campaign_context(campaign_id)["characters"]
        char = _resolve_character(actor_hint, live_chars)
        if char is None:
            return [], [f"Unknown character for state update: {actor_hint!r}"]
        if not isinstance(raw_changes, dict) or not raw_changes:
            return [], []

        raw_changes = dict(raw_changes)
        ip_entry = raw_changes.pop("ip", None)
        patches: list[dict[str, Any]] = []
        warnings: list[str] = []

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
                    ctx = self.gameplay.campaign_context(campaign_id)
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
                            "name": char["name"],
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
                    "name": char["name"],
                    "before": before_vals,
                    "after": {k: updated.get(k) for k in changes},
                    "reason": reason,
                }
            )
            return patches, warnings
        except (TypeError, ValueError) as exc:
            warnings.append(f"Skipped character update: {exc}")
            return patches, warnings

    def execute_solo_op(
        self,
        campaign_id: str,
        op: dict[str, Any],
        default_actor: str | None,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        action = str(op.get("action") or op.get("type") or "").strip()
        if action == "update_character":
            raw_changes = op.get("changes")
            if not isinstance(raw_changes, dict):
                raw_changes = op.get("arguments") if isinstance(op.get("arguments"), dict) else {
                    k: v for k, v in op.items()
                    if k not in {"action", "type", "subaction", "mode", "actor", "reason"}
                }
            return self.apply_character_update_op(
                campaign_id,
                op.get("actor") or default_actor,
                raw_changes,
                str(op.get("reason") or "GM turn state update"),
                operation_id,
            )
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
        }
        if action not in allowed:
            return [], [f"Ignored unsupported solo_op action: {action!r}"]

        ctx = self.gameplay.campaign_context(campaign_id)
        live_chars = ctx["characters"]
        solo_rev = int(ctx["solo"]["revision"])
        if isinstance(op.get("arguments"), dict):
            raw_args = dict(op["arguments"])
        else:
            raw_args = {
                k: v
                for k, v in op.items()
                if k not in {"action", "type", "subaction", "mode", "actor", "reason"}
            }
        reason = str(op.get("reason") or f"GM solo action: {action}").strip()
        actor_hint = op.get("actor") or raw_args.pop("actor", None) or default_actor
        actor_char = _resolve_character(actor_hint, live_chars)

        before_clock = int(ctx["solo"]["runtime"].get("clock_minutes") or 0)
        if action == "start_encounter":
            cur_enc = ctx["solo"]["runtime"].get("encounter")
            if isinstance(cur_enc, dict) and cur_enc.get("active"):
                return [], []
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
                        matched = _resolve_character(entry, live_chars)
                        if matched is not None and matched["id"] not in seen_ids:
                            ids.append(matched["id"])
                            seen_ids.add(matched["id"])
            if not ids:
                ids = [actor_char["id"]] if actor_char is not None else [c["id"] for c in live_chars]
            if not ids:
                return [], ["Skipped solo action (start_encounter): no campaign members attached"]
            raw_args = {"character_ids": ids}
        elif action == "advance_time":
            elapsed_raw = op.get("elapsed_minutes", raw_args.get("elapsed_minutes", 0))
            try:
                elapsed_val = int(elapsed_raw)
            except (TypeError, ValueError):
                return [], [f"Invalid elapsed_minutes for advance_time: {elapsed_raw!r}"]
            raw_args = {"elapsed_minutes": elapsed_val}
        elif action == "end_encounter":
            raw_args = {}
        else:
            if action in {"economy_action", "gear_action", "role_action"}:
                if "character_id" not in raw_args:
                    if actor_char is None:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"]
                    raw_args["character_id"] = actor_char["id"]
            else:
                if "actor_id" not in raw_args:
                    if actor_char is None:
                        return [], [f"Unknown character for {action}: {actor_hint!r}"]
                    raw_args["actor_id"] = actor_char["id"]

            if "target" in raw_args and "target_id" not in raw_args:
                tgt = _resolve_character(raw_args.pop("target"), live_chars)
                if tgt is not None:
                    raw_args["target_id"] = tgt["id"]

            subaction = op.get("subaction") or op.get("mode") or raw_args.get("action")
            nested_args = dict(raw_args.get("arguments")) if isinstance(raw_args.get("arguments"), dict) else None
            if nested_args is None:
                # Support flat arguments from model JSON by nesting remaining non-envelope keys.
                envelope_keys = {"character_id", "actor_id", "action", "subaction", "arguments"}
                nested_args = {k: v for k, v in raw_args.items() if k not in envelope_keys}
                raw_args = {k: v for k, v in raw_args.items() if k in {"character_id", "actor_id"}}
                raw_args["arguments"] = nested_args
            if subaction:
                raw_args["action"] = str(subaction)

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
                catalog = self.catalog_items()
                if isinstance(wanted_item, str) and wanted_item and wanted_item not in catalog:
                    norm_w = sourcecatalog._normalize(wanted_item)
                    matched = next(
                        (item_id for item_id, item in catalog.items() if sourcecatalog._normalize(item.get("name", "")) == norm_w),
                        None,
                    )
                    if matched:
                        g_args["item_id"] = matched

        before_map = {c["id"]: c for c in live_chars}
        payload_args = {**raw_args, "expected_revision": solo_rev, "reason": reason, "operation_id": operation_id}
        try:
            res = self.gameplay.execute(action, payload_args, campaign_id=campaign_id)["result"]
        except (TypeError, ValueError, KeyError) as exc:
            return [], [f"Skipped solo action ({action}): {exc}"]

        if isinstance(res, dict) and res.get("committed") is False:
            ruling_reason = (res.get("result") or {}).get("reason") or "Requires manual tabletop ruling."
            return [], [f"Solo action ({action}) deferred: {ruling_reason}"]

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
                        "name": after_c.get("name"),
                        "before": b_diff,
                        "after": a_diff,
                        "reason": reason,
                    }
                )
        if action == "advance_time" and isinstance(res, dict):
            time_res = res.get("result") if isinstance(res.get("result"), dict) else res
            b_m = int(time_res["before_minutes"]) if time_res.get("before_minutes") is not None else before_clock
            a_m = int(time_res["after_minutes"]) if time_res.get("after_minutes") is not None else (b_m + elapsed_val)
            patches.append(
                {
                    "target": "solo",
                    "before": {"time": _format_clock_label(b_m)},
                    "after": {"time": _format_clock_label(a_m)},
                    "reason": reason,
                }
            )
        elif action in {"health_action", "economy_action"}:
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
        return patches, []

    def execute_plan(
        self,
        campaign_id: str,
        plan: dict[str, Any],
        prep: dict[str, Any],
        *,
        overclock: bool = False,
        luck_spend: int = 0,
        default_actor: str | None = None,
        op_prefix: str | None = None,
        allow_checks: bool = True,
        allow_solo: bool = True,
    ) -> dict[str, Any]:
        turn_id = op_prefix or prep["turn_id"]
        rolls: list[dict[str, Any]] = []
        blocked_checks: list[str] = []
        patches: list[dict[str, Any]] = []
        added_library: list[dict[str, Any]] = []
        warnings: list[str] = []

        # 1. Create any AI-proposed campaign homebrew entries first so skill checks can reference new skills.
        raw_homebrew = (plan.get("new_homebrew") or []) if self.turn_settings.get("allow_ai_homebrew", True) else []
        for idx, hb in enumerate(raw_homebrew):
            if not isinstance(hb, dict):
                continue
            try:
                raw_cat = hb.get("category")
                norm_cat = normalize_category(str(raw_cat)) if raw_cat else "gear"
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

        # Refresh characters snapshot helper
        def current_chars() -> list[dict[str, Any]]:
            return self.gameplay.campaign_context(campaign_id)["characters"]

        # 2. Resolve checks with fuzzy actor matching + entity hallucination guard + Overclock & pre-roll LUCK support.
        planned_checks = [chk for chk in (plan.get("checks") or []) if isinstance(chk, dict)] if allow_checks else []
        requested_luck = max(0, int(luck_spend or 0))
        luck_applied = False

        for idx, chk in enumerate(planned_checks):
            live_chars = current_chars()
            char = _resolve_character(chk.get("actor") or default_actor, live_chars)
            if char is None:
                msg = f"Unknown character for check: {chk.get('actor')!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue
            skill_ok, resolved_skill, resolved_stat, _ = self.verify_skill(
                campaign_id, chk.get("skill"), chk.get("stat")
            )
            if not skill_ok or not resolved_stat:
                msg = f"Blocked unverified skill/stat in check: {chk.get('skill')!r}"
                warnings.append(msg)
                blocked_checks.append(msg)
                continue
            try:
                dv = int(chk.get("dv", 13))
                modifier = int(chk.get("modifier", 0))
                luck = max(0, int(chk.get("luck", 0)))
            except (TypeError, ValueError):
                warnings.append("Invalid numeric parameters in planned skill check")
                continue

            if requested_luck > 0 and not luck_applied and (not default_actor or char["id"] == default_actor or char["name"] == default_actor or idx == 0):
                avail = int(char.get("luck_remaining", 0))
                applied = min(max(luck, requested_luck), avail)
                if applied < requested_luck:
                    warnings.append(f"Clamped committed LUCK for {char['name']} to available pool ({avail}).")
                luck = applied
                luck_applied = True

            use_overclock = bool(chk.get("overclock")) or (overclock and idx == 0)
            expected_rev = int(char["revision"])
            if use_overclock:
                try:
                    oc = self.deduct_humanity(
                        char["id"],
                        2,
                        reason=f"Overclock bonus for {resolved_skill or resolved_stat}",
                        operation_id=f"{turn_id}:oc:{idx}",
                    )
                    expected_rev = int(oc["revision"])
                    modifier += 2
                    patches.append(
                        {
                            "target": "character",
                            "character_id": char["id"],
                            "name": char["name"],
                            "before": {"humanity": oc["before"]},
                            "after": {"humanity": oc["after"]},
                            "reason": "Overclock (-2 Humanity for +2 Check Bonus)",
                        }
                    )
                except ValueError as exc:
                    warnings.append(str(exc))

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
                        "reason": str(chk.get("reason") or f"{resolved_skill or resolved_stat} check"),
                        "operation_id": f"{turn_id}:chk:{idx}",
                    },
                    campaign_id=campaign_id,
                )["result"]
                dice_vals = res.get("dice") or []
                rolls.append(
                    {
                        "actor": char["name"],
                        "character_id": char["id"],
                        "skill": resolved_skill,
                        "stat": resolved_stat,
                        "dv": dv,
                        "modifier": modifier,
                        "luck_spent": luck,
                        "overclock": use_overclock,
                        "die": dice_vals[0] if dice_vals else None,
                        "explosion": res.get("critical_adjustment", 0),
                        **res,
                    }
                )
            except ValueError as exc:
                warnings.append(f"Check failed validation: {exc}")

        # 3. Execute explicit state_ops through GameplayService with before/after snapshot capture.
        for idx, op in enumerate(plan.get("state_ops") or []):
            if not isinstance(op, dict):
                continue
            op_type = op.get("type")
            reason = str(op.get("reason") or "GM turn state update")
            if op_type == "update_character":
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

        # 4. Execute deterministic SoloService operations (economy, gear, health, encounter).
        solo_time_advanced = False
        if allow_solo:
            for idx, sop in enumerate(plan.get("solo_ops") or []):
                if not isinstance(sop, dict):
                    continue
                if str(sop.get("action") or sop.get("type") or "").strip() == "advance_time" or (
                    str(sop.get("subaction") or sop.get("mode") or sop.get("action") or "").strip()
                    in {"rest", "treat_injury", "therapy", "hustle"}
                ):
                    solo_time_advanced = True
                s_patches, s_warns = self.execute_solo_op(
                    campaign_id, sop, default_actor, operation_id=f"{turn_id}:solo:{idx}"
                )
                patches.extend(s_patches)
                warnings.extend(s_warns)

        # 4b. Sync opening wall-clock time when clock_minutes == 0 and Planner parsed a start_time (e.g. "22:15").
        if allow_solo and plan.get("start_time"):
            cur_clock = int(self.gameplay.campaign_context(campaign_id)["solo"]["runtime"].get("clock_minutes") or 0)
            start_mins = _parse_clock_minutes(plan.get("start_time"))
            if cur_clock == 0 and start_mins is not None and start_mins > 0:
                st_patches, st_warns = self.execute_solo_op(
                    campaign_id,
                    {"action": "advance_time", "elapsed_minutes": start_mins, "reason": f"Scene opening time ({_format_clock_label(start_mins)})"},
                    default_actor,
                    operation_id=f"{turn_id}:start_time",
                )
                patches.extend(st_patches)
                warnings.extend(st_warns)

        # 4c. Advance campaign clock when time_elapsed_minutes is specified (or default fallback configured).
        raw_elapsed = plan.get("time_elapsed_minutes")
        if (raw_elapsed is None or raw_elapsed == 0) and allow_solo:
            fallback_step = int(self.turn_settings.get("default_time_step_minutes") or 0)
            if fallback_step > 0:
                raw_elapsed = fallback_step
        if (
            not solo_time_advanced
            and not isinstance(raw_elapsed, bool)
            and isinstance(raw_elapsed, (int, float))
            and int(raw_elapsed) > 0
        ):
            mins = min(43200, int(raw_elapsed))
            t_patches, t_warns = self.execute_solo_op(
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
                        "luck_spent": r.get("luck_spent", 0),
                        "success": r.get("success"),
                        "critical": (
                            "critical_success"
                            if (r.get("explosion") or 0) > 0
                            else ("fumble" if (r.get("explosion") or 0) < 0 else None)
                        ),
                    }
                    for r in rolls
                ],
                "blocked_checks": blocked_checks,
                "unspent_luck_requested": requested_luck if (requested_luck > 0 and not luck_applied) else 0,
                "patches": patches,
                "library_added": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in added_library],
                "gm_notes": str(plan.get("gm_notes") or ""),
            },
        }
