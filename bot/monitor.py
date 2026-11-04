"""V3: descoberta MANUAL de notícias públicas de ingressos nos sites dos clubes.

Nenhuma consulta é iniciada no carregamento do painel ou em background.
Nenhum login, checkout, anti-bot, navegador automatizado ou pagamento.
"""
import json
import re
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, HTTPException

from .workspace import database

router = APIRouter(prefix='/api/monitor', tags=['monitoramento-publico'])

# Fonte observada no DevTools do site oficial em 04/11/2026.
# O domínio serve notícias públicas em JSON; não é uma API de venda de ingressos.
VASCO_NEWS_ENDPOINT = 'https://fancontentapi-vasco.vasco.com.br/api/owner/297/newsArticles?page=1&size=13'
SOURCES = (
    {'club': 'Vasco', 'url': 'https://vasco.com.br/noticias/',
     'fetch_url': VASCO_NEWS_ENDPOINT, 'format': 'json'},
    {'club': 'Flamengo', 'url': 'https://www.flamengo.com.br/noticias/ingressos',
     'fetch_url': 'https://www.flamengo.com.br/noticias/ingressos', 'format': 'html'},
)
_ALLOWED_HOSTS = {
    'Vasco': {'vasco.com.br', 'www.vasco.com.br'},
    'Flamengo': {'flamengo.com.br', 'www.flamengo.com.br'},
}
_scan_lock = threading.Lock()


class StrictSameHostRedirectHandler(HTTPRedirectHandler):
    """Nunca seguir redirecionamentos para destinos não esperados."""

    def __init__(self, host):
        self.host = host
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != 'https' or parts.hostname != self.host or parts.port not in (None, 443):
            raise ValueError('Redirecionamento externo recusado')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_public_page(url):
    """Consulta única, limitada, sem enviar credenciais ou seguir hosts externos."""
    parts = urlsplit(url)
    source = next((s for s in SOURCES if url == s['fetch_url']), None)
    if source is None:
        raise ValueError('Fonte fora da lista de sites oficiais permitidos')
    expected = 'json' if source['format'] == 'json' else 'html'
    request = Request(url, headers={
        'User-Agent': 'TicketOrchestrator/3.1 (consulta manual a noticias publicas)',
        'Accept': 'application/json' if expected == 'json' else 'text/html,application/xhtml+xml',
    })
    opener = build_opener(StrictSameHostRedirectHandler(parts.hostname))
    with opener.open(request, timeout=8) as response:
        ctype = response.headers.get('Content-Type', '')
        if expected not in ctype.lower():
            raise ValueError('O site não retornou conteúdo ' + expected.upper())
        data = response.read(600_001)
        if len(data) > 600_000:
            raise ValueError('Página acima do limite de leitura (600 KB)')
        return data


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None
        self.text_parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a' and self.href is None:
            self.href = dict(attrs).get('href') or ''
            self.text_parts = []

    def handle_data(self, data):
        if self.href is not None:
            self.text_parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((self.href, ' '.join(self.text_parts)))
            self.href = None
            self.text_parts = []


def extract_articles(club, base_url, html):
    """Filtra anúncios em links canônicos dentro do domínio oficial."""
    if club not in _ALLOWED_HOSTS:
        raise ValueError('Clube não suportado')
    parser = _Links()
    parser.feed(html.decode('utf-8', errors='replace') if isinstance(html, bytes) else html)
    found = {}
    for href, raw_title in parser.links:
        if not href or href.startswith(('#', 'javascript:', 'data:')):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme != 'https' or parts.hostname not in _ALLOWED_HOSTS[club] or parts.port not in (None, 443):
            continue
        path = parts.path
        if club == 'Flamengo':
            if not path.startswith('/noticias/ingressos/'):
                continue
        else:
            if 'ingress' not in path.lower() and 'ingress' not in raw_title.lower():
                continue
            if path in ('/', '/noticias/', '/ingressos/'):
                continue
        title = re.sub(r'\s+', ' ', raw_title).strip()
        if len(title) < 10:
            continue
        canonical = urlunsplit(('https', parts.hostname, path.rstrip('/') or '/', '', ''))
        if canonical not in found:
            found[canonical] = {'club': club, 'url': canonical, 'title': title[:260]}
        if len(found) >= 30:
            break
    return list(found.values())


# Somente anúncios claramente relacionados a ingressos entram no monitor.
# Não analisar articleBody para evitar falsos positivos em notícias gerais.
_VASCO_TICKET_TITLE = re.compile(r'ingress|bilheteria|informativo de partida|camarote firezone', re.I)


