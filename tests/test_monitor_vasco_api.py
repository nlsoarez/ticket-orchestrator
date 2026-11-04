"""Contracts for the public Vasco news JSON response observed in DevTools."""
import json
import os
import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault('API_KEY', 'this_is_only_a_test_secret_32_chars_long')
from bot import monitor
from bot.server import app

HEADERS = {'X-API-Key': os.environ['API_KEY']}


def payload(items, header=None):
    return json.dumps({'header': header or {'codigo': 1, 'msg': 'Ok.'},
                       'data': {'items': items, 'page': 1, 'size': 13}}, ensure_ascii=False).encode('utf-8')


ITEMS = [
    {'id': 1578710, 'title': 'VascoTV estreia o reality show', 'link': None},
    {'id': 1577773, 'title': 'Informações sobre ingressos – Vasco x Palmeiras – Copa do Brasil 2026', 'link': None},
    {'id': 1573504, 'title': 'CAMAROTE FIREZONE - VASCO X Flamengo', 'link': None},
]


def test_vasco_api_parser_recognizes_only_ticket_announcements():
    found = monitor.extract_vasco_articles(payload(ITEMS))
    assert {x['url'] for x in found} == {'vasco:article:1577773', 'vasco:article:1573504'}
    assert all(x['club'] == 'Vasco' for x in found)
    assert all('VascoTV' not in x['title'] for x in found)


def test_invalid_json_or_api_envelope_fails_closed():
    for response in (b'<html>No articles</html>',
                     payload([], header={'codigo': 0}),
                     b'{"header":{"codigo":1},"data":{"items":"wrong"}}',
                     b'{"header":{"codigo":1},"data":{}}'):
        with pytest.raises(ValueError):
            monitor.extract_vasco_articles(response)


def test_api_does_not_trust_external_article_link():
    found = monitor.extract_vasco_articles(payload([{
        'id': 1577773,
        'title': 'Informações sobre ingressos Vasco x Palmeiras',
        'link': 'https://evil.example/phishing'
    }]))
    assert found[0]['url'] == 'vasco:article:1577773'


@pytest.mark.anyio
async def test_scan_realistic_api_baselines_without_fabricating_article_links(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'tickets.sqlite3'))
    queried = []

    def fetch(url):
        queried.append(url)
        if 'fancontentapi-vasco.vasco.com.br' in url:
            return payload(ITEMS)
        if 'flamengo.com.br' in url:
            return b'<a href="/noticias/ingressos/flamengo-x-vasco">Flamengo x Vasco: venda de ingressos</a>'
        raise AssertionError('Unexpected source URL: ' + url)

    monkeypatch.setattr(monitor, 'fetch_public_page', fetch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/monitor/status', headers=HEADERS)).status_code == 200
        assert queried == []
        response = await client.post('/api/monitor/scan', headers=HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data['outcome'] == 'ok'
        assert data['new_count'] == 0
        assert len(data['announcements']) == 3
        vasco = [x for x in data['announcements'] if x['club'] == 'Vasco']
        assert all(x['open_url'] == 'https://vasco.com.br/noticias/' for x in vasco)
        assert all(x['link_type'] == 'archive' for x in vasco)
        assert next(s for s in data['sources'] if s['club'] == 'Vasco')['url'] == 'https://vasco.com.br/noticias/'
        assert 'fancontentapi-vasco.vasco.com.br' in queried[0]

        response = await client.post('/api/monitor/scan', headers=HEADERS)
        assert response.json()['new_count'] == 0
        assert len(response.json()['announcements']) == 3

        changed = payload(ITEMS + [{'id': 1580000, 'title': 'Venda de ingressos Vasco x Botafogo'}])
        monkeypatch.setattr(monitor, 'fetch_public_page',
                            lambda url: changed if 'fancontentapi-vasco' in url else fetch(url))
        response = await client.post('/api/monitor/scan', headers=HEADERS)
        assert response.json()['new_count'] == 1
        assert len(response.json()['announcements']) == 4


@pytest.mark.anyio
async def test_valid_api_without_ticket_news_is_not_false_failure(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'tickets.sqlite3'))
    monkeypatch.setattr(monitor, 'fetch_public_page',
                        lambda url: payload([{'id': 5, 'title': 'Treino do Vasco hoje'}])
                        if 'fancontentapi-vasco' in url else
                        b'<a href="/noticias/ingressos/flamengo-x-vasco">Flamengo x Vasco: ingressos</a>')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        result = (await client.post('/api/monitor/scan', headers=HEADERS)).json()
        assert result['outcome'] == 'ok'
        assert next(s for s in result['sources'] if s['club'] == 'Vasco')['found_count'] == 0


def test_unlisted_api_endpoints_are_refused_before_network():
    with pytest.raises(ValueError):
        monitor.fetch_public_page('https://evil.example/api/owner/297/newsArticles?page=1&size=13')
