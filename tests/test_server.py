import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("API_KEY", "a_test_only_secret_key_longer_than_32_bytes")
os.environ.setdefault("JOB_DELAY_SECONDS", "0.05")

from bot.server import app, runtime


@pytest.fixture(autouse=True)
async def reset_runtime():
    await runtime.stop()
    runtime.reset_for_tests()
    yield
    await runtime.stop()


@pytest.mark.anyio
async def test_health_is_reachable_without_api_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.anyio
async def test_api_requires_valid_secret():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/api/start")
        wrong = await client.get("/api/status", headers={"X-API-Key": "wrong"})
    assert denied.status_code == 403
    assert wrong.status_code == 403


@pytest.mark.anyio
async def test_start_finished_and_repeat_no_external_calls():
    headers = {"X-API-Key": os.environ["API_KEY"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        initial = (await client.get("/api/status", headers=headers)).json()
        assert initial["status"] == "idle"
        started = await client.post("/api/start", headers=headers)
        assert started.status_code == 200
        assert started.json()["status"] == "started"
        duplicate = (await client.post("/api/start", headers=headers)).json()
        assert duplicate["status"] == "already_running"
        await asyncio.sleep(0.25)
        finished = (await client.get("/api/status", headers=headers)).json()
    assert finished["status"] == "finished"
    assert finished["mode"] == "simulation"
    assert finished["stats"] == {"successes": 0, "failures": 0, "conflicts": 0}


@pytest.mark.anyio
async def test_stop_really_cancels_job():
    headers = {"X-API-Key": os.environ["API_KEY"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/start", headers=headers)
        stop = await client.post("/api/stop", headers=headers)
        await asyncio.sleep(0.08)
        current = (await client.get("/api/status", headers=headers)).json()
    assert stop.status_code == 200
    assert current["status"] == "stopped"
    assert current["progress"] < 100


@pytest.mark.anyio
async def test_root_has_dashboard():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Orchestrator" in response.text


@pytest.mark.anyio
async def test_missing_server_secret_is_configuration_error(monkeypatch):
    monkeypatch.delenv("API_KEY")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/status", headers={"X-API-Key": "irrelevant"})
    assert response.status_code == 503


@pytest.mark.anyio
async def test_start_after_stop_works():
    headers = {"X-API-Key": os.environ["API_KEY"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/start", headers=headers)).json()["status"] == "started"
        assert (await client.post("/api/stop", headers=headers)).json()["status"] == "stopped"
        assert (await client.post("/api/start", headers=headers)).json()["status"] == "started"
    await runtime.stop()


@pytest.mark.anyio
async def test_placeholder_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("API_KEY", "SUBSTITUA_POR_OPENSSL_RAND_HEX_32")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/status", headers={"X-API-Key": "SUBSTITUA_POR_OPENSSL_RAND_HEX_32"})
    assert response.status_code == 503
