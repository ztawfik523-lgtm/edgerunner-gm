"""Tests for Admin/User authentication, exposed turn options, prompt customization, and server settings."""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import AuthError, AuthManager, AuthRateLimitError, hash_password, verify_password
from gameplay import GameplayService
import redkb
import server.security
from tests.test_library import _create_rules_db
from turn_engine import (
    DEFAULT_PROMPT_TEMPLATES,
    LLMConfig,
    TurnEngine,
    load_llm_settings,
    load_prompt_settings,
    load_server_settings,
    save_llm_settings,
    save_prompt_settings,
    save_server_settings,
)


class RecordingLLM:
    """Stub LLM that records prompt messages passed to complete() and stream()."""

    def __init__(self):
        self.config = LLMConfig(model="stub-model", mode="two_pass")
        self.complete_calls: list[list[dict[str, str]]] = []
        self.stream_calls: list[list[dict[str, str]]] = []

    async def complete(self, messages, **_kwargs):
        self.complete_calls.append(messages)
        system = messages[0]["content"] if messages else ""
        if "Chronicler" in system or "continuity" in system.lower():
            return json.dumps({"time_elapsed_minutes": 15})
        if "Memory Summarizer" in system:
            return json.dumps({
                "scene": "Watson alley",
                "summary": "Picked up the datashard.",
                "npcs": {},
                "objectives": {},
                "discoveries": {},
                "unresolved": {},
                "library_entries": [],
                "clocks": [],
            })
        return json.dumps({"rolls": [], "patches": [], "library_adds": [], "clocks": []})

    def pop_call_meta(self):
        return {}

    async def stream(self, messages, **_kwargs):
        self.stream_calls.append(messages)
        yield "Neon static hangs over the street."


_TEST_BOOTSTRAP_TOKEN = "test-bootstrap-token-" + ("a" * 40)


def _bootstrap(client: TestClient, payload: dict):
    return client.post(
        "/v1/auth/setup",
        json={**payload, "bootstrap_token": _TEST_BOOTSTRAP_TOKEN},
    )


def test_password_hashing_and_auth_manager_lifecycle(tmp_path: Path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    encoded = hash_password("secret-admin-pass")
    assert encoded.startswith("scrypt$")
    assert verify_password("secret-admin-pass", encoded)
    assert not verify_password("wrong-pass", encoded)

    mgr = AuthManager(settings_path)
    assert mgr.auth_enabled() is False
    assert mgr.can_bootstrap() is True
    assert mgr.resolve_session(None)["role"] == "open"

    boot = mgr.setup_initial(
        admin_username="boss",
        admin_password="boss-password",
        user_username="runner",
        user_password="runner-pass",
        allow_guest_users=False,
    )
    assert boot["role"] == "admin"
    assert boot["username"] == "boss"
    assert mgr.auth_enabled() is True
    assert mgr.can_bootstrap() is False

    admin_sess = mgr.resolve_session(boot["token"])
    assert admin_sess["authenticated"] is True
    assert admin_sess["role"] == "admin"

    user_login = mgr.authenticate(mode="user", username="runner", password="runner-pass")
    assert user_login["role"] == "user"
    user_sess = mgr.resolve_session(user_login["token"])
    assert user_sess["authenticated"] is True
    assert user_sess["role"] == "user"

    # Admin login must reject regular user account.
    with pytest.raises(AuthError):
        mgr.authenticate(mode="admin", username="runner", password="runner-pass")

    # Revoking tokens increments version and invalidates prior tokens.
    mgr.update_access({"action": "policy", "revoke_all_tokens": True})
    assert mgr.resolve_session(boot["token"])["authenticated"] is False

    # Repeated failures trigger rate limiting.
    for _ in range(12):
        with pytest.raises(AuthError):
            mgr.authenticate(mode="admin", username="boss", password="wrong", bucket="10.0.0.5")
    with pytest.raises(AuthRateLimitError):
        mgr.authenticate(mode="admin", username="boss", password="wrong", bucket="10.0.0.5")


def test_account_security_changes_revoke_existing_sessions(tmp_path: Path):
    mgr = AuthManager(tmp_path / "settings.json")
    boot = mgr.setup_initial(admin_username="boss", admin_password="boss-password")
    mgr.update_access({"username": "runner", "password": "runner-password"})
    user_token = mgr.authenticate(mode="user", username="runner", password="runner-password")["token"]
    assert mgr.resolve_session(user_token)["authenticated"]

    mgr.update_access({"username": "runner", "role": "admin"})
    assert not mgr.resolve_session(user_token)["authenticated"]

    replacement = mgr.authenticate(mode="admin", username="runner", password="runner-password")["token"]
    mgr.update_access({"username": "runner", "password": "new-runner-password"})
    assert not mgr.resolve_session(replacement)["authenticated"]
    replacement = mgr.authenticate(
        mode="admin", username="runner", password="new-runner-password"
    )["token"]
    mgr.delete_account("runner")
    assert not mgr.resolve_session(replacement)["authenticated"]
    assert mgr.resolve_session(boot["token"])["authenticated"]


def test_deleted_account_token_rejected_on_recreate(tmp_path: Path):
    mgr = AuthManager(tmp_path / "settings.json")
    mgr.setup_initial(admin_username="admin", admin_password="admin-pass")
    mgr.update_access({"username": "target", "password": "pass1", "role": "user"})
    token = mgr.authenticate(mode="user", username="target", password="pass1")["token"]
    assert mgr.resolve_session(token)["authenticated"]

    mgr.delete_account("target")
    assert not mgr.resolve_session(token)["authenticated"]

    # Recreate account with same username and password
    mgr.update_access({"username": "target", "password": "pass1", "role": "user"})
    # Old token should still be invalid (different account_id)
    assert not mgr.resolve_session(token)["authenticated"]
    # New login should work
    new_token = mgr.authenticate(mode="user", username="target", password="pass1")["token"]
    assert mgr.resolve_session(new_token)["authenticated"]


def test_environment_account_tokens_follow_current_environment(tmp_path: Path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings))
    monkeypatch.setenv("REDGM_ADMIN_USER", "env-admin")
    monkeypatch.setenv("REDGM_ADMIN_PASS", "env-password")
    mgr = AuthManager(settings)
    mgr.update_access({"username": "saved-user", "password": "saved-password"})
    token = mgr.authenticate(mode="admin", username="env-admin", password="env-password")["token"]
    assert mgr.resolve_session(token)["role"] == "admin"
    monkeypatch.delenv("REDGM_ADMIN_PASS")
    assert not mgr.resolve_session(token)["authenticated"]


