"""Gameplay action dispatch, character/campaign creation, and library routes."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from server.redaction import redact_campaign_context
from server.security import ServerContext


def register_game_routes(app: FastAPI, ctx: ServerContext) -> None:
    """Register /v1/game, /v1/creation/*, and /v1/library* endpoints."""

    @app.post("/v1/game")
    async def game(request: Request):
        request_id = uuid.uuid4().hex
        try:
            blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
            if blocked is not None:
                return blocked
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("action"), str) or not isinstance(body.get("arguments"), dict):
                raise ValueError("Body must contain string action and object arguments")
            action_name = body["action"]
            args_payload = dict(body["arguments"])
            auto_revision = bool(body.get("auto_revision", False))
            sess = ctx.session(request)
            eff_role = ctx.effective_role(request, sess)
            uname = str(sess.get("username") or "").strip()

            admin_campaign_actions = {
                "create_campaign",
                "update_campaign",
                "rename_campaign",
                "start_session",
                "undo_campaign",
                "delete_campaign",
                "set_primary_campaign",
            }
            if action_name in admin_campaign_actions and eff_role == "user":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Admin permission required to create or modify campaigns and sessions.", "request_id": request_id},
                )

            # Automatically stamp owner_username when a signed-in user creates a character
            if uname and action_name == "create_character":
                det = dict(args_payload.get("detail") or {}) if isinstance(args_payload.get("detail"), dict) else {}
                if not det.get("owner_username"):
                    det["owner_username"] = uname
                args_payload["detail"] = det
            elif uname and action_name == "create_player_character":
                inner_args = dict(args_payload.get("arguments") or {}) if isinstance(args_payload.get("arguments"), dict) else {}
                if not inner_args.get("owner_username"):
                    inner_args["owner_username"] = uname
                args_payload["arguments"] = inner_args

            if eff_role == "user" and action_name == "delete_character":
                target_char_id = args_payload.get("character_id")
                if isinstance(target_char_id, str) and target_char_id:
                    existing_char = await asyncio.to_thread(lambda: ctx.gameplay_service().store.get_character(target_char_id))
                    denied = ctx.check_character_ownership(
                        existing_char,
                        eff_role=eff_role,
                        uname=uname,
                        action_name=action_name,
                        request_id=request_id,
                    )
                    if denied is not None:
                        return denied

            char_mutating_actions = {
                "update_character",
                "update_character_profile",
                "undo",
                "skill_check",
                "role_action",
                "gear_action",
                "health_action",
                "economy_action",
            }
            if eff_role == "user" and uname and action_name in char_mutating_actions:
                target_char_id = args_payload.get("character_id")
                if isinstance(target_char_id, str) and target_char_id:
                    existing_char = await asyncio.to_thread(lambda: ctx.gameplay_service().store.get_character(target_char_id))
                    denied = ctx.check_character_ownership(
                        existing_char,
                        eff_role=eff_role,
                        uname=uname,
                        action_name=action_name,
                        request_id=request_id,
                    )
                    if denied is not None:
                        return denied

            read_only_actions = {
                "list_campaigns",
                "get_campaign",
                "campaign_context",
                "campaign_history",
                "get_character",
                "list_characters",
                "history",
                "solo_context",
                "solo_history",
            }

            def _exec_with_optional_auto_rev(camp_id: str | None):
                svc = ctx.gameplay_service()
                if auto_revision:
                    if action_name in {"update_character", "update_character_profile", "undo", "skill_check"}:
                        cid = args_payload.get("character_id")
                        if isinstance(cid, str) and cid:
                            cur_c = svc.store.get_character(cid)
                            if cur_c is not None:
                                args_payload["expected_revision"] = cur_c["revision"]
                    elif action_name in {"update_campaign", "attach_character", "start_session", "undo_campaign"}:
                        target_camp = camp_id or args_payload.get("campaign_id")
                        if isinstance(target_camp, str) and target_camp:
                            cur_camp = svc.memory.get_campaign(target_camp)
                            if cur_camp is not None:
                                args_payload["expected_revision"] = cur_camp["revision"]
                    elif camp_id and "expected_revision" in args_payload:
                        try:
                            cur_solo = svc.solo.context(camp_id)
                            args_payload["expected_revision"] = cur_solo["revision"]
                        except Exception:
                            pass
                before_session_num: int | None = None
                if action_name == "start_session":
                    target_camp_pre = camp_id or args_payload.get("campaign_id")
                    if isinstance(target_camp_pre, str) and target_camp_pre:
                        cur_pre = svc.memory.get_campaign(target_camp_pre)
                        if cur_pre is not None:
                            before_session_num = int(cur_pre.get("session_number") or 0)
                res_out = (
                    svc.execute(action_name, args_payload, campaign_id=camp_id)
                    if camp_id is not None
                    else svc.execute(action_name, args_payload)
                )
                if action_name == "start_session" and isinstance(res_out.get("result"), dict):
                    try:
                        from turnloop import ChatTreeStore
                        camp_obj = res_out["result"]
                        sess_num = int(camp_obj.get("session_number") or 1)
                        target_camp = camp_id or camp_obj.get("id")
                        if target_camp and (before_session_num is None or sess_num > before_session_num):
                            ts = ChatTreeStore(svc)
                            main_tree = ts.get_tree(target_camp, channel_id="main")
                            revs = ts._current_revisions(target_camp)
                            ts.append_message(
                                target_camp,
                                parent_id=main_tree.get("active_leaf_id"),
                                role="system",
                                content=f"Session {sess_num} started — Party LUCK refilled.",
                                campaign_revision=revs["campaign_revision"],
                                solo_revision=revs["solo_revision"],
                                channel_id="main",
                                metadata={"session_started": sess_num},
                            )
                            ts.sync_active_leaf_revisions(target_camp, channel_id="main")
                    except Exception:
                        pass
                if auto_revision and camp_id and action_name not in read_only_actions:
                    try:
                        from turnloop import ChatTreeStore
                        ChatTreeStore(svc).sync_active_leaf_revisions(camp_id)
                    except Exception:
                        pass
                if action_name == "campaign_context" and isinstance(res_out.get("result"), dict):
                    try:
                        from turnloop import (
                            TurnEngine,
                            build_npc_profiles,
                            compute_party_grouping,
                            parse_campaign_meta,
                            parse_session_zero,
                        )
                        ctx_res = res_out["result"]
                        camp_obj = ctx_res.get("campaign") or {}
                        camp_id_ctx = camp_obj.get("id")
                        state_obj = camp_obj.get("state") or {}
                        chars_obj = ctx_res.get("characters") or []
                        eng_ctx = TurnEngine(svc, None)
                        secrets_obj = eng_ctx._get_gm_secrets(camp_id_ctx) if camp_id_ctx else {}
                        include_hidden = ctx.can_view_gm_private_state(request, sess)
                        ctx_res["npc_profiles"] = build_npc_profiles(state_obj, secrets_obj, include_hidden=include_hidden)
                        ctx_res["party_grouping"] = compute_party_grouping(chars_obj, state_obj)
                        ctx_res["campaign_meta"] = parse_campaign_meta(state_obj)
                        ctx_res["session_zero"] = parse_session_zero(state_obj)
                        if camp_id_ctx:
                            ctx_res["clocks"] = (
                                eng_ctx.list_all_clocks(camp_id_ctx)
                                if include_hidden
                                else eng_ctx.list_public_clocks(camp_id_ctx)
                            )
                        if include_hidden:
                            ctx_res["gm_secrets"] = {
                                str(k): str(v)
                                for k, v in secrets_obj.items()
                                if not str(k).startswith("__")
                            }
                        res_out["result"] = redact_campaign_context(ctx_res, is_gm=include_hidden, viewer_username=uname)
                    except Exception:
                        pass
                return res_out

            if "campaign_id" in body:
                if not isinstance(body["campaign_id"], str) or not body["campaign_id"]:
                    raise ValueError("campaign_id must be a nonempty string")
                result = await asyncio.to_thread(lambda: _exec_with_optional_auto_rev(body["campaign_id"]))
                if action_name not in read_only_actions:
                    ctx.coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "game", "action": action_name})
            else:
                result = await asyncio.to_thread(lambda: _exec_with_optional_auto_rev(None))
            return {**result, "request_id": request_id}
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except (sqlite3.Error, OSError) as exc:
            logging.getLogger("uvicorn.error").warning("campaign_unavailable request_id=%s error_type=%s", request_id, type(exc).__name__)
            return JSONResponse(status_code=503, content={"detail": "Campaign operation unavailable.", "request_id": request_id})

    @app.get("/v1/creation/reference")
    def creation_reference(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        from creation_reference import build_creation_reference
        payload = build_creation_reference(ctx.db_path)
        payload["request_id"] = request_id
        return payload

    @app.post("/v1/creation/ai-assist")
    async def creation_ai_assist(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body", "request_id": request_id})
        sess = ctx.session(request)
        eff_role = ctx.effective_role(request, sess)
        try:
            active_llm = ctx.resolve_active_llm(body.get("llm") if isinstance(body, dict) else None, eff_role=eff_role)
        except Exception as exc:
            return JSONResponse(status_code=503, content={"detail": f"LLM settings unavailable: {exc}", "request_id": request_id})
        try:
            from creation_catalog import generate_creation_ai_assist
            result = await generate_creation_ai_assist(
                ctx.db_path,
                active_llm,
                body,
                settings_path=ctx.resolved_settings_path(),
            )
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except Exception as exc:
            return JSONResponse(status_code=502, content={"detail": f"AI narrative assist failed: {exc}", "request_id": request_id})
        return {**result, "request_id": request_id}

    @app.get("/v1/library")
    def library_search(
        request: Request,
        q: str = "",
        category: str | None = None,
        campaign_id: str | None = None,
        include_corebook: bool = True,
        include_homebrew: bool = True,
        limit: int = Query(20, ge=1, le=100),
    ):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        from library import search_library
        try:
            items = search_library(
                ctx.db_path,
                q=q,
                category=category,
                campaign_path=ctx.campaign_db_path() if campaign_id else None,
                campaign_id=campaign_id,
                include_corebook=include_corebook,
                include_homebrew=include_homebrew,
                limit=limit,
            )
            return {"query": q, "category": category, "items": items, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/library/{entry_id:path}")
    def library_entry(request: Request, entry_id: str, campaign_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        from library import get_library_entry
        try:
            item = get_library_entry(
                entry_id,
                rules_path=ctx.db_path,
                campaign_path=ctx.campaign_db_path() if campaign_id else None,
                campaign_id=campaign_id,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        if item is None:
            return JSONResponse(status_code=404, content={"detail": "Library entry not found", "request_id": request_id})
        return {"item": item, "request_id": request_id}

    @app.post("/v1/library/homebrew")
    async def library_add_homebrew(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from library import CampaignLibrary
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"]:
                raise ValueError("campaign_id must be a nonempty string")
            lib = CampaignLibrary(ctx.gameplay_service().store, rules_path=ctx.db_path)
            entry = await asyncio.to_thread(
                lambda: lib.add_entry(
                    body["campaign_id"],
                    name=body.get("name"),
                    category=body.get("category"),
                    operation_id=body.get("operation_id") or f"hb:{uuid.uuid4().hex[:12]}",
                    summary=body.get("summary", ""),
                    description=body.get("description", ""),
                    stats=body.get("stats"),
                    tags=body.get("tags"),
                    created_by=body.get("created_by", "user"),
                    allow_variant=bool(body.get("allow_variant", False)),
                )
            )
            ctx.coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "library"})
            return {"item": entry, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/library/homebrew/{entry_id:path}")
    async def library_delete_homebrew(request: Request, entry_id: str, campaign_id: str):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False)
        if blocked is not None:
            return blocked
        from library import CampaignLibrary
        try:
            lib = CampaignLibrary(ctx.gameplay_service().store, rules_path=ctx.db_path)
            removed = await asyncio.to_thread(lambda: lib.remove_entry(campaign_id, entry_id))
            if not removed:
                return JSONResponse(status_code=404, content={"detail": "Homebrew entry not found", "request_id": request_id})
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "library"})
            return {"deleted": True, "entry_id": entry_id, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
