"""TurnEngine orchestrator composing ChatTreeStore, BranchPrivateStateStore, PlanExecutor, prompts, and router."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, AsyncIterator
import uuid

from gameplay import GameplayService
from encounters import npc_stat_blocks
from library import CampaignLibrary, normalize_category, search_library
import sourcecatalog
from turn_engine.chat_tree import BranchPrivateStateStore, ChatTreeStore
from turn_engine.executor import PlanExecutor
from turn_engine.llm_client import (
    OpenAICompatibleLLM,
    StreamSanitizer,
    extract_gm_plan,
    extract_tagged_gm_ops,
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
    _visible_state_for_prompt,
    build_npc_profiles,
    compute_party_grouping,
    parse_session_zero,
)

logger = logging.getLogger(__name__)

_NARRATION_FAILED_TEXT = (
    "[Narration failed after the turn resolved. The rolls and state changes on this message are saved — "
    "regenerate to narrate them.]"
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

    def _get_gm_secrets(self, campaign_id: str) -> dict[str, str]:
        return self.private_state.get_gm_secrets(campaign_id)

    def update_gm_secrets(self, campaign_id: str, updates: dict[str, str | None]) -> dict[str, str]:
        """Persist secret updates across root gm_secrets AND all active channel branch snapshots."""
        return self.private_state.update_gm_secrets(campaign_id, updates)

    def list_public_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        return self.private_state.list_public_clocks(campaign_id, leaf_id=leaf_id)

    def list_all_clocks(self, campaign_id: str, leaf_id: str | None = None) -> list[dict[str, Any]]:
        return self.private_state.list_all_clocks(campaign_id, leaf_id=leaf_id)

    def mutate_public_clock(
        self,
        campaign_id: str,
        body: dict[str, Any],
        leaf_id: str | None = None,
        *,
        allow_secret: bool = False,
    ) -> list[dict[str, Any]]:
        return self.private_state.mutate_public_clock(campaign_id, body, leaf_id=leaf_id, allow_secret=allow_secret)

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

    def _solo_summary(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import combat as _combat
        import rules_eval as _rules_eval

        runtime = (ctx.get("solo") or {}).get("runtime") or {}
        enc = runtime.get("encounter")
        chars_by_id = {
            c["id"]: str((c.get("detail") or {}).get("handle") or c["name"])
            for c in ctx.get("characters") or []
        }
        enc_view = None
        if isinstance(enc, dict) and enc.get("active"):
            enc_npcs = enc.get("npcs")
            npc_items: list[tuple[str, dict[str, Any]]] = []
            if isinstance(enc_npcs, dict):
                npc_items = [(str(npc.get("id") or nid), npc) for nid, npc in enc_npcs.items() if isinstance(npc, dict)]
            elif isinstance(enc_npcs, list):
                npc_items = [(str(npc.get("id") or f"npc-{i}"), npc) for i, npc in enumerate(enc_npcs) if isinstance(npc, dict)]

            npc_statuses: list[dict[str, Any]] = []
            for npc_id, npc in npc_items:
                detail = npc.get("detail") if isinstance(npc.get("detail"), dict) else {}
                display_name = str(detail.get("handle") or npc.get("name") or npc_id)
                chars_by_id[npc_id] = display_name

                hp_val = npc.get("hp", 0)
                hp_int = int(hp_val) if isinstance(hp_val, int) and not isinstance(hp_val, bool) else 0
                raw_max = npc.get("max_hp")
                max_hp_int = int(raw_max) if isinstance(raw_max, int) and not isinstance(raw_max, bool) and raw_max >= 1 else max(1, hp_int)
                stats = npc.get("stats") if isinstance(npc.get("stats"), dict) else {}
                raw_move = stats.get("MOVE", 0)
                move_int = max(0, int(raw_move)) if isinstance(raw_move, int) and not isinstance(raw_move, bool) else 0
                is_dead = bool(detail.get("dead") or (detail.get("conditions") or {}).get("dead"))
                w_state = "dead" if is_dead else _combat.wound_state(hp_int, max_hp_int, move_int)["name"]

                equip = detail.get("equipment") if isinstance(detail.get("equipment"), dict) else {}
                armor_list = equip.get("armor") if isinstance(equip.get("armor"), list) else []
                body_sps = [
                    int(a["sp"]) for a in armor_list
                    if isinstance(a, dict) and a.get("equipped") is not False
                    and str(a.get("location") or "body").strip().casefold() in {"body", "body & head"}
                    and isinstance(a.get("sp"), int) and not isinstance(a.get("sp"), bool)
                ]
                head_sps = [
                    int(a["sp"]) for a in armor_list
                    if isinstance(a, dict) and a.get("equipped") is not False
                    and str(a.get("location") or "").strip().casefold() in {"head", "body & head"}
                    and isinstance(a.get("sp"), int) and not isinstance(a.get("sp"), bool)
                ]
                eq_body = detail.get("equipped_armor") if isinstance(detail.get("equipped_armor"), dict) else {}
                eq_head = detail.get("equipped_head_armor") if isinstance(detail.get("equipped_head_armor"), dict) else {}
                sp_body = max(body_sps) if body_sps else (int(eq_body["sp"]) if isinstance(eq_body.get("sp"), int) else 0)
                sp_head = max(head_sps) if head_sps else (int(eq_head["sp"]) if isinstance(eq_head.get("sp"), int) else 0)

                injuries = [
                    str(inj.get("name") or inj.get("id"))
                    for inj in _rules_eval.active_injuries(npc)
                    if not inj.get("suppressed") and not inj.get("treated") and not inj.get("quick_fixed")
                ]
                weapons = equip.get("weapons") if isinstance(equip.get("weapons"), list) else []
                primary_weapon = None
                for w in weapons:
                    if isinstance(w, dict) and (w.get("type") or w.get("name")):
                        primary_weapon = str(w.get("type") or w.get("name"))
                        break
                if primary_weapon is None and isinstance(detail.get("equipped_weapon"), str) and detail["equipped_weapon"].strip():
                    primary_weapon = detail["equipped_weapon"].strip()

                npc_statuses.append({
                    "id": npc_id,
                    "name": display_name,
                    "hp": hp_int,
                    "max_hp": max_hp_int,
                    "wound_state": w_state,
                    "sp_body": sp_body,
                    "sp_head": sp_head,
                    "injuries": injuries,
                    "weapon": primary_weapon,
                })

            q = enc.get("queue") or []
            idx = enc.get("turn_index", 0)
            cur_id = q[idx] if isinstance(idx, int) and 0 <= idx < len(q) else None
            enc_view = {
                "active": True,
                "round": enc.get("round", 1),
                "current_actor": chars_by_id.get(cur_id, cur_id),
                "queue": [chars_by_id.get(cid, cid) for cid in q],
                "npcs": npc_statuses,
            }
        runs_view: dict[str, Any] = {}
        for rid, r in (runtime.get("runs") or {}).items():
            if not isinstance(r, dict):
                continue
            inner = r.get("run") if isinstance(r.get("run"), dict) else r
            if inner.get("connected"):
                floor = inner.get("floor_id")
                if floor in (None, ""):
                    floor = inner.get("current_floor_id")
                runs_view[rid] = {
                    "connected": True,
                    "floor": floor,
                    "actions_remaining": inner.get("actions_remaining"),
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
        """Gather dual memory, branch secrets/clocks, rulebook cards, and branch history."""
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

        branch_secrets, branch_clocks = self.private_state.load_branch_private_state(campaign_id, branch_parent, channel_id=chan)

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
        compressed_count = self.private_state.get_compressed_count(campaign_id, channel_id=chan)
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
            "citations": citations,
            "npc_stat_blocks": self._npc_stat_block_names(),
            "compression_recommended": bool(self.turn_settings.get("auto_compress_prompt", True)) and turns_since_compress >= threshold,
        }

    def _npc_stat_block_names(self) -> list[str]:
        rules_path = self.gameplay.rules_path
        if not rules_path or not Path(rules_path).is_file():
            return []
        return [f"{e['name']} ({e['stats'].get('tier', 'npc')})" for e in npc_stat_blocks(rules_path)]

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
        progress: dict[str, Any],
        stored_executed: dict[str, Any] | None = None,
        regenerated_from: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Plan, execute, narrate and persist one GM turn.

        With `stored_executed` (regenerate of a resolved turn) only the Narrator runs, grounded in the
        stored rolls/outcomes; no planner, executor, chronicler or time step touches game state.
        `progress` is filled for the caller's failure handling: `mode`/`is_think` describing the turn,
        `executed` once state has been committed, and `clean_text`/`raw_text` once narration finished.
        """
        turn_started_at = time.perf_counter()
        total_completion_tokens = 0
        usage_observed = False
        stream_elapsed_s = 0.0

        def _collect_usage() -> dict[str, Any]:
            nonlocal total_completion_tokens, usage_observed
            meta = self.llm.pop_call_meta() or {}
            u = meta.get("usage")
            finish_reason = meta.get("finish_reason")
            truncated = bool(meta.get("truncated", False) or finish_reason == "length")
            if isinstance(u, dict) and isinstance(u.get("completion_tokens"), (int, float)):
                total_completion_tokens += int(u["completion_tokens"])
                usage_observed = True
            return {"usage": u, "finish_reason": finish_reason, "truncated": truncated}

        user_text = user_msg["content"]
        is_think = not is_intro and str(turn_intent or "action").strip().lower() == "think"
        default_actor = speaker.get("id") or speaker.get("name") if speaker else None
        progress["mode"] = "intro" if is_intro else active_mode
        progress["is_think"] = is_think
        yield {"event": "rule_citation", "data": {"entries": prep["citations"]}}

        renarrate = stored_executed is not None and not is_intro
        if renarrate:
            executed = stored_executed
            narration: dict[str, Any] = {}
            async for ev in self._stream_narration(
                prep,
                user_text,
                executed,
                is_think=is_think,
                speaker=speaker,
                guidance=guidance,
                collect_usage=_collect_usage,
                result=narration,
            ):
                yield ev
            raw_text, clean_text = narration["raw_text"], narration["clean_text"]
            stream_elapsed_s = narration["elapsed_s"]
        elif is_intro:
            executed = {
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
            intro_msgs = await asyncio.to_thread(
                lambda: self._build_intro_messages(prep, user_text, speaker=speaker, guidance=guidance)
            )
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
            executed = await asyncio.to_thread(
                lambda: self.executor.execute_plan(
                    campaign_id,
                    exec_plan,
                    prep,
                    overclock=overclock,
                    luck_spend=luck_spend,
                    default_actor=default_actor,
                    allow_solo=not is_think,
                    allow_character_updates=not is_think,
                )
            )
            progress["executed"] = executed
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

            narration = {}
            async for ev in self._stream_narration(
                prep,
                user_text,
                executed,
                is_think=is_think,
                speaker=speaker,
                guidance=guidance,
                collect_usage=_collect_usage,
                result=narration,
            ):
                yield ev
            raw_text, clean_text = narration["raw_text"], narration["clean_text"]
            stream_elapsed_s = narration["elapsed_s"]
            progress["raw_text"], progress["clean_text"] = raw_text, clean_text
        else:
            empty_exec = {"rolls": [], "patches": [], "library_added": [], "warnings": [], "outcomes": {}}
            sp_builder = self._build_think_narrator_messages if is_think else self._build_narrator_messages
            msgs = await asyncio.to_thread(
                lambda: sp_builder(
                    prep,
                    user_text,
                    empty_exec,
                    tagged_single_pass=True,
                    overclock=overclock,
                    luck_spend=luck_spend,
                    speaker=speaker,
                    guidance=guidance,
                )
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
            plan = extract_tagged_gm_ops(raw_text)
            exec_plan = self._sanitize_think_pass1_plan(plan) if is_think else plan
            executed = await asyncio.to_thread(
                lambda: self.executor.execute_plan(
                    campaign_id,
                    exec_plan,
                    prep,
                    overclock=overclock,
                    luck_spend=luck_spend,
                    default_actor=default_actor,
                    allow_solo=not is_think,
                    allow_character_updates=not is_think,
                )
            )
            progress["executed"] = executed
            if sp_meta["truncated"]:
                executed["warnings"].append("Single-pass response reached max_tokens (finish_reason=length) and was truncated.")
            if plan is None and "<gm_ops" in raw_text.lower():
                executed["warnings"].append("Single-pass <gm_ops> block was unparseable; operations were skipped.")
            clean_text = strip_gm_tags(raw_text)
            if not clean_text.strip():
                warn_msg = "Model returned an empty narrative response."
                executed["warnings"].append(warn_msg)
                clean_text = "[GM response was empty — please retry or regenerate.]"
                yield {"event": "text_delta", "data": {"delta": clean_text}}
            progress["raw_text"], progress["clean_text"] = raw_text, clean_text
            for r in executed["rolls"]:
                yield {"event": "dice_roll", "data": r}
            for p in executed["patches"]:
                yield {"event": "state_patch", "data": p}
            for entry in executed["library_added"]:
                yield {"event": "library_added", "data": entry}
            for w in executed["warnings"]:
                yield {"event": "warning", "data": {"message": w}}

        chan = str(prep.get("channel_id") or "main")

        def _compute_generation_stats() -> dict[str, Any]:
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
            return {
                "elapsed_seconds": overall_elapsed_s,
                "tokens_per_second": tokens_per_second,
                "completion_tokens": completion_tokens,
                "estimated": tokens_estimated,
            }

        # Persist assistant_msg immediately after Narrator completes so client disconnect / Chronicler failure never loses the reply.
        extra_meta: dict[str, Any] = {"generation_stats": _compute_generation_stats()}
        if is_intro:
            extra_meta["is_intro"] = True
        if isinstance(guidance, str) and guidance.strip():
            extra_meta["guidance"] = guidance.strip()
        if regenerated_from:
            extra_meta["regenerated_from"] = regenerated_from
        user_msg, assistant_msg = await asyncio.to_thread(
            lambda: self._persist_assistant_message(
                campaign_id,
                user_msg,
                prep,
                executed,
                clean_text=clean_text,
                raw_text=raw_text,
                mode="intro" if is_intro else active_mode,
                is_think=is_think,
                extra_meta=extra_meta,
            )
        )

        # Optional 3rd pass (Post-Turn Chronicler) when enabled and using OpenAI-compatible or opted-in multi-call adapters.
        # On /think turns, skip Chronicler unless at least one observation check succeeded, and restrict to discoveries-only.
        chronicler_allowed = bool(self.turn_settings.get("enable_chronicler", True))
        has_successful_think_roll = any(r.get("success") is True for r in (executed.get("rolls") or []))
        use_chronicler = (
            not is_intro
            and not renarrate
            and chronicler_allowed
            and bool(getattr(self.llm, "enable_multi_call", isinstance(self.llm, OpenAICompatibleLLM)))
            and bool(clean_text.strip())
            and (not is_think or has_successful_think_roll)
        )
        if use_chronicler:
            try:
                chron_ctx = await asyncio.to_thread(self.gameplay.campaign_context, campaign_id)
                chron_prep = {
                    **prep,
                    "context": chron_ctx,
                    "gm_secrets": executed["gm_secrets"],
                    "clocks": executed["clocks"],
                }
                chron_msgs = await asyncio.to_thread(
                    lambda: self._build_chronicler_messages(
                        chron_prep,
                        user_text,
                        clean_text,
                        executed,
                        speaker=speaker,
                        deferred_turns=None if is_think else (prep.get("deferred_user_texts") or None),
                    )
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
                    chron_exec = await asyncio.to_thread(
                        lambda: self.executor.execute_plan(
                            campaign_id,
                            chron_plan,
                            chron_prep,
                            default_actor=default_actor,
                            op_prefix=f"{prep['turn_id']}:chron",
                            allow_checks=False,
                            allow_solo=False,
                            allow_character_updates=False,
                        )
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
        if not is_intro and not renarrate and not is_think and fallback_step > 0:
            already_timed = any(
                p.get("target") == "solo"
                and p.get("kind") != "start_time"
                and isinstance(p.get("after"), dict)
                and "time" in p["after"]
                for p in executed["patches"]
            )
            if not already_timed:
                mins = min(43200, fallback_step)
                t_patches, t_warns, _, t_outcomes = await asyncio.to_thread(
                    lambda: self.executor.execute_solo_op(
                        campaign_id,
                        {"action": "advance_time", "elapsed_minutes": mins, "reason": f"Scene time elapsed (+{mins}m)"},
                        default_actor,
                        operation_id=f"{prep['turn_id']}:default_time",
                    )
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

        generation_stats = _compute_generation_stats()

        def _finalize_assistant() -> dict[str, Any]:
            revs = self.tree._current_revisions(campaign_id)
            updated = self.tree.update_message_metadata(
                campaign_id,
                assistant_msg["id"],
                {"generation_stats": generation_stats, **self._executed_metadata(prep, executed)},
                campaign_revision=revs["campaign_revision"],
                solo_revision=revs["solo_revision"],
            )
            final = updated if updated is not None else assistant_msg
            self.private_state.save_branch_private_state(
                campaign_id, final["id"], user_msg["id"], executed["gm_secrets"], executed["clocks"]
            )
            return final

        assistant_msg = await asyncio.to_thread(_finalize_assistant)
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
                "state_patches": [] if renarrate else executed["patches"],
                "library_added": [] if renarrate else executed["library_added"],
                "warnings": executed["warnings"],
                "compression_recommended": prep["compression_recommended"],
                **({"regenerated_from": regenerated_from} if regenerated_from else {}),
            },
        }

    async def _stream_narration(
        self,
        prep: dict[str, Any],
        user_text: str,
        executed: dict[str, Any],
        *,
        is_think: bool,
        speaker: dict[str, str] | None,
        guidance: str | None,
        collect_usage: Any,
        result: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream Narrator prose grounded in already-executed outcomes; fills `result` with raw/clean text and timing."""
        builder = self._build_think_narrator_messages if is_think else self._build_narrator_messages
        narrator_msgs = await asyncio.to_thread(
            lambda: builder(prep, user_text, executed, tagged_single_pass=False, speaker=speaker, guidance=guidance)
        )
        narrator_kwargs = self._thinking_kwargs_for_pass(self.llm.stream, disable_in_balanced=True)
        sanitizer = StreamSanitizer()
        stream_t0 = time.perf_counter()
        async for delta in self.llm.stream(narrator_msgs, **narrator_kwargs):
            new_piece = sanitizer.feed(delta)
            if new_piece:
                yield {"event": "text_delta", "data": {"delta": new_piece}}
        result["elapsed_s"] = max(0.01, time.perf_counter() - stream_t0)
        narr_meta = collect_usage()
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
        result["raw_text"] = raw_text
        result["clean_text"] = clean_text

    @staticmethod
    def _executed_metadata(prep: dict[str, Any], executed: dict[str, Any]) -> dict[str, Any]:
        """Message metadata recording what the turn executed, sufficient to re-narrate it without re-running it."""
        return {
            "rolls": executed["rolls"],
            "patches": executed["patches"],
            "outcomes": executed.get("outcomes") or {},
            "library_added": [e["id"] for e in executed["library_added"]],
            "citations": [c["id"] for c in prep["citations"]],
            "citation_cards": [
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
            ],
            "warnings": executed["warnings"],
        }

    def _persist_assistant_message(
        self,
        campaign_id: str,
        user_msg: dict[str, Any],
        prep: dict[str, Any],
        executed: dict[str, Any],
        *,
        clean_text: str,
        raw_text: str,
        mode: str,
        is_think: bool,
        extra_meta: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Save the GM reply with the turn's executed record and branch GM state; returns (user_msg, assistant_msg)."""
        chan = str(prep.get("channel_id") or "main")
        if not is_think:
            for def_id in prep.get("deferred_user_ids") or []:
                if def_id != user_msg["id"]:
                    self.tree.update_message_metadata(campaign_id, def_id, {"gm_deferred": None, "defer_reason": None})
        user_meta = user_msg.get("metadata") or {}
        user_meta_updates: dict[str, Any] = {}
        if not user_meta.get("manual_roll"):
            if executed["rolls"]:
                user_meta_updates["rolls"] = executed["rolls"]
            elif "rolls" in user_meta:
                user_meta_updates["rolls"] = None
        if not is_think and user_meta.get("gm_deferred"):
            user_meta_updates["gm_deferred"] = None
            user_meta_updates["defer_reason"] = None
        if user_meta_updates:
            updated_user = self.tree.update_message_metadata(campaign_id, user_msg["id"], user_meta_updates)
            if updated_user is not None:
                user_msg = updated_user
        revs = self.tree._current_revisions(campaign_id)
        assistant_msg = self.tree.append_message(
            campaign_id,
            parent_id=user_msg["id"],
            role="assistant",
            content=clean_text,
            raw_content=raw_text,
            model=getattr(getattr(self.llm, "config", None), "model", ""),
            campaign_revision=revs["campaign_revision"],
            solo_revision=revs["solo_revision"],
            channel_id=chan,
            metadata={
                "turn_id": prep["turn_id"],
                "channel_id": chan,
                "mode": mode,
                **({"turn_intent": "think"} if is_think else {}),
                **self._executed_metadata(prep, executed),
                **extra_meta,
            },
        )
        self.private_state.save_branch_private_state(
            campaign_id, assistant_msg["id"], user_msg["id"], executed["gm_secrets"], executed["clocks"]
        )
        return user_msg, assistant_msg

    async def _guarded_turn_stream(
        self,
        campaign_id: str,
        user_msg: dict[str, Any],
        prep: dict[str, Any],
        *,
        delete_user_message_on_abort: bool,
        **turn_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        progress: dict[str, Any] = {}
        try:
            async for ev in self._stream_turn_from_user_msg(campaign_id, user_msg, prep, progress=progress, **turn_kwargs):
                yield ev
        except BaseException as exc:
            # Synchronous on purpose: this also runs on client disconnect/cancellation, where awaiting is unreliable.
            self._settle_interrupted_turn(
                campaign_id, user_msg, prep, progress, exc, delete_user_message=delete_user_message_on_abort
            )
            raise

    def _settle_interrupted_turn(
        self,
        campaign_id: str,
        user_msg: dict[str, Any],
        prep: dict[str, Any],
        progress: dict[str, Any],
        exc: BaseException,
        *,
        delete_user_message: bool,
    ) -> None:
        """Leave a visible, undoable record when a turn stops before its GM reply is saved.

        Nothing committed: drop the new user message so the player can resend. State already committed:
        keep the user message and save a reply carrying the executed record (a placeholder when narration
        did not finish) so the changes are visible and a retry re-narrates via regenerate instead of re-planning.
        """
        try:
            if self.tree.has_children(campaign_id, user_msg["id"]):
                return
            executed = progress.get("executed")
            if executed is None or not (executed["rolls"] or executed["patches"] or executed["library_added"]):
                if delete_user_message:
                    self.tree.delete_message(campaign_id, user_msg["id"])
                return
            clean_text = progress.get("clean_text")
            extra_meta: dict[str, Any] = {}
            if clean_text is None:
                extra_meta = {"narration_failed": True, "narration_error": f"{type(exc).__name__}: {exc}"[:500]}
            self._persist_assistant_message(
                campaign_id,
                user_msg,
                prep,
                executed,
                clean_text=_NARRATION_FAILED_TEXT if clean_text is None else clean_text,
                raw_text=progress.get("raw_text") or "",
                mode=progress["mode"],
                is_think=progress["is_think"],
                extra_meta=extra_meta,
            )
        except Exception:
            logger.exception("Could not record interrupted turn %s", prep.get("turn_id"))

    async def compress_memory(self, campaign_id: str, leaf_id: str | None = None) -> dict[str, Any]:
        """Distill branch history into structured Campaign Library dossiers + concise cross-referenced summary."""
        ctx = self.gameplay.campaign_context(campaign_id)
        target_chan = "main"
        if leaf_id:
            leaf_info = self.tree.get_message(campaign_id, leaf_id)
            if leaf_info is not None:
                target_chan = ChatTreeStore._norm_channel(leaf_info.get("channel_id"))
        tree = self.tree.get_tree(campaign_id, channel_id=target_chan)
        target_leaf = leaf_id or tree.get("active_leaf_id")
        branch = self.tree.get_branch_to(campaign_id, target_leaf) if target_leaf else list(tree.get("active_branch") or [])
        secrets, clocks = self.private_state.load_branch_private_state(campaign_id, target_leaf, channel_id=target_chan)
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
            f"Current Campaign State: {json.dumps(_visible_state_for_prompt(ctx['campaign']['state']))}\n"
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

        live_ctx = self.gameplay.campaign_context(campaign_id)
        live_camp = live_ctx["campaign"]
        raw_updates = parsed.get("campaign_updates") if isinstance(parsed.get("campaign_updates"), dict) else {}
        updated_campaign = live_camp
        if raw_updates:
            changes, norm_notes = _normalize_campaign_changes(
                raw_updates,
                live_camp["state"],
                characters=live_ctx["characters"],
                existing_secrets=secrets,
            )
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

        next_secrets = BranchPrivateStateStore.merge_gm_secrets(secrets, parsed.get("gm_secrets"))
        next_clocks, _ = BranchPrivateStateStore.apply_clock_ops(clocks, parsed.get("clock_ops"), allow_secret=True)
        parent_id = None
        if target_leaf:
            leaf_msg = self.tree.get_message(campaign_id, target_leaf)
            parent_id = leaf_msg["parent_id"] if leaf_msg else None
        self.private_state.save_branch_private_state(campaign_id, target_leaf, parent_id, next_secrets, next_clocks)
        if not target_leaf:
            self.private_state.save_branch_private_state(campaign_id, None, None, next_secrets, next_clocks)
        self.private_state.set_compressed_count(campaign_id, target_leaf, len(branch), channel_id=target_chan)
        self.tree.sync_all_active_leaf_revisions(campaign_id)

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
        if parent_id is not None and chan == "main":
            parent_msg = await asyncio.to_thread(self.tree.get_message, campaign_id, parent_id)
            if parent_msg is not None:
                chan = ChatTreeStore._norm_channel(parent_msg.get("channel_id"))
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
            user_msg = await asyncio.to_thread(
                lambda: self.tree.append_message(
                    campaign_id,
                    parent_id=prep["parent_id"],
                    role="user",
                    content=clean_user_text,
                    campaign_revision=pre_ctx["campaign"]["revision"],
                    solo_revision=pre_ctx["solo"]["revision"],
                    channel_id=chan,
                    metadata=meta,
                )
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

        user_msg = await asyncio.to_thread(
            lambda: self.tree.append_message(
                campaign_id,
                parent_id=prep["parent_id"],
                role="user",
                content=clean_user_text,
                campaign_revision=pre_ctx["campaign"]["revision"],
                solo_revision=pre_ctx["solo"]["revision"],
                channel_id=chan,
                metadata=meta,
            )
        )
        yield {"event": "user_message", "data": {"message": user_msg, "channel_id": chan}}
        async for ev in self._guarded_turn_stream(
            campaign_id,
            user_msg,
            prep,
            delete_user_message_on_abort=True,
            overclock=overclock,
            luck_spend=luck_spend,
            active_mode=active_mode,
            speaker=speaker,
            is_intro=is_intro,
            turn_intent=clean_turn_intent,
        ):
            yield ev

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
        """Regenerate the GM reply to a user turn as a sibling branch.

        A turn that already resolved (it has a GM reply, including a failed-narration placeholder) is
        re-narrated from the rolls, patches and outcomes stored on that reply (`message_id` itself when it
        is a GM reply, else the user turn's latest one): no planner, no executor, no state change, and
        `overclock`/`luck_spend` are rejected. A user turn with no GM reply yet (held/deferred) is resolved
        as a normal turn.
        """
        active_mode = mode or self.turn_settings.get("mode") or getattr(getattr(self.llm, "config", None), "mode", "two_pass")
        if active_mode not in {"two_pass", "single_pass_tagged"}:
            raise ValueError(f"Unsupported turn mode: {active_mode!r}")
        target = await asyncio.to_thread(self.tree.get_message, campaign_id, message_id)
        if target is None:
            raise ValueError(f"message not found in campaign: {message_id}")
        if target["role"] == "assistant":
            if not target["parent_id"]:
                raise ValueError("Assistant message has no parent user message")
            user_msg = await asyncio.to_thread(self.tree.get_message, campaign_id, target["parent_id"])
            if user_msg is None or user_msg["role"] != "user":
                raise ValueError("Parent message is not a user turn")
            source: dict[str, Any] | None = target
        elif target["role"] == "user":
            user_msg = target
            children = await asyncio.to_thread(self.tree.get_children, campaign_id, user_msg["id"])
            source = next((c for c in reversed(children) if c["role"] == "assistant"), None)
        else:
            raise ValueError("Only user or assistant messages can be regenerated")

        user_meta = user_msg["metadata"]
        is_intro = bool(user_meta.get("is_intro", False))
        renarrate = source is not None and not is_intro
        if renarrate and (overclock is not None or luck_spend is not None):
            raise ValueError("overclock and luck_spend cannot change when regenerating a resolved turn; its rolls are kept")
        use_overclock = bool(user_meta.get("overclock", False)) if overclock is None else bool(overclock)
        use_luck = int(user_meta.get("luck_spend", 0)) if luck_spend is None else int(luck_spend)
        if use_luck < 0:
            raise ValueError("luck_spend must be a nonnegative integer")

        await asyncio.to_thread(self.tree.switch_branch, campaign_id, user_msg["id"])
        chan = ChatTreeStore._norm_channel(user_msg.get("channel_id"))
        prep = await asyncio.to_thread(
            lambda: self.preprocess(
                campaign_id,
                user_msg["content"],
                parent_id=user_msg["parent_id"],
                branch_from_root=(user_msg["parent_id"] is None),
                turn_id=(source["metadata"].get("turn_id") if renarrate else None),
                channel_id=chan,
            )
        )
        stored_executed: dict[str, Any] | None = None
        if renarrate:
            src_meta = source["metadata"]
            secrets, clocks = await asyncio.to_thread(
                lambda: self.private_state.load_branch_private_state(campaign_id, source["id"], channel_id=chan)
            )
            stored_executed = {
                "rolls": list(src_meta.get("rolls") or []),
                "patches": list(src_meta.get("patches") or []),
                "library_added": [{"id": lib_id} for lib_id in src_meta.get("library_added") or []],
                "warnings": list(src_meta.get("warnings") or []),
                "outcomes": dict(src_meta.get("outcomes") or {}),
                "gm_secrets": secrets,
                "clocks": clocks,
            }
        speaker = self._resolve_speaker(
            prep["context"]["characters"],
            user_meta.get("speaker_character_id"),
            user_meta.get("speaker_name"),
        )
        inherited_intent = str(user_meta.get("turn_intent") or "action").strip().lower()
        if inherited_intent not in {"action", "think"}:
            inherited_intent = "action"
        async for ev in self._guarded_turn_stream(
            campaign_id,
            user_msg,
            prep,
            delete_user_message_on_abort=False,
            overclock=use_overclock,
            luck_spend=use_luck,
            active_mode=active_mode,
            speaker=speaker,
            guidance=guidance,
            is_intro=is_intro,
            turn_intent=inherited_intent,
            stored_executed=stored_executed,
            regenerated_from=source["id"] if renarrate else None,
        ):
            yield ev