def test_initial_admin_setup_is_atomic_and_rate_limit_buckets_are_bounded(tmp_path: Path):
    mgr = AuthManager(tmp_path / "settings.json")

    def setup(username):
        try:
            return mgr.setup_initial(admin_username=username, admin_password="strong-password")
        except AuthError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(setup, ("first", "second")))
    assert sum(result is not None for result in results) == 1

    limiter = AuthManager(tmp_path / "other-settings.json")
    for i in range(5000):
        limiter._check_rate_limit(f"client-{i}")
    assert len(limiter._failures) <= 4096


def test_pin_is_player_only_and_json_bodies_are_bounded(tmp_path: Path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))
    app = redkb.make_api(
        rules_db, (), tmp_path / "campaign.sqlite", settings_path=settings_path,
        room_pin="table-pin", server_host="127.0.0.1", server_port=8765,
    )
    client = TestClient(app)
    pin_headers = {"X-RedGM-Pin": "table-pin"}

    assert client.get("/v1/library").status_code == 401
    assert client.get("/v1/library", headers=pin_headers).status_code == 200
    assert client.get("/v1/settings/public", headers=pin_headers).status_code == 200
    assert client.get("/v1/settings/all", headers=pin_headers).status_code == 403

    bootstrap_payload = {
        "admin_username": "first-admin",
        "admin_password": "a-strong-admin-password",
        "bootstrap_token": _TEST_BOOTSTRAP_TOKEN,
    }
    monkeypatch.delenv("REDGM_BOOTSTRAP_TOKEN")
    assert client.post("/v1/auth/setup", json=bootstrap_payload).status_code == 503
    monkeypatch.setenv("REDGM_BOOTSTRAP_TOKEN", _TEST_BOOTSTRAP_TOKEN)
    wrong_token = {**bootstrap_payload, "bootstrap_token": "wrong-token"}
    assert client.post("/v1/auth/setup", json=wrong_token).status_code == 403
    assert client.post("/v1/auth/setup", json=bootstrap_payload).status_code == 200
    client.cookies.clear()
    assert client.get("/v1/settings/all", headers=pin_headers).status_code == 403

    monkeypatch.setattr(server.security, "_AUTH_JSON_MAX_BYTES", 128)
    oversized_auth = '{"username":"runner","password":"' + ("x" * 200) + '"}'
    assert client.post(
        "/v1/auth/login", content=oversized_auth,
        headers={"Content-Type": "application/json"},
    ).status_code == 413

    monkeypatch.setattr(server.security, "_JSON_MAX_BYTES", 128)
    oversized_json = '{"value":"' + ("x" * 200) + '"}'
    assert client.post(
        "/v1/chat/branch", content=oversized_json,
        headers={"Content-Type": "application/json", **pin_headers},
    ).status_code == 413

    async def verify_chunked_body_limit():
        reached_app = False
        messages = iter((
            {"type": "http.request", "body": b"x" * 100, "more_body": True},
            {"type": "http.request", "body": b"y" * 60, "more_body": False},
        ))
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        async def inner_app(_scope, _receive, _send):
            nonlocal reached_app
            reached_app = True

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/turn",
            "headers": [(b"content-type", b"application/json")],
        }
        await server.security._JsonBodyLimitMiddleware(inner_app)(scope, receive, send)
        assert sent[0]["status"] == 413
        assert not reached_app

    asyncio.run(verify_chunked_body_limit())


