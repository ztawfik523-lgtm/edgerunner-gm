"""TurnEngine orchestrator composing ChatTreeStore, BranchPrivateStateStore, PlanExecutor, prompts, and router."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import re
import time
from typing import Any, AsyncIterator
import uuid

from gameplay import GameplayService
from library import CampaignLibrary, normalize_category, search_library
from mechanics import roll_dice as _roll_dice
import sourcecatalog
from turn_engine.chat_tree import BranchPrivateStateStore, ChatTreeStore
from turn_engine.executor import PlanExecutor
from turn_engine.llm_client import (
    OpenAICompatibleLLM,
    StreamSanitizer,
    extract_gm_plan,
    strip_gm_tags,
)
from turn_engine.prompts import (
    build_chronicler_messages,
    build_intro_messages,
    build_narrator_messages,
    build_planner_messages,
    build_think_narrator_messages,
    build_think_planner_messages,
    format_player_message,
    format_roll_ledger,
)
from turn_engine.router import should_gm_intervene as _router_should_gm_intervene
from turn_engine.settings import (
    DEFAULT_PROMPT_TEMPLATES,
    _COMPRESSION_MESSAGE_THRESHOLD,
    _GM_STYLE_HINTS,
    _LENGTH_HINTS,
    _NON_EMPTY_PROMPT_KEYS,
    _PACING_HINTS,
    _STATIC_INTRO_PRIMER,
    _default_llm_dict,
    _validate_llm_settings,
    load_llm_settings,
    load_prompt_settings,
)
from turn_engine.state_normalization import (
    _format_clock_label,
    _normalize_campaign_changes,
    _visible_gm_secrets_for_prompt,
    build_npc_profiles,
    compute_party_grouping,
    parse_session_zero,
)

_LIB_REF_RE = re.compile(r"\[([a-zA-Z]+)\s*:\s*([^\]\n]+)\]")
_THINK_CMD_RE = re.compile(r"^/think(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


class TurnEngine:
    """Hybrid 3-phase / 2-pass GM turn orchestrator backed by deterministic Cyberpunk RED tools."""

    def __init__(
        self,
        gameplay: GameplayService,
        llm: Any | None = None,
        *,
        library: CampaignLibrary | None = None,
        tree: ChatTreeStore | None = None,
        settings_path: Path | None = None,
        turn_settings: dict[str, Any] | None = None,
        prompt_settings: dict[str, str] | None = None,
    ):
        self.gameplay = gameplay
        self.llm = llm or OpenAICompatibleLLM()
        self.library = library or CampaignLibrary(gameplay.store, rules_path=gameplay.rules_path)
        self.tree = tree or ChatTreeStore(gameplay)
        self.settings_path = settings_path
        base_turn = load_llm_settings(settings_path) if settings_path is not None else _default_llm_dict()
        if settings_path is None and (not isinstance(turn_settings, dict) or "mode" not in turn_settings):
            llm_mode = getattr(getattr(self.llm, "config", None), "mode", None)
            if llm_mode in {"two_pass", "single_pass_tagged"}:
                base_turn["mode"] = llm_mode
        if isinstance(turn_settings, dict):
            base_turn = _validate_llm_settings(turn_settings, base_turn)
        self.turn_settings = base_turn
        base_prompts = load_prompt_settings(settings_path) if settings_path is not None else dict(DEFAULT_PROMPT_TEMPLATES)
        if isinstance(prompt_settings, dict):
            for k in DEFAULT_PROMPT_TEMPLATES:
                if isinstance(prompt_settings.get(k), str):
                    val = prompt_settings[k].strip()
                    base_prompts[k] = val if (val or k not in _NON_EMPTY_PROMPT_KEYS) else DEFAULT_PROMPT_TEMPLATES[k]
        self.prompt_settings = base_prompts
        self.private_state = BranchPrivateStateStore(gameplay, self.tree)
        self.executor = PlanExecutor(gameplay, self.library, self.private_state, self.turn_settings)

    @property
    def _skill_cache(self) -> dict[str, dict[str, Any]] | None:
        return self.executor._skill_cache

    @_skill_cache.setter
    def _skill_cache(self, value: dict[str, dict[str, Any]] | None) -> None:
        self.executor._skill_cache = value

    @property
    def _item_cache(self) -> dict[str, dict[str, Any]] | None:
        return self.executor._item_cache

    @_item_cache.setter
    def _item_cache(self, value: dict[str, dict[str, Any]] | None) -> None:
        self.executor._item_cache = value

    @staticmethod
    def _supports_kwarg(fn: Any, kwarg: str) -> bool:
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        return kwarg in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )

    @classmethod
    def _supports_enable_thinking(cls, fn: Any) -> bool:
        return cls._supports_kwarg(fn, "enable_thinking")

    def _thinking_kwargs_for_pass(self, fn: Any, *, disable_in_balanced: bool) -> dict[str, Any]:
        if not disable_in_balanced:
            return {}
        if self.turn_settings.get("gm_thinking_mode", "quality") != "balanced":
            return {}
        return {"enable_thinking": False} if self._supports_enable_thinking(fn) else {}

    def _effective_turn_settings(self, raw_state: dict[str, Any] | None) -> dict[str, Any]:
        eff = dict(self.turn_settings)
        sz = parse_session_zero(raw_state)
        if sz.get("gm_style") in _GM_STYLE_HINTS:
            eff["gm_style"] = sz["gm_style"]
        if sz.get("narrator_length") in _LENGTH_HINTS:
            eff["narrator_length"] = sz["narrator_length"]
        if sz.get("narrator_pacing") in _PACING_HINTS:
            eff["narrator_pacing"] = sz["narrator_pacing"]
        return eff

    def _ensure_private_tables(self) -> None:
        self.private_state.ensure_private_tables()

    @staticmethod
    def _clean_secrets_dict(raw: Any) -> dict[str, str]:
        return BranchPrivateStateStore.clean_secrets_dict(raw)

    @staticmethod
    def _merge_gm_secrets(current: dict[str, str], updates: Any) -> dict[str, str]:
        return BranchPrivateStateStore.merge_gm_secrets(current, updates)

    @staticmethod
    def _normalize_clock_list(raw: Any) -> list[dict[str, Any]]:
        return BranchPrivateStateStore.normalize_clock_list(raw)

    @classmethod
    def _apply_clock_ops(
        cls,
        current: list[dict[str, Any]],
        ops: Any,
        *,
        allow_secret: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return BranchPrivateStateStore.apply_clock_ops(current, ops, allow_secret=allow_secret)

    def _load_branch_private_state(
        self, campaign_id: str, parent_id: str | None
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        return self.private_state.load_branch_private_state(campaign_id, parent_id)

    def _save_branch_private_state(
        self,
        campaign_id: str,
        message_id: str | None,
        parent_id: str | None,
        secrets: dict[str, str],
        clocks: list[dict[str, Any]],
    ) -> None:
        self.private_state.save_branch_private_state(campaign_id, message_id, parent_id, secrets, clocks)

    def _latest_snapshot_leaf(self, campaign_id: str) -> str | None:
        return self.private_state.latest_snapshot_leaf(campaign_id)

    def _active_channel_leaves(self, campaign_id: str) -> list[str]:
        return self.private_state.active_channel_leaves(campaign_id)

    def _get_gm_secrets(self, campaign_id: str) -> dict[str, str]:
        return self.private_state.get_gm_secrets(campaign_id)

    def update_gm_secrets(self, campaign_id: str, updates: dict[str, str | None]) -> dict[str, str]:
        """Persist secret updates across root gm_secrets AND all active channel branch snapshots."""
        return self.private_state.update_gm_secrets(campaign_id, updates)

    def list_public_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        return self.private_state.list_public_clocks(campaign_id, leaf_id=leaf_id)

    def list_all_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        return self.private_state.list_all_clocks(campaign_id, leaf_id=leaf_id)

    def mutate_public_clock(self, campaign_id: str, body: dict[str, Any], leaf_id: str | None = None) -> list[dict[str, Any]]:
        return self.private_state.mutate_public_clock(campaign_id, body, leaf_id=leaf_id)

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
        return self.private_state.seed_initial_gm_state(
            campaign_id,
            secrets=secrets,
            opening_clock=opening_clock,
            clocks=clocks,
            replace_secrets=replace_secrets,
            replace_clocks=replace_clocks,
        )

    def _get_compressed_count(self, campaign_id: str) -> int:
        return self.private_state.get_compressed_count(campaign_id)

    def _set_compressed_count(self, campaign_id: str, leaf_id: str | None, count: int) -> None:
        self.private_state.set_compressed_count(campaign_id, leaf_id, count)

    def _catalog_items(self) -> dict[str, dict[str, Any]]:
        return self.executor.catalog_items()

    def _corebook_skills(self) -> dict[str, dict[str, Any]]:
        return self.executor.corebook_skills()

    def _verify_skill(
        self, campaign_id: str, skill_name: str | None, requested_stat: str | None
    ) -> tuple[bool, str | None, str | None, dict[str, Any] | None]:
        """Validate proposed skill against Corebook or campaign homebrew skill entries."""
        return self.executor.verify_skill(campaign_id, skill_name, requested_stat)

    def _deduct_humanity(self, character_id: str, amount: int, reason: str, operation_id: str) -> dict[str, Any]:
        return self.executor.deduct_humanity(character_id, amount, reason, operation_id)

    def _solo_summary(self, ctx: dict[str, Any]) -> dict[str, Any]:
        runtime = (ctx.get("solo") or {}).get("runtime") or {}
        enc = runtime.get("encounter")
        chars_by_id = {
            c["id"]: str((c.get("detail") or {}).get("handle") or c["name"])
            for c in ctx.get("characters") or []
        }
        enc_view = None
        if isinstance(enc, dict) and enc.get("active"):
            enc_npcs = enc.get("npcs")
            if isinstance(enc_npcs, dict):
                for nid, npc in enc_npcs.items():
                    if isinstance(npc, dict):
                        chars_by_id[str(npc.get("id") or nid)] = str((npc.get("detail") or {}).get("handle") or npc.get("name") or nid)
            q = enc.get("queue") or []
            idx = enc.get("turn_index", 0)
            cur_id = q[idx] if isinstance(idx, int) and 0 <= idx < len(q) else None
            enc_view = {
                "active": True,
                "round": enc.get("round", 1),
                "current_actor": chars_by_id.get(cur_id, cur_id),
                "queue": [chars_by_id.get(cid, cid) for cid in q],
            }
        runs_view = {
            rid: {"connected": bool(r.get("connected")), "floor": r.get("current_floor_id"), "actions_remaining": r.get("actions_remaining")}
            for rid, r in (runtime.get("runs") or {}).items()
            if isinstance(r, dict) and r.get("connected")
        }
        clock_mins = int(runtime.get("clock_minutes") or 0)
        return {
            "clock_minutes": clock_mins,
            "clock_label": _format_clock_label(clock_mins),
            "encounter": enc_view,
            "active_runs": runs_view,
        }

    def _collect_citations(
        self,
        campaign_id: str,
        user_text: str,
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cit_limit = max(1, min(30, int(self.turn_settings.get("citation_limit", 4))))
        total_cap = max(8, cit_limit + 4)
        citations = search_library(
            self.gameplay.rules_path,
            q=user_text.strip()[:200],
            campaign_path=self.gameplay.store.path,
            campaign_id=campaign_id,
            strict_names=True,
            limit=cit_limit,
        )
        seen_ids = {c["id"] for c in citations}
        # Also resolve explicit [Category: Name] tags or campaign dossier names mentioned in state/summary.
        state_blob = "\n".join(
            [
                str(state.get("scene") or ""),
                str(state.get("summary") or ""),
                *(f"{k} {v}" for k, v in (state.get("npcs") or {}).items()),
                *(f"{k} {v}" for k, v in (state.get("discoveries") or {}).items()),
            ]
        )
        if state_blob.strip() or user_text.strip():
            ref_names = {sourcecatalog._normalize(m.group(2)) for m in _LIB_REF_RE.finditer(state_blob)}
            npc_names_text = " ".join(str(k) for k in (state.get("npcs") or {}).keys())
            hay_norm = sourcecatalog._normalize(f"{user_text}\n{state.get('scene', '')}\n{state.get('summary', '')}\n{npc_names_text}")
            try:
                camp_entries = self.library.list_entries(campaign_id)
            except ValueError:
                camp_entries = []
            for entry in camp_entries:
                if entry["id"] in seen_ids:
                    continue
                norm_n = sourcecatalog._normalize(entry["name"])
                if norm_n in ref_names or (len(norm_n) >= 4 and norm_n in hay_norm):
                    citations.append(entry)
                    seen_ids.add(entry["id"])
                    if len(citations) >= total_cap:
                        break
        return citations[:total_cap]

    def _saved_campaign_npcs(self, campaign_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return compact dossiers of saved NPCs in campaign_library so the GM can recall and reuse them."""
        try:
            entries = self.library.list_entries(campaign_id, category="npc")
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for e in entries[:limit]:
            st = e.get("stats") if isinstance(e.get("stats"), dict) else {}
            item: dict[str, Any] = {"name": e.get("name"), "summary": e.get("summary")}
            for k in ("role", "disposition", "personality", "speech_style"):
                if st.get(k):
                    item[k] = st[k]
            out.append(item)
        return out

    def _apply_character_update_op(
        self,
        campaign_id: str,
        actor_hint: Any,
        raw_changes: Any,
        reason: str,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Normalize and apply a character state patch via GameplayService."""
        return self.executor.apply_character_update_op(campaign_id, actor_hint, raw_changes, reason, operation_id)

    def _execute_solo_op(
        self,
        campaign_id: str,
        op: dict[str, Any],
        default_actor: str | None,
        operation_id: str,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        return self.executor.execute_solo_op(campaign_id, op, default_actor, operation_id)

    @staticmethod
    def _trailing_deferred_user_messages(branch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collect contiguous trailing deferred user turns (skipping system dividers) in chronological order."""
        trailing: list[dict[str, Any]] = []
        for msg in reversed(branch or []):
            role = msg.get("role")
            meta = msg.get("metadata") or {}
            if role == "system":
                continue
            if role == "user" and meta.get("gm_deferred"):
                trailing.append(msg)
            else:
                break
        trailing.reverse()
        return trailing

    def preprocess(
        self,
        campaign_id: str,
        user_text: str,
        *,
        parent_id: str | None = None,
        branch_from_root: bool = False,
        turn_id: str | None = None,
        channel_id: str = "main",
    ) -> dict[str, Any]:
        """Gather dual memory, branch secrets/clocks, pre-rolled server dice pool, rulebook cards, and branch history."""
        op_base = turn_id or uuid.uuid4().hex[:12]
        context = self.gameplay.campaign_context(campaign_id)
        chan = ChatTreeStore._norm_channel(channel_id)
        tree_state = self.tree.get_tree(campaign_id, channel_id=chan)
        if branch_from_root:
            branch_parent = None
            branch = []
        elif parent_id is None and tree_state["active_leaf_id"] is not None:
            branch_parent = tree_state["active_leaf_id"]
            branch = list(tree_state["active_branch"])
        elif parent_id is not None:
            branch_parent = parent_id
            branch = self.tree.get_branch_to(campaign_id, parent_id)
        else:
            branch_parent = None
            branch = []

        main_tail: list[dict[str, Any]] = []
        if chan != "main":
            main_tree = self.tree.get_tree(campaign_id, channel_id="main")
            main_tail = list(main_tree.get("active_branch") or [])[-6:]

        branch_secrets, branch_clocks = self._load_branch_private_state(campaign_id, branch_parent)

        dice_pool = {"d10": _roll_dice(3, 10), "d6": _roll_dice(4, 6)}

        deferred_tail = self._trailing_deferred_user_messages(branch)
        deferred_user_ids = [m["id"] for m in deferred_tail if m.get("id")]
        deferred_user_texts = [
            self._format_player_message(str(m.get("content") or ""), (m.get("metadata") or {}).get("speaker_name"))
            for m in deferred_tail
            if str(m.get("content") or "").strip()
        ]
        citation_query = "\n".join(
            [
                *(str(m.get("content") or "") for m in deferred_tail if not (m.get("metadata") or {}).get("manual_roll")),
                user_text,
            ]
        ).strip()
        citations = self._collect_citations(campaign_id, citation_query or user_text, context["campaign"]["state"])
        compressed_count = self._get_compressed_count(campaign_id)
        turns_since_compress = max(0, len(branch) - compressed_count)
        threshold = max(4, int(self.turn_settings.get("compression_threshold", _COMPRESSION_MESSAGE_THRESHOLD)))
        party_grouping = compute_party_grouping(context["characters"], context["campaign"]["state"], active_channel_id=chan)
        npc_profiles = build_npc_profiles(context["campaign"]["state"], branch_secrets, include_hidden=True)
        return {
            "turn_id": op_base,
            "channel_id": chan,
            "context": context,
            "parent_id": branch_parent,
            "branch": branch,
            "main_tail": main_tail,
            "deferred_user_ids": deferred_user_ids,
            "deferred_user_texts": deferred_user_texts,
            "gm_secrets": branch_secrets,
            "clocks": branch_clocks,
            "party_grouping": party_grouping,
            "npc_profiles": npc_profiles,
            "dice_pool": dice_pool,
            "citations": citations,
            "compression_recommended": bool(self.turn_settings.get("auto_compress_prompt", True)) and turns_since_compress >= threshold,
        }

    def _format_player_message(self, text: str, speaker_name: str | None = None) -> str:
        return format_player_message(text, speaker_name, prompt_settings=self.prompt_settings)

    @staticmethod
    def _format_roll_ledger(executed: dict[str, Any], *, tagged_single_pass: bool = False) -> str:
        """Render an unambiguous plain-text roll ledger for the Narrator."""
        return format_roll_ledger(executed, tagged_single_pass=tagged_single_pass)

    def _build_planner_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        *,
        overclock: bool,
        luck_spend: int = 0,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = prep["context"]
        return build_planner_messages(
            prep,
            user_text,
            overclock=overclock,
            luck_spend=luck_spend,
            speaker=speaker,
            guidance=guidance,
            turn_settings=self.turn_settings,
            prompt_settings=self.prompt_settings,
            effective_turn_settings=self._effective_turn_settings(ctx["campaign"]["state"]),
            solo_summary=self._solo_summary(ctx),
            player_message_formatter=self._format_player_message,
        )

    def _build_think_planner_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        *,
        overclock: bool,
        luck_spend: int = 0,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = prep["context"]
        return build_think_planner_messages(
            prep,
            user_text,
            overclock=overclock,
            luck_spend=luck_spend,
            speaker=speaker,
            guidance=guidance,
            turn_settings=self.turn_settings,
            prompt_settings=self.prompt_settings,
            effective_turn_settings=self._effective_turn_settings(ctx["campaign"]["state"]),
            solo_summary=self._solo_summary(ctx),
            player_message_formatter=self._format_player_message,
        )

    def _build_intro_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        *,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = self.gameplay.campaign_context(prep["context"]["campaign"]["id"])
        return build_intro_messages(
            prep,
            user_text,
            speaker=speaker,
            guidance=guidance,
            campaign_context=ctx,
            prompt_settings=self.prompt_settings,
            player_message_formatter=self._format_player_message,
        )

    def _build_narrator_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        executed: dict[str, Any],
        *,
        tagged_single_pass: bool = False,
        overclock: bool = False,
        luck_spend: int = 0,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = self.gameplay.campaign_context(prep["context"]["campaign"]["id"])
        return build_narrator_messages(
            prep,
            user_text,
            executed,
            tagged_single_pass=tagged_single_pass,
            overclock=overclock,
            luck_spend=luck_spend,
            speaker=speaker,
            guidance=guidance,
            campaign_context=ctx,
            turn_settings=self.turn_settings,
            prompt_settings=self.prompt_settings,
            effective_turn_settings=self._effective_turn_settings(ctx["campaign"]["state"]),
            solo_summary=self._solo_summary(ctx),
            saved_npcs=self._saved_campaign_npcs(ctx["campaign"]["id"]),
            player_message_formatter=self._format_player_message,
            roll_ledger_formatter=self._format_roll_ledger,
        )

    def _build_think_narrator_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        executed: dict[str, Any],
        *,
        tagged_single_pass: bool = False,
        overclock: bool = False,
        luck_spend: int = 0,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
    ) -> list[dict[str, str]]:
        ctx = self.gameplay.campaign_context(prep["context"]["campaign"]["id"])
        return build_think_narrator_messages(
            prep,
            user_text,
            executed,
            tagged_single_pass=tagged_single_pass,
            overclock=overclock,
            luck_spend=luck_spend,
            speaker=speaker,
            guidance=guidance,
            campaign_context=ctx,
            turn_settings=self.turn_settings,
            prompt_settings=self.prompt_settings,
            effective_turn_settings=self._effective_turn_settings(ctx["campaign"]["state"]),
            solo_summary=self._solo_summary(ctx),
            saved_npcs=self._saved_campaign_npcs(ctx["campaign"]["id"]),
            player_message_formatter=self._format_player_message,
            roll_ledger_formatter=self._format_roll_ledger,
        )

    @staticmethod
    def _sanitize_think_pass1_plan(plan: dict[str, Any] | None) -> dict[str, Any] | None:
        """Restrict Pass 1 /think execution strictly to checks and optional new_homebrew (zero world mutations/time)."""
        if not isinstance(plan, dict):
            return plan
        sanitized: dict[str, Any] = {}
        if "checks" in plan:
            sanitized["checks"] = plan["checks"]
        if "new_homebrew" in plan:
            sanitized["new_homebrew"] = plan["new_homebrew"]
        if "gm_notes" in plan:
            sanitized["gm_notes"] = plan["gm_notes"]
        return sanitized

    @staticmethod
    def _sanitize_think_chronicler_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
        """Restrict Post-Turn Chronicler after a successful /think check strictly to discoveries-only."""
        if not isinstance(plan, dict):
            return {}
        filtered_ops: list[dict[str, Any]] = []
        for op in plan.get("state_ops") or []:
            if not isinstance(op, dict) or op.get("type") != "update_campaign":
                continue
            raw_changes = op.get("changes")
            if not isinstance(raw_changes, dict):
                continue
            disc = raw_changes.get("discoveries")
            if isinstance(disc, dict) and disc:
                filtered_ops.append(
                    {
                        "type": "update_campaign",
                        "changes": {"discoveries": disc},
                        "reason": str(op.get("reason") or "Observation discovery"),
                    }
                )
        return {"state_ops": filtered_ops}

    def _build_chronicler_messages(
        self,
        prep: dict[str, Any],
        user_text: str,
        narrated_text: str,
        executed: dict[str, Any],
        *,
        speaker: dict[str, str] | None = None,
        deferred_turns: list[str] | None = None,
    ) -> list[dict[str, str]]:
        ctx = prep["context"]
        return build_chronicler_messages(
            prep,
            user_text,
            narrated_text,
            executed,
            speaker=speaker,
            deferred_turns=deferred_turns,
            turn_settings=self.turn_settings,
            prompt_settings=self.prompt_settings,
            solo_summary=self._solo_summary(ctx),
            saved_npcs=self._saved_campaign_npcs(ctx["campaign"]["id"]),
            player_message_formatter=self._format_player_message,
        )

    def _execute_plan(
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
        return self.executor.execute_plan(
            campaign_id,
            plan,
            prep,
            overclock=overclock,
            luck_spend=luck_spend,
            default_actor=default_actor,
            op_prefix=op_prefix,
            allow_checks=allow_checks,
            allow_solo=allow_solo,
            allow_character_updates=allow_character_updates,
        )

    async def _stream_turn_from_user_msg(
        self,
        campaign_id: str,
        user_msg: dict[str, Any],
        prep: dict[str, Any],
        *,
        overclock: bool,
        luck_spend: int = 0,
        active_mode: str,
        speaker: dict[str, str] | None = None,
        guidance: str | None = None,
        is_intro: bool = False,
        turn_intent: str = "action",
    ) -> AsyncIterator[dict[str, Any]]:
        turn_started_at = time.perf_counter()
        total_completion_tokens = 0
        usage_observed = False
        stream_elapsed_s = 0.0

        def _collect_usage() -> dict[str, Any]:
            nonlocal total_completion_tokens, usage_observed
            pop_fn = getattr(self.llm, "pop_call_meta", None)
            if callable(pop_fn):
                meta = pop_fn() or {}
                u = meta.get("usage")
                finish_reason = meta.get("finish_reason")
                truncated = bool(meta.get("truncated", False) or finish_reason == "length")
            else:
                u = getattr(self.llm, "last_usage", None)
                finish_reason = getattr(self.llm, "last_finish_reason", None)
                truncated = bool(getattr(self.llm, "last_truncated", False) or finish_reason == "length")
            if isinstance(u, dict) and isinstance(u.get("completion_tokens"), (int, float)):
                total_completion_tokens += int(u["completion_tokens"])
                usage_observed = True
            return {"usage": u, "finish_reason": finish_reason, "truncated": truncated}

        user_text = user_msg["content"]
        is_think = not is_intro and str(turn_intent or "action").strip().lower() == "think"
        default_actor = speaker.get("id") or speaker.get("name") if speaker else None
        yield {"event": "rule_citation", "data": {"entries": prep["citations"], "dice_pool": prep["dice_pool"]}}

        if is_intro:
            executed: dict[str, Any] = {
                "rolls": [],
                "patches": [],
                "library_added": [],
                "warnings": [],
                "gm_secrets": prep.get("gm_secrets") or {},
                "clocks": prep.get("clocks") or [],
                "outcomes": {},
            }
            primer_block = f"{_STATIC_INTRO_PRIMER}\n\n---\n\n### CAMPAIGN TABLE WELCOME\n"
            yield {"event": "text_delta", "data": {"delta": primer_block}}
            intro_msgs = self._build_intro_messages(prep, user_text, speaker=speaker, guidance=guidance)
            intro_kwargs = self._thinking_kwargs_for_pass(self.llm.stream, disable_in_balanced=True)
            intro_max_tokens = max(256, int(self.turn_settings.get("intro_max_tokens") or 4096))
            if self._supports_kwarg(self.llm.stream, "max_tokens"):
                intro_kwargs["max_tokens"] = intro_max_tokens
            intro_sanitizer = StreamSanitizer()
            stream_t0 = time.perf_counter()
            intro_failed = False
            try:
                async for delta in self.llm.stream(intro_msgs, **intro_kwargs):
                    new_piece = intro_sanitizer.feed(delta)
                    if new_piece:
                        yield {"event": "text_delta", "data": {"delta": new_piece}}
                trailing, stream_raw = intro_sanitizer.finalize()
                if trailing:
                    yield {"event": "text_delta", "data": {"delta": trailing}}
            except Exception as exc:
                intro_failed = True
                fallback = "Open the **Character** tab to build or claim your Edgerunner, or click **Screamsheet & Briefing** at the top to review the campaign situation."
                stream_raw = fallback
                yield {"event": "text_delta", "data": {"delta": fallback}}
                executed["warnings"].append(f"Campaign welcome generation skipped ({exc}); static rules primer delivered.")
                yield {"event": "warning", "data": {"message": executed["warnings"][-1]}}
            stream_elapsed_s = max(0.01, time.perf_counter() - stream_t0)
            intro_meta = _collect_usage()
            raw_text = primer_block + stream_raw
            stripped_welcome = strip_gm_tags(stream_raw)
            if not intro_failed and not stripped_welcome:
                warn_msg = "Campaign welcome generation returned empty output; static rules primer delivered."
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}
            if intro_meta["truncated"]:
                warn_msg = "Campaign welcome response reached max_tokens (finish_reason=length) and may be truncated."
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}
            clean_text = f"{primer_block}{stripped_welcome}"
        elif active_mode == "two_pass":
            planner_builder = self._build_think_planner_messages if is_think else self._build_planner_messages
            planner_msgs = planner_builder(
                prep,
                user_text,
                overclock=overclock,
                luck_spend=luck_spend,
                speaker=speaker,
                guidance=guidance,
            )
            planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
            planner_kwargs = self._thinking_kwargs_for_pass(self.llm.complete, disable_in_balanced=False)
            raw_plan = await self.llm.complete(planner_msgs, temperature=planner_temp, json_mode=True, **planner_kwargs)
            plan_meta = _collect_usage()
            plan = extract_gm_plan(raw_plan)
            exec_plan = self._sanitize_think_pass1_plan(plan) if is_think else plan
            executed = self._execute_plan(
                campaign_id,
                exec_plan,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                default_actor=default_actor,
                allow_solo=not is_think,
                allow_character_updates=not is_think,
            )
            if plan_meta["truncated"]:
                executed["warnings"].append("Planner pass reached max_tokens (finish_reason=length) and may be truncated.")
            if plan is None:
                executed["warnings"].append("Planner pass returned empty or unparseable output; pre-turn operations were skipped.")

            for r in executed["rolls"]:
                yield {"event": "dice_roll", "data": r}
            for p in executed["patches"]:
                yield {"event": "state_patch", "data": p}
            for entry in executed["library_added"]:
                yield {"event": "library_added", "data": entry}
            for w in executed["warnings"]:
                yield {"event": "warning", "data": {"message": w}}

            narrator_builder = self._build_think_narrator_messages if is_think else self._build_narrator_messages
            narrator_msgs = narrator_builder(
                prep, user_text, executed, tagged_single_pass=False, speaker=speaker, guidance=guidance
            )
            narrator_kwargs = self._thinking_kwargs_for_pass(self.llm.stream, disable_in_balanced=True)
            sanitizer = StreamSanitizer()
            stream_t0 = time.perf_counter()
            async for delta in self.llm.stream(narrator_msgs, **narrator_kwargs):
                new_piece = sanitizer.feed(delta)
                if new_piece:
                    yield {"event": "text_delta", "data": {"delta": new_piece}}
            stream_elapsed_s = max(0.01, time.perf_counter() - stream_t0)
            narr_meta = _collect_usage()
            trailing, raw_text = sanitizer.finalize()
            if trailing:
                yield {"event": "text_delta", "data": {"delta": trailing}}
            if narr_meta["truncated"]:
                warn_msg = "Narrative response reached max_tokens (finish_reason=length) and was truncated."
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}
            clean_text = strip_gm_tags(raw_text)
            if not clean_text.strip():
                warn_msg = "Model returned an empty narrative response."
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}
                clean_text = "[GM response was empty — please retry or regenerate.]"
                yield {"event": "text_delta", "data": {"delta": clean_text}}
        else:
            empty_exec = {"rolls": [], "patches": [], "library_added": [], "warnings": [], "outcomes": {}}
            sp_builder = self._build_think_narrator_messages if is_think else self._build_narrator_messages
            msgs = sp_builder(
                prep,
                user_text,
                empty_exec,
                tagged_single_pass=True,
                overclock=overclock,
                luck_spend=luck_spend,
                speaker=speaker,
                guidance=guidance,
            )
            narrator_kwargs = self._thinking_kwargs_for_pass(self.llm.stream, disable_in_balanced=True)
            sanitizer = StreamSanitizer()
            stream_t0 = time.perf_counter()
            async for delta in self.llm.stream(msgs, **narrator_kwargs):
                new_piece = sanitizer.feed(delta)
                if new_piece:
                    yield {"event": "text_delta", "data": {"delta": new_piece}}
            stream_elapsed_s = max(0.01, time.perf_counter() - stream_t0)
            sp_meta = _collect_usage()
            trailing, raw_text = sanitizer.finalize()
            if trailing:
                yield {"event": "text_delta", "data": {"delta": trailing}}
            plan = extract_gm_plan(raw_text)
            exec_plan = self._sanitize_think_pass1_plan(plan) if is_think else plan
            executed = self._execute_plan(
                campaign_id,
                exec_plan,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                default_actor=default_actor,
                allow_solo=not is_think,
                allow_character_updates=not is_think,
            )
            if sp_meta["truncated"]:
                executed["warnings"].append("Single-pass response reached max_tokens (finish_reason=length) and was truncated.")
            if plan is None and ("<gm_ops" in raw_text.lower() or "[[gm_state" in raw_text.lower()):
                executed["warnings"].append("Single-pass <gm_ops> block was unparseable; operations were skipped.")
            clean_text = strip_gm_tags(raw_text)
            if not clean_text.strip():
                warn_msg = "Model returned an empty narrative response."
                executed["warnings"].append(warn_msg)
                clean_text = "[GM response was empty — please retry or regenerate.]"
                yield {"event": "text_delta", "data": {"delta": clean_text}}
            for r in executed["rolls"]:
                yield {"event": "dice_roll", "data": r}
            for p in executed["patches"]:
                yield {"event": "state_patch", "data": p}
            for entry in executed["library_added"]:
                yield {"event": "library_added", "data": entry}
            for w in executed["warnings"]:
                yield {"event": "warning", "data": {"message": w}}

        # Optional 3rd pass (Post-Turn Chronicler) when enabled and using OpenAI-compatible or opted-in multi-call adapters.
        # On /think turns, skip Chronicler unless at least one observation check succeeded, and restrict to discoveries-only.
        chronicler_allowed = bool(self.turn_settings.get("enable_chronicler", True))
        has_successful_think_roll = any(r.get("success") is True for r in (executed.get("rolls") or []))
        use_chronicler = (
            not is_intro
            and chronicler_allowed
            and bool(getattr(self.llm, "enable_multi_call", isinstance(self.llm, OpenAICompatibleLLM)))
            and bool(clean_text.strip())
            and (not is_think or has_successful_think_roll)
        )
        if use_chronicler:
            try:
                chron_ctx = self.gameplay.campaign_context(campaign_id)
                chron_prep = {
                    **prep,
                    "context": chron_ctx,
                    "gm_secrets": executed["gm_secrets"],
                    "clocks": executed["clocks"],
                }
                chron_msgs = self._build_chronicler_messages(
                    chron_prep,
                    user_text,
                    clean_text,
                    executed,
                    speaker=speaker,
                    deferred_turns=None if is_think else (prep.get("deferred_user_texts") or None),
                )
                chron_kwargs = self._thinking_kwargs_for_pass(self.llm.complete, disable_in_balanced=True)
                planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
                raw_chron = await self.llm.complete(chron_msgs, temperature=planner_temp, json_mode=True, **chron_kwargs)
                chron_meta = _collect_usage()
                chron_plan = extract_gm_plan(raw_chron)
                if chron_meta["truncated"]:
                    warn_msg = "Post-turn chronicler reached max_tokens (finish_reason=length) and may be truncated."
                    executed["warnings"].append(warn_msg)
                    yield {"event": "warning", "data": {"message": warn_msg}}
                if chron_plan is None:
                    warn_msg = "Post-turn chronicler returned empty or unparseable output; post-turn sync was skipped."
                    executed["warnings"].append(warn_msg)
                    yield {"event": "warning", "data": {"message": warn_msg}}
                elif chron_plan:
                    if is_think:
                        chron_plan = self._sanitize_think_chronicler_plan(chron_plan)
                    else:
                        already_timed = any(
                            p.get("target") == "solo"
                            and p.get("kind") != "start_time"
                            and isinstance(p.get("after"), dict)
                            and "time" in p["after"]
                            for p in executed["patches"]
                        )
                        if already_timed:
                            chron_plan.pop("time_elapsed_minutes", None)
                    chron_exec = self._execute_plan(
                        campaign_id,
                        chron_plan,
                        chron_prep,
                        default_actor=default_actor,
                        op_prefix=f"{prep['turn_id']}:chron",
                        allow_checks=False,
                        allow_solo=False,
                        allow_character_updates=False,
                    )
                    for p in chron_exec["patches"]:
                        executed["patches"].append(p)
                        yield {"event": "state_patch", "data": p}
                    for entry in chron_exec["library_added"]:
                        executed["library_added"].append(entry)
                        yield {"event": "library_added", "data": entry}
                    for w in chron_exec["warnings"]:
                        executed["warnings"].append(w)
                        yield {"event": "warning", "data": {"message": w}}
                    executed["gm_secrets"] = chron_exec["gm_secrets"]
                    executed["clocks"] = chron_exec["clocks"]
            except Exception as exc:
                warn_msg = f"Post-turn chronicler skipped: {exc}"
                executed["warnings"].append(warn_msg)
                yield {"event": "warning", "data": {"message": warn_msg}}

        # Apply default_time_step_minutes once after Chronicler if neither Pass 1 nor Chronicler advanced non-start_time world time.
        fallback_step = int(self.turn_settings.get("default_time_step_minutes") or 0)
        if not is_intro and not is_think and fallback_step > 0:
            already_timed = any(
                p.get("target") == "solo"
                and p.get("kind") != "start_time"
                and isinstance(p.get("after"), dict)
                and "time" in p["after"]
                for p in executed["patches"]
            )
            if not already_timed:
                mins = min(43200, fallback_step)
                t_patches, t_warns, _, t_outcomes = self._execute_solo_op(
                    campaign_id,
                    {"action": "advance_time", "elapsed_minutes": mins, "reason": f"Scene time elapsed (+{mins}m)"},
                    default_actor,
                    operation_id=f"{prep['turn_id']}:default_time",
                )
                for p in t_patches:
                    executed["patches"].append(p)
                    yield {"event": "state_patch", "data": p}
                for w in t_warns:
                    executed["warnings"].append(w)
                    yield {"event": "warning", "data": {"message": w}}
                if t_outcomes:
                    executed.setdefault("outcomes", {}).setdefault("solo_results", []).extend(t_outcomes)

        if prep["compression_recommended"]:
            msg = "Long conversation branch; update or compress the campaign summary when convenient."
            executed["warnings"].append(msg)
            yield {"event": "warning", "data": {"message": msg}}

        post_ctx = self.gameplay.campaign_context(campaign_id)
        model_name = getattr(getattr(self.llm, "config", None), "model", "")
        citation_cards = [
            {
                "id": c["id"],
                "name": c["name"],
                "category": c["category"],
                "summary": c["summary"],
                "source": c.get("source"),
                "printed_page": c.get("printed_page"),
                "pdf_page": c.get("pdf_page"),
            }
            for c in prep["citations"]
        ]
        overall_elapsed_s = round(max(0.01, time.perf_counter() - turn_started_at), 2)
        if usage_observed and total_completion_tokens > 0:
            completion_tokens = total_completion_tokens
            tokens_per_second = round(completion_tokens / overall_elapsed_s, 1)
            tokens_estimated = False
        else:
            completion_tokens = max(1, round(len(raw_text) / 4)) if raw_text else 0
            tokens_per_second = (
                round(completion_tokens / max(0.01, stream_elapsed_s), 1)
                if completion_tokens > 0
                else 0.0
            )
            tokens_estimated = True
        generation_stats = {
            "elapsed_seconds": overall_elapsed_s,
            "tokens_per_second": tokens_per_second,
            "completion_tokens": completion_tokens,
            "estimated": tokens_estimated,
        }

        if not is_think:
            for def_id in prep.get("deferred_user_ids") or []:
                if def_id != user_msg["id"]:
                    self.tree.update_message_metadata(
                        campaign_id,
                        def_id,
                        {"gm_deferred": None, "defer_reason": None},
                    )

        if executed["rolls"] or (not is_think and user_msg.get("metadata", {}).get("gm_deferred")):
            updated_user = self.tree.update_message_metadata(
                campaign_id,
                user_msg["id"],
                {
                    **({"rolls": executed["rolls"]} if executed["rolls"] else {}),
                    **({"gm_deferred": None, "defer_reason": None} if not is_think else {}),
                },
            )
            if updated_user is not None:
                user_msg = updated_user

        chan = str(prep.get("channel_id") or "main")
        assistant_msg = self.tree.append_message(
            campaign_id,
            parent_id=user_msg["id"],
            role="assistant",
            content=clean_text,
            raw_content=raw_text,
            model=model_name,
            campaign_revision=post_ctx["campaign"]["revision"],
            solo_revision=post_ctx["solo"]["revision"],
            channel_id=chan,
            metadata={
                "turn_id": prep["turn_id"],
                "channel_id": chan,
                "mode": "intro" if is_intro else active_mode,
                **({"is_intro": True} if is_intro else {}),
                **({"turn_intent": "think"} if is_think else {}),
                "generation_stats": generation_stats,
                "rolls": executed["rolls"],
                "patches": executed["patches"],
                "library_added": [e["id"] for e in executed["library_added"]],
                "citations": [c["id"] for c in prep["citations"]],
                "citation_cards": citation_cards,
                "warnings": executed["warnings"],
                **({"guidance": guidance.strip()} if isinstance(guidance, str) and guidance.strip() else {}),
            },
        )
        self._save_branch_private_state(
            campaign_id,
            assistant_msg["id"],
            user_msg["id"],
            executed["gm_secrets"],
            executed["clocks"],
        )
        yield {
            "event": "turn_done",
            "data": {
                "turn_id": prep["turn_id"],
                "channel_id": chan,
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "generation_stats": generation_stats,
                "citations": prep["citations"],
                "rolls": executed["rolls"],
                "state_patches": executed["patches"],
                "library_added": executed["library_added"],
                "warnings": executed["warnings"],
                "compression_recommended": prep["compression_recommended"],
            },
        }

    async def compress_memory(self, campaign_id: str, leaf_id: str | None = None) -> dict[str, Any]:
        """Distill branch history into structured Campaign Library dossiers + concise cross-referenced summary."""
        ctx = self.gameplay.campaign_context(campaign_id)
        tree = self.tree.get_tree(campaign_id)
        target_leaf = leaf_id or tree.get("active_leaf_id")
        branch = self.tree.get_branch_to(campaign_id, target_leaf) if target_leaf else list(tree.get("active_branch") or [])
        secrets, clocks = self._load_branch_private_state(campaign_id, target_leaf)
        existing_lib = [
            {
                "name": e["name"],
                "category": e["category"],
                "summary": e["summary"],
                "stats": e["stats"],
            }
            for e in self.library.list_entries(campaign_id)
        ]
        transcript_lines = [
            (
                f"[{((m.get('metadata') or {}).get('speaker_name') or 'USER').upper()}] {m['content'].strip()}"
                if m.get("role") == "user"
                else f"[{m['role'].upper()}] {m['content'].strip()}"
            )
            for m in branch[-60:]
            if isinstance(m.get("content"), str) and m["content"].strip()
        ]
        if not transcript_lines and not ctx["campaign"]["state"]["summary"].strip():
            raise ValueError("No conversation history or summary to compress yet")

        archivist_extra = (self.prompt_settings.get("archivist_extra") or "").strip()
        archivist_core = (self.prompt_settings.get("archivist_core_rules") or "").strip()
        arch_block = f"\nCustom Archivist Instructions:\n{archivist_extra}\n" if archivist_extra else "\n"
        core_block = f"Critical rules:\n{archivist_core}\n" if archivist_core else ""
        comp_prompt = (
            "You are the Cyberpunk RED Campaign Archivist. Compress the conversation history into clean, structured persistent records.\n"
            f"{arch_block}"
            "Return ONLY a single valid JSON object with no markdown:\n"
            "{\n"
            '  "library_entries": [\n'
            '    {"name": "...", "category": "npc|faction|location|weapon|armor|cyberware|program|hardware|gear|role|rule", "summary": "1-sentence player-known summary", "description": "concise factual dossier/lore/mechanics", "stats": {"role": "...", "district": "...", "disposition": "Wary (-1)", "cost_eb": 500}, "tags": ["..."]}\n'
            "  ],\n"
            '  "campaign_updates": {\n'
            '    "scene": "concise current location + active situation",\n'
            '    "summary": "crisp chronological recap <= 1400 chars referencing Library dossiers with [Category: Name] tags (e.g. [NPC: Mara Kovic], [Location: Dock 7], [Faction: Maelstrom]) instead of repeating bios/stats inline",\n'
            '    "npcs": {"NPC Name": "Role, location — Disposition (Hostile -2..Trusted +2); latest tie-in"},\n'
            '    "objectives": {"Objective": "Active|Completed|Blocked"},\n'
            '    "discoveries": {"Topic": "Verified PC-observed clue (can cite [Category: Name])"},\n'
            '    "unresolved": {"Thread": "Open hook or pending threat"}\n'
            "  },\n"
            '  "gm_secrets": {"secret_key": "private GM truth, hidden motive, or null to remove resolved secret"},\n'
            '  "clock_ops": [{"id": "...", "name": "...", "delta": 0, "filled": 0, "segments": 4, "category": "heat|obligation|deadline|faction|recovery", "visibility": "public|secret", "note": "..."}]\n'
            "}\n"
            f"{core_block}"
            f"Current Campaign State: {json.dumps(ctx['campaign']['state'])}\n"
            f"Existing Campaign Library Entries: {json.dumps(existing_lib)}\n"
            f"Current Private GM Secrets: {json.dumps(_visible_gm_secrets_for_prompt(secrets))}\n"
            f"Current Clocks: {json.dumps(clocks)}"
        )
        planner_temp = float(self.turn_settings.get("planner_temperature", 0.1))
        comp_kwargs = self._thinking_kwargs_for_pass(self.llm.complete, disable_in_balanced=True)
        raw = await self.llm.complete(
            [
                {"role": "system", "content": comp_prompt},
                {"role": "user", "content": "Branch Transcript:\n" + "\n\n".join(transcript_lines)},
            ],
            temperature=planner_temp,
            json_mode=True,
            **comp_kwargs,
        )
        parsed = extract_gm_plan(raw)
        if not parsed:
            raise ValueError("Compression model returned empty or invalid JSON")

        op_base = f"compress:{uuid.uuid4().hex[:10]}"
        upserted_entries: list[dict[str, Any]] = []
        warnings: list[str] = []

        for idx, raw_entry in enumerate(parsed.get("library_entries") or []):
            if not isinstance(raw_entry, dict):
                continue
            try:
                raw_cat = raw_entry.get("category")
                norm_cat = normalize_category(str(raw_cat)) if raw_cat else "rule"
                upserted = self.library.upsert_entry(
                    campaign_id,
                    name=str(raw_entry.get("name") or ""),
                    category=norm_cat or "rule",
                    summary=str(raw_entry.get("summary") or ""),
                    description=str(raw_entry.get("description") or ""),
                    stats=raw_entry.get("stats") if isinstance(raw_entry.get("stats"), dict) else {},
                    tags=raw_entry.get("tags") if isinstance(raw_entry.get("tags"), list) else [],
                    created_by="ai",
                    allow_variant=False,
                    operation_id=f"{op_base}:lib:{idx}",
                )
                upserted_entries.append(upserted)
            except (TypeError, ValueError) as exc:
                warnings.append(f"Skipped library entry '{raw_entry.get('name', '?')}': {exc}")

        live_camp = self.gameplay.campaign_context(campaign_id)["campaign"]
        raw_updates = parsed.get("campaign_updates") if isinstance(parsed.get("campaign_updates"), dict) else {}
        updated_campaign = live_camp
        if raw_updates:
            changes, norm_notes = _normalize_campaign_changes(raw_updates, live_camp["state"])
            warnings.extend(norm_notes)
            if changes:
                updated_campaign = self.gameplay.execute(
                    "update_campaign",
                    {
                        "campaign_id": campaign_id,
                        "expected_revision": live_camp["revision"],
                        "changes": changes,
                        "reason": "Compress campaign memory & archive to Library",
                        "operation_id": f"{op_base}:camp",
                    },
                    campaign_id=campaign_id,
                )["result"]

        next_secrets = self._merge_gm_secrets(secrets, parsed.get("gm_secrets"))
        next_clocks, _ = self._apply_clock_ops(clocks, parsed.get("clock_ops"), allow_secret=True)
        parent_id = None
        if target_leaf:
            leaf_msg = self.tree.get_message(campaign_id, target_leaf)
            parent_id = leaf_msg["parent_id"] if leaf_msg else None
        self._save_branch_private_state(campaign_id, target_leaf, parent_id, next_secrets, next_clocks)
        if not target_leaf:
            self._save_branch_private_state(campaign_id, None, None, next_secrets, next_clocks)
        self._set_compressed_count(campaign_id, target_leaf, len(branch))
        self.tree.sync_active_leaf_revisions(campaign_id)

        return {
            "campaign": updated_campaign,
            "library_upserted": upserted_entries,
            "compressed_messages": len(branch),
            "clocks": [c for c in next_clocks if c.get("visibility") != "secret"],
            "warnings": warnings,
        }

    @staticmethod
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
        turn_intent: str = "action",
    ) -> tuple[bool, str]:
        """Decide if the AI GM should respond immediately or let party members reply first."""
        return _router_should_gm_intervene(
            user_text,
            branch=branch,
            characters=characters,
            npcs=npcs,
            speaker=speaker,
            coop_player_count=coop_player_count,
            overclock=overclock,
            luck_spend=luck_spend,
            turn_intent=turn_intent,
        )

    async def run_turn(
        self,
        campaign_id: str,
        user_text: str,
        *,
        parent_id: str | None = None,
        branch_from_root: bool = False,
        overclock: bool = False,
        luck_spend: int = 0,
        mode: str | None = None,
        speaker_character_id: str | None = None,
        speaker_name: str | None = None,
        is_intro: bool = False,
        gm_mode: str = "auto",
        coop_player_count: int = 1,
        channel_id: str = "main",
        turn_intent: str = "action",
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one complete AI GM turn and stream typed events for the frontend UI."""
        if not isinstance(user_text, str):
            raise ValueError("user_text must be a nonempty string")
        clean_turn_intent = str(turn_intent or "action").strip().lower()
        if clean_turn_intent not in {"action", "think"}:
            raise ValueError("turn_intent must be 'action' or 'think'")
        clean_user_text = user_text.strip()
        if clean_turn_intent != "think":
            think_match = _THINK_CMD_RE.match(clean_user_text)
            if think_match:
                clean_turn_intent = "think"
                clean_user_text = (think_match.group(1) or "").strip()
        if clean_turn_intent == "think" and not clean_user_text:
            raise ValueError("Enter a thought or observation question after /think.")
        if not clean_user_text:
            raise ValueError("user_text must be a nonempty string")
        if isinstance(luck_spend, bool) or not isinstance(luck_spend, int) or luck_spend < 0:
            raise ValueError("luck_spend must be a nonnegative integer")
        active_mode = mode or self.turn_settings.get("mode") or getattr(getattr(self.llm, "config", None), "mode", "two_pass")
        if active_mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError(f"Unsupported turn mode: {active_mode!r}")

        chan = ChatTreeStore._norm_channel(channel_id)
        prep = await asyncio.to_thread(
            lambda: self.preprocess(
                campaign_id,
                clean_user_text,
                parent_id=parent_id,
                branch_from_root=branch_from_root,
                channel_id=chan,
            )
        )
        pre_ctx = prep["context"]
        speaker = self._resolve_speaker(pre_ctx["characters"], speaker_character_id, speaker_name)
        meta: dict[str, Any] = {"overclock": overclock, "luck_spend": luck_spend, "channel_id": chan}
        if is_intro:
            meta["is_intro"] = True
        elif clean_turn_intent == "think":
            meta["turn_intent"] = "think"
        if speaker.get("id"):
            meta["speaker_character_id"] = speaker["id"]
        if speaker.get("name"):
            meta["speaker_name"] = speaker["name"]
        if speaker.get("color"):
            meta["speaker_color"] = speaker["color"]
        if speaker.get("portrait_url"):
            meta["speaker_portrait_url"] = speaker["portrait_url"]

        clean_gm_mode = (gm_mode or "auto").strip().lower()
        should_run_gm = True
        defer_reason = ""
        if not is_intro and clean_turn_intent != "think":
            if clean_gm_mode == "hold_gm":
                should_run_gm = False
                defer_reason = "Action/dialogue posted to table — waiting for party or 'Resolve GM Turn'"
            elif clean_gm_mode == "auto":
                grouping = prep.get("party_grouping") or {}
                channel_chars = (
                    [
                        c for c in pre_ctx["characters"]
                        if (grouping.get("char_channel_map") or {}).get(c["id"], "main") == chan
                    ]
                    if grouping.get("mode") == "split" and chan != "main"
                    else pre_ctx["characters"]
                )
                should_run_gm, defer_reason = self.should_gm_intervene(
                    clean_user_text,
                    branch=prep["branch"],
                    characters=channel_chars,
                    npcs=(pre_ctx["campaign"].get("state") or {}).get("npcs") or {},
                    speaker=speaker,
                    coop_player_count=coop_player_count,
                    overclock=overclock,
                    luck_spend=luck_spend,
                    turn_intent=clean_turn_intent,
                )

        if not should_run_gm:
            meta["gm_deferred"] = True
            meta["defer_reason"] = defer_reason
            revs = self.tree._current_revisions(campaign_id)
            user_msg = self.tree.append_message(
                campaign_id,
                parent_id=prep["parent_id"],
                role="user",
                content=clean_user_text,
                campaign_revision=revs["campaign_revision"],
                solo_revision=revs["solo_revision"],
                channel_id=chan,
                metadata=meta,
            )
            yield {"event": "user_message", "data": {"message": user_msg, "channel_id": chan}}
            yield {
                "event": "turn_done",
                "data": {
                    "turn_id": prep["turn_id"],
                    "channel_id": chan,
                    "user_message": user_msg,
                    "assistant_message": None,
                    "gm_deferred": True,
                    "defer_reason": defer_reason,
                    "citations": [],
                    "rolls": [],
                    "state_patches": [],
                    "library_added": [],
                    "warnings": [],
                    "compression_recommended": False,
                },
            }
            return

        user_msg = self.tree.append_message(
            campaign_id,
            parent_id=prep["parent_id"],
            role="user",
            content=clean_user_text,
            campaign_revision=pre_ctx["campaign"]["revision"],
            solo_revision=pre_ctx["solo"]["revision"],
            channel_id=chan,
            metadata=meta,
        )
        yield {"event": "user_message", "data": {"message": user_msg, "channel_id": chan}}
        turn_completed = False
        try:
            async for ev in self._stream_turn_from_user_msg(
                campaign_id,
                user_msg,
                prep,
                overclock=overclock,
                luck_spend=luck_spend,
                active_mode=active_mode,
                speaker=speaker,
                is_intro=is_intro,
                turn_intent=clean_turn_intent,
            ):
                if ev.get("event") == "turn_done":
                    turn_completed = True
                yield ev
        finally:
            if not turn_completed:
                try:
                    self.tree.delete_message(campaign_id, user_msg["id"])
                except Exception:
                    pass

    @staticmethod
    def _resolve_speaker(
        characters: list[dict[str, Any]],
        speaker_character_id: str | None,
        speaker_name: str | None,
    ) -> dict[str, str]:
        if speaker_character_id:
            found = next((c for c in characters if c["id"] == speaker_character_id), None)
            if found:
                d = found.get("detail") or {}
                out = {"id": found["id"], "name": str(d.get("handle") or found["name"])}
                if isinstance(d.get("color"), str) and d["color"].strip():
                    out["color"] = d["color"].strip()
                if isinstance(d.get("portrait_url"), str) and d["portrait_url"].strip():
                    out["portrait_url"] = d["portrait_url"].strip()
                return out
        if isinstance(speaker_name, str) and speaker_name.strip():
            return {"id": "", "name": speaker_name.strip()}
        return {}

    async def regenerate_turn(
        self,
        campaign_id: str,
        message_id: str,
        *,
        overclock: bool | None = None,
        luck_spend: int | None = None,
        mode: str | None = None,
        guidance: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Regenerate an assistant reply as a sibling branch without duplicating the user message."""
        active_mode = mode or self.turn_settings.get("mode") or getattr(getattr(self.llm, "config", None), "mode", "two_pass")
        if active_mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError(f"Unsupported turn mode: {active_mode!r}")
        target = self.tree.get_message(campaign_id, message_id)
        if target is None:
            raise ValueError(f"message not found in campaign: {message_id}")
        if target["role"] == "assistant":
            if not target["parent_id"]:
                raise ValueError("Assistant message has no parent user message")
            user_msg = self.tree.get_message(campaign_id, target["parent_id"])
            if user_msg is None or user_msg["role"] != "user":
                raise ValueError("Parent message is not a user turn")
        elif target["role"] == "user":
            user_msg = target
        else:
            raise ValueError("Only user or assistant messages can be regenerated")

        self.tree.switch_branch(campaign_id, user_msg["id"])
        chan = ChatTreeStore._norm_channel(user_msg.get("channel_id"))
        use_overclock = bool(user_msg["metadata"].get("overclock", False)) if overclock is None else bool(overclock)
        use_luck = int(user_msg["metadata"].get("luck_spend", 0)) if luck_spend is None else int(luck_spend)
        if use_luck < 0:
            raise ValueError("luck_spend must be a nonnegative integer")
        prep = await asyncio.to_thread(
            lambda: self.preprocess(
                campaign_id,
                user_msg["content"],
                parent_id=user_msg["parent_id"],
                branch_from_root=(user_msg["parent_id"] is None),
                channel_id=chan,
            )
        )
        speaker = self._resolve_speaker(
            prep["context"]["characters"],
            user_msg["metadata"].get("speaker_character_id"),
            user_msg["metadata"].get("speaker_name"),
        )
        inherited_intent = str((user_msg.get("metadata") or {}).get("turn_intent") or "action").strip().lower()
        if inherited_intent not in {"action", "think"}:
            inherited_intent = "action"
        async for ev in self._stream_turn_from_user_msg(
            campaign_id,
            user_msg,
            prep,
            overclock=use_overclock,
            luck_spend=use_luck,
            active_mode=active_mode,
            speaker=speaker,
            guidance=guidance,
            is_intro=bool(user_msg["metadata"].get("is_intro", False)),
            turn_intent=inherited_intent,
        ):
            yield ev
