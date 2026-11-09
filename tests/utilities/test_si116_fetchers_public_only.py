"""SI-116 — the other fetchers of web-influenced URLs reach only the public internet (utils/public_fetch.py).

1.0.0.354 guarded lookup_website and fetch_image. Still open then: search_web (fetches each result page a search
engine chose and gives its text to the model), get_news_summaries' feed reader, and research/link_liveness (a GET on
every cited URL). A hostile page can rank for a query, a feed can list any link, and a model can cite any address.
Each test points one of them at a loopback-only service and requires that the service is never reached.
Offline: the search engine is a stub; the only server is on loopback.
"""
import http.server
import json
import pathlib
import socketserver
import sys
import threading
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import utils.public_fetch as pf  # noqa: E402

SECRET = "INTERNAL-ONLY-5519"
ARTICLE = "/news/world/2026/11/09/internal-admin-report-page-123"     # passes the article-URL gates


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(pf, 'settings', lambda: {'max_redirects': 3, 'timeout_seconds': 5, 'connect_retries': 0})


@pytest.fixture
def internal():
    state = {'hits': 0}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state['hits'] += 1
            body = (f"<?xml version='1.0'?><rss><channel><item><title>{SECRET}</title>"
                    f"<link>https://www.bbc.com/news/world-middle-east-67890123</link>"
                    f"<description>{SECRET} {SECRET} {SECRET} {SECRET} {SECRET}</description></item>"
                    f"</channel></rss>" if 'rss' in self.path else
                    f"<html><body><p>{SECRET} " + "secret paragraph text " * 10 + "</p></body></html>").encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/rss+xml' if 'rss' in self.path else 'text/html')
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state['base'] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield state
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope='module')
def F():
    import fastapi_server_complete as server
    return server


def test_search_web_never_fetches_an_internal_result(internal, F, monkeypatch):
    """A search result pointing inward: its page must not be fetched, and its text must not reach the model."""
    url = internal['base'] + ARTICLE

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def text(self, query, max_results=3, backend=None):
            return [{'title': 'Result', 'href': url, 'body': 'snippet'}]

    monkeypatch.setitem(sys.modules, 'ddgs', types.SimpleNamespace(DDGS=FakeDDGS))
    monkeypatch.delitem(sys.modules, 'ddgs.engines', raising=False)
    import asyncio
    out = asyncio.run(F.AsyncToolManager.search_web(None, json.dumps({'query': 'si116 probe'})))
    assert internal['hits'] == 0, 'search_web fetched an internal address'
    assert SECRET not in out


def test_news_feed_reader_never_fetches_an_internal_feed(internal, F):
    blocks, n = F._get_news_content_with_article_urls(internal['base'] + '/feed.rss', 1)
    assert internal['hits'] == 0, 'the news feed reader fetched an internal address'
    assert SECRET not in blocks and n == 0


def test_link_liveness_never_requests_an_internal_citation(internal):
    """A cited internal address is not requested at all, and it is dropped: no reader can open it."""
    import research.link_liveness as ll
    assert ll.verify_url_live(internal['base'] + ARTICLE, timeout=2) is False
    assert internal['hits'] == 0, 'link_liveness requested an internal address'


def test_link_liveness_keeps_an_unresolvable_host(monkeypatch):
    """Lenient as before: a DNS failure is a network hiccup, not proof the article is gone."""
    import research.link_liveness as ll

    def unresolved(*a, **k):
        raise pf.HostUnresolved("refused: the host 'x' could not be resolved")
    monkeypatch.setattr(pf, 'get', unresolved)
    assert ll.verify_url_live('https://news.example/world/2026/a-story-123', timeout=1) is True


def test_a_public_page_is_still_fetched(internal, F, monkeypatch):
    """Positive control: with loopback counted as public, the same calls reach the service — so the tests above
    measure the guard, not a broken fetch."""
    real = pf._is_public
    monkeypatch.setattr(pf, '_is_public', lambda ip: ip == '127.0.0.1' or real(ip))
    import research.link_liveness as ll
    assert ll.verify_url_live(internal['base'] + ARTICLE, timeout=2) is True
    F._get_news_content_with_article_urls(internal['base'] + '/feed.rss', 1)
    assert internal['hits'] >= 2


def test_no_fetcher_of_web_urls_bypasses_public_fetch():
    """Identifiers only (comments and docstrings stripped): the fetch paths use public_fetch, not a direct client."""
    import ast
    src = (ROOT / 'fastapi_server_complete.py').read_text()
    tree = ast.parse(src)
    names = {'search_web', 'get_news_summaries', '_get_news_content_with_article_urls'}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            found.add(node.name)
            calls = {ast.unparse(c.func) for c in ast.walk(node) if isinstance(c, ast.Call)}
            for direct in ('requests_compatible_get', 'requests.get', 'requests.head', 'trafilatura.fetch_url'):
                assert direct not in calls, f'{node.name} still fetches with {direct}'
    assert found == names
    assert not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == 'lookup_website_old'
                   for n in ast.walk(tree)), 'the unguarded lookup_website_old is back'
    ll = ast.parse((ROOT / 'research' / 'link_liveness.py').read_text())
    calls = {ast.unparse(c.func) for c in ast.walk(ll) if isinstance(c, ast.Call)}
    assert 'requests_compatible_get' not in calls and 'public_fetch.get' in calls