def test_http_admin_vs_user_role_enforcement(tmp_path: Path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    campaign_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    app = redkb.make_api(rules_db, (), campaign_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)

    # Open mode initially allows bootstrap.
    status_open = client.get("/v1/auth/status").json()
    assert status_open["auth_enabled"] is False
    assert status_open["role"] == "open"
    assert status_open["can_bootstrap"] is True

    boot_resp = _bootstrap(
        client,
        {
            "admin_username": "netwatch",
            "admin_password": "admin-secret-99",
            "user_username": "edge",
            "user_password": "player-pass",
            "user_passcode": "table-code",
            "allow_guest_users": False,
        },
    )
    assert boot_resp.status_code == 200
    admin_token = boot_resp.json()["token"]

    # Unauthenticated calls now receive 401 when auth is enabled.
    client.cookies.clear()
    assert client.post("/v1/game", json={"action": "list_campaigns", "arguments": {}}).status_code == 401
    assert client.get("/v1/settings/all").status_code == 401
    assert client.get("/v1/library").status_code == 401

    # Sign in as normal User via username + password.
    client.cookies.clear()
    login_user = client.post(
        "/v1/auth/login",
        json={"mode": "user", "username": "edge", "password": "player-pass"},
    )
    assert login_user.status_code == 200
    user_token = login_user.json()["token"]
    assert login_user.json()["role"] == "user"

    user_headers = {"Authorization": "Bearer " + user_token}
    # Normal play features work for User; campaign creation/mutation & export are Admin-only.
    pub = client.get("/v1/settings/public", headers=user_headers)
    assert pub.status_code == 200
    assert pub.json()["role"] == "user"
    assert client.get("/v1/library", headers=user_headers).status_code == 200

    blocked_create = client.post(
        "/v1/game",
        headers=user_headers,
        json={"action": "create_campaign", "arguments": {"name": "Kabuki Run", "operation_id": "op-1"}},
    )
    assert blocked_create.status_code == 403

    # Admin creates campaign; user cannot mutate campaign, clocks, or export chat.
    admin_headers = {"Authorization": "Bearer " + admin_token}
    created = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_campaign", "arguments": {"name": "Kabuki Run", "operation_id": "op-1"}},
    )
    assert created.status_code == 200
    camp_id = created.json()["result"]["id"]
    assert client.post(
        "/v1/game",
        headers=user_headers,
        json={"action": "update_campaign", "campaign_id": camp_id, "arguments": {"expected_revision": 1, "changes": {"scene": "Hacked"}, "reason": "test", "operation_id": "op-u1"}},
    ).status_code == 403
    assert client.post(
        "/v1/game",
        headers=user_headers,
        json={"action": "start_session", "campaign_id": camp_id, "arguments": {"expected_revision": 1, "reason": "test", "operation_id": "op-u2"}},
    ).status_code == 403
    assert client.post(f"/v1/campaigns/{camp_id}/clocks", headers=user_headers, json={"action": "upsert", "name": "Heat"}).status_code == 403
    assert client.get("/v1/chat/export", params={"campaign_id": camp_id}, headers=user_headers).status_code == 403
    assert client.get("/v1/chat/export", params={"campaign_id": camp_id}, headers=admin_headers).status_code == 200

    # Starting a session appends a system divider in chat without triggering GM.
    started = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "start_session", "campaign_id": camp_id, "arguments": {"expected_revision": 1, "reason": "next session", "operation_id": "op-s2"}},
    )
    assert started.status_code == 200
    assert started.json()["result"]["session_number"] == 1
    tree = client.get("/v1/chat/tree", params={"campaign_id": camp_id}, headers=user_headers).json()
    assert any(
        n["role"] == "system" and n["metadata"].get("session_started") == 1 and "LUCK refilled" in n["content"]
        for n in tree["active_branch"]
    )

    # Admin-only endpoints reject User with 403 Forbidden.
    assert client.get("/v1/settings/all", headers=user_headers).status_code == 403
    assert client.get("/v1/settings/llm", headers=user_headers).status_code == 403
    assert client.post("/v1/settings/llm", headers=user_headers, json={"model": "x"}).status_code == 403
    assert client.post("/v1/settings/prompts", headers=user_headers, json={"system_persona": "hacked"}).status_code == 403
    assert client.post("/v1/settings/server", headers=user_headers, json={"port": 9999}).status_code == 403
    assert client.get("/v1/auth/accounts", headers=user_headers).status_code == 403

    # Shared player passcode also works for User login.
    client.cookies.clear()
    passcode_login = client.post(
        "/v1/auth/login",
        json={"mode": "user", "username": "TableGuest", "password": "table-code"},
    )
    assert passcode_login.status_code == 200
    assert passcode_login.json()["role"] == "user"

    # Admin token can read and write all settings, prompts, network IP/port, and accounts.
    all_res = client.get("/v1/settings/all", headers=admin_headers)
    assert all_res.status_code == 200
    assert all_res.json()["runtime"]["active_port"] == 8765

    upd_llm = client.post(
        "/v1/settings/llm",
        headers=admin_headers,
        json={
            "temperature": 0.65,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.1,
            "enable_chronicler": False,
            "gm_style": "lethal",
            "narrator_length": "concise",
            "gm_thinking_mode": "balanced",
            "default_time_step_minutes": 15,
            "history_window": 10,
            "citation_limit": 3,
        },
    )
    assert upd_llm.status_code == 200
    assert upd_llm.json()["gm_style"] == "lethal"
    assert upd_llm.json()["gm_thinking_mode"] == "balanced"
    assert upd_llm.json()["enable_chronicler"] is False
    assert client.get("/v1/settings/public", headers=user_headers).json()["gm_thinking_mode"] == "balanced"
    bad_tm = client.post(
        "/v1/settings/llm",
        headers=admin_headers,
        json={"gm_thinking_mode": "fast"},
    )
    assert bad_tm.status_code == 400

    upd_prompts = client.post(
        "/v1/settings/prompts",
        headers=admin_headers,
        json={"narrator_extra": "Keep prose tense and noir."},
    )
    assert upd_prompts.status_code == 200
    assert upd_prompts.json()["prompts"]["narrator_extra"] == "Keep prose tense and noir."

    upd_server = client.post(
        "/v1/settings/server",
        headers=admin_headers,
        json={
            "bind_host": "0.0.0.0",
            "port": 9090,
            "public_url": "https://nightcity.example.com",
            "allowed_origins": ["https://nightcity.example.com"],
        },
    )
    assert upd_server.status_code == 200
    assert upd_server.json()["restart_required"] is True
    assert upd_server.json()["server"]["port"] == 9090

    net_info = client.get("/v1/network/info", headers=admin_headers).json()
    assert net_info["join_urls"][0].startswith("https://nightcity.example.com/")

    # Accounts management: add user, promote to admin, demote back, then delete user.
    add_user = client.post(
        "/v1/auth/accounts",
        headers=admin_headers,
        json={"action": "upsert_account", "username": "solo2", "password": "pass-1234", "role": "user"},
    )
    assert add_user.status_code == 200
    assert any(a["username"] == "solo2" and a["role"] == "user" for a in add_user.json()["accounts"])

    promote = client.post(
        "/v1/auth/accounts",
        headers=admin_headers,
        json={"action": "upsert_account", "username": "solo2", "role": "admin"},
    )
    assert promote.status_code == 200
    assert any(a["username"] == "solo2" and a["role"] == "admin" for a in promote.json()["accounts"])

    demote = client.post(
        "/v1/auth/accounts",
        headers=admin_headers,
        json={"action": "upsert_account", "username": "solo2", "role": "user"},
    )
    assert demote.status_code == 200
    assert any(a["username"] == "solo2" and a["role"] == "user" for a in demote.json()["accounts"])

    # Cannot demote the sole remaining admin account.
    demote_last = client.post(
        "/v1/auth/accounts",
        headers=admin_headers,
        json={"action": "upsert_account", "username": "netwatch", "role": "user"},
    )
    assert demote_last.status_code == 400

    del_user = client.delete("/v1/auth/accounts/solo2", headers=admin_headers)
    assert del_user.status_code == 200
    assert all(a["username"] != "solo2" for a in del_user.json()["accounts"])


def test_prompt_customization_and_turn_tuning_apply_to_turn_engine(tmp_path: Path):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    campaign_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"

    save_llm_settings(
        {
            "enable_chronicler": False,
            "gm_style": "lethal",
            "narrator_length": "concise",
            "default_time_step_minutes": 20,
            "history_window": 8,
            "compression_threshold": 24,
            "citation_limit": 2,
        },
        settings_path,
    )
    save_prompt_settings(
        {
            "system_persona": "CUSTOM PERSONA: Brutal Night City referee.",
            "world_rules_prefix": "WORLD PREFIX: Trauma Team strikes fast.",
            "planner_extra": "CUSTOM PLANNER RULE.",
            "narrator_extra": "CUSTOM NARRATOR STYLE.",
        },
        settings_path,
    )
    save_server_settings({"bind_host": "127.0.0.1", "port": 8888}, settings_path)
    assert load_server_settings(settings_path)["port"] == 8888
    assert load_llm_settings(settings_path)["enable_chronicler"] is False

    service = GameplayService(campaign_db, rules_db)
    camp = service.execute("create_campaign", {"name": "Prompt Test", "operation_id": "c1"})["result"]
    cid = camp["id"]

    llm = RecordingLLM()
    engine = TurnEngine(service, llm, settings_path=settings_path)

    import asyncio

    async def _run():
        events = []
        async for ev in engine.run_turn(cid, "I scan the rooftop alley"):
            events.append(ev)
        return events

    events = asyncio.run(_run())
    done_ev = [e for e in events if e["event"] == "turn_done"][0]["data"]

    # Chronicler disabled => only 1 complete() call (Planner) and 1 stream() call (Narrator).
    assert len(llm.complete_calls) == 1
    assert len(llm.stream_calls) == 1
    assert "WORLD PREFIX: Trauma Team strikes fast." in llm.complete_calls[0][0]["content"]
    assert "CUSTOM PLANNER RULE." in llm.complete_calls[0][0]["content"]
    assert "CUSTOM PERSONA: Brutal Night City referee." in llm.stream_calls[0][0]["content"]
    assert "WORLD PREFIX: Trauma Team strikes fast." in llm.stream_calls[0][0]["content"]
    assert "CUSTOM NARRATOR STYLE." in llm.stream_calls[0][0]["content"]
    assert "Lethal" in llm.stream_calls[0][0]["content"]
    assert "Keep replies crisp" in llm.stream_calls[0][0]["content"]

    # Default time step applied automatically when Chronicler is disabled.
    ctx = service.campaign_context(cid)
    assert ctx["solo"]["runtime"]["clock_minutes"] == 20
    assert done_ev["turn_id"]

    # Reset prompts back to factory defaults.
    reset = save_prompt_settings({"reset": True}, settings_path)
    assert reset == DEFAULT_PROMPT_TEMPLATES
    assert load_prompt_settings(settings_path) == DEFAULT_PROMPT_TEMPLATES


