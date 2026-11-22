"""Chat tree, SSE turn streaming, co-op presence/events, clocks, NPC identity, party location, and campaign bootstrap routes."""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.redaction import redact_chat_tree, redact_sse_event
from server.security import ServerContext

_THINK_CMD_RE = re.compile(r"^/think(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


def _parse_luck_spend(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool):
        raise ValueError("luck_spend must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("luck_spend must be an integer") from exc
    if value < 0:
        raise ValueError("luck_spend must be >= 0")
    return value


def register_chat_routes(app: FastAPI, ctx: ServerContext) -> None:
    """Register chat, turn streaming, co-op SSE/presence, clocks, and campaign routes."""
    from turnloop import load_llm_settings

    def _relay_coop_turn(
        events_iter_fn,
        *,
        campaign_id: str,
        channel_id: str,
        client_id: str,
        speaker_name: str,
        speaker_color: str | None = None,
        speaker_portrait_url: str | None = None,
        user_text: str = "",
        overclock: bool = False,
        truncate_from_id: str | None = None,
        is_gm: bool = True,
        turn_intent: str = "action",
    ):
        async def _wrapped():
            delta_buf: list[str] = []
            last_flush = time.monotonic()
            meta_base: dict[str, Any] = {
                "campaign_id": campaign_id,
                "channel_id": channel_id,
                "client_id": client_id,
                "speaker_name": speaker_name,
                **({"speaker_color": speaker_color} if speaker_color else {}),
                **({"speaker_portrait_url": speaker_portrait_url} if speaker_portrait_url else {}),
                "user_text": user_text,
                "overclock": overclock,
                **({"turn_intent": "think"} if turn_intent == "think" else {}),
                **({"truncate_from_id": truncate_from_id} if truncate_from_id else {}),
            }

            def _flush_deltas():
                nonlocal last_flush
                if not delta_buf:
                    return
                joined = "".join(delta_buf)
                delta_buf.clear()
                last_flush = time.monotonic()
                ctx.coop.publish(
                    campaign_id,
                    "peer_stream",
                    {**meta_base, "event": "text_delta", "data": {"delta": joined}},
                )

            done_emitted = False
            try:
                async for ev in events_iter_fn():
                    ev_name = ev.get("event")
                    ev_data = ev.get("data") or {}
                    if ev_name == "user_message":
                        ctx.coop.publish(
                            campaign_id,
                            "peer_user_message",
                            {
                                "campaign_id": campaign_id,
                                "channel_id": channel_id,
                                "client_id": client_id,
                                "message": ev_data.get("message"),
                            },
                        )
                        ctx.coop.publish(
                            campaign_id,
                            "sync",
                            {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                        )
                        continue
                    if ev_name == "text_delta":
                        piece = str(ev_data.get("delta") or "")
                        if piece:
                            delta_buf.append(piece)
                            now_m = time.monotonic()
                            if sum(len(x) for x in delta_buf) >= 24 or (now_m - last_flush) >= 0.045:
                                _flush_deltas()
                    elif ev_name in {"rule_citation", "dice_roll", "state_patch", "library_added", "warning"}:
                        _flush_deltas()
                        ctx.coop.publish(
                            campaign_id,
                            "peer_stream",
                            {**meta_base, "event": ev_name, "data": ev_data},
                        )
                    elif ev_name == "turn_done":
                        _flush_deltas()
                        done_emitted = True
                        ctx.coop.publish(
                            campaign_id,
                            "peer_turn_done",
                            {
                                "campaign_id": campaign_id,
                                "channel_id": channel_id,
                                "client_id": client_id,
                                **ev_data,
                            },
                        )
                        ctx.coop.publish(
                            campaign_id,
                            "sync",
                            {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                        )
                    yield {"event": ev_name, "data": redact_sse_event(str(ev_name), ev_data, is_gm=is_gm)}
            finally:
                if not done_emitted:
                    _flush_deltas()
                    ctx.coop.publish(
                        campaign_id,
                        "peer_turn_done",
                        {
                            "campaign_id": campaign_id,
                            "channel_id": channel_id,
                            "client_id": client_id,
                            "aborted": True,
                        },
                    )
                    ctx.coop.publish(
                        campaign_id,
                        "sync",
                        {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id},
                    )

        return _wrapped

    @app.get("/v1/chat/tree")
    def chat_tree(request: Request, campaign_id: str, channel_id: str = "main"):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore
        try:
            tree = ChatTreeStore(ctx.gameplay_service()).get_tree(campaign_id, channel_id=channel_id)
            tree = redact_chat_tree(tree, is_gm=is_gm)
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/branch")
    async def chat_branch(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(ctx.gameplay_service()).switch_branch(body["campaign_id"], body["message_id"])
            )
            tree = redact_chat_tree(tree, is_gm=is_gm)
            ctx.coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/delete")
    async def chat_delete(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            scope = body.get("scope", "branch")
            if not isinstance(scope, str) or scope not in {"branch", "single"}:
                raise ValueError("scope must be 'branch' or 'single'")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(ctx.gameplay_service()).delete_message(body["campaign_id"], body["message_id"], scope=scope)
            )
            tree = redact_chat_tree(tree, is_gm=is_gm)
            ctx.coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/message/update")
    async def chat_message_update(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str) or not isinstance(body.get("content"), str):
                raise ValueError("campaign_id, message_id, and content must be strings")
            tree = await asyncio.to_thread(
                lambda: ChatTreeStore(ctx.gameplay_service()).update_message(body["campaign_id"], body["message_id"], body["content"])
            )
            tree = redact_chat_tree(tree, is_gm=is_gm)
            ctx.coop.publish(body["campaign_id"], "sync", {"campaign_id": body["campaign_id"], "kind": "chat"})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/chat/export")
    def chat_export(request: Request, campaign_id: str, leaf_id: str | None = None, channel_id: str = "main"):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        if ctx.effective_role(request, sess) == "user" and not sess.get("pin_only_mode"):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to export story logs.", "request_id": request_id})
        from turnloop import ChatTreeStore
        try:
            exported = ChatTreeStore(ctx.gameplay_service()).export_branch(campaign_id, leaf_id, channel_id=channel_id)
            return {**exported, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/presence")
    async def campaign_presence(request: Request, campaign_id: str):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        try:
            await asyncio.to_thread(lambda: ctx.gameplay_service().campaign_context(campaign_id))
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Body must be a JSON object")
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or "").strip()
            if not client_id:
                raise ValueError("client_id must be a nonempty string")
            player_name = str(body.get("player_name") or "Player").strip()
            character_id = body.get("character_id") if isinstance(body.get("character_id"), str) and body["character_id"].strip() else None
            is_host = bool(body.get("is_host", False))
            roster = ctx.coop.update_presence(
                campaign_id,
                client_id=client_id,
                player_name=player_name,
                character_id=character_id,
                is_host=is_host,
            )
            turns = ctx.coop.all_active_turns(campaign_id)
            return {
                "players": roster,
                "active_turn": turns.get("main") or next(iter(turns.values()), None),
                "active_turns": turns,
                "sync_seq": ctx.coop.current_seq(campaign_id),
                "request_id": request_id,
            }
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/campaigns/{campaign_id}/events")
    async def campaign_events(request: Request, campaign_id: str):
        request_id = uuid.uuid4().hex
        sess = ctx.session(request)
        if sess["role"] != "open" and not sess["authenticated"]:
            if sess["pin_only_mode"]:
                return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
            return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
        try:
            await asyncio.to_thread(lambda: ctx.gameplay_service().campaign_context(campaign_id))
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        from starlette.responses import StreamingResponse
        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        subs = ctx.coop.subscribers.setdefault(campaign_id, set())
        subs.add(q)

        async def room_stream():
            try:
                turns = ctx.coop.all_active_turns(campaign_id)
                init_payload = json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "players": ctx.coop.roster(campaign_id),
                        "active_turn": turns.get("main") or next(iter(turns.values()), None),
                        "active_turns": turns,
                        "sync_seq": ctx.coop.current_seq(campaign_id),
                    },
                    ensure_ascii=False,
                )
                yield f"event: presence\ndata: {init_payload}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=12.0)
                        payload = json.dumps(msg["data"], ensure_ascii=False)
                        yield f"event: {msg['event']}\ndata: {payload}\n\n"
                    except asyncio.TimeoutError:
                        ping_payload = json.dumps({"ts": time.time(), "sync_seq": ctx.coop.current_seq(campaign_id)})
                        yield f"event: ping\ndata: {ping_payload}\n\n"
            finally:
                subs.discard(q)

        return StreamingResponse(
            room_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/v1/chat/turn")
    async def chat_turn(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore, TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("user_text"), str):
                raise ValueError("campaign_id and user_text must be strings")
            campaign_id = body["campaign_id"]
            raw_intent = body.get("turn_intent")
            if raw_intent is None:
                turn_intent = "action"
            elif isinstance(raw_intent, str) and raw_intent.strip().lower() in {"action", "think"}:
                turn_intent = raw_intent.strip().lower()
            else:
                raise ValueError("turn_intent must be 'action' or 'think'")
            stripped_user = body["user_text"].strip()
            think_match = _THINK_CMD_RE.match(stripped_user)
            if think_match:
                turn_intent = "think"
                user_text = (think_match.group(1) or "").strip()
            else:
                user_text = stripped_user
            if turn_intent == "think" and not user_text:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Enter a thought or observation question after /think.", "request_id": request_id},
                )
            if not user_text:
                raise ValueError("user_text must be nonempty")
            channel_id = ChatTreeStore._norm_channel(body.get("channel_id"))
            luck_spend = _parse_luck_spend(body.get("luck_spend"))
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or request_id)
            player_name = str(body.get("player_name") or body.get("speaker_name") or "Player")
            gm_mode = str(body.get("gm_mode") or "auto").strip().lower()
            if gm_mode not in {"auto", "force_gm", "hold_gm"}:
                raise ValueError("gm_mode must be 'auto', 'force_gm', or 'hold_gm'")
            is_intro = bool(body.get("is_intro", False))
            sess = ctx.session(request)
            eff_role = ctx.effective_role(request, sess)
            is_gm = ctx.can_view_gm_private_state(request, sess)
            uname = str(sess.get("username") or "").strip()
            llm_cfg = load_llm_settings(ctx.resolved_settings_path())

            active_llm = ctx.resolve_active_llm(body.get("llm_config"), eff_role=eff_role)
            engine = TurnEngine(ctx.gameplay_service(), active_llm, settings_path=ctx.resolved_settings_path())
            ctx_camp = await asyncio.to_thread(engine.gameplay.campaign_context, campaign_id)
            chars = ctx_camp.get("characters") or []
            speaker_char_id = body.get("speaker_character_id")
            speaker_info = engine._resolve_speaker(chars, speaker_char_id, body.get("speaker_name"))

            denied = ctx.check_speaking_character(
                chars,
                speaker_char_id=speaker_char_id,
                eff_role=eff_role,
                uname=uname,
                is_intro=is_intro,
                pin_only_mode=bool(sess.get("pin_only_mode")),
                require_character_to_speak=bool(llm_cfg.get("require_character_to_speak", True)),
                request_id=request_id,
            )
            if denied is not None:
                return denied

            if body.get("parent_id") is not None:
                await asyncio.to_thread(engine.tree.get_branch_to, campaign_id, body["parent_id"])
            acquire_lock = gm_mode != "hold_gm" or turn_intent == "think"
            if acquire_lock:
                busy_turn = ctx.coop.acquire_turn(campaign_id, client_id=client_id, player_name=player_name, channel_id=channel_id)
                if busy_turn is not None:
                    return JSONResponse(status_code=409, content={"detail": f"GM is currently resolving {busy_turn['player_name']}'s turn", "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        coop_count = max(1, len(ctx.coop.roster(campaign_id)))

        def finish_turn():
            if acquire_lock:
                ctx.coop.release_turn(campaign_id, client_id, channel_id=channel_id)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": channel_id})

        relayed = _relay_coop_turn(
            lambda: engine.run_turn(
                campaign_id,
                user_text,
                parent_id=body.get("parent_id"),
                branch_from_root=bool(body.get("branch_from_root", False)),
                overclock=bool(body.get("overclock", False)),
                luck_spend=luck_spend,
                mode=body.get("mode"),
                speaker_character_id=body.get("speaker_character_id"),
                speaker_name=body.get("speaker_name"),
                is_intro=is_intro,
                gm_mode=gm_mode,
                coop_player_count=coop_count,
                channel_id=channel_id,
                turn_intent=turn_intent,
            ),
            campaign_id=campaign_id,
            channel_id=channel_id,
            client_id=client_id,
            speaker_name=speaker_info.get("name") or player_name,
            speaker_color=speaker_info.get("color"),
            speaker_portrait_url=speaker_info.get("portrait_url"),
            user_text=user_text,
            overclock=bool(body.get("overclock", False)),
            truncate_from_id=str(body["replace_message_id"]).strip() if body.get("replace_message_id") else None,
            is_gm=is_gm,
            turn_intent=turn_intent,
        )
        return ctx.sse_response(
            relayed,
            request_id,
            on_finish=finish_turn,
        )

    @app.post("/v1/chat/roll")
    async def chat_manual_roll(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("character_id"), str):
                raise ValueError("campaign_id and character_id are required")
            campaign_id = body["campaign_id"].strip()
            character_id = body["character_id"].strip()
            stat = str(body.get("stat") or "REF").strip().upper()
            skill = str(body.get("skill") or "").strip() or None
            dv = int(body.get("dv", 13))
            modifier = int(body.get("modifier", 0))
            luck = _parse_luck_spend(body.get("luck", 0))
            reason = str(body.get("reason") or "Manual skill roll").strip() or "Manual skill roll"

            sess = ctx.session(request)
            eff_role = ctx.effective_role(request, sess)
            is_gm = ctx.can_view_gm_private_state(request, sess)
            uname = str(sess.get("username") or "").strip()

            def _do_roll():
                svc = ctx.gameplay_service()
                char = svc.store.get_character(character_id)
                if char is None:
                    raise ValueError("Character not found")
                d = char.get("detail") or {}
                owner = str(d.get("owner_username") or "").strip()
                if eff_role == "user" and uname and owner and owner.lower() != uname.lower():
                    raise PermissionError(f"You cannot roll for {char.get('name')} (owned by {owner}).")
                check_res = svc.execute(
                    "skill_check",
                    {
                        "character_id": character_id,
                        "expected_revision": char["revision"],
                        "stat": stat,
                        "skill": skill,
                        "dv": dv,
                        "modifier": modifier,
                        "luck": luck,
                        "reason": reason,
                        "operation_id": f"mroll-{uuid.uuid4().hex[:12]}",
                    },
                    campaign_id=campaign_id,
                )["result"]
                speaker_label = str(d.get("handle") or char["name"])
                roll_card = {
                    "actor": speaker_label,
                    "character_id": character_id,
                    "stat": stat,
                    "skill": skill,
                    "dv": dv,
                    "modifier": modifier,
                    "luck_spent": luck,
                    "reason": reason,
                    "total": check_res["total"],
                    "die": check_res.get("die"),
                    "dice": check_res.get("dice"),
                    "base": check_res.get("base"),
                    "explosion": check_res.get("explosion", 0),
                    "wound_modifier": check_res.get("wound_modifier", 0),
                    "success": check_res["success"],
                }
                channel_id = ChatTreeStore._norm_channel(body.get("channel_id"))
                tree_store = ChatTreeStore(svc)
                cur_tree = tree_store.get_tree(campaign_id, channel_id=channel_id)
                revs = tree_store._current_revisions(campaign_id)
                verdict = "SUCCESS" if check_res["success"] else "FAIL"
                skill_label = f"{skill} ({stat})" if skill else stat
                msg_text = f"Rolled **{skill_label}** vs DV {dv} — **{check_res['total']}** ({verdict}) · *{reason}*"
                meta: dict[str, Any] = {
                    "speaker_character_id": character_id,
                    "speaker_name": speaker_label,
                    "channel_id": channel_id,
                    "manual_roll": True,
                    "gm_deferred": True,
                    "defer_reason": "Manual skill roll posted to table",
                    "rolls": [roll_card],
                }
                if isinstance(d.get("color"), str) and d["color"].strip():
                    meta["speaker_color"] = d["color"].strip()
                if isinstance(d.get("portrait_url"), str) and d["portrait_url"].strip():
                    meta["speaker_portrait_url"] = d["portrait_url"].strip()
                msg = tree_store.append_message(
                    campaign_id,
                    parent_id=cur_tree.get("active_leaf_id"),
                    role="user",
                    content=msg_text,
                    campaign_revision=revs["campaign_revision"],
                    solo_revision=revs["solo_revision"],
                    channel_id=channel_id,
                    metadata=meta,
                )
                updated_tree = redact_chat_tree(tree_store.sync_active_leaf_revisions(campaign_id, channel_id=channel_id), is_gm=is_gm)
                return {"roll": roll_card, "result": check_res, "message": msg, "tree": updated_tree}

            out = await asyncio.to_thread(_do_roll)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat"})
            return {**out, "request_id": request_id}
        except PermissionError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc), "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/sync-revisions")
    async def chat_sync_revisions(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"].strip():
                raise ValueError("campaign_id is required")
            campaign_id = body["campaign_id"].strip()
            chan = ChatTreeStore._norm_channel(body.get("channel_id"))
            tree = await asyncio.to_thread(lambda: ChatTreeStore(ctx.gameplay_service()).sync_active_leaf_revisions(campaign_id, channel_id=chan))
            tree = redact_chat_tree(tree, is_gm=is_gm)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": chan})
            return {**tree, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/chat/regenerate")
    async def chat_regenerate(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        eff_role = ctx.effective_role(request, sess)
        is_gm = ctx.can_view_gm_private_state(request, sess)
        from turnloop import ChatTreeStore, TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not isinstance(body.get("message_id"), str):
                raise ValueError("campaign_id and message_id must be strings")
            campaign_id = body["campaign_id"]
            message_id = body["message_id"]
            client_id = str(body.get("client_id") or request.headers.get("x-redgm-client-id") or request_id)
            player_name = str(body.get("player_name") or "Player")
            active_llm = ctx.resolve_active_llm(body.get("llm_config"), eff_role=eff_role)
            engine = TurnEngine(ctx.gameplay_service(), active_llm, settings_path=ctx.resolved_settings_path())
            await asyncio.to_thread(engine.gameplay.campaign_context, campaign_id)
            target = await asyncio.to_thread(engine.tree.get_message, campaign_id, message_id)
            if target is None:
                raise ValueError(f"message not found in campaign: {message_id}")
            target_channel = ChatTreeStore._norm_channel(target.get("channel_id"))
            regen_luck = (
                _parse_luck_spend(body["luck_spend"])
                if "luck_spend" in body and body["luck_spend"] is not None
                else None
            )
            busy_turn = ctx.coop.acquire_turn(campaign_id, client_id=client_id, player_name=player_name, channel_id=target_channel)
            if busy_turn is not None:
                return JSONResponse(status_code=409, content={"detail": f"GM is currently resolving {busy_turn['player_name']}'s turn", "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        def finish_regen():
            ctx.coop.release_turn(campaign_id, client_id, channel_id=target_channel)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "chat", "channel_id": target_channel})

        relayed_regen = _relay_coop_turn(
            lambda: engine.regenerate_turn(
                campaign_id,
                message_id,
                overclock=body["overclock"] if "overclock" in body and body["overclock"] is not None else None,
                luck_spend=regen_luck,
                mode=body.get("mode"),
                guidance=body.get("guidance"),
            ),
            campaign_id=campaign_id,
            channel_id=target_channel,
            client_id=client_id,
            speaker_name=str((target.get("metadata") or {}).get("speaker_name") or player_name),
            speaker_color=(target.get("metadata") or {}).get("speaker_color"),
            speaker_portrait_url=(target.get("metadata") or {}).get("speaker_portrait_url"),
            user_text=str(target.get("content") or ""),
            truncate_from_id=message_id if target.get("role") == "assistant" else None,
            is_gm=is_gm,
            turn_intent=str((target.get("metadata") or {}).get("turn_intent") or "action"),
        )
        return ctx.sse_response(
            relayed_regen,
            request_id,
            on_finish=finish_regen,
        )

    @app.post("/v1/chat/compress")
    async def chat_compress(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        eff_role = ctx.effective_role(request, sess)
        from turnloop import TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("campaign_id"), str) or not body["campaign_id"].strip():
                raise ValueError("campaign_id is required")
            campaign_id = body["campaign_id"]
            leaf_id = body.get("leaf_id")
            active_llm = ctx.resolve_active_llm(body.get("llm_config"), eff_role=eff_role)
            engine = TurnEngine(ctx.gameplay_service(), active_llm, settings_path=ctx.resolved_settings_path())
            result = await engine.compress_memory(campaign_id, leaf_id=leaf_id)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "library"})
            return {**result, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/campaigns/{campaign_id}/clocks")
    def campaign_clocks_list(campaign_id: str, request: Request, leaf_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        from turnloop import TurnEngine
        try:
            clocks = TurnEngine(ctx.gameplay_service(), None, settings_path=ctx.resolved_settings_path()).list_public_clocks(campaign_id, leaf_id=leaf_id)
            return {"campaign_id": campaign_id, "clocks": clocks, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/clocks")
    async def campaign_clocks_mutate(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        if not ctx.is_admin_or_pin_only(request, sess):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to modify world clocks.", "request_id": request_id})
        from turnloop import TurnEngine
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            clocks = TurnEngine(ctx.gameplay_service(), None).mutate_public_clock(
                campaign_id,
                body,
                leaf_id=body.get("leaf_id"),
            )
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {"campaign_id": campaign_id, "clocks": clocks, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/npc-identity")
    async def campaign_npc_identity(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        from turnloop import TurnEngine, _normalize_campaign_changes, build_npc_profiles
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            handle = str(body.get("handle") or "").strip()[:100]
            if not handle:
                raise ValueError("handle is required")
            delete_npc = bool(body.get("delete", False))
            description = str(body.get("description") or "").strip()[:2000]
            real_name = str(body.get("real_name") or "").strip()[:100] if isinstance(body.get("real_name"), str) else ""
            real_name_hidden = bool(body.get("real_name_hidden", True))

            def _apply():
                svc = ctx.gameplay_service()
                camp_ctx = svc.campaign_context(campaign_id)
                camp = camp_ctx["campaign"]
                eng = TurnEngine(svc, None)
                existing_sec = eng._get_gm_secrets(campaign_id)
                sec_key = f"__npc_real:{handle}"
                effective_real_name = real_name or str(existing_sec.get(sec_key) or "").strip()
                raw_changes: dict[str, Any] = {}
                if delete_npc:
                    raw_changes["npcs"] = {handle: None}
                    raw_changes["npc_identities"] = {handle: None}
                else:
                    if description:
                        raw_changes["npcs"] = {handle: description}
                    raw_changes["npc_identities"] = {
                        handle: {
                            "real_name": effective_real_name,
                            "real_name_hidden": real_name_hidden,
                        }
                    }
                changes, _ = _normalize_campaign_changes(
                    raw_changes,
                    camp["state"],
                    characters=camp_ctx["characters"],
                    existing_secrets=existing_sec,
                )
                if changes:
                    svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": f"Update NPC identity: {handle}",
                            "operation_id": f"npcid-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )
                if delete_npc or not real_name_hidden or not effective_real_name:
                    eng.update_gm_secrets(campaign_id, {sec_key: None})
                else:
                    eng.update_gm_secrets(campaign_id, {sec_key: effective_real_name})
                eng.tree.sync_active_leaf_revisions(campaign_id)
                fresh_ctx = svc.campaign_context(campaign_id)
                fresh_sec = eng._get_gm_secrets(campaign_id)
                profiles = build_npc_profiles(
                    fresh_ctx["campaign"]["state"],
                    fresh_sec,
                    include_hidden=ctx.can_view_gm_private_state(request, sess),
                )
                return {"campaign": fresh_ctx["campaign"], "npc_profiles": profiles}

            res = await asyncio.to_thread(_apply)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {**res, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/party-location")
    async def campaign_party_location(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        eff_role = ctx.effective_role(request, sess)
        uname = str(sess.get("username") or "").strip().lower()
        from turnloop import ChatTreeStore, _normalize_campaign_changes, _resolve_character, compute_party_grouping
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            action = str(body.get("action") or "update").strip().lower()
            pc_locations = body.get("pc_locations") if isinstance(body.get("pc_locations"), dict) else None
            location = str(body.get("location") or "").strip()[:160]
            append_notice = bool(body.get("append_notice", True))

            def _apply():
                svc = ctx.gameplay_service()
                camp_ctx = svc.campaign_context(campaign_id)
                camp = camp_ctx["campaign"]
                chars = camp_ctx["characters"]
                if eff_role == "user" and not sess.get("pin_only_mode"):
                    if action == "reunite":
                        raise PermissionError("Only the GM/Admin can reunite all party members at once.")
                    if isinstance(pc_locations, dict):
                        for raw_actor in pc_locations.keys():
                            matched = _resolve_character(str(raw_actor), chars)
                            if matched is None:
                                raise PermissionError(f"Unknown character '{raw_actor}'.")
                            owner = str((matched.get("detail") or {}).get("owner_username") or "").strip().lower()
                            if not uname or (owner and owner != uname):
                                raise PermissionError(f"You can only update your own character's location (not {matched.get('name')}).")
                before_grouping = compute_party_grouping(chars, camp["state"])
                raw_changes: dict[str, Any] = {}
                if action == "reunite":
                    target_loc = location or str(camp["state"].get("scene") or "").strip() or "Main Scene"
                    raw_changes["all_together"] = target_loc
                    if location:
                        raw_changes["scene"] = target_loc
                elif pc_locations:
                    raw_changes["pc_locations"] = pc_locations
                else:
                    raise ValueError("Provide pc_locations or action='reunite'")
                changes, _ = _normalize_campaign_changes(raw_changes, camp["state"], characters=chars)
                updated_camp = camp
                if changes:
                    updated_camp = svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": "Update party locations / grouping",
                            "operation_id": f"ploc-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                after_grouping = compute_party_grouping(chars, updated_camp["state"])
                tree_store = ChatTreeStore(svc)
                if append_notice and before_grouping["mode"] != after_grouping["mode"]:
                    main_tree = tree_store.get_tree(campaign_id, channel_id="main")
                    revs = tree_store._current_revisions(campaign_id)
                    if after_grouping["mode"] == "split":
                        parts = [f"{', '.join(ch['handles'])} -> {ch['location']}" for ch in after_grouping["channels"]]
                        notice = f"*Party split into separate scene channels: {'; '.join(parts)}.*"
                    else:
                        notice = f"*Party reunited at {after_grouping['active_location']} (Main Table).* "
                    tree_store.append_message(
                        campaign_id,
                        parent_id=main_tree.get("active_leaf_id"),
                        role="system",
                        content=notice.strip(),
                        campaign_revision=revs["campaign_revision"],
                        solo_revision=revs["solo_revision"],
                        channel_id="main",
                        metadata={"party_transition": after_grouping["mode"]},
                    )
                tree_store.sync_active_leaf_revisions(campaign_id, channel_id="main")
                return {"campaign": updated_camp, "party_grouping": after_grouping}

            res = await asyncio.to_thread(_apply)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "all"})
            return {**res, "request_id": request_id}
        except PermissionError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc), "request_id": request_id})
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/bootstrap")
    async def campaign_bootstrap(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        if not ctx.is_admin_or_pin_only(request, sess):
            return JSONResponse(status_code=403, content={"detail": "Admin permission required to modify campaign setup.", "request_id": request_id})
        from library import CampaignLibrary
        from turnloop import (
            TurnEngine,
            _encode_npc_identities_json,
            encode_campaign_meta_json,
            encode_session_zero_json,
            parse_campaign_meta,
            parse_npc_identities_public,
            parse_session_zero,
        )
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")

            def _apply():
                svc = ctx.gameplay_service()
                camp_ctx = svc.campaign_context(campaign_id)
                camp = camp_ctx["campaign"]
                new_name = body.get("name")
                if isinstance(new_name, str) and new_name.strip() and new_name.strip() != camp["name"]:
                    camp = svc.execute(
                        "rename_campaign",
                        {
                            "campaign_id": campaign_id,
                            "name": new_name.strip(),
                            "expected_revision": camp["revision"],
                            "reason": "Rename campaign",
                            "operation_id": f"camp-rename-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )["result"]
                clear_missing = bool(body.get("clear_missing", False))
                cur_state = dict(camp.get("state") or {})
                cur_disc = dict(cur_state.get("discoveries") or {})
                internal_disc = {k: v for k, v in cur_disc.items() if str(k).startswith("__")}
                changes: dict[str, Any] = {}
                for field in ("scene", "summary"):
                    if field in body:
                        val = body.get(field)
                        if isinstance(val, str) and val.strip():
                            changes[field] = val.strip()
                        elif clear_missing and isinstance(val, str):
                            changes[field] = ""
                for map_field in ("npcs", "objectives", "discoveries", "unresolved"):
                    if map_field not in body:
                        continue
                    val = body.get(map_field)
                    if isinstance(val, dict):
                        cleaned = {
                            str(k).strip(): str(v).strip()
                            for k, v in val.items()
                            if str(k).strip() and str(v).strip() and not (map_field == "discoveries" and str(k).strip().startswith("__"))
                        }
                        if map_field == "discoveries":
                            if cleaned or clear_missing:
                                changes[map_field] = {**internal_disc, **cleaned}
                        elif cleaned or clear_missing:
                            changes[map_field] = cleaned
                has_meta_input = any(
                    k in body
                    for k in ("district", "zone_type", "threat_rating", "caper_style", "factions", "screamsheet_hook", "campaign_meta", "world_entities")
                )
                if has_meta_input:
                    merged_meta = {} if clear_missing else dict(parse_campaign_meta(cur_state))
                    if isinstance(body.get("campaign_meta"), dict):
                        merged_meta.update(body["campaign_meta"])
                    for mk in ("district", "zone_type", "threat_rating", "caper_style", "screamsheet_hook"):
                        if mk in body:
                            mv = str(body.get(mk) or "").strip()
                            if mv:
                                merged_meta[mk] = mv
                            else:
                                merged_meta.pop(mk, None)
                    if "factions" in body and isinstance(body["factions"], list):
                        merged_meta["factions"] = [str(f).strip() for f in body["factions"] if str(f).strip()]
                    we = body.get("world_entities")
                    if isinstance(we, dict):
                        if "factions" in we and isinstance(we.get("factions"), list):
                            fds = [f for f in we["factions"] if isinstance(f, dict) and str(f.get("name") or "").strip()]
                            if fds:
                                merged_meta["faction_details"] = fds
                            else:
                                merged_meta.pop("faction_details", None)
                        if "locations" in we and isinstance(we.get("locations"), list):
                            locs = [l for l in we["locations"] if isinstance(l, dict) and str(l.get("name") or "").strip()]
                            if locs:
                                merged_meta["locations"] = locs
                            else:
                                merged_meta.pop("locations", None)
                        if "gig" in we:
                            if isinstance(we.get("gig"), dict) and any(str(we["gig"].get(k) or "").strip() for k in ("title", "client", "target", "notes")):
                                merged_meta["gig"] = dict(we["gig"])
                            else:
                                merged_meta.pop("gig", None)
                    base_disc = dict(changes.get("discoveries") if "discoveries" in changes else cur_disc)
                    base_disc["__campaign_meta"] = encode_campaign_meta_json(merged_meta)
                    changes["discoveries"] = base_disc

                if isinstance(body.get("session_zero"), dict) or "starting_clock_minutes" in body:
                    merged_sz = dict(parse_session_zero(cur_state))
                    if isinstance(body.get("session_zero"), dict):
                        merged_sz.update(body["session_zero"])
                    if isinstance(body.get("starting_clock_minutes"), int) and body["starting_clock_minutes"] >= 0:
                        merged_sz["starting_clock_minutes"] = int(body["starting_clock_minutes"])
                    base_disc = dict(changes.get("discoveries") if "discoveries" in changes else cur_disc)
                    base_disc["__session_zero"] = encode_session_zero_json(merged_sz)
                    changes["discoveries"] = base_disc

                eng = TurnEngine(svc, None)
                npc_secret_updates: dict[str, str | None] = {}
                npc_ids_in = body.get("npc_identities")
                existing_sec = eng._get_gm_secrets(campaign_id)
                cur_ids_prev = parse_npc_identities_public(cur_state)
                if isinstance(npc_ids_in, dict):
                    cur_ids = {} if clear_missing else dict(cur_ids_prev)
                    for raw_handle, spec in npc_ids_in.items():
                        if not isinstance(raw_handle, str) or not raw_handle.strip() or not isinstance(spec, dict):
                            continue
                        handle = raw_handle.strip()
                        entry: dict[str, Any] = {
                            "handle": str(spec.get("handle") or handle).strip() or handle,
                            "real_name_hidden": bool(spec.get("real_name_hidden", False)),
                        }
                        if isinstance(spec.get("personality"), str) and spec["personality"].strip():
                            entry["personality"] = spec["personality"].strip()[:240]
                        if isinstance(spec.get("speech_style"), str) and spec["speech_style"].strip():
                            entry["speech_style"] = spec["speech_style"].strip()[:160]
                        real_name = str(spec.get("real_name") or "").strip()
                        if not real_name and not entry["real_name_hidden"]:
                            real_name = str(existing_sec.get(f"__npc_real:{handle}") or cur_ids_prev.get(handle, {}).get("real_name") or "").strip()
                        if real_name:
                            if entry["real_name_hidden"]:
                                npc_secret_updates[f"__npc_real:{handle}"] = real_name
                            else:
                                entry["real_name"] = real_name
                                npc_secret_updates[f"__npc_real:{handle}"] = None
                        elif not entry["real_name_hidden"]:
                            npc_secret_updates[f"__npc_real:{handle}"] = None
                        cur_ids[handle] = entry
                    if clear_missing:
                        for sec_k in list(existing_sec):
                            if str(sec_k).startswith("__npc_real:"):
                                sec_handle = str(sec_k)[len("__npc_real:"):]
                                if sec_handle not in cur_ids:
                                    npc_secret_updates[str(sec_k)] = None
                    base_disc = dict(changes.get("discoveries") if "discoveries" in changes else cur_disc)
                    base_disc["__npc_identities"] = _encode_npc_identities_json(cur_ids)
                    changes["discoveries"] = base_disc

                if changes:
                    camp = svc.execute(
                        "update_campaign",
                        {
                            "campaign_id": campaign_id,
                            "expected_revision": camp["revision"],
                            "changes": changes,
                            "reason": "Initialize campaign world & premise",
                            "operation_id": f"camp-boot-{uuid.uuid4().hex[:12]}",
                        },
                        campaign_id=campaign_id,
                    )["result"]

                start_mins = body.get("starting_clock_minutes")
                if type(start_mins) is int and start_mins >= 0:
                    svc.solo.set_initial_clock_minutes(campaign_id, start_mins)

                attach_ids = body.get("attach_character_ids")
                if isinstance(attach_ids, list):
                    existing_members = set(camp.get("character_ids") or [])
                    for raw_cid in attach_ids:
                        cid = str(raw_cid or "").strip()
                        if not cid or cid in existing_members:
                            continue
                        camp = svc.execute(
                            "attach_character",
                            {
                                "campaign_id": campaign_id,
                                "character_id": cid,
                                "expected_revision": camp["revision"],
                                "reason": "Attach starting party character",
                                "operation_id": f"camp-attach-{uuid.uuid4().hex[:12]}",
                            },
                            campaign_id=campaign_id,
                        )["result"]
                        existing_members.add(cid)

                we_in = body.get("world_entities")
                seeded_library: list[dict[str, Any]] = []
                if isinstance(we_in, dict):
                    lib = CampaignLibrary(svc.store, rules_path=ctx.db_path)
                    for fac in we_in.get("factions") or []:
                        if not isinstance(fac, dict) or not str(fac.get("name") or "").strip():
                            continue
                        fname = str(fac["name"]).strip()
                        disp = str(fac.get("disposition") or "Neutral").strip()
                        turf = str(fac.get("turf") or "").strip()
                        notes = str(fac.get("notes") or "").strip()
                        summary_txt = f"{disp}" + (f" · {turf}" if turf else "")
                        seeded_library.append(
                            lib.upsert_entry(
                                campaign_id,
                                name=fname,
                                category="faction",
                                operation_id=f"boot-fac-{uuid.uuid4().hex[:12]}",
                                summary=summary_txt[:240],
                                description=notes or summary_txt,
                                stats={"disposition": disp, **({"turf": turf} if turf else {})},
                                tags=["faction", disp.lower()],
                                created_by="user",
                                allow_variant=True,
                            )
                        )
                    for loc in we_in.get("locations") or []:
                        if not isinstance(loc, dict) or not str(loc.get("name") or "").strip():
                            continue
                        lname = str(loc["name"]).strip()
                        ldist = str(loc.get("district") or body.get("district") or "").strip()
                        lsec = str(loc.get("security") or "").strip()
                        lnotes = str(loc.get("notes") or "").strip()
                        lsum = " · ".join(p for p in (ldist, lsec) if p) or "Campaign location"
                        seeded_library.append(
                            lib.upsert_entry(
                                campaign_id,
                                name=lname,
                                category="location",
                                operation_id=f"boot-loc-{uuid.uuid4().hex[:12]}",
                                summary=lsum[:240],
                                description=lnotes or lsum,
                                stats={**({"district": ldist} if ldist else {}), **({"security": lsec} if lsec else {})},
                                tags=["location"],
                                created_by="user",
                                allow_variant=True,
                            )
                        )
                    gig = we_in.get("gig")
                    if isinstance(gig, dict) and any(str(gig.get(k) or "").strip() for k in ("title", "client", "target", "notes")):
                        gtitle = str(gig.get("title") or "Opening Contract").strip()
                        gclient = str(gig.get("client") or "").strip()
                        gtarget = str(gig.get("target") or "").strip()
                        gdeadline = str(gig.get("deadline") or "").strip()
                        gpayout = int(gig["payout_eb"]) if isinstance(gig.get("payout_eb"), (int, float)) and gig["payout_eb"] >= 0 else 0
                        gnotes = str(gig.get("notes") or "").strip()
                        gsum = f"Client: {gclient or 'Fixer'} · Target: {gtarget or 'TBD'}" + (f" · {gpayout} eb" if gpayout else "")
                        seeded_library.append(
                            lib.upsert_entry(
                                campaign_id,
                                name=gtitle,
                                category="encounter",
                                operation_id=f"boot-gig-{uuid.uuid4().hex[:12]}",
                                summary=gsum[:240],
                                description=gnotes or gsum,
                                stats={
                                    **({"client": gclient} if gclient else {}),
                                    **({"target": gtarget} if gtarget else {}),
                                    **({"payout_eb": gpayout} if gpayout else {}),
                                    **({"deadline": gdeadline} if gdeadline else {}),
                                },
                                tags=["gig", "contract"],
                                created_by="user",
                                allow_variant=True,
                            )
                        )
                    sheet = we_in.get("screamsheet")
                    if isinstance(sheet, dict) and str(sheet.get("headline") or "").strip():
                        headline = str(sheet["headline"]).strip()
                        sbody = str(sheet.get("body") or "").strip()
                        seeded_library.append(
                            lib.upsert_entry(
                                campaign_id,
                                name=headline,
                                category="screamsheet",
                                operation_id=f"boot-sheet-{uuid.uuid4().hex[:12]}",
                                summary=(sbody or headline)[:240],
                                description=sbody or headline,
                                stats={"headline": headline},
                                tags=["screamsheet", "n54"],
                                created_by="user",
                                allow_variant=True,
                            )
                        )

                secrets_in = body.get("gm_secrets")
                secrets_map: dict[str, str | None] = dict(npc_secret_updates)
                has_secrets_payload = "gm_secrets" in body or bool(npc_secret_updates)
                if isinstance(secrets_in, str) and secrets_in.strip():
                    secrets_map["Premise Secret"] = secrets_in.strip()
                elif isinstance(secrets_in, dict):
                    for k, v in secrets_in.items():
                        if str(k).strip() and str(v).strip() and not str(k).strip().startswith("__"):
                            secrets_map[str(k).strip()] = str(v).strip()
                opening_clock = body.get("opening_clock") if isinstance(body.get("opening_clock"), dict) else None
                clocks_in = body.get("clocks") if isinstance(body.get("clocks"), list) else None
                gm_seed = eng.seed_initial_gm_state(
                    campaign_id,
                    secrets=secrets_map if has_secrets_payload else None,
                    opening_clock=opening_clock,
                    clocks=clocks_in,
                    replace_secrets=bool(clear_missing and "gm_secrets" in body),
                    replace_clocks=bool(clear_missing and ("clocks" in body or "opening_clock" in body)),
                )
                eng.tree.sync_active_leaf_revisions(campaign_id)
                return {
                    "campaign": camp,
                    **gm_seed,
                    **({"library_seeded": len(seeded_library)} if seeded_library else {}),
                }

            res = await asyncio.to_thread(_apply)
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {**res, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/campaigns/{campaign_id}/primary")
    async def campaign_set_primary(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            res = await asyncio.to_thread(
                lambda: ctx.gameplay_service().execute("set_primary_campaign", {"campaign_id": campaign_id})["result"]
            )
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign"})
            return {"campaign": res, "request_id": request_id}
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/campaigns/{campaign_id}")
    async def campaign_delete(campaign_id: str, request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            res = await asyncio.to_thread(
                lambda: ctx.gameplay_service().execute("delete_campaign", {"campaign_id": campaign_id})["result"]
            )
            ctx.coop.publish(campaign_id, "sync", {"campaign_id": campaign_id, "kind": "campaign_deleted"})
            return {**res, "request_id": request_id}
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc), "request_id": request_id})
