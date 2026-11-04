"""Contract and regression tests for public-news, user-triggered monitoring."""
import os
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('API_KEY','this_is_only_a_test_secret_32_chars_long')
from bot.server import app
from bot import monitor

KEY={'X-API-Key':os.environ['API_KEY']}

FLAMENGO_HTML = b'''<!doctype html><a href="/noticias/ingressos/flamengo-x-vasco-informacoes-sobre-ingressos">Flamengo x Vasco: ingressos para o classico</a>
<a href="/noticias/ingressos/flamengo-x-botafogo">Flamengo x Botafogo: venda de ingressos</a>
<a href="https://evil.example/noticias/ingressos/captura">Ingressos falsos</a>
<a href="/noticias/futebol/placar">Placar</a>'''
VASCO_HTML=b'<a href="/vasco/informacoes-sobre-ingressos-vasco-x-palmeiras-2026/">Informacoes sobre ingressos Vasco x Palmeiras</a>'

@pytest.fixture
async def client(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'tickets.sqlite3'))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as http:
        yield http

def fake_fetch(url):
    return FLAMENGO_HTML if 'flamengo' in url else VASCO_HTML


def test_link_extraction_is_same_origin_and_ticket_only():
    results=monitor.extract_articles('Flamengo', 'https://www.flamengo.com.br/noticias/ingressos', FLAMENGO_HTML)
    assert len(results)==2
    assert all(a['url'].startswith('https://www.flamengo.com.br/noticias/ingressos/') for a in results)
    assert all('evil.example' not in a['url'] for a in results)


def test_redirect_guard_rejects_untrusted_destination():
    redirect=monitor.StrictSameHostRedirectHandler('www.flamengo.com.br')
    with pytest.raises(ValueError):
        redirect.redirect_request(None,None,302,'https://evil.example/index',{}, 'https://evil.example/index')

@pytest.mark.anyio
async def test_monitor_requires_key_and_does_not_start_scan_automatically(client,monkeypatch):
    attempts=[]
    monkeypatch.setattr(monitor,'fetch_public_page',lambda url: attempts.append(url))
    assert (await client.get('/api/monitor/status')).status_code==403
    assert (await client.post('/api/monitor/scan')).status_code==403
    r=await client.get('/api/monitor/status',headers=KEY)
    assert r.status_code==200
    assert r.json()['announcements']==[]
    assert attempts==[]

@pytest.mark.anyio
async def test_first_scan_baselines_without_alerts_and_is_persistent(client,monkeypatch):
    monkeypatch.setattr(monitor,'fetch_public_page',fake_fetch)
    r=await client.post('/api/monitor/scan',headers=KEY)
    assert r.status_code==200,r.text
    d=r.json()
    assert d['outcome']=='ok'
    assert d['new_count']==0
    assert len(d['announcements'])==3
    stored=(await client.get('/api/monitor/status',headers=KEY)).json()
    assert len(stored['announcements'])==3
    assert stored['new_count']==0
    assert all(s['error'] is None for s in stored['sources'])

@pytest.mark.anyio
async def test_new_item_generates_single_alert_without_duplicates(client,monkeypatch):
    monkeypatch.setattr(monitor,'fetch_public_page',fake_fetch)
    assert (await client.post('/api/monitor/scan',headers=KEY)).status_code==200
    new_html=FLAMENGO_HTML+b'<a href="/noticias/ingressos/flamengo-x-gremio">Nova informacao de ingressos</a>'
    monkeypatch.setattr(monitor,'fetch_public_page',lambda url: new_html if 'flamengo' in url else VASCO_HTML)
    d=(await client.post('/api/monitor/scan',headers=KEY)).json()
    assert len(d['announcements'])==4
    assert d['new_count']==1
    again=(await client.post('/api/monitor/scan',headers=KEY)).json()
    assert again['new_count']==1
    assert len(again['announcements'])==4
    ack=(await client.post('/api/monitor/ack',headers=KEY)).json()
    assert ack['new_count']==0

@pytest.mark.anyio
async def test_partial_failure_is_visible_and_other_club_continues(client,monkeypatch):
    def broken(url):
        if 'vasco.com.br' in url: raise TimeoutError('Tempo limite de acesso')
        return FLAMENGO_HTML
    monkeypatch.setattr(monitor,'fetch_public_page',broken)
    result=(await client.post('/api/monitor/scan',headers=KEY)).json()
    assert result['outcome']=='partial_failure'
    assert len(result['announcements'])==2
    vasco=next(s for s in result['sources'] if s['club']=='Vasco')
    assert 'Tempo limite' in vasco['error']
    assert result['new_count']==0

@pytest.mark.anyio
async def test_no_match_must_be_error_not_empty_success(client,monkeypatch):
    monkeypatch.setattr(monitor,'fetch_public_page',lambda url:b'<html><body>0 noticias no momento</body></html>')
    result=(await client.post('/api/monitor/scan',headers=KEY)).json()
    assert result['outcome']=='failed'
    assert result['announcements']==[]
    assert all(s['error'] for s in result['sources'])

@pytest.mark.anyio
async def test_source_unavailable_is_reported_without_leaking_secret(client,monkeypatch):
    monkeypatch.setattr(monitor,'fetch_public_page',lambda url:(_ for _ in ()).throw(RuntimeError('403 - Access denied')))
    r=await client.post('/api/monitor/scan',headers=KEY)
    assert r.status_code==200
    assert '403 - Access denied' in r.text
    assert KEY['X-API-Key'] not in r.text

