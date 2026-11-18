import asyncio

import httpx
import pytest

from campaign import STAT_NAMES
from gameplay import GameplayService
from redkb import make_api


def test_campaign_scope_and_snapshot_survive_restart(tmp_path):
    path = tmp_path / "campaign.sqlite"
    game = GameplayService(path)
    a = game.execute("create_campaign", {"name": "Night City", "operation_id": "campaign-a"})["result"]
    b = game.execute("create_campaign", {"name": "Badlands", "operation_id": "campaign-b"})["result"]
    char = game.execute("create_character", {"name": "Solo", "stats": dict.fromkeys(STAT_NAMES, 6),
                        "operation_id": "character"}, campaign_id=a["id"])["result"]
    game.execute("attach_character", {"character_id": char["id"], "expected_revision": 1,
                 "reason": "player character", "operation_id": "attach"}, campaign_id=a["id"])
    game.execute("update_campaign", {"expected_revision": 2, "changes": {
        "scene": "Outside the clinic", "npcs": {"Mara": "The ripperdoc owes the crew a favor"}},
        "reason": "scene established", "operation_id": "memory"}, campaign_id=a["id"])
    reopened = GameplayService(path)
    snapshot = reopened.execute("campaign_context", {}, campaign_id=a["id"])["result"]
    assert snapshot["campaign"]["revision"] == 3
    assert snapshot["campaign"]["state"]["scene"] == "Outside the clinic"
    assert [c["id"] for c in snapshot["characters"]] == [char["id"]]
    assert reopened.execute("list_characters", {}, campaign_id=b["id"])["result"] == []
    with pytest.raises(ValueError, match="not attached"):
        reopened.execute("get_character", {"character_id": char["id"]}, campaign_id=b["id"])
    with pytest.raises(ValueError, match="another campaign"):
        reopened.execute("get_campaign", {"campaign_id": a["id"]}, campaign_id=b["id"])


def test_operation_ids_cannot_cross_memory_and_mechanics(tmp_path):
    game = GameplayService(tmp_path / "campaign.sqlite")
    game.execute("create_campaign", {"name": "Test", "operation_id": "shared"})
    with pytest.raises(ValueError, match="campaign change"):
        game.execute("roll_dice", {"count": 1, "sides": 6, "operation_id": "shared", "reason": "test"})
    with pytest.raises(ValueError, match="campaign change"):
        game.execute("create_character", {"name": "Test", "stats": dict.fromkeys(STAT_NAMES, 6), "operation_id": "shared"})


def test_scoped_campaign_http_contract(tmp_path):
    async def run():
        path = tmp_path / "campaign.sqlite"
        app = make_api(tmp_path / "rules.sqlite", campaign_path=path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            response = await client.post("/v1/game", json={"action": "create_campaign", "arguments": {
                "name": "Night City", "operation_id": "create"}})
            assert response.status_code == 200
            campaign = response.json()["result"]
            response = await client.post("/v1/game", json={"action": "update_campaign", "campaign_id": campaign["id"],
                "arguments": {"expected_revision": 1, "changes": {"scene": "The Afterlife"}, "reason": "arrived", "operation_id": "update"}})
            assert response.status_code == 200
            assert response.json()["result"]["state"]["scene"] == "The Afterlife"
            response = await client.post("/v1/game", json={"action": "campaign_context", "campaign_id": campaign["id"], "arguments": {}})
            assert response.status_code == 200
            assert response.json()["result"]["campaign"]["revision"] == 2
            response = await client.post("/v1/game", json={"action": "campaign_context", "campaign_id": None, "arguments": {}})
            assert response.status_code == 400
    asyncio.run(run())


def test_scoped_actions_do_not_rebuild_full_campaign_context(tmp_path, monkeypatch):
    game = GameplayService(tmp_path / "campaign.sqlite")
    camp = game.execute("create_campaign", {"name": "Night City", "operation_id": "c1"})["result"]
    char = game.execute("create_character", {"name": "Solo", "stats": dict.fromkeys(STAT_NAMES, 6),
                        "operation_id": "ch1"}, campaign_id=camp["id"])["result"]
    game.execute("attach_character", {"character_id": char["id"], "expected_revision": 1,
                 "reason": "attach", "operation_id": "a1"}, campaign_id=camp["id"])

    def fail_context(_campaign_id):
        raise AssertionError("campaign_context should not be called for scoped roll/character actions")

    monkeypatch.setattr(game, "campaign_context", fail_context)
    rolled = game.execute("roll_dice", {"count": 1, "sides": 10, "reason": "test", "operation_id": "r1"},
                          campaign_id=camp["id"])
    assert len(rolled["result"]["dice"]) == 1
    fetched = game.execute("get_character", {"character_id": char["id"]}, campaign_id=camp["id"])
    assert fetched["result"]["id"] == char["id"]
    listed = game.execute("list_characters", {}, campaign_id=camp["id"])
    assert [c["id"] for c in listed["result"]] == [char["id"]]