def test_player_self_registration_and_campaign_primary_delete(tmp_path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))
    app = redkb.make_api(rules_db, (), camp_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)

    setup = _bootstrap(
        client,
        {"admin_username": "gm", "admin_password": "admin-password-1", "allow_self_signup": True},
    )
    assert setup.status_code == 200
    admin_token = setup.json()["token"]
    admin_headers = {"Authorization": "Bearer " + admin_token}

    # Player self-registers without admin creating an account for them.
    client.cookies.clear()
    reg = client.post("/v1/auth/register", json={"username": "choom_alice", "password": "alice-pass"})
    assert reg.status_code == 200
    assert reg.json()["role"] == "user"
    assert reg.json()["username"] == "choom_alice"
    alice_headers = {"Authorization": "Bearer " + reg.json()["token"]}

    # Duplicate username is rejected.
    dup = client.post("/v1/auth/register", json={"username": "choom_alice", "password": "other-pass"})
    assert dup.status_code == 400

    # Admin creates two campaigns, sets one primary, and deletes the other.
    c1 = client.post("/v1/game", headers=admin_headers, json={"action": "create_campaign", "arguments": {"name": "Alpha Run", "operation_id": "c1"}}).json()["result"]
    c2 = client.post("/v1/game", headers=admin_headers, json={"action": "create_campaign", "arguments": {"name": "Beta Run", "operation_id": "c2"}}).json()["result"]

    # Non-admin user cannot set primary or delete campaigns.
    assert client.post(f"/v1/campaigns/{c2['id']}/primary", headers=alice_headers).status_code == 403
    assert client.delete(f"/v1/campaigns/{c1['id']}", headers=alice_headers).status_code == 403

    prim = client.post(f"/v1/campaigns/{c2['id']}/primary", headers=admin_headers)
    assert prim.status_code == 200
    assert prim.json()["campaign"]["is_primary"] is True

    listed = client.post("/v1/game", headers=alice_headers, json={"action": "list_campaigns", "arguments": {}}).json()["result"]
    assert listed[0]["id"] == c2["id"]
    assert listed[0]["is_primary"] is True

    deleted = client.delete(f"/v1/campaigns/{c1['id']}", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listed_after = client.post("/v1/game", headers=alice_headers, json={"action": "list_campaigns", "arguments": {}}).json()["result"]
    assert [c["id"] for c in listed_after] == [c2["id"]]


def test_delete_character_requires_claim_or_admin(tmp_path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))
    app = redkb.make_api(rules_db, (), camp_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)

    setup = _bootstrap(
        client,
        {"admin_username": "gm", "admin_password": "admin-password-1", "allow_self_signup": True},
    )
    admin_headers = {"Authorization": "Bearer " + setup.json()["token"]}
    client.cookies.clear()
    alice_reg = client.post("/v1/auth/register", json={"username": "alice", "password": "alice-password"})
    alice_headers = {"Authorization": "Bearer " + alice_reg.json()["token"]}
    client.cookies.clear()
    bob_reg = client.post("/v1/auth/register", json={"username": "bob", "password": "bob-password"})
    bob_headers = {"Authorization": "Bearer " + bob_reg.json()["token"]}

    camp = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_campaign", "arguments": {"name": "Delete Test", "operation_id": "del-c1"}},
    ).json()["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}

    # Admin creates a character and unclaims it so it is shared/unclaimed
    unclaimed = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_character", "arguments": {"name": "Unclaimed", "stats": stats, "operation_id": "del-u1"}},
    ).json()["result"]
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={
            "action": "attach_character",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {"character_id": unclaimed["id"], "expected_revision": 1, "reason": "join", "operation_id": "del-a1"},
        },
    )
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={
            "action": "update_character_profile",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {
                "character_id": unclaimed["id"],
                "expected_revision": 1,
                "profile": {"owner_username": None},
                "reason": "make unclaimed",
                "operation_id": "del-uncl-1",
            },
        },
    )

    # Normal user cannot delete an unclaimed character
    res_unclaimed = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "delete_character", "campaign_id": camp["id"], "arguments": {"character_id": unclaimed["id"]}},
    )
    assert res_unclaimed.status_code == 403
    assert "Claim this character first" in res_unclaimed.json()["detail"]

    # Alice claims it, then Bob still cannot delete it, but Alice can
    claim_res = client.post(
        "/v1/game",
        headers=alice_headers,
        json={
            "action": "update_character_profile",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {
                "character_id": unclaimed["id"],
                "expected_revision": 1,
                "profile": {"owner_username": "alice"},
                "reason": "claim",
                "operation_id": "del-cl1",
            },
        },
    )
    assert claim_res.status_code == 200

    res_bob = client.post(
        "/v1/game",
        headers=bob_headers,
        json={"action": "delete_character", "campaign_id": camp["id"], "arguments": {"character_id": unclaimed["id"]}},
    )
    assert res_bob.status_code == 403

    res_alice = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "delete_character", "campaign_id": camp["id"], "arguments": {"character_id": unclaimed["id"]}},
    )
    assert res_alice.status_code == 200
    assert res_alice.json()["result"]["deleted"] is True

    # Admin can delete an unclaimed character directly
    unclaimed2 = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_character", "arguments": {"name": "AdminDel", "stats": stats, "operation_id": "del-u2"}},
    ).json()["result"]
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={
            "action": "attach_character",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {"character_id": unclaimed2["id"], "expected_revision": 1, "reason": "join", "operation_id": "del-a2"},
        },
    )
    res_admin = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "delete_character", "campaign_id": camp["id"], "arguments": {"character_id": unclaimed2["id"]}},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["result"]["deleted"] is True


