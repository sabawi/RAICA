"""utils/public_fetch.py — a model-chosen URL reaches only the public internet (docs/DESIGN_fetch_image_and_public_fetch.md §3).

Measured 2026-11-09, before this module: trafilatura.fetch_url and requests.get both read a loopback-only service and
returned its text; lookup_website checked nothing first. Each test below names the attack it blocks and goes red when
its own control is removed (plants recorded in the design doc §8). Offline: the only servers are on loopback, and
"public" is simulated by marking ONE loopback address public for the test that needs it.
"""
import http.server
import pathlib
import socketserver
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import utils.public_fetch as pf  # noqa: E402

SECRET = b"INTERNAL-ONLY-7731"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(pf, 'settings', lambda: {'max_redirects': 3, 'timeout_seconds': 5, 'connect_retries': 0})


@pytest.fixture
def server():
    """A loopback-only service; `redirect_to` makes it answer 302 to that address instead."""
    state = {'redirect_to': None, 'hits': 0}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            state['hits'] += 1
            if state['redirect_to']:
                self.send_response(302)
                self.send_header('Location', state['redirect_to'])
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(SECRET * 100)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state['port'] = srv.server_address[1]
    yield state
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize('url', [
    'http://127.0.0.1/', 'http://localhost/', 'http://10.0.0.1/', 'http://192.168.1.10/', 'http://172.16.0.1/',
    'http://169.254.169.254/latest/meta-data/',          # cloud metadata service
    'http://0.0.0.0/', 'http://[::1]/', 'http://[::ffff:127.0.0.1]/', 'http://[fd00::1]/', 'http://100.64.0.1/',
])
def test_internal_addresses_are_refused(url):
    """The direct attack: "read http://127.0.0.1:5000/…" or the metadata service."""
    with pytest.raises(pf.PublicFetchRefused):
        pf.check_url(url)


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'gopher://example.com/', 'ftp://example.com/x', 'x'])
def test_only_http_and_https(url):
    with pytest.raises(pf.PublicFetchRefused):
        pf.check_url(url)


def test_a_public_address_is_allowed():
    """Positive control: without it, a check that refuses everything would pass every test above."""
    pf.check_url('http://93.184.216.34/')
    pf.check_url('https://[2606:2800:220:1:248:1893:25c8:1946]/')


def test_get_refuses_loopback_and_never_connects(server):
    with pytest.raises(pf.PublicFetchRefused):
        pf.get(f"http://127.0.0.1:{server['port']}/")
    assert server['hits'] == 0, 'the internal service was reached'


def test_redirect_to_an_internal_address_is_refused(server, monkeypatch):
    """A public page that redirects inward. Simulated: 127.0.0.1 counts as public, 127.0.0.2 does not."""
    real = pf._is_public
    monkeypatch.setattr(pf, '_is_public', lambda ip: ip == '127.0.0.1' or real(ip))
    server['redirect_to'] = f"http://127.0.0.2:{server['port']}/"
    with pytest.raises(pf.PublicFetchRefused):
        pf.get(f"http://127.0.0.1:{server['port']}/")
    assert server['hits'] == 1, 'the second hop must never be requested'


def test_dns_rebinding_is_caught_at_the_connected_peer(server, monkeypatch):
    """The name looked public when checked, then connected to loopback: the peer check refuses before a request
    byte is sent. Simulated by holding the pre-connect check open."""
    monkeypatch.setattr(pf, 'check_url', lambda url: None)
    with pytest.raises(Exception) as e:
        pf.get(f"http://127.0.0.1:{server['port']}/")
    assert 'non-public' in str(e.value)
    assert server['hits'] == 0, 'a request reached the internal service'


def test_connection_retries_come_from_config_and_never_retry_a_refusal(server, monkeypatch):
    """SI-116: search and news moved here from a session that retried failed connections 3 times; the retries are
    kept (public_fetch.connect_retries), and a peer refusal is not a connection error, so it is not retried."""
    monkeypatch.setattr(pf, 'settings', lambda: {'max_redirects': 3, 'timeout_seconds': 5, 'connect_retries': 3})
    assert pf.session(3).get_adapter('https://example.org/').max_retries.total == 3
    monkeypatch.setattr(pf, 'check_url', lambda url: None)
    calls = {'n': 0}
    real = pf._check_peer

    def counting(sock, host):
        calls['n'] += 1
        return real(sock, host)
    monkeypatch.setattr(pf, '_check_peer', counting)
    with pytest.raises(Exception, match='non-public'):
        pf.get(f"http://127.0.0.1:{server['port']}/")
    assert calls['n'] == 1 and server['hits'] == 0


def test_too_many_redirects(server, monkeypatch):
    monkeypatch.setattr(pf, '_is_public', lambda ip: True)
    server['redirect_to'] = f"http://127.0.0.1:{server['port']}/again"
    with pytest.raises(pf.PublicFetchRefused, match='redirects'):
        pf.get(f"http://127.0.0.1:{server['port']}/")


def test_proxy_variables_are_ignored():
    """With trust_env on, HTTP(S)_PROXY would route the request to the proxy, and the peer check would see the
    proxy, not the destination."""
    assert pf.session().trust_env is False


def test_read_capped_discloses_a_cut(server, monkeypatch):
    monkeypatch.setattr(pf, '_is_public', lambda ip: True)
    r = pf.get(f"http://127.0.0.1:{server['port']}/", stream=True)
    data, cut = pf.read_capped(r, 50)
    assert len(data) == 50 and cut is True


def test_lookup_website_paths_all_use_public_fetch():
    """Every lookup_website fetch path goes through public_fetch — a path left on requests/trafilatura directly is
    an open door. Identifiers only (comments stripped)."""
    import re
    src = (ROOT / 'fastapi_server_complete.py').read_text()

    def body(name):
        i = src.find(f"    def {name}(")
        i = i if i >= 0 else src.index(f"    async def {name}(")
        nxt = min(x for x in (src.find("\n    def ", i + 10), src.find("\n    async def ", i + 10),
                              src.find("\n    @staticmethod", i + 10)) if x > 0)
        return re.sub(r'#[^\n]*', '', src[i:nxt])
    for name in ('_extract_pdf_content', '_extract_web_content', '_probe_content_type', '_extract_data_content'):
        b = body(name)
        assert 'public_get(' in b, f'{name} does not fetch through public_fetch'
        for direct in ('trafilatura.fetch_url(', 'requests.get(', 'requests.head(', 'requests_compatible_get(',
                       'getattr(requests'):
            assert direct not in b, f'{name} still fetches directly with {direct}'
    assert 'check_url(url)' in body('lookup_website'), 'lookup_website does not refuse internal addresses up front'
