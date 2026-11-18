"""Tests for Admin/User authentication, exposed turn options, prompt customization, and server settings."""
from __future__ import annotations

import json
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
from tests.test_library import _create_rules_db
from turnloop import (
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

    async def stream(self, messages, **_kwargs):
        self.stream_calls.append(messages)
        yield "Neon static hangs over the street."


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

    boot_resp = client.post(
        "/v1/auth/setup",
        json={
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

    user_headers = {"X-RedGM-Token": user_token}
    # Normal play features work for User.
    pub = client.get("/v1/settings/public", headers=user_headers)
    assert pub.status_code == 200
    assert pub.json()["role"] == "user"

    created = client.post(
        "/v1/game",
        headers=user_headers,
        json={"action": "create_campaign", "arguments": {"name": "Kabuki Run", "operation_id": "op-1"}},
    )
    assert created.status_code == 200
    assert client.get("/v1/library", headers=user_headers).status_code == 200

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
    admin_headers = {"X-RedGM-Token": admin_token}
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

    # Accounts management: add user, then delete user.
    add_user = client.post(
        "/v1/auth/accounts",
        headers=admin_headers,
        json={"action": "upsert_account", "username": "solo2", "password": "pass-1234", "role": "user"},
    )
    assert add_user.status_code == 200
    assert any(a["username"] == "solo2" for a in add_user.json()["accounts"])

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

    setup = client.post(
        "/v1/auth/setup",
        json={"admin_username": "gm", "admin_password": "admin-password-1", "allow_self_signup": True},
    )
    assert setup.status_code == 200
    admin_token = setup.json()["token"]
    admin_headers = {"X-RedGM-Token": admin_token}

    # Player self-registers without admin creating an account for them.
    client.cookies.clear()
    reg = client.post("/v1/auth/register", json={"username": "choom_alice", "password": "alice-pass"})
    assert reg.status_code == 200
    assert reg.json()["role"] == "user"
    assert reg.json()["username"] == "choom_alice"
    alice_headers = {"X-RedGM-Token": reg.json()["token"]}

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


def test_corebook_upload_and_expanded_settings_prompts(tmp_path, monkeypatch):
    import time
    import pymupdf

    rules_db = tmp_path / "rules.sqlite"
    camp_db = tmp_path / "campaign.sqlite"
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("REDGM_SETTINGS_FILE", str(settings_path))
    app = redkb.make_api(rules_db, (), camp_db, server_host="127.0.0.1", server_port=8765)
    client = TestClient(app)

    setup = client.post(
        "/v1/auth/setup",
        json={"admin_username": "admin", "admin_password": "admin-password-1"},
    )
    assert setup.status_code == 200
    admin_headers = {"X-RedGM-Token": setup.json()["token"]}

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
    p1.insert_text((72, 72), "129\nSkill Checks\nRoll 1d10 + STAT + Skill against a DV.")
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
        },
    )
    assert upd_prompts.status_code == 200
    assert upd_prompts.json()["prompts"]["creation_assist_persona"] == "CUSTOM CREATOR PERSONA"
    assert upd_prompts.json()["prompts"]["narrator_core_rules"] == "CUSTOM CORE RULES"

    # Verify custom narrator_core_rules + enable_highlights=False take effect in TurnEngine
    svc = GameplayService(camp_db, rules_db)
    camp = svc.execute("create_campaign", {"name": "Custom Rules Camp", "operation_id": "crc-1"})["result"]
    llm = RecordingLLM()
    engine = TurnEngine(svc, llm, settings_path=settings_path)
    import asyncio

    async def _run():
        return [ev async for ev in engine.run_turn(camp["id"], "Look around")]

    asyncio.run(_run())
    narrator_sys = llm.stream_calls[0][0]["content"]
    assert "CUSTOM CORE RULES" in narrator_sys
    assert "Visual UI flair" not in narrator_sys