def extract_vasco_articles(raw):
    """Extrai notícias da API pública; IDs estáveis, sem inventar links individuais.

    A resposta atualmente tem link=null em notícias normais. Registramos chave
    sintética por ID e direcionamos o leitor para a seção pública de notícias,
    explicitamente identificada como listagem, não como permalink.
    """
    try:
        document = json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError('Resposta JSON inválida da fonte Vasco') from exc
    if not isinstance(document, dict) or not isinstance(document.get('header'), dict):
        raise ValueError('Cabeçalho da API Vasco ausente')
    if document['header'].get('codigo') != 1:
        raise ValueError('API de notícias do Vasco retornou código de erro')
    data = document.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise ValueError('Lista de notícias da API Vasco ausente')
    articles = {}
    for item in data['items'][:30]:
        if not isinstance(item, dict):
            continue
        article_id = item.get('id')
        title = item.get('title')
        if type(article_id) is not int or article_id < 1 or not isinstance(title, str):
            continue
        title = re.sub(r'\s+', ' ', title).strip()
        if not 10 <= len(title) <= 500 or not _VASCO_TICKET_TITLE.search(title):
            continue
        key = f'vasco:article:{article_id}'
        articles[key] = {'club': 'Vasco', 'url': key, 'title': title[:260]}
    return list(articles.values())


def _public_announcement(row):
    item = dict(row)
    if item['club'] == 'Vasco' and re.fullmatch(r'vasco:article:[1-9]\d*', item['url']):
        item['open_url'] = 'https://vasco.com.br/noticias/'
        item['link_type'] = 'archive'
    else:
        item['open_url'] = item['url']
        item['link_type'] = 'article'
    return item


def _init(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS monitor_announcements (
        club TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
        discovered_at TEXT NOT NULL, is_new INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(club,url)
    );
    CREATE TABLE IF NOT EXISTS monitor_sources (
        club TEXT PRIMARY KEY, url TEXT NOT NULL,
        last_attempt TEXT, last_success TEXT, last_error TEXT, last_count INTEGER NOT NULL DEFAULT 0
    );
    ''')


def _now():
    return datetime.now(timezone.utc).isoformat()


def monitor_status():
    with database() as conn:
        _init(conn)
        rows = {r['club']: dict(r) for r in conn.execute('SELECT * FROM monitor_sources').fetchall()}
        announcements = [_public_announcement(r) for r in conn.execute('''
            SELECT club, url, title, discovered_at, is_new
            FROM monitor_announcements ORDER BY discovered_at DESC, club, url LIMIT 60
        ''').fetchall()]
        pending = conn.execute('SELECT COUNT(*) FROM monitor_announcements WHERE is_new=1').fetchone()[0]
    return {
        'mode': 'manual_public_news_only',
        'sources': [
            {'club': s['club'], 'url': s['url'], 'last_attempt': rows.get(s['club'], {}).get('last_attempt'),
             'last_success': rows.get(s['club'], {}).get('last_success'),
             'error': rows.get(s['club'], {}).get('last_error'),
             'found_count': rows.get(s['club'], {}).get('last_count', 0)}
            for s in SOURCES
        ],
        'announcements': announcements,
        'new_count': pending,
    }


@router.get('/status')
def status():
    return monitor_status()


@router.post('/scan')
def scan():
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail='Já existe uma consulta em andamento')
    success, failure = 0, 0
    try:
        for source in SOURCES:
            club, url = source['club'], source['url']
            attempt = _now()
            try:
                data = fetch_public_page(source['fetch_url'])
                if source['format'] == 'json':
                    articles = extract_vasco_articles(data)
                else:
                    articles = extract_articles(club, url, data)
                    if not articles:
                        raise ValueError('Nenhuma notícia de ingressos identificada; estrutura do site pode ter mudado')
                with database() as conn:
                    _init(conn)
                    has_baseline = conn.execute('SELECT 1 FROM monitor_announcements WHERE club=? LIMIT 1', (club,)).fetchone()
                    for item in articles:
                        conn.execute('''INSERT OR IGNORE INTO monitor_announcements
                            (club, url, title, discovered_at, is_new) VALUES(?,?,?,?,?)''',
                            (club, item['url'], item['title'], attempt, int(bool(has_baseline))))
                    conn.execute('''INSERT INTO monitor_sources (club,url,last_attempt,last_success,last_error,last_count)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(club) DO UPDATE SET
                        url=excluded.url,last_attempt=excluded.last_attempt,last_success=excluded.last_success,
                        last_error=NULL,last_count=excluded.last_count''',
                        (club, url, attempt, attempt, None, len(articles)))
                success += 1
            except Exception as exc:
                # Não incluir traceback, chave de API ou payload de páginas nos retornos.
                reason = str(exc).strip()[:170] or type(exc).__name__
                with database() as conn:
                    _init(conn)
                    conn.execute('''INSERT INTO monitor_sources (club,url,last_attempt,last_error) VALUES(?,?,?,?)
                        ON CONFLICT(club) DO UPDATE SET last_attempt=excluded.last_attempt,
                        last_error=excluded.last_error''', (club, url, attempt, reason))
                failure += 1
        result = monitor_status()
        result['outcome'] = 'ok' if not failure else ('partial_failure' if success else 'failed')
        return result
    finally:
        _scan_lock.release()


@router.post('/ack')
def acknowledge():
    with database() as conn:
        _init(conn)
        conn.execute('UPDATE monitor_announcements SET is_new=0 WHERE is_new=1')
    return monitor_status()
