"""Regression tests for auth, ownership, redaction, and origin hardening."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from auth import AuthManager
import redkb
from tests.test_library import _create_rules_db

_BOOTSTRAP = "test-bootstrap-token-" + ("a" * 40)
_STATS = {s: 6 for s in ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")}


def _app(tmp_path: Path, **kwargs):
    rules_db = _create_rules_db(tmp_path / "rules.sqlite")
    return redkb.make_api(rules_db, (), tmp_path / "campaign.sqlite", **kwargs)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _table(tmp_path: Path, **setup):
    """App with an Admin ("gm"), self-signup, and the given extra setup fields."""
    client = TestClient(_app(tmp_path))
    boot = client.post("/v1/auth/setup", json={
        "bootstrap_token": _BOOTSTRAP,
        "admin_username": "gm",
        "admin_password": "gm-password-1",
        "allow_self_signup": True,
        **setup,
    })
    assert boot.status_code == 200, boot.text
    client.cookies.clear()
    return client, _bearer(boot.json()["token"])


def _register(client: TestClient, username: str) -> dict[str, str]:
    res = client.post("/v1/auth/register", json={"username": username, "password": f"{username}-password"})
    assert res.status_code == 200, res.text
    client.cookies.clear()
    return _bearer(res.json()["token"])


def _game(client, headers, action, arguments, campaign_id=None, **extra):
    body = {"action": action, "arguments": arguments, **extra}
    if campaign_id is not None:
        body["campaign_id"] = campaign_id
    return client.post("/v1/game", headers=headers, json=body)


def _campaign_with_secret_pc(client, admin, owner_headers):
    camp = _game(client, admin, "create_campaign", {"name": "Night City", "operation_id": "c1"}).json()["result"]
    pc = _game(client, owner_headers, "create_character", {
        "name": "Alice Real",
        "stats": _STATS,
        "operation_id": "pc1",
        "detail": {"handle": "Spark", "real_name": "Alice Real", "real_name_hidden": True,
                   "backstory": {"secret": "Arasaka mole", "private": True}},
    }).json()["result"]
    assert _game(client, admin, "attach_character", {"character_id": pc["id"], "expected_revision": 1, "reason": "join", "operation_id": "att1"},
                 campaign_id=camp["id"], auto_revision=True).status_code == 200
    changes = {"unresolved": {"Mole": "Alice is a mole"}, "discoveries": {"__npc_identities": "{}", "Clue": "public"}}
    assert _game(client, admin, "update_campaign", {"expected_revision": 2, "changes": changes, "reason": "prep", "operation_id": "u1"},
                 campaign_id=camp["id"]).status_code == 200
    return camp, pc


def test_shared_passcode_login_cannot_impersonate_named_account(tmp_path):
    client, admin = _table(tmp_path, user_passcode="table-code")
    alice = _register(client, "alice")
    camp, alice_pc = _campaign_with_secret_pc(client, admin, alice)

    login = client.post("/v1/auth/login", json={"mode": "user", "username": "alice", "password": "table-code"})
    assert login.status_code == 200
    assert login.json()["username"] == "player"
    client.cookies.clear()
    shared = _bearer(login.json()["token"])

    denied = _game(client, shared, "update_character", {"character_id": alice_pc["id"], "expected_revision": 1, "changes": {"money": 9}, "reason": "x", "operation_id": "steal"},
                   campaign_id=camp["id"], auto_revision=True)
    assert denied.status_code == 403
    seen = _game(client, shared, "get_character", {"character_id": alice_pc["id"]}).json()["result"]
    assert "secret" not in json.dumps(seen["detail"])

    # The shared identity is reserved, so no account can ever own as "player".
    assert client.post("/v1/auth/register", json={"username": "Player", "password": "pw-1234"}).status_code == 400


def test_account_update_requires_account_token_and_is_rate_limited(tmp_path):
    client, admin = _table(tmp_path, user_passcode="table-code")
    alice = _register(client, "alice")

    shared = _bearer(client.post("/v1/auth/login", json={"password": "table-code"}).json()["token"])
    client.cookies.clear()
    assert client.post("/v1/auth/me", headers=shared, json={"current_password": "table-code", "new_password": "new-pass"}).status_code == 403

    for _ in range(12):
        res = client.post("/v1/auth/me", headers=alice, json={"current_password": "wrong", "new_password": "new-pass"})
        assert res.status_code == 400
    blocked = client.post("/v1/auth/me", headers=alice, json={"current_password": "alice-password", "new_password": "new-pass"})
    assert blocked.status_code == 429


def test_player_game_reads_strip_gm_only_state(tmp_path):
    client, admin = _table(tmp_path)
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    camp, alice_pc = _campaign_with_secret_pc(client, admin, alice)

    campaigns = _game(client, bob, "list_campaigns", {}).json()["result"]
    state = campaigns[0]["state"]
    assert state["unresolved"] == {} and "__npc_identities" not in state["discoveries"]

    history = _game(client, bob, "campaign_history", {}, campaign_id=camp["id"]).json()["result"]
    assert "Alice is a mole" not in json.dumps(history) and "__npc_identities" not in json.dumps(history)

    audit = _game(client, bob, "history", {"character_id": alice_pc["id"]}).json()["result"]
    solo = _game(client, bob, "solo_context", {}, campaign_id=camp["id"]).json()["result"]
    context = _game(client, bob, "campaign_context", {}, campaign_id=camp["id"]).json()["result"]
    for payload in (audit, solo, context):
        dumped = json.dumps(payload)
        assert "Arasaka mole" not in dumped and "Alice Real" not in dumped

    # The owner and the GM still see everything.
    assert "Arasaka mole" in json.dumps(_game(client, alice, "history", {"character_id": alice_pc["id"]}).json()["result"])
    assert "Alice is a mole" in json.dumps(_game(client, admin, "list_campaigns", {}).json()["result"])

    moved = client.post(f"/v1/campaigns/{camp['id']}/party-location", headers=alice,
                        json={"pc_locations": {alice_pc["id"]: "Afterlife"}})
    assert moved.status_code == 200, moved.text
    assert "Alice is a mole" not in json.dumps(moved.json()["campaign"])


def test_players_cannot_undo_solo_actions_or_drive_others_netruns(tmp_path):
    client, admin = _table(tmp_path)
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    camp, alice_pc = _campaign_with_secret_pc(client, admin, alice)

    undo = _game(client, bob, "undo_action", {"expected_revision": 0, "reason": "oops", "operation_id": "undo1"}, campaign_id=camp["id"])
    assert undo.status_code == 403

    import sqlite3
    runtime = {
        "encounter": None,
        "architectures": {"arch": {"floors": [], "access_points": []}},
        "runs": {"run-1": {"character_id": alice_pc["id"], "architecture_id": "arch", "discovered": []}},
        "clock_minutes": 0,
    }
    with sqlite3.connect(tmp_path / "campaign.sqlite") as conn:
        conn.execute("INSERT INTO solo_state VALUES(?,?,?)", (camp["id"], 1, json.dumps(runtime)))
    net = _game(client, bob, "net_action", {"run_id": "run-1", "action": "pathfinder", "expected_revision": 1, "reason": "hack", "operation_id": "net1"},
                campaign_id=camp["id"])
    assert net.status_code == 403
    missing = _game(client, admin, "net_action", {"run_id": "nope", "action": "pathfinder", "expected_revision": 1, "reason": "hack", "operation_id": "net2"},
                    campaign_id=camp["id"])
    assert missing.status_code == 400 and "Unknown NET run" in missing.json()["detail"]
    no_action = _game(client, admin, "net_action", {"run_id": "run-1", "expected_revision": 1, "reason": "hack", "operation_id": "net3"},
                      campaign_id=camp["id"])
    assert no_action.status_code == 400


def test_public_bind_never_grants_unauthenticated_admin(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, server_host="0.0.0.0"))
    assert client.get("/v1/settings/all").status_code == 401
    assert client.post("/v1/auth/setup", json={"bootstrap_token": _BOOTSTRAP, "admin_password": "gm-password-1"}).status_code == 200

    settings = tmp_path / "unconfigured.json"
    monkeypatch.delenv("REDGM_BOOTSTRAP_TOKEN")
    with pytest.raises(ValueError, match="Refusing to listen"):
        redkb.check_public_bind_auth("0.0.0.0", settings_path=settings)
    redkb.check_public_bind_auth("127.0.0.1", settings_path=settings)
    redkb.check_public_bind_auth("0.0.0.0", "1234", settings_path=settings)
    monkeypatch.setenv("REDGM_BOOTSTRAP_TOKEN", _BOOTSTRAP)
    redkb.check_public_bind_auth("0.0.0.0", settings_path=settings)


def test_account_rename_moves_ownership_atomically_and_delete_releases_it(tmp_path, monkeypatch):
    import auth as auth_module
    from gameplay import GameplayService
    from turnloop import ChatTreeStore

    client, admin = _table(tmp_path)
    alice = _register(client, "alice")
    camp, alice_pc = _campaign_with_secret_pc(client, admin, alice)
    svc = GameplayService(tmp_path / "campaign.sqlite", tmp_path / "rules.sqlite")
    store = ChatTreeStore(svc)
    msg = store.append_message(camp["id"], parent_id=None, role="user", content="hi", campaign_revision=1, solo_revision=0,
                               metadata={"author_username": "alice"})

    def owner():
        return svc.store.get_character(alice_pc["id"])["detail"].get("owner_username")

    def author():
        return store.get_message(camp["id"], msg["id"])["metadata"].get("author_username")

    # A failed account write rolls back the ownership move.
    def broken_write(doc, path):
        raise OSError("disk full")
    with monkeypatch.context() as patch:
        patch.setattr(auth_module, "write_settings_doc", broken_write)
        with pytest.raises(OSError):
            AuthManager().update_self_account("alice", current_password="alice-password", new_username="alice2",
                                              owner_transfer=lambda o, n: svc.store.transfer_owner(o, n, set()))
    assert owner() == "alice" and author() == "alice"

    renamed = client.post("/v1/auth/me", headers=alice, json={"current_password": "alice-password", "new_username": "alice2"})
    assert renamed.status_code == 200, renamed.text
    assert owner() == "alice2" and author() == "alice2"

    assert client.delete("/v1/auth/accounts/alice2", headers=admin).status_code == 200
    assert owner() is None and author() is None
    newcomer = _register(client, "alice2")
    denied = _game(client, newcomer, "get_character", {"character_id": alice_pc["id"]}).json()["result"]
    assert "Arasaka mole" not in json.dumps(denied)
