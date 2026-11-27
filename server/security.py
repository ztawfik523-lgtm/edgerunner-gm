"""HTTP security, request limits, auth/session context, CORS, and ownership gates."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from server.coop import _CoopHub

_AUTH_JSON_MAX_BYTES = 64 * 1024
_JSON_MAX_BYTES = 8 * 1024 * 1024


def is_loopback_host(host: str) -> bool:
    """True when a bind host only accepts connections from this machine."""
    cleaned = (host or "").strip().strip("[]").lower()
    if cleaned == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def url_origin(url: Any) -> tuple[str, str]:
    """(scheme, netloc) of a URL, lowercased, for same-origin credential checks."""
    parts = urlsplit(str(url or "").strip())
    return parts.scheme.lower(), parts.netloc.lower()


class _JsonBodyLimitMiddleware:
    """Bound JSON request memory before FastAPI parses an untrusted payload."""

    # Paths that unconditionally parse JSON via request.json()
    _JSON_CONSUMING_PATHS = {
        "/v1/auth/",  # prefix for auth sub-routes
        "/v1/game",
        "/v1/creation/ai-assist",
        "/v1/library/homebrew",
        "/v1/chat/branch",
        "/v1/chat/delete",
        "/v1/chat/message/update",
        "/v1/campaigns/",  # prefix for campaign sub-routes
        "/v1/settings/llm",
        "/v1/settings/prompts",
        "/v1/settings/server",
        "/v1/settings/llm/test",
        "/v1/chat/turn",
        "/v1/chat/roll",
        "/v1/chat/sync-revisions",
        "/v1/chat/regenerate",
        "/v1/chat/compress",
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()

        is_json_consumer = any(path.startswith(p) for p in self._JSON_CONSUMING_PATHS)
        enforce_limit = (content_type == b"application/json" or content_type.endswith(b"+json")) or is_json_consumer
        if not enforce_limit:
            await self.app(scope, receive, send)
            return

        limit = _AUTH_JSON_MAX_BYTES if path.startswith("/v1/auth/") else _JSON_MAX_BYTES
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limit:
                    await self._too_large(send)
                    return
            except ValueError:
                await self._too_large(send)
                return

        messages = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > limit:
                await self._too_large(send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _too_large(send):
        body = b'{"detail":"JSON request body exceeds the configured size limit."}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")],
        })
        await send({"type": "http.response.body", "body": body})


def _in_docker() -> bool:
    return bool(os.environ.get("REDGM_MANAGED_BY_DOCKER")) or Path("/.dockerenv").exists()


class _SessionMiddleware:
    """Resolve the caller's auth session once per HTTP request, off the event loop.

    Token verification and passcode-PIN checks may run scrypt; doing it here
    once means routes read a cached session and a wrong PIN counts once
    against the PIN rate limit.
    """

    def __init__(self, app, ctx: "ServerContext"):
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request
            request = Request(scope)
            session = await asyncio.to_thread(self.ctx.resolve_session, request)
            scope.setdefault("state", {})["redgm_session"] = session
        await self.app(scope, receive, send)


def _settings_cors_middleware(ctx: "ServerContext"):
    """CORSMiddleware whose allowed origins are read live from settings + CLI flags."""
    from fastapi.middleware.cors import CORSMiddleware

    class _LiveOriginCORSMiddleware(CORSMiddleware):
        def is_allowed_origin(self, origin: str) -> bool:
            return origin in ctx.current_allowed_origins()

    return _LiveOriginCORSMiddleware


def setup_app_middleware(app: Any, ctx: "ServerContext") -> None:
    """Install session resolution, JSON size limits, operational 503 handlers, and CORS."""
    from fastapi.responses import JSONResponse

    app.add_middleware(_SessionMiddleware, ctx=ctx)
    app.add_middleware(_JsonBodyLimitMiddleware)

    async def unavailable(request, exc):
        request_id = uuid.uuid4().hex
        logging.getLogger("uvicorn.error").warning(
            "corebook_unavailable request_id=%s error_type=%s",
            request_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Corebook retrieval unavailable. Check the local index, embedding dependencies and backend logs.",
                "request_id": request_id,
            },
        )

    for error_type in (OSError, sqlite3.Error, RuntimeError, ValueError):
        app.add_exception_handler(error_type, unavailable)

    app.add_middleware(
        _settings_cors_middleware(ctx),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "X-Filename",
            "X-RedGM-Client-Id",
            "X-RedGM-Pin",
            "X-RedGM-View-Role",
        ],
    )


class ServerContext:
    """Shared security, session, settings, and service context for server route modules."""

    def __init__(
        self,
        *,
        db_path: Path,
        campaign_path: Any,
        llm: Any,
        settings_path: Path | None,
        server_host: str,
        server_port: int,
        room_pin: str,
        allow_server_control: bool,
        auth: Any,
        cli_origins: tuple[str, ...],
        coop: _CoopHub,
        entrypoint_path: Path | None = None,
    ):
        self.db_path = db_path
        self.campaign_path = campaign_path
        self.llm = llm
        self.settings_path = settings_path
        self.server_host = server_host
        self.server_port = server_port
        self.room_pin = room_pin
        self.allow_server_control = allow_server_control
        self.auth = auth
        self.resolved_pin = auth.room_pin
        self.cli_origins = tuple(cli_origins)
        self.coop = coop
        self.entrypoint_path = entrypoint_path or (Path(__file__).resolve().parent.parent / "redkb.py")
        self._service = None
        self._service_lock = threading.Lock()
        self.corebook_job_lock = threading.Lock()
        self.corebook_job: dict[str, Any] = {
            "status": "idle",
            "stage": "idle",
            "percent": 0,
            "current": 0,
            "total": 0,
            "filename": None,
            "message": "",
            "warning": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    def resolved_settings_path(self) -> Path:
        if self.settings_path is not None:
            return Path(self.settings_path)
        from turnloop import default_settings_path
        return default_settings_path()

    def campaign_db_path(self) -> Path:
        from campaign import DEFAULT_DB as DEFAULT_CAMPAIGN_DB
        return DEFAULT_CAMPAIGN_DB if self.campaign_path is None else Path(self.campaign_path)

    def gameplay_service(self):
        from campaign import DEFAULT_DB
        path = DEFAULT_DB if self.campaign_path is None else Path(self.campaign_path)
        if path.expanduser().resolve() == Path(self.db_path).expanduser().resolve():
            raise ValueError("Campaign database must be separate from the rules index")
        with self._service_lock:
            if self._service is None:
                from gameplay import GameplayService
                self._service = GameplayService(path, self.db_path)
            return self._service

    @staticmethod
    def audit(tool: str, results: list[dict[str, Any]]) -> str:
        request_id = uuid.uuid4().hex
        logging.getLogger("uvicorn.error").info("corebook_tool %s", json.dumps({
            "request_id": request_id,
            "tool": tool,
            "pdf_pages": [row["pdf_page"] for row in results],
            "source_sha256": results[0].get("source_sha256") if results else None,
        }))
        return request_id

    @staticmethod
    def extract_token(request: Any) -> str | None:
        """Browsers send the httpOnly ``redgm_token`` cookie; other clients send ``Authorization: Bearer``."""
        auth_hdr = (request.headers.get("authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            return auth_hdr[7:].strip() or None
        return (request.cookies.get("redgm_token") or "").strip() or None

    def resolve_session(self, request: Any) -> dict[str, Any]:
        """Verify the request's credentials (may hash); called once per request by _SessionMiddleware."""
        pin = (request.headers.get("x-redgm-pin") or request.query_params.get("pin") or "").strip()
        client_host = request.client.host if request.client else "local"
        return self.auth.resolve_session(self.extract_token(request), pin=pin, pin_bucket=client_host)

    @staticmethod
    def session(request: Any) -> dict[str, Any]:
        return request.state.redgm_session

    def current_allowed_origins(self) -> set[str]:
        from turnloop import load_server_settings
        origins = set(self.cli_origins)
        origins.update(load_server_settings(self.resolved_settings_path()).get("allowed_origins") or [])
        return origins

    def require_player(self, request: Any, request_id: str):
        from fastapi.responses import JSONResponse
        if self.session(request)["authenticated"]:
            return None
        return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})

    def require_admin(self, request: Any, request_id: str):
        from fastapi.responses import JSONResponse
        sess = self.session(request)
        if sess["role"] in {"open", "admin"}:
            return None
        if not sess["authenticated"]:
            if sess["pin_only_mode"]:
                return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
            return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
        return JSONResponse(status_code=403, content={"detail": "Admin privileges required", "admin_required": True, "request_id": request_id})

    def check_mutable_origin(self, request: Any, request_id: str, *, require_json: bool = True, min_role: str = "user"):
        from fastapi.responses import JSONResponse
        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        host = request.headers.get("host")
        same_origin = bool(origin and host and origin == f"{request.url.scheme}://{host}")
        origins_now = self.current_allowed_origins()
        if sec_fetch_site == "cross-site" and origin not in origins_now:
            return JSONResponse(status_code=403, content={"detail": "Cross-site game requests are forbidden", "request_id": request_id})
        if origin is not None and origin not in origins_now and not same_origin:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed", "request_id": request_id})
        sess = self.session(request)
        if sess["role"] != "open":
            if not sess["authenticated"]:
                if sess["pin_only_mode"]:
                    return JSONResponse(status_code=401, content={"detail": "Room PIN required", "pin_required": True, "request_id": request_id})
                return JSONResponse(status_code=401, content={"detail": "Sign in required", "auth_required": True, "request_id": request_id})
            if min_role == "admin" and sess["role"] != "admin":
                return JSONResponse(status_code=403, content={"detail": "Admin privileges required", "admin_required": True, "request_id": request_id})
        if require_json and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse(status_code=415, content={"detail": "Content-Type must be application/json", "request_id": request_id})
        return None

    @staticmethod
    def effective_role(request: Any, sess: dict[str, Any]) -> str:
        view_override = (request.headers.get("x-redgm-view-role") or "").strip().lower()
        if sess.get("role") in {"admin", "open"} and view_override == "user":
            return "user"
        return str(sess.get("role") or "anon")

    def can_view_gm_private_state(self, request: Any, sess: dict[str, Any]) -> bool:
        if self.effective_role(request, sess) in {"admin", "open"}:
            return True
        return bool(
            sess.get("authenticated")
            and sess.get("pin_only_mode")
            and not self.auth.is_admin_configured()
            and (request.headers.get("x-redgm-view-role") or "").strip().lower() != "user"
        )

    @staticmethod
    def filter_llm_override_for_role(cfg_raw: dict[str, Any] | None, *, eff_role: str | None = None) -> dict[str, Any] | None:
        """Restrict per-request LLM overrides to admin/open callers."""
        if eff_role not in {"admin", "open"} or not isinstance(cfg_raw, dict) or not cfg_raw:
            return None
        return cfg_raw

    def resolve_active_llm(self, cfg_raw: dict[str, Any] | None = None, *, eff_role: str | None = None):
        if isinstance(cfg_raw, dict) and cfg_raw and eff_role not in {"admin", "open"}:
            raise PermissionError("Admin privileges required for per-request LLM overrides")
        if self.llm is not None:
            return self.llm
        from turnloop import LLMConfig, OpenAICompatibleLLM, load_llm_settings
        saved = load_llm_settings(self.resolved_settings_path())
        merged = dict(saved)
        filtered = self.filter_llm_override_for_role(cfg_raw, eff_role=eff_role)
        if isinstance(filtered, dict):
            if "base_url" in filtered and filtered["base_url"] is not None:
                explicit_key = "api_key" in filtered and filtered["api_key"] is not None
                if url_origin(filtered["base_url"]) != url_origin(saved.get("base_url")) and not explicit_key:
                    merged["api_key"] = ""
            for key in (
                "base_url",
                "model",
                "api_key",
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
                "max_tokens",
                "timeout_s",
                "mode",
                "retry_attempts",
            ):
                if key in filtered and filtered[key] is not None:
                    merged[key] = filtered[key]
        return OpenAICompatibleLLM(
            LLMConfig(
                base_url=str(merged["base_url"]),
                model=str(merged["model"]),
                api_key=str(merged.get("api_key") or ""),
                temperature=float(merged["temperature"]),
                top_p=float(merged.get("top_p", 1.0)),
                presence_penalty=float(merged.get("presence_penalty", 0.0)),
                frequency_penalty=float(merged.get("frequency_penalty", 0.0)),
                max_tokens=int(merged["max_tokens"]),
                timeout_s=float(merged["timeout_s"]),
                mode=str(merged["mode"]),
                retry_attempts=int(merged.get("retry_attempts", 2)),
            )
        )

    @staticmethod
    def sse_response(events_iter_fn: Callable[[], Any], request_id: str, on_finish: Callable[[], None] | None = None):
        from starlette.responses import StreamingResponse

        async def event_stream():
            try:
                async for ev in events_iter_fn():
                    payload = json.dumps(ev["data"], ensure_ascii=False)
                    yield f"event: {ev['event']}\ndata: {payload}\n\n"
            except Exception as exc:
                err = json.dumps({"detail": str(exc), "request_id": request_id}, ensure_ascii=False)
                yield f"event: error\ndata: {err}\n\n"
            finally:
                if on_finish is not None:
                    on_finish()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @staticmethod
    def check_character_ownership(
        existing_char: dict[str, Any] | None,
        *,
        eff_role: str,
        uname: str,
        action_name: str,
        request_id: str,
    ):
        from fastapi.responses import JSONResponse
        if eff_role != "user" or existing_char is None:
            return None
        owner = str((existing_char.get("detail") or {}).get("owner_username") or "").strip()
        if action_name == "delete_character":
            if not owner:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Claim this character first before deleting it, or ask an Admin to delete it.",
                        "request_id": request_id,
                    },
                )
            if not uname or owner.lower() != uname.lower():
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Character '{existing_char.get('name')}' belongs to {owner}. Only its owner or Admin can delete it.",
                        "request_id": request_id,
                    },
                )
            return None
        if owner and (not uname or owner.lower() != uname.lower()):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Character '{existing_char.get('name')}' belongs to {owner}. Only its owner or Admin can modify it.",
                    "request_id": request_id,
                },
            )
        return None

    @staticmethod
    def check_speaking_character(
        chars: list[dict[str, Any]],
        *,
        speaker_char_id: Any,
        eff_role: str,
        uname: str,
        is_intro: bool,
        pin_only_mode: bool,
        require_character_to_speak: bool,
        request_id: str,
    ):
        from fastapi.responses import JSONResponse
        if eff_role != "user" or is_intro or pin_only_mode:
            return None
        if isinstance(speaker_char_id, str) and speaker_char_id.strip():
            matched_char = next((c for c in chars if c["id"] == speaker_char_id.strip()), None)
            if matched_char is None:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Selected speaking character is not attached to this campaign.", "request_id": request_id},
                )
            owner = str((matched_char.get("detail") or {}).get("owner_username") or "").strip()
            if owner and (not uname or owner.lower() != uname.lower()):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"You cannot speak as {matched_char.get('name')} (owned by {owner}).", "request_id": request_id},
                )
            return None
        if require_character_to_speak:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "You must create or claim a character before speaking in chat (Admin has 'Require Character to Speak' enabled).",
                    "request_id": request_id,
                },
            )
        return None

    @staticmethod
    def check_message_ownership(
        msg: dict[str, Any] | None,
        *,
        eff_role: str,
        uname: str,
        chars: list[dict[str, Any]] | None = None,
        pin_only_mode: bool = False,
        request_id: str,
    ):
        """Enforce message authorship or owned-character attribution for non-admin edits/deletes."""
        from fastapi.responses import JSONResponse
        if eff_role != "user" or pin_only_mode or msg is None:
            return None
        if msg.get("role") != "user":
            return JSONResponse(
                status_code=403,
                content={"detail": "Only Admin can modify or delete GM or system messages.", "request_id": request_id},
            )
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        author = str(meta.get("author_username") or "").strip()
        if author:
            if uname and author.lower() == uname.lower():
                return None
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Message belongs to {author}. Only its author or Admin can modify or delete it.",
                    "request_id": request_id,
                },
            )
        speaker_cid = str(meta.get("speaker_character_id") or "").strip()
        if speaker_cid and chars and uname:
            matched = next((c for c in chars if c.get("id") == speaker_cid), None)
            if matched is not None:
                char_owner = str((matched.get("detail") or {}).get("owner_username") or "").strip()
                if char_owner and char_owner.lower() == uname.lower():
                    return None
        return JSONResponse(
            status_code=403,
            content={"detail": "Only the message author or Admin can modify or delete this message.", "request_id": request_id},
        )