def test_corebook_upload_and_expanded_settings_prompts(tmp_path, monkeypatch):
    import time
    import pymupdf

    rules_db = tmp_path / "rules.sqlite"
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))
    app = redkb.make_api(rules_db, (), camp_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)

    setup = _bootstrap(
        client, {"admin_username": "admin", "admin_password": "admin-password-1"}
    )
    assert setup.status_code == 200
    admin_headers = {"Authorization": "Bearer " + setup.json()["token"]}

    # Initially unindexed
    st0 = client.get("/v1/corebook/status", headers=admin_headers)
    assert st0.status_code == 200
    assert st0.json()["rules_indexed"] is False

    # Reject non-PDF upload cleanly
    bad = client.post(
        "/v1/corebook/upload",
        headers={**admin_headers, "Content-Type": "application/pdf", "X-Filename": "notpdf.pdf"},
        content=b"plain text not a pdf",
    )
    assert bad.status_code == 400

    # Build a small valid in-memory PDF with PyMuPDF
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Skill Checks\nRoll 1d10 + STAT + Skill against a DV.")
    p1.insert_text((30, p1.rect.height - 30), "129")
    pdf_bytes = doc.tobytes()
    doc.close()

    up = client.post(
        "/v1/corebook/upload",
        headers={**admin_headers, "Content-Type": "application/pdf", "X-Filename": "MyCorebook.pdf"},
        content=pdf_bytes,
    )
    assert up.status_code == 202
    assert up.json()["started"] is True

    final_status = None
    for _ in range(60):
        res = client.get("/v1/corebook/status", headers=admin_headers)
        assert res.status_code == 200
        data = res.json()
        if data["job"]["status"] in {"completed", "error"}:
            final_status = data
            break
        time.sleep(0.05)

    assert final_status is not None
    assert final_status["job"]["status"] == "completed", final_status
    assert final_status["rules_indexed"] is True
    assert final_status["indexed_pages"] == 1
    assert final_status["source_filename"] == "MyCorebook.pdf"
    assert client.get("/health", headers=admin_headers).json()["rules_indexed"] is True
    assert client.get("/v1/pages/129", headers=admin_headers).status_code == 200

    # Expanded settings & prompts work end-to-end
    upd_llm = client.post(
        "/v1/settings/llm",
        headers=admin_headers,
        json={
            "planner_temperature": 0.25,
            "creation_temperature": 0.9,
            "enable_highlights": False,
            "allow_ai_homebrew": False,
            "auto_compress_prompt": False,
        },
    )
    assert upd_llm.status_code == 200
    assert upd_llm.json()["planner_temperature"] == 0.25
    assert upd_llm.json()["creation_temperature"] == 0.9
    assert upd_llm.json()["enable_highlights"] is False
    assert upd_llm.json()["allow_ai_homebrew"] is False
    assert upd_llm.json()["auto_compress_prompt"] is False

    upd_prompts = client.post(
        "/v1/settings/prompts",
        headers=admin_headers,
        json={
            "creation_assist_persona": "CUSTOM CREATOR PERSONA",
            "narrator_core_rules": "CUSTOM CORE RULES",
            "player_message_template": "<<{speaker}>> {message}",
            "player_dialogue_rules": "CUSTOM DIALOGUE RULES",
            "player_narration_rules": "CUSTOM PLAYER NARRATION",
            "multiplayer_rules": "CUSTOM COOP RULES",
        },
    )
    assert upd_prompts.status_code == 200
    assert upd_prompts.json()["prompts"]["creation_assist_persona"] == "CUSTOM CREATOR PERSONA"
    assert upd_prompts.json()["prompts"]["narrator_core_rules"] == "CUSTOM CORE RULES"
    assert upd_prompts.json()["prompts"]["player_message_template"] == "<<{speaker}>> {message}"

    # Verify separated prompt fields + enable_highlights=False take effect in TurnEngine
    svc = GameplayService(camp_db, rules_db)
    camp = svc.execute("create_campaign", {"name": "Custom Rules Camp", "operation_id": "crc-1"})["result"]
    llm = RecordingLLM()
    engine = TurnEngine(svc, llm, settings_path=settings_path)
    import asyncio

    async def _run():
        return [ev async for ev in engine.run_turn(camp["id"], "Look around", speaker_name="Vee")]

    asyncio.run(_run())
    planner_sys = llm.complete_calls[0][0]["content"]
    planner_user = llm.complete_calls[0][-1]["content"]
    narrator_sys = llm.stream_calls[0][0]["content"]
    narrator_user = llm.stream_calls[0][-1]["content"]
    assert "CUSTOM CORE RULES" in narrator_sys
    assert "CUSTOM DIALOGUE RULES" in planner_sys
    assert "CUSTOM DIALOGUE RULES" in narrator_sys
    assert "CUSTOM PLAYER NARRATION" in narrator_sys
    assert "CUSTOM COOP RULES" in planner_sys
    assert "CUSTOM COOP RULES" in narrator_sys
    assert planner_user == "<<Vee>> Look around"
    assert narrator_user == "<<Vee>> Look around"
    assert "Visual UI flair" not in narrator_sys


def test_recreated_username_invalidates_tokens_no_temp_keys_and_auth_body_limit(tmp_path, monkeypatch):
    import json
    from auth import AuthManager, hash_password
    from turn_engine import read_settings_doc

    rules_db = tmp_path / "rules.sqlite"
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    auth = AuthManager(settings_path=settings_path)
    auth.setup_initial(admin_username="admin", admin_password="admin-pass-1")
    first = auth.register_user(username="reuser", password="reuser-pass-1")
    login_res = auth.authenticate(username="reuser", password="reuser-pass-1")
    assert auth.verify_token(login_res["token"]) == {"username": "reuser", "role": "user", "kind": "account"}

    # Deleting and recreating the same username invalidates the old token
    auth.delete_account("reuser")
    auth.register_user(username="reuser", password="reuser-pass-2")
    assert auth.verify_token(login_res["token"]) is None
    assert auth.verify_token(first["token"]) is None

    # Registering a new user does not leave _create_account_id in settings.json
    reg_res = auth.register_user(username="newuser", password="newuser-pass-1")
    assert auth.verify_token(reg_res["token"]) == {"username": "newuser", "role": "user", "kind": "account"}
    saved_auth = read_settings_doc(settings_path)["auth"]
    assert "_create_account_id" not in saved_auth
    assert "_setup_adm_id" not in saved_auth

    # _JsonBodyLimitMiddleware enforces 64 KiB on /v1/auth/* even with non-JSON Content-Type
    app = redkb.make_api(rules_db, (), camp_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)
    oversized = json.dumps({"username": "a", "password": "x" * (65 * 1024)}).encode("utf-8")
    res = client.post(
        "/v1/auth/login",
        headers={"Content-Type": "text/plain"},
        content=oversized,
    )
    assert res.status_code == 413


