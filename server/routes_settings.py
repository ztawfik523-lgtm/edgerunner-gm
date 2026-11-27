"""Auth, Corebook upload/search/lookup, settings, health, and LAN network routes."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import redkb
from server.security import ServerContext, _in_docker, url_origin

_COREBOOK_MAX_BYTES = 512 * 1024 * 1024


def _semantic_available() -> bool:
    return importlib.util.find_spec("fastembed") is not None and importlib.util.find_spec("numpy") is not None


def _check_auth_origin(ctx: ServerContext, request: Request, request_id: str) -> JSONResponse | None:
    origin = request.headers.get("origin")
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    host = request.headers.get("host")
    same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
    origins_now = ctx.current_allowed_origins()
    if sec_fetch_site == "cross-site" and origin not in origins_now:
        return JSONResponse(status_code=403, content={"detail": "Cross-site requests are forbidden", "request_id": request_id})
    if origin is not None and origin not in origins_now and not same_origin:
        return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
    return None


def register_settings_routes(app: FastAPI, ctx: ServerContext) -> None:
    """Register auth, corebook, search/lookup, settings, health, and network endpoints."""
    from auth import AuthError, AuthRateLimitError, _secret_eq
    from turnloop import (
        DEFAULT_PROMPT_TEMPLATES,
        load_llm_settings,
        load_prompt_settings,
        load_server_settings,
        masked_llm_settings,
        save_llm_settings,
        save_prompt_settings,
        save_server_settings,
    )

    @app.get("/v1/auth/status")
    def auth_status(request: Request):
        request_id = uuid.uuid4().hex
        llm_cfg = load_llm_settings(ctx.resolved_settings_path())
        return {
            **ctx.session(request),
            "require_character_to_speak": bool(llm_cfg.get("require_character_to_speak", True)),
            "request_id": request_id,
        }

    @app.post("/v1/auth/setup")
    async def auth_setup(request: Request):
        request_id = uuid.uuid4().hex
        origin_blocked = _check_auth_origin(ctx, request, request_id)
        if origin_blocked is not None:
            return origin_blocked
        if not ctx.auth.can_bootstrap():
            return JSONResponse(status_code=403, content={"detail": "Admin is already configured; sign in as Admin instead.", "request_id": request_id})
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bootstrap_secret = os.environ.get("REDGM_BOOTSTRAP_TOKEN", "")
            if len(bootstrap_secret) < 32:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Initial Admin setup is disabled until the server operator configures REDGM_BOOTSTRAP_TOKEN (at least 32 characters).", "request_id": request_id},
                )
            bucket = request.client.host if request.client else "local"
            try:
                ctx.auth._check_rate_limit(bucket)
            except AuthRateLimitError as exc:
                return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
            supplied_secret = body.get("bootstrap_token")
            if not isinstance(supplied_secret, str) or not _secret_eq(supplied_secret, bootstrap_secret):
                ctx.auth._record_failure(bucket)
                return JSONResponse(status_code=403, content={"detail": "Invalid Admin bootstrap token.", "request_id": request_id})
            ctx.auth._clear_failures(bucket)
            res = await asyncio.to_thread(
                lambda: ctx.auth.setup_initial(
                    admin_username=str(body.get("admin_username") or "admin"),
                    admin_password=str(body.get("admin_password") or ""),
                    user_username=str(body.get("user_username") or ""),
                    user_password=str(body.get("user_password") or ""),
                    user_passcode=str(body.get("user_passcode") or ""),
                    allow_guest_users=bool(body.get("allow_guest_users", False)),
                    allow_self_signup=bool(body.get("allow_self_signup", True)),
                )
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/login")
    async def auth_login(request: Request):
        request_id = uuid.uuid4().hex
        origin_blocked = _check_auth_origin(ctx, request, request_id)
        if origin_blocked is not None:
            return origin_blocked
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bucket = request.client.host if request.client else "local"
            res = await asyncio.to_thread(
                lambda: ctx.auth.authenticate(
                    mode=str(body.get("mode") or "auto"),
                    username=str(body.get("username") or ""),
                    password=str(body.get("password") or ""),
                    bucket=bucket,
                )
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except AuthRateLimitError as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/register")
    async def auth_register(request: Request):
        request_id = uuid.uuid4().hex
        origin_blocked = _check_auth_origin(ctx, request, request_id)
        if origin_blocked is not None:
            return origin_blocked
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bucket = request.client.host if request.client else "local"
            res = await asyncio.to_thread(
                lambda: ctx.auth.register_user(
                    username=str(body.get("username") or ""),
                    password=str(body.get("password") or ""),
                    bucket=bucket,
                )
            )
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except AuthRateLimitError as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/auth/logout")
    def auth_logout():
        request_id = uuid.uuid4().hex
        resp = JSONResponse(content={"ok": True, "request_id": request_id})
        resp.delete_cookie("redgm_token")
        return resp

    @app.post("/v1/auth/me")
    async def auth_update_me(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="user")
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        cur_uname = str(sess.get("username") or "").strip()
        if not cur_uname or sess.get("token_kind") != "account":
            return JSONResponse(
                status_code=403,
                content={"detail": "Sign in with a named account to update username or password.", "request_id": request_id},
            )
        affected_camps: set[str] = set()

        def _owner_transfer(old: str, new: str | None):
            return ctx.gameplay_service().store.transfer_owner(old, new, affected_camps)

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            bucket = request.client.host if request.client else "local"
            res = await asyncio.to_thread(
                lambda: ctx.auth.update_self_account(
                    cur_uname,
                    current_password=str(body.get("current_password") or ""),
                    new_username=body.get("new_username"),
                    new_password=body.get("new_password"),
                    bucket=bucket,
                    owner_transfer=_owner_transfer,
                )
            )
            for cid in affected_camps:
                ctx.coop.publish(cid, "sync", {"campaign_id": cid, "kind": "campaign"})
            resp = JSONResponse(content={**res, "request_id": request_id})
            resp.set_cookie("redgm_token", res["token"], max_age=res["expires_in"], httponly=True, samesite="lax")
            return resp
        except AuthRateLimitError as exc:
            return JSONResponse(status_code=429, content={"detail": str(exc), "request_id": request_id})
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/v1/auth/accounts")
    def auth_list_accounts(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_admin(request, request_id)
        if blocked is not None:
            return blocked
        return {**ctx.auth.list_accounts(), "request_id": request_id}

    @app.post("/v1/auth/accounts")
    async def auth_update_accounts(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            res = await asyncio.to_thread(lambda: ctx.auth.update_access(body))
            return {**res, "request_id": request_id}
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.delete("/v1/auth/accounts/{username}")
    async def auth_delete_account(request: Request, username: str):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        affected_camps: set[str] = set()

        def _owner_transfer(old: str, new: str | None):
            return ctx.gameplay_service().store.transfer_owner(old, new, affected_camps)

        try:
            res = await asyncio.to_thread(lambda: ctx.auth.delete_account(username, owner_transfer=_owner_transfer))
            for cid in affected_camps:
                ctx.coop.publish(cid, "sync", {"campaign_id": cid, "kind": "campaign"})
            return {**res, "request_id": request_id}
        except (AuthError, TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.get("/health")
    def health(request: Request):
        resolved = Path(ctx.db_path).expanduser().resolve()
        lan_enabled = ctx.server_host in {"0.0.0.0", "::"}
        sess = ctx.session(request)
        if not resolved.is_file():
            payload = {
                "status": "ok",
                "rules_indexed": False,
                "lan_enabled": lan_enabled,
                "pin_required": bool(ctx.resolved_pin),
                "auth_enabled": sess["auth_enabled"],
                "detail": "Corebook PDF not indexed yet. Homebrew and campaign play remain available.",
            }
            if sess["role"] in {"open", "admin"}:
                payload["db_path"] = str(resolved)
            return payload
        info = redkb.inspect_index(ctx.db_path)
        if sess["role"] not in {"open", "admin"}:
            info = {k: v for k, v in info.items() if k != "db_path"}
        return {
            **info,
            "status": "ok",
            "rules_indexed": True,
            "lan_enabled": lan_enabled,
            "pin_required": bool(ctx.resolved_pin),
            "auth_enabled": sess["auth_enabled"],
        }

    @app.get("/v1/corebook/status")
    def corebook_status(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        resolved = Path(ctx.db_path).expanduser().resolve()
        sess = ctx.session(request)
        indexed_info: dict[str, Any] = {}
        rules_indexed = resolved.is_file()
        if rules_indexed:
            try:
                indexed_info = redkb.inspect_index(ctx.db_path)
            except (OSError, sqlite3.Error):
                rules_indexed = False
        with ctx.corebook_job_lock:
            job_snapshot = dict(ctx.corebook_job)
        payload: dict[str, Any] = {
            "rules_indexed": rules_indexed,
            "indexed_pages": int(indexed_info.get("indexed_pages") or 0),
            "pdf_page_count": int(indexed_info.get("pdf_page_count") or indexed_info.get("indexed_pages") or 0),
            "source_filename": indexed_info.get("source_filename"),
            "semantic_available": _semantic_available(),
            "semantic_indexed": bool(indexed_info.get("embedding_model")),
            "job": job_snapshot,
            "request_id": request_id,
        }
        if sess["role"] in {"open", "admin"}:
            payload["db_path"] = str(resolved)
        return payload

    @app.post("/v1/corebook/upload")
    async def corebook_upload(request: Request, run_semantic: bool = False, filename: str = ""):
        from urllib.parse import unquote

        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked

        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type.startswith("multipart/"):
            return JSONResponse(
                status_code=415,
                content={"detail": "Upload raw PDF bytes with Content-Type: application/pdf.", "request_id": request_id},
            )

        raw_name = unquote((request.headers.get("x-filename") or filename or "Corebook.pdf").strip())
        safe_name = Path(raw_name.replace("\\", "/")).name or "Corebook.pdf"
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        with ctx.corebook_job_lock:
            if ctx.corebook_job["status"] == "running":
                return JSONResponse(
                    status_code=409,
                    content={"detail": "A Corebook upload or indexing job is already running.", "job": dict(ctx.corebook_job), "request_id": request_id},
                )
            ctx.corebook_job.update({
                "status": "running",
                "stage": "uploading",
                "percent": 1,
                "current": 0,
                "total": 0,
                "filename": safe_name,
                "message": f"Receiving {safe_name}...",
                "warning": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            })

        tmp_path: Path | None = None
        try:
            fd, tmp_str = tempfile.mkstemp(prefix="redgm-corebook-", suffix=".pdf")
            tmp_path = Path(tmp_str)
            total_bytes = 0
            header_buf = b""
            header_checked = False
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > _COREBOOK_MAX_BYTES:
                        raise OverflowError("PDF exceeds the 512 MB upload limit.")
                    if not header_checked:
                        header_buf += chunk
                        stripped = header_buf.lstrip()
                        if len(stripped) >= 5:
                            if not stripped.startswith(b"%PDF-"):
                                raise ValueError("This file does not appear to be a valid PDF.")
                            header_checked = True
                    handle.write(chunk)
            if total_bytes == 0:
                raise ValueError("Uploaded PDF file is empty.")
            if not header_checked and not header_buf.lstrip().startswith(b"%PDF-"):
                raise ValueError("This file does not appear to be a valid PDF.")
        except OverflowError as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            with ctx.corebook_job_lock:
                ctx.corebook_job.update({"status": "error", "stage": "error", "error": str(exc), "message": str(exc), "finished_at": time.time()})
            return JSONResponse(status_code=413, content={"detail": str(exc), "request_id": request_id})
        except (ValueError, OSError) as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            with ctx.corebook_job_lock:
                ctx.corebook_job.update({"status": "error", "stage": "error", "error": str(exc), "message": str(exc), "finished_at": time.time()})
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

        def _on_progress(ev: dict[str, Any]) -> None:
            with ctx.corebook_job_lock:
                ctx.corebook_job.update({
                    "stage": ev.get("stage", "extracting"),
                    "percent": int(ev.get("percent", 0)),
                    "current": int(ev.get("current", 0)),
                    "total": int(ev.get("total", 0)),
                    "message": str(ev.get("message") or ""),
                })

        build_index_fn = redkb.build_index

        def _worker(pdf_file: Path, orig_name: str, want_semantic: bool) -> None:
            try:
                info = build_index_fn(
                    pdf_file,
                    Path(ctx.db_path),
                    progress_cb=_on_progress,
                    source_filename=orig_name,
                )
                warning_msg: str | None = None
                if want_semantic and _semantic_available():
                    with ctx.corebook_job_lock:
                        ctx.corebook_job.update({
                            "stage": "embedding",
                            "percent": 99,
                            "message": "Building local AI meaning search embeddings...",
                        })
                    try:
                        from semantic import build_embeddings
                        build_embeddings(Path(ctx.db_path))
                    except Exception as sem_exc:
                        warning_msg = f"Corebook indexed, but semantic embeddings skipped: {sem_exc}"
                with ctx.corebook_job_lock:
                    ctx.corebook_job.update({
                        "status": "completed",
                        "stage": "done",
                        "percent": 100,
                        "message": f"Corebook ready ({info.get('indexed_pages', 0)} pages).",
                        "warning": warning_msg,
                        "error": None,
                        "finished_at": time.time(),
                    })
            except Exception as exc:
                with ctx.corebook_job_lock:
                    ctx.corebook_job.update({
                        "status": "error",
                        "stage": "error",
                        "error": str(exc),
                        "message": f"Indexing failed: {exc}",
                        "finished_at": time.time(),
                    })
            finally:
                pdf_file.unlink(missing_ok=True)

        worker = threading.Thread(
            target=_worker,
            args=(tmp_path, safe_name, bool(run_semantic)),
            daemon=True,
        )
        worker.start()
        with ctx.corebook_job_lock:
            snapshot = dict(ctx.corebook_job)
        return JSONResponse(status_code=202, content={"started": True, "job": snapshot, "request_id": request_id})

    @app.get("/v1/search")
    def search(request: Request, q: str = Query(min_length=2), limit: int = Query(5, ge=1, le=20)):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        results = redkb.search_pages(ctx.db_path, q, limit)
        return {
            "query": q,
            "results": results,
            "request_id": ctx.audit("search_corebook", results),
            "evidence_status": "candidates_not_verified_answers" if results else "no_matches",
        }

    @app.get("/v1/pages/{page}")
    def page_lookup(request: Request, page: int, numbering: str = "printed"):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        try:
            result = redkb.read_page(ctx.db_path, page, numbering)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if result is None:
            ctx.audit("read_corebook_page", [])
            raise HTTPException(404, "Page not found")
        result["request_id"] = ctx.audit("read_corebook_page", [result])
        return result

    @app.get("/v1/phrase")
    def phrase(request: Request, q: str = Query(min_length=3), limit: int = Query(10, ge=1, le=100)):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        return {"query": q, "results": redkb.find_phrase(ctx.db_path, q, limit)}

    @app.get("/v1/catalog")
    def source_catalog(request: Request):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import catalog
        result = catalog(ctx.db_path)
        result["request_id"] = ctx.audit("catalog_corebook", [])
        return result

    @app.get("/v1/sections/{section_id}")
    def source_section(request: Request, section_id: str, offset: int = Query(0, ge=0), limit: int = Query(8, ge=1, le=12)):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import section
        result = section(ctx.db_path, section_id, offset, limit)
        result["request_id"] = ctx.audit("read_corebook_section", result["pages"])
        return result

    @app.get("/v1/page-batch")
    def source_pages(request: Request, numbers: str, numbering: str = "printed"):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        from knowledge import pages
        try:
            result = pages(ctx.db_path, [int(n) for n in numbers.split(",")], numbering)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        result["request_id"] = ctx.audit("read_corebook_pages", result["pages"])
        return result

    @app.get("/v1/skills")
    def skill_catalog(request: Request):
        blocked = ctx.require_player(request, uuid.uuid4().hex)
        if blocked is not None:
            return blocked
        if not Path(ctx.db_path).expanduser().is_file():
            return {"skills": {}, "rules_indexed": False, "request_id": ctx.audit("catalog_corebook_skills", [])}
        from sourcecatalog import skills
        return {"skills": skills(ctx.db_path), "rules_indexed": True, "request_id": ctx.audit("catalog_corebook_skills", [])}

    @app.get("/v1/network/info")
    def network_info(request: Request, campaign_id: str | None = None):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        lan_enabled = ctx.server_host in {"0.0.0.0", "::"}
        ips = redkb._detect_lan_ips() if lan_enabled else []
        host_header = request.headers.get("host") or f"127.0.0.1:{ctx.server_port}"
        scheme = request.url.scheme or "http"
        suffix = f"/?campaign={campaign_id}" if campaign_id else "/"
        srv_cfg = load_server_settings(ctx.resolved_settings_path())
        public_url = str(srv_cfg.get("public_url") or "").strip().rstrip("/")
        urls: list[str] = []
        if public_url:
            urls.append(f"{public_url}{suffix}")
        for ip in ips:
            u = f"{scheme}://{ip}:{ctx.server_port}{suffix}"
            if u not in urls:
                urls.append(u)
        if not urls:
            urls = [f"{scheme}://{host_header}{suffix}"]
        turns = ctx.coop.all_active_turns(campaign_id) if campaign_id else {}
        return {
            "bind_host": ctx.server_host,
            "port": ctx.server_port,
            "lan_enabled": lan_enabled,
            "pin_required": bool(ctx.resolved_pin),
            "public_url": public_url,
            "lan_ips": ips,
            "join_urls": urls,
            "roster": ctx.coop.roster(campaign_id) if campaign_id else [],
            "active_turn": turns.get("main") or next(iter(turns.values()), None),
            "active_turns": turns,
            "sync_seq": ctx.coop.current_seq(campaign_id) if campaign_id else 0,
            "request_id": request_id,
        }

    @app.get("/v1/settings/public")
    def get_public_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_player(request, request_id)
        if blocked is not None:
            return blocked
        sess = ctx.session(request)
        llm_cfg = load_llm_settings(ctx.resolved_settings_path())
        return {
            "role": sess["role"],
            "username": sess["username"],
            "auth_enabled": sess["auth_enabled"],
            "mode": llm_cfg["mode"],
            "gm_style": llm_cfg.get("gm_style", "grounded"),
            "narrator_length": llm_cfg.get("narrator_length", "standard"),
            "narrator_pacing": llm_cfg.get("narrator_pacing", "balanced"),
            "gm_thinking_mode": llm_cfg.get("gm_thinking_mode", "quality"),
            "require_character_to_speak": bool(llm_cfg.get("require_character_to_speak", True)),
            "enable_chronicler": bool(llm_cfg.get("enable_chronicler", True)),
            "enable_highlights": bool(llm_cfg.get("enable_highlights", True)),
            "allow_ai_homebrew": bool(llm_cfg.get("allow_ai_homebrew", True)),
            "auto_compress_prompt": bool(llm_cfg.get("auto_compress_prompt", True)),
            "history_window": int(llm_cfg.get("history_window", 14)),
            "compression_threshold": int(llm_cfg.get("compression_threshold", 14)),
            "citation_limit": int(llm_cfg.get("citation_limit", 4)),
            "default_time_step_minutes": int(llm_cfg.get("default_time_step_minutes", 0)),
            "request_id": request_id,
        }

    @app.get("/v1/settings/all")
    def get_all_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_admin(request, request_id)
        if blocked is not None:
            return blocked
        s_path = ctx.resolved_settings_path()
        llm_cfg = load_llm_settings(s_path)
        prompts_cfg = load_prompt_settings(s_path)
        server_cfg = load_server_settings(s_path)
        acc_info = ctx.auth.list_accounts()
        return {
            "llm": masked_llm_settings(llm_cfg),
            "prompts": prompts_cfg,
            "prompt_defaults": DEFAULT_PROMPT_TEMPLATES,
            "server": server_cfg,
            "auth_policy": {
                "allow_guest_users": acc_info["allow_guest_users"],
                "allow_self_signup": acc_info["allow_self_signup"],
                "user_passcode_configured": acc_info["user_passcode_configured"],
                "admin_configured": ctx.auth.is_admin_configured(),
                "user_configured": ctx.auth.is_user_configured(),
                "accounts": acc_info["accounts"],
            },
            "runtime": {
                "active_host": ctx.server_host,
                "active_port": ctx.server_port,
                "in_docker": _in_docker(),
                "restart_supported": bool(ctx.allow_server_control),
                "restart_required": (
                    server_cfg["bind_host"] != ctx.server_host or int(server_cfg["port"]) != int(ctx.server_port)
                ),
            },
            "request_id": request_id,
        }

    @app.get("/v1/settings/llm")
    def get_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.require_admin(request, request_id)
        if blocked is not None:
            return blocked
        settings = load_llm_settings(ctx.resolved_settings_path())
        return {**masked_llm_settings(settings), "request_id": request_id}

    @app.post("/v1/settings/llm")
    async def update_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_llm_settings(body, ctx.resolved_settings_path()))
            return {**masked_llm_settings(saved), "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/prompts")
    async def update_prompt_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_prompt_settings(body, ctx.resolved_settings_path()))
            return {"prompts": saved, "prompt_defaults": DEFAULT_PROMPT_TEMPLATES, "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/server")
    async def update_server_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        try:
            body = await request.json()
            saved = await asyncio.to_thread(lambda: save_server_settings(body, ctx.resolved_settings_path()))
            return {
                "server": saved,
                "active_host": ctx.server_host,
                "active_port": ctx.server_port,
                "in_docker": _in_docker(),
                "restart_supported": bool(ctx.allow_server_control),
                "restart_required": (
                    saved["bind_host"] != ctx.server_host or int(saved["port"]) != int(ctx.server_port)
                ),
                "request_id": request_id,
            }
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})

    @app.post("/v1/settings/server/restart")
    async def restart_server(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=False, min_role="admin")
        if blocked is not None:
            return blocked
        srv = load_server_settings(ctx.resolved_settings_path())
        if not ctx.allow_server_control:
            return JSONResponse(
                status_code=400,
                content={"detail": "Server self-restart is only available when running via redkb.py serve", "request_id": request_id},
            )

        def _reexec():
            cleaned: list[str] = []
            skip_next = False
            for arg in sys.argv[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if arg in {"--host", "--port"}:
                    skip_next = True
                    continue
                if arg.startswith("--host=") or arg.startswith("--port=") or arg in {"--lan", "--from-settings"}:
                    continue
                cleaned.append(arg)
            if "serve" not in cleaned:
                cleaned.append("serve")
            cleaned.append("--from-settings")
            cmd = [sys.executable, str(ctx.entrypoint_path), *cleaned]
            os.execv(sys.executable, cmd)

        timer = threading.Timer(0.35, _reexec)
        timer.daemon = True
        timer.start()
        return {
            "restarting": True,
            "bind_host": srv["bind_host"],
            "port": srv["port"],
            "in_docker": _in_docker(),
            "request_id": request_id,
        }

    @app.post("/v1/settings/llm/test")
    async def test_llm_settings(request: Request):
        request_id = uuid.uuid4().hex
        blocked = ctx.check_mutable_origin(request, request_id, require_json=True, min_role="admin")
        if blocked is not None:
            return blocked
        import httpx
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Request body must be an object")
            saved = load_llm_settings(ctx.resolved_settings_path())
            base_url = str(body.get("base_url") or saved["base_url"]).strip().rstrip("/")
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                raise ValueError("base_url must start with http:// or https://")
            if isinstance(body.get("api_key"), str) and body["api_key"].strip():
                api_key = body["api_key"].strip()
            elif url_origin(base_url) == url_origin(saved["base_url"]):
                api_key = str(saved.get("api_key") or "")
            else:
                # Never send the saved key to a different provider origin.
                api_key = ""
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            models_url = base_url[:-len("/chat/completions")] + "/models" if base_url.endswith("/chat/completions") else f"{base_url}/models"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(models_url, headers=headers)
            if resp.status_code >= 400:
                return {"ok": False, "status_code": resp.status_code, "models": [], "detail": f"Provider returned HTTP {resp.status_code}", "request_id": request_id}
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
            return {"ok": True, "status_code": resp.status_code, "models": models[:50], "detail": f"Connected ({len(models)} models found)" if models else "Connected", "request_id": request_id}
        except (TypeError, ValueError) as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc), "request_id": request_id})
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            return {"ok": False, "status_code": 0, "models": [], "detail": f"Connection failed: {exc}", "request_id": request_id}
