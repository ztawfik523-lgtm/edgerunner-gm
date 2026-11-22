"""HTTP security, request limits, auth/session context, CORS, and ownership gates."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from server.coop import _CoopHub

_DEFAULT_AUTH_JSON_MAX_BYTES = 64 * 1024
_DEFAULT_JSON_MAX_BYTES = 8 * 1024 * 1024
_AUTH_JSON_MAX_BYTES = _DEFAULT_AUTH_JSON_MAX_BYTES
_JSON_MAX_BYTES = _DEFAULT_JSON_MAX_BYTES


def _resolve_json_limits() -> tuple[int, int]:
    """Read JSON body limits, honoring monkeypatches on either redkb or server.security."""
    auth_limit = _AUTH_JSON_MAX_BYTES
    body_limit = _JSON_MAX_BYTES
    redkb_mod = sys.modules.get("redkb")
    if redkb_mod is not None:
        redkb_auth = getattr(redkb_mod, "_AUTH_JSON_MAX_BYTES", _DEFAULT_AUTH_JSON_MAX_BYTES)
        redkb_body = getattr(redkb_mod, "_JSON_MAX_BYTES", _DEFAULT_JSON_MAX_BYTES)
        if redkb_auth != _DEFAULT_AUTH_JSON_MAX_BYTES:
            auth_limit = redkb_auth
        if redkb_body != _DEFAULT_JSON_MAX_BYTES:
            body_limit = redkb_body
    return int(auth_limit), int(body_limit)


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

        auth_limit, body_limit = _resolve_json_limits()
        limit = auth_limit if path.startswith("/v1/auth/") else body_limit
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


def setup_app_middleware(app: Any, dynamic_origins: set[str]) -> None:
    """Install JSON size limit middleware, operational 503 handlers, and CORS."""
    from fastapi.responses import JSONResponse

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

    if dynamic_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=sorted(dynamic_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=[
                "Accept",
                "Authorization",
                "Content-Type",
                "X-RedGM-Client-Id",
                "X-RedGM-Pin",
                "X-RedGM-Token",
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
        dynamic_origins: set[str],
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
        self.dynamic_origins = dynamic_origins
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

        # Aliases matching original redkb.py helper names
        self._extract_token = self.extract_token
        self._session = self.session
        self._current_allowed_origins = self.current_allowed_origins
        self._effective_role = self.effective_role
        self._can_view_gm_private_state = self.can_view_gm_private_state
        self._resolve_active_llm = self.resolve_active_llm
        self._sse_response = self.sse_response

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
        hdr = (request.headers.get("x-redgm-token") or "").strip()
        if hdr:
            return hdr
        auth_hdr = (request.headers.get("authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            return auth_hdr[7:].strip()
        cookie_tok = (request.cookies.get("redgm_token") or "").strip()
        if cookie_tok:
            return cookie_tok
        qp_tok = (request.query_params.get("token") or "").strip()
        return qp_tok or None

    def session(self, request: Any) -> dict[str, Any]:
        pin = (request.headers.get("x-redgm-pin") or request.query_params.get("pin") or "").strip()
        client_host = request.client.host if request.client else "local"
        return self.auth.resolve_session(self.extract_token(request), pin=pin, pin_bucket=client_host)

    def current_allowed_origins(self) -> set[str]:
        from turnloop import load_server_settings
        origins = set(self.dynamic_origins)
        origins.update(load_server_settings(self.resolved_settings_path()).get("allowed_origins") or [])
        return origins

    def require_player(self, request: Any, request_id: str):
        from fastapi.responses import JSONResponse
        sess = self.session(request)
        if not self.auth.auth_enabled():
            return None
        if sess["authenticated"]:
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
        eff_role = self.effective_role(request, sess)
        return eff_role in {"admin", "open"}

    def is_admin_or_pin_only(self, request: Any, sess: dict[str, Any]) -> bool:
        eff_role = self.effective_role(request, sess)
        if eff_role != "user":
            return True
        return bool(sess.get("pin_only_mode") and not self.auth.is_admin_configured())

    @staticmethod
    def filter_llm_override_for_role(cfg_raw: dict[str, Any] | None, *, eff_role: str | None = None) -> dict[str, Any] | None:
        """Hook for gating/filtering per-request LLM overrides by caller role."""
        return cfg_raw

    def resolve_active_llm(self, cfg_raw: dict[str, Any] | None = None, *, eff_role: str | None = None):
        if self.llm is not None:
            return self.llm
        from turnloop import LLMConfig, OpenAICompatibleLLM, load_llm_settings
        saved = load_llm_settings(self.resolved_settings_path())
        merged = dict(saved)
        filtered = self.filter_llm_override_for_role(cfg_raw, eff_role=eff_role)
        if isinstance(filtered, dict):
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
        if uname and owner and owner.lower() != uname.lower():
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
            if uname and owner and owner.lower() != uname.lower():
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
        request_id: str,
    ):
        """Hook for message authorship/ownership verification (expanded in Phase 4)."""
        return None


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
    from turnloop import default_settings_path, load_server_settings

    resolved_settings = Path(settings_path) if settings_path is not None else default_settings_path()
    auth = AuthManager(resolved_settings, room_pin=room_pin or os.environ.get("REDGM_ROOM_PIN", ""))
    dynamic_origins: set[str] = set(allowed_origins)
    dynamic_origins.update(load_server_settings(resolved_settings).get("allowed_origins") or [])

    setup_app_middleware(app, dynamic_origins)
    coop = _CoopHub()
    return ServerContext(
        db_path=db_path,
        campaign_path=campaign_path,
        llm=llm,
        settings_path=settings_path,
        server_host=server_host,
        server_port=server_port,
        room_pin=room_pin,
        allow_server_control=allow_server_control,
        auth=auth,
        dynamic_origins=dynamic_origins,
        coop=coop,
        entrypoint_path=entrypoint_path,
    )