def test_llm_override_hardening_and_origin_key_stripping(tmp_path: Path, monkeypatch):
    from fastapi import FastAPI
    from server.coop import _CoopHub
    from server.security import ServerContext, create_server_context

    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    save_llm_settings(
        {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-admin-secret",
        },
        settings_path,
    )

    dummy_app = FastAPI()
    ctx = create_server_context(dummy_app, rules_db, campaign_path=camp_db, settings_path=settings_path)
    assert ctx.filter_llm_override_for_role({"base_url": "http://evil:9999"}, eff_role="user") is None
    assert ctx.filter_llm_override_for_role({"base_url": "http://evil:9999"}, eff_role=None) is None
    assert ctx.filter_llm_override_for_role({"model": "x"}, eff_role="admin") == {"model": "x"}

    with pytest.raises(PermissionError):
        ctx.resolve_active_llm({"base_url": "http://evil:9999"}, eff_role="user")

    # Admin overriding base_url to a different origin without api_key strips saved key.
    diff_origin_llm = ctx.resolve_active_llm(
        {"base_url": "https://attacker.example/v1", "model": "other"},
        eff_role="admin",
    )
    assert diff_origin_llm.config.base_url == "https://attacker.example/v1"
    assert diff_origin_llm.config.api_key == ""

    # Admin overriding path on the SAME origin preserves saved api_key.
    same_origin_llm = ctx.resolve_active_llm(
        {"base_url": "https://api.openai.com/v1/custom", "model": "other"},
        eff_role="admin",
    )
    assert same_origin_llm.config.api_key == "sk-admin-secret"

    # Admin supplying explicit api_key on new origin uses the supplied key.
    explicit_llm = ctx.resolve_active_llm(
        {"base_url": "https://other.example/v1", "api_key": "sk-explicit"},
        eff_role="admin",
    )
    assert explicit_llm.config.api_key == "sk-explicit"

    # End-to-end HTTP checks on /v1/chat/turn, /v1/chat/regenerate, /v1/creation/ai-assist.
    app = redkb.make_api(rules_db, (), camp_db, settings_path=settings_path, llm=RecordingLLM(), server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)
    boot = _bootstrap(
        client,
        {"admin_username": "gm", "admin_password": "gm-password-1", "allow_self_signup": True},
    )
    admin_headers = {"Authorization": "Bearer " + boot.json()["token"]}
    client.cookies.clear()
    reg = client.post("/v1/auth/register", json={"username": "alice", "password": "alice-password"})
    alice_headers = {"Authorization": "Bearer " + reg.json()["token"]}

    camp = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_campaign", "arguments": {"name": "LLM Gate", "operation_id": "llm-c1"}},
    ).json()["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    pc = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "create_character", "arguments": {"name": "Vee", "stats": stats, "operation_id": "llm-pc1"}},
    ).json()["result"]
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "attach_character", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": pc["id"], "expected_revision": 1, "reason": "attach", "operation_id": "llm-att1"}},
    )

    r_turn = client.post(
        "/v1/chat/turn",
        headers=alice_headers,
        json={
            "campaign_id": camp["id"],
            "user_text": "Look around",
            "speaker_character_id": pc["id"],
            "llm_config": {"base_url": "http://127.0.0.1:9999/v1"},
        },
    )
    assert r_turn.status_code == 403

    r_assist = client.post(
        "/v1/creation/ai-assist",
        headers=alice_headers,
        json={"target": "bio", "mode": "scratch", "llm": {"base_url": "http://127.0.0.1:9999/v1"}},
    )
    assert r_assist.status_code == 403

    # Admin can still send a normal turn, then non-admin cannot override llm_config on regenerate.
    ok_turn = client.post(
        "/v1/chat/turn",
        headers=admin_headers,
        json={"campaign_id": camp["id"], "user_text": "Open the gate", "gm_mode": "force_gm"},
    )
    assert ok_turn.status_code == 200
    tree = client.get("/v1/chat/tree", params={"campaign_id": camp["id"]}, headers=admin_headers).json()
    asst_id = tree["active_branch"][-1]["id"]
    r_regen = client.post(
        "/v1/chat/regenerate",
        headers=alice_headers,
        json={"campaign_id": camp["id"], "message_id": asst_id, "llm_config": {"model": "hijack"}},
    )
    assert r_regen.status_code == 403