def create_server_context(
    app: Any,
    db_path: Path,
    *,
    allowed_origins: tuple[str, ...] = (),
    campaign_path: Any = None,
    llm: Any = None,
    settings_path: Path | None = None,
    server_host: str = "127.0.0.1",
    server_port: int = 8765,
    room_pin: str = "",
    allow_server_control: bool = False,
    entrypoint_path: Path | None = None,
) -> ServerContext:
    """Initialize auth, settings, CORS/limit middleware, and shared ServerContext."""
    from auth import AuthManager
    from turnloop import default_settings_path

    resolved_settings = Path(settings_path) if settings_path is not None else default_settings_path()
    auth = AuthManager(
        resolved_settings,
        room_pin=room_pin or os.environ.get("REDGM_ROOM_PIN", ""),
        allow_open=is_loopback_host(server_host),
    )
    coop = _CoopHub()
    ctx = ServerContext(
        db_path=db_path,
        campaign_path=campaign_path,
        llm=llm,
        settings_path=settings_path,
        server_host=server_host,
        server_port=server_port,
        room_pin=room_pin,
        allow_server_control=allow_server_control,
        auth=auth,
        cli_origins=allowed_origins,
        coop=coop,
        entrypoint_path=entrypoint_path,
    )
    setup_app_middleware(app, ctx)
    return ctx
