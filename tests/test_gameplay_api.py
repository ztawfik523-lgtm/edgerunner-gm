import asyncio
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redkb


def test_game_api_lazy_service_and_envelope(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    created = []

    class Service:
        def __init__(self, *args):
            created.append(args)

        def execute(self, action, arguments):
            return {"action": action, "arguments": arguments}

    monkeypatch.setattr("gameplay.GameplayService", Service, raising=False)

    async def run():
        app = redkb.make_api(tmp_path / "rules.sqlite", ("http://localhost:8000",), campaign_path=tmp_path / "campaign.sqlite")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert not created
            response = await client.post("/v1/game", json={"action": "list_characters", "arguments": {}})
            assert response.status_code == 200
            assert response.json()["action"] == "list_characters"
            assert response.json()["request_id"]
            assert len(created) == 1
            bad = await client.post("/v1/game", json={"action": "x", "arguments": []})
            assert bad.status_code == 400 and bad.json()["request_id"]
            blocked = await client.post("/v1/game", json={}, headers={"Origin": "http://evil"})
            assert blocked.status_code == 403
            cross_site = await client.post("/v1/game", json={}, headers={"Sec-Fetch-Site": "cross-site"})
            assert cross_site.status_code == 403
            wrong_type = await client.post("/v1/game", content="{}", headers={"Content-Type": "text/plain"})
            assert wrong_type.status_code == 415
            allowed = await client.post("/v1/game", json={"action": "list_characters", "arguments": {}},
                                        headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "cross-site"})
            assert allowed.status_code == 200
    asyncio.run(run())


def test_game_api_database_collision_rejected_before_service(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")

    async def run():
        path = tmp_path / "same.sqlite"
        app = redkb.make_api(path, campaign_path=path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/game", json={"action": "list_characters", "arguments": {}})
            assert response.status_code == 400
            assert response.json()["request_id"]
            assert not path.exists()
    asyncio.run(run())


def test_game_api_runs_service_off_event_loop_thread(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    loop_thread = threading.current_thread()
    seen_threads = []

    class Service:
        def __init__(self, *args):
            pass

        def execute(self, action, arguments):
            seen_threads.append(threading.current_thread())
            return {"action": action, "arguments": arguments}

    monkeypatch.setattr("gameplay.GameplayService", Service, raising=False)

    async def run():
        app = redkb.make_api(tmp_path / "rules.sqlite", campaign_path=tmp_path / "campaign.sqlite")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/game", json={"action": "list_characters", "arguments": {}})
            assert response.status_code == 200
    asyncio.run(run())
    assert seen_threads and seen_threads[0] is not loop_thread