def test_admin_and_pin_only_permission_gates(tmp_path: Path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    app = redkb.make_api(rules_db, (), camp_db, settings_path=settings_path, llm=RecordingLLM(), server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)
    boot = _bootstrap(
        client,
        {"admin_username": "gm", "admin_password": "gm-password-1", "allow_self_signup": True},
    )
    admin_headers = {"Authorization": "Bearer " + boot.json()["token"]}
    client.cookies.clear()
    reg = client.post("/v1/auth/register", json={"username": "alice", "password": "alice-password"})
    alice_headers = {"Authorization": "Bearer " + reg.json()["token"]}

    camp = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_campaign", "arguments": {"name": "Gate Run", "operation_id": "g-c1"}},
    ).json()["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    pc = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "create_character", "arguments": {"name": "Nyx", "stats": stats, "operation_id": "g-pc1"}},
    ).json()["result"]
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "attach_character", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": pc["id"], "expected_revision": 1, "reason": "attach", "operation_id": "g-att1"}},
    )

    # Admin creates initial message for regenerate/guidance checks.
    t_res = client.post(
        "/v1/chat/turn",
        headers=admin_headers,
        json={"campaign_id": camp["id"], "user_text": "Start", "gm_mode": "force_gm"},
    )
    assert t_res.status_code == 200
    asst_id = client.get("/v1/chat/tree", params={"campaign_id": camp["id"]}, headers=admin_headers).json()["active_branch"][-1]["id"]

    # Non-admin user receives 403 on all GM/Admin endpoints and mutations.
    assert client.post("/v1/chat/turn", headers=alice_headers, json={"campaign_id": camp["id"], "user_text": "Intro", "is_intro": True}).status_code == 403
    assert client.post("/v1/chat/turn", headers=alice_headers, json={"campaign_id": camp["id"], "user_text": "Hi", "speaker_character_id": pc["id"], "guidance": "GM secret"}).status_code == 403
    assert client.post("/v1/chat/regenerate", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": asst_id, "guidance": "Make boss die"}).status_code == 403
    assert client.post("/v1/chat/compress", headers=alice_headers, json={"campaign_id": camp["id"]}).status_code == 403
    assert client.post(f"/v1/campaigns/{camp['id']}/npc-identity", headers=alice_headers, json={"handle": "Fixer", "real_name": "Secret", "real_name_hidden": True}).status_code == 403
    assert client.post(f"/v1/campaigns/{camp['id']}/clocks", headers=alice_headers, json={"action": "upsert", "name": "Heat"}).status_code == 403
    assert client.post(f"/v1/campaigns/{camp['id']}/bootstrap", headers=alice_headers, json={"scene": "Hacked"}).status_code == 403
    assert client.get("/v1/chat/export", params={"campaign_id": camp["id"]}, headers=alice_headers).status_code == 403

    for action_name, action_args in (
        ("attach_character", {"character_id": pc["id"], "expected_revision": 1, "reason": "x", "operation_id": "u-att"}),
        ("start_encounter", {"character_ids": [pc["id"]], "expected_revision": 1, "reason": "x", "operation_id": "u-enc"}),
        ("end_encounter", {"expected_revision": 1, "reason": "x", "operation_id": "u-eenc"}),
        ("create_architecture", {"floors": [], "access_points": [], "expected_revision": 1, "reason": "x", "operation_id": "u-arch"}),
        ("start_netrun", {"character_id": pc["id"], "architecture_id": "x", "access_point_id": "a", "distance": 1, "expected_revision": 1, "reason": "x", "operation_id": "u-net"}),
        ("advance_time", {"elapsed_minutes": 30, "expected_revision": 1, "reason": "x", "operation_id": "u-time"}),
        ("encounter_action", {"action": "add_npc", "arguments": {"name": "Mook"}, "expected_revision": 1, "reason": "x", "operation_id": "u-npc"}),
    ):
        resp = client.post(
            "/v1/game",
            headers=alice_headers,
            json={"action": action_name, "campaign_id": camp["id"], "arguments": action_args},
        )
        assert resp.status_code == 403, f"Expected 403 for {action_name}, got {resp.status_code}"

    # Legacy pin_only_mode (no admin configured) allows GM actions unless X-RedGM-View-Role: user is set.
    pin_settings = tmp_path / "pin_settings.json"
    pin_camp_db = tmp_path / "pin_campaign.sqlite"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(pin_settings))
    pin_app = redkb.make_api(
        rules_db, (), pin_camp_db, settings_path=pin_settings, room_pin="4321",
        llm=RecordingLLM(), server_host="127.0.0.1", server_port=8765,
    )
    pin_client = TestClient(pin_app)
    pin_hdr = {"X-RedGM-Pin": "4321"}
    pin_view_user = {"X-RedGM-Pin": "4321", "X-RedGM-View-Role": "user"}

    pcamp_res = pin_client.post(
        "/v1/game",
        headers=pin_hdr,
        json={"action": "create_campaign", "arguments": {"name": "PIN Run", "operation_id": "pin-c1"}},
    )
    assert pcamp_res.status_code == 200
    pcamp_id = pcamp_res.json()["result"]["id"]

    assert pin_client.post(f"/v1/campaigns/{pcamp_id}/bootstrap", headers=pin_hdr, json={"scene": "Alley", "gm_secrets": "Mole"}).status_code == 200
    assert pin_client.post(f"/v1/campaigns/{pcamp_id}/clocks", headers=pin_hdr, json={"action": "upsert", "name": "Heat"}).status_code == 200
    assert pin_client.post(f"/v1/campaigns/{pcamp_id}/npc-identity", headers=pin_hdr, json={"handle": "Fixer", "real_name": "J. Doe", "real_name_hidden": True}).status_code == 200
    assert pin_client.get("/v1/chat/export", params={"campaign_id": pcamp_id}, headers=pin_hdr).status_code == 200
    assert pin_client.post("/v1/chat/turn", headers=pin_hdr, json={"campaign_id": pcamp_id, "user_text": "Intro", "is_intro": True}).status_code == 200

    # With X-RedGM-View-Role: user, pin_only_mode acts as non-GM player and blocks GM mutations.
    assert pin_client.post(f"/v1/campaigns/{pcamp_id}/clocks", headers=pin_view_user, json={"action": "upsert", "name": "Heat2"}).status_code == 403
    assert pin_client.post(f"/v1/campaigns/{pcamp_id}/bootstrap", headers=pin_view_user, json={"scene": "Hacked"}).status_code == 403
    assert pin_client.get("/v1/chat/export", params={"campaign_id": pcamp_id}, headers=pin_view_user).status_code == 403
    assert pin_client.post("/v1/chat/turn", headers=pin_view_user, json={"campaign_id": pcamp_id, "user_text": "Intro", "is_intro": True}).status_code == 403


