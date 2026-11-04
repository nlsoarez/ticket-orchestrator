"""Schedule is opt-in, persistent and never triggers checkout requests."""
import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('API_KEY', 'this_is_only_a_test_secret_32_chars_long')
from bot.server import app
from bot import monitor, monitor_scheduler
from bot.workspace import database

HEADERS = {'X-API-Key': os.environ['API_KEY']}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'tickets.sqlite3'))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http:
        yield http


@pytest.mark.anyio
async def test_schedule_default_disabled_does_not_scan_on_reads(client, monkeypatch):
    touched = []
    monkeypatch.setattr(monitor, 'fetch_public_page', lambda url: touched.append(url))
    denied = await client.get('/api/monitor/schedule')
    assert denied.status_code == 403
    denied = await client.put('/api/monitor/schedule', json={'enabled': True, 'interval_minutes': 15})
    assert denied.status_code == 403
    result = (await client.get('/api/monitor/schedule', headers=HEADERS)).json()
    assert result['enabled'] is False
    assert result['interval_minutes'] == 30
    assert result['next_run_at'] is None
    assert monitor_scheduler.scheduler_tick() is False
    assert touched == []


@pytest.mark.anyio
async def test_enable_disable_persists_and_validates_intervals(client):
    for mins in (0, 1, 14, 1441):
        r = await client.put('/api/monitor/schedule', headers=HEADERS,
                             json={'enabled': True, 'interval_minutes': mins})
        assert r.status_code == 422
    response = await client.put('/api/monitor/schedule', headers=HEADERS,
                                json={'enabled': True, 'interval_minutes': 15})
    assert response.status_code == 200
    assert response.json()['enabled'] is True
    assert response.json()['next_run_at']
    # Reading state does not reset the planned time.
    next_run = response.json()['next_run_at']
    again = (await client.get('/api/monitor/schedule', headers=HEADERS)).json()
    assert again['next_run_at'] == next_run
    same_settings = (await client.put('/api/monitor/schedule', headers=HEADERS,
                                     json={'enabled': True, 'interval_minutes': 15})).json()
    assert same_settings['next_run_at'] == next_run
    stopped = await client.put('/api/monitor/schedule', headers=HEADERS,
                               json={'enabled': False, 'interval_minutes': 15})
    assert stopped.status_code == 200
    assert stopped.json()['enabled'] is False
    assert stopped.json()['next_run_at'] is None


@pytest.mark.anyio
async def test_due_schedule_scans_once_and_avoids_duplicates(client, monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        if 'fancontentapi-vasco' in url:
            return b'{"header":{"codigo":1},"data":{"items":[{"id":8,"title":"Ingressos Vasco x Flamengo"}]}}'
        return b'<a href="/noticias/ingressos/flamengo-x-vasco">Flamengo x Vasco - ingressos</a>'

    monkeypatch.setattr(monitor, 'fetch_public_page', fetch)
    await client.put('/api/monitor/schedule', headers=HEADERS,
                     json={'enabled': True, 'interval_minutes': 15})
    assert monitor_scheduler.scheduler_tick() is False
    assert calls == []
    with database() as conn:
        conn.execute("UPDATE monitor_schedule SET next_run_at=? WHERE id=1",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert monitor_scheduler.scheduler_tick() is True
    assert len(calls) == 2
    assert monitor_scheduler.scheduler_tick() is False
    assert len(calls) == 2
    state = (await client.get('/api/monitor/schedule', headers=HEADERS)).json()
    assert state['last_run_at'] is not None
    assert state['last_outcome'] == 'ok'
    assert (await client.get('/api/monitor/status', headers=HEADERS)).json()['new_count'] == 0


@pytest.mark.anyio
async def test_busy_manual_scan_does_not_trigger_scheduler(client, monkeypatch):
    await client.put('/api/monitor/schedule', headers=HEADERS,
                     json={'enabled': True, 'interval_minutes': 15})
    with database() as conn:
        conn.execute("UPDATE monitor_schedule SET next_run_at=? WHERE id=1",
                     ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert monitor._scan_lock.acquire(blocking=False)
    try:
        assert monitor_scheduler.scheduler_tick() is False
    finally:
        monitor._scan_lock.release()
    result = (await client.get('/api/monitor/schedule', headers=HEADERS)).json()
    assert result['last_run_at'] is None


def test_first_empty_success_is_baseline_for_future_new_article(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'tickets.sqlite3'))
    monkeypatch.setattr(monitor, 'fetch_public_page', lambda url: b'{"header":{"codigo":1},"data":{"items":[]}}'
                        if 'fancontentapi-vasco' in url else
                        b'<a href="/noticias/ingressos/flamengo-x-vasco">Flamengo x Vasco ingressos</a>')
    assert monitor.scan()['outcome'] == 'ok'
    monkeypatch.setattr(monitor, 'fetch_public_page', lambda url: b'{"header":{"codigo":1},"data":{"items":[{"id":1234,"title":"Ingressos Vasco x Fluminense"}]}}'
                        if 'fancontentapi-vasco' in url else
                        b'<a href="/noticias/ingressos/flamengo-x-vasco">Flamengo x Vasco ingressos</a>')
    result = monitor.scan()
    assert result['new_count'] == 1