def test_ownership_hardening_guests_characters_and_messages(tmp_path: Path, monkeypatch):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))

    app = redkb.make_api(
        rules_db,
        ("http://localhost:5173",),
        camp_db,
        settings_path=settings_path,
        llm=RecordingLLM(),
        server_host="127.0.0.1",
        server_port=8765,
    )
    client = TestClient(app)

    # Verify CORS preflight allows X-RedGM-View-Role and X-Filename.
    cors_pre = client.options(
        "/v1/chat/tree",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-RedGM-View-Role, X-Filename",
        },
    )
    allow_hdrs = (cors_pre.headers.get("access-control-allow-headers") or "").lower()
    assert "x-redgm-view-role" in allow_hdrs
    assert "x-filename" in allow_hdrs

    boot = _bootstrap(
        client,
        {
            "admin_username": "gm",
            "admin_password": "gm-password-1",
            "allow_self_signup": True,
            "allow_guest_users": True,
        },
    )
    admin_headers = {"Authorization": "Bearer " + boot.json()["token"]}
    client.cookies.clear()
    alice_headers = {"Authorization": "Bearer " + client.post("/v1/auth/register", json={"username": "alice", "password": "alice-password"}).json()["token"]}
    client.cookies.clear()
    bob_headers = {"Authorization": "Bearer " + client.post("/v1/auth/register", json={"username": "bob", "password": "bob-password"}).json()["token"]}
    client.cookies.clear()

    camp = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_campaign", "arguments": {"name": "Ownership Run", "operation_id": "own-c1"}},
    ).json()["result"]
    stats = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}
    alice_pc = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "create_character", "arguments": {"name": "AlicePC", "stats": stats, "operation_id": "own-a1"}},
    ).json()["result"]
    bob_pc = client.post(
        "/v1/game",
        headers=bob_headers,
        json={"action": "create_character", "arguments": {"name": "BobPC", "stats": stats, "operation_id": "own-b1"}},
    ).json()["result"]
    unclaimed_pc = client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "create_character", "arguments": {"name": "SharedPC", "stats": stats, "operation_id": "own-s1"}},
    ).json()["result"]
    client.post(
        "/v1/game",
        headers=admin_headers,
        json={"action": "update_character_profile", "auto_revision": True, "arguments": {"character_id": unclaimed_pc["id"], "expected_revision": 1, "profile": {"owner_username": None}, "reason": "unclaim", "operation_id": "own-uncl"}},
    )
    for idx, cid in enumerate((alice_pc["id"], bob_pc["id"], unclaimed_pc["id"]), start=1):
        client.post(
            "/v1/game",
            headers=admin_headers,
            json={"action": "attach_character", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": cid, "expected_revision": 1, "reason": "att", "operation_id": f"own-att-{idx}"}},
        )

    # 1. Guest (no token, empty uname) cannot modify, speak as, or roll for Alice's owned PC.
    assert client.post("/v1/game", json={"action": "update_character", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": alice_pc["id"], "expected_revision": 1, "changes": {"money": 999}, "reason": "steal", "operation_id": "gst-1"}}).status_code == 403
    assert client.post("/v1/game", json={"action": "substance_action", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"actor_id": alice_pc["id"], "action": "use_drug", "arguments": {"drug": "Synthcoke"}, "expected_revision": 1, "reason": "dose", "operation_id": "gst-2"}}).status_code == 403
    assert client.post("/v1/chat/turn", json={"campaign_id": camp["id"], "user_text": "Impersonate", "speaker_character_id": alice_pc["id"]}).status_code == 403
    assert client.post("/v1/chat/roll", json={"campaign_id": camp["id"], "character_id": alice_pc["id"], "stat": "REF", "skill": "Handgun", "dv": 13}).status_code == 403

    # 2. Alice cannot target Bob's PC via health_action / substance_action actor_id or target_id.
    assert client.post(
        "/v1/game",
        headers=alice_headers,
        json={
            "action": "health_action",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {"actor_id": alice_pc["id"], "action": "first_aid", "arguments": {"target_id": bob_pc["id"]}, "expected_revision": 1, "reason": "heal", "operation_id": "hl-1"},
        },
    ).status_code == 403
    assert client.post(
        "/v1/game",
        headers=alice_headers,
        json={
            "action": "substance_action",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {"actor_id": bob_pc["id"], "action": "use_drug", "arguments": {"drug": "Synthcoke"}, "expected_revision": 1, "reason": "dose", "operation_id": "sub-1"},
        },
    ).status_code == 403

    # 3. Non-admin cannot overwrite owner_username on owned PC or claim unclaimed PC for another user.
    assert client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "update_character_profile", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": alice_pc["id"], "expected_revision": 1, "profile": {"owner_username": "bob"}, "reason": "reassign", "operation_id": "reown-1"}},
    ).status_code == 403
    assert client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "update_character_profile", "campaign_id": camp["id"], "auto_revision": True, "arguments": {"character_id": unclaimed_pc["id"], "expected_revision": 1, "profile": {"owner_username": "bob"}, "reason": "claim-other", "operation_id": "reown-2"}},
    ).status_code == 403

    # 4. create_player_character stamps owner_username from signed-in user at top level.
    import sqlite3
    values = [(r, 6, 7, 7, 3, 8, 6, 5, 5, 6, 5) for r in range(1, 11)]
    solo_text = "▶Solo\nRoll\nINT\nREF\nDEX\nTECH\nCOOL\nWILL\nLUCK\nMOVE\nBODY\nEMP\n" + "\n".join(str(n) for row in values for n in row)
    skills_tbl = "| Media |  | Lawman |  | Exec |  | Fixer |  | Nomad |  | Rockerboy |  | Solo |  | Netrunner |  | Tech |  | Medtech |\n"
    skills_tbl += "| Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl | Skill | Lvl |\n"
    skills_tbl += "\n".join(f"| Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 | Skill {i} | 4 |" for i in range(20))
    basics = ["Athletics", "Brawling", "Concentration", "Conversation", "Education", "Evasion", "First Aid", "Human Perception", "Language (Streetslang)", "Local Expert (Your Home)", "Perception", "Persuasion", "Stealth"]
    defs = "\n".join(f"{name}........INT" for name in basics + [f"Skill {i}" + (" (x2)" if i == 0 else "") for i in range(20)])
    p74_txt = solo_text + "\n" + skills_tbl
    with sqlite3.connect(rules_db) as rconn:
        rconn.execute(
            "INSERT OR REPLACE INTO pages(pdf_page, printed_page, header, text, chars) VALUES(74, 73, '', ?, ?)",
            (p74_txt, len(p74_txt)),
        )
    from tests.rules_fixture import add_skill_definitions
    add_skill_definitions(rules_db, defs.splitlines())

    created_pc_res = client.post(
        "/v1/game",
        headers=alice_headers,
        json={
            "action": "create_player_character",
            "campaign_id": camp["id"],
            "auto_revision": True,
            "arguments": {
                "name": "CreatedSolo",
                "role": "Solo",
                "method": "streetrat",
                "handle": "CreatedSolo",
                "lifepath": {},
                "expected_revision": 0,
                "reason": "new pc",
                "operation_id": "cpc-alice-1",
            },
        },
    )
    assert created_pc_res.status_code == 200, created_pc_res.text
    created_cid = created_pc_res.json()["result"]["result"]["character_id"]
    fetched_created = client.post(
        "/v1/game",
        headers=alice_headers,
        json={"action": "get_character", "arguments": {"character_id": created_cid}},
    ).json()["result"]
    assert fetched_created["detail"]["owner_username"] == "alice"

    # 5. Message authorship stamping & edit/delete ownership enforcement.
    turn_res = client.post(
        "/v1/chat/turn",
        headers=alice_headers,
        json={"campaign_id": camp["id"], "user_text": "Alice checks the door", "speaker_character_id": alice_pc["id"], "gm_mode": "force_gm"},
    )
    assert turn_res.status_code == 200
    roll_res = client.post(
        "/v1/chat/roll",
        headers=alice_headers,
        json={"campaign_id": camp["id"], "character_id": alice_pc["id"], "stat": "INT", "skill": "Perception", "dv": 13},
    )
    assert roll_res.status_code == 200
    assert roll_res.json()["message"]["metadata"]["author_username"] == "alice"

    tree = client.get("/v1/chat/tree", params={"campaign_id": camp["id"]}, headers=alice_headers).json()
    alice_user_msg = next(m for m in tree["active_branch"] if m["role"] == "user" and "Alice checks the door" in m["content"])
    asst_msg = next(m for m in tree["active_branch"] if m["role"] == "assistant")
    assert alice_user_msg["metadata"]["author_username"] == "alice"

    # Bob cannot update or delete Alice's message; Alice cannot edit/delete GM assistant message.
    assert client.post("/v1/chat/message/update", headers=bob_headers, json={"campaign_id": camp["id"], "message_id": alice_user_msg["id"], "content": "Hacked"}).status_code == 403
    assert client.post("/v1/chat/delete", headers=bob_headers, json={"campaign_id": camp["id"], "message_id": alice_user_msg["id"]}).status_code == 403
    assert client.post("/v1/chat/message/update", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": asst_msg["id"], "content": "Hacked GM"}).status_code == 403
    assert client.post("/v1/chat/delete", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": asst_msg["id"]}).status_code == 403

    # Alice can update and delete her own message; Admin can edit/delete any message.
    assert client.post("/v1/chat/message/update", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": alice_user_msg["id"], "content": "Alice edits her action"}).status_code == 200
    assert client.post("/v1/chat/message/update", headers=admin_headers, json={"campaign_id": camp["id"], "message_id": asst_msg["id"], "content": "GM edited"}).status_code == 200
    # Players may only delete single messages: a branch delete would remove others' replies too.
    assert client.post("/v1/chat/delete", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": roll_res.json()["message"]["id"], "scope": "branch"}).status_code == 403
    assert client.post("/v1/chat/delete", headers=alice_headers, json={"campaign_id": camp["id"], "message_id": roll_res.json()["message"]["id"], "scope": "single"}).status_code == 200
