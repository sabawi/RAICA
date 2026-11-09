"""user_tools/fetch_image_tool.py — a real picture, decoded, re-encoded, published, credited (docs/DESIGN_fetch_image_and_public_fetch.md).

Offline and side-effect free: the download is served from loopback with the address check opened ONLY for that
server, and publish_chart is replaced by a recorder (a real call would write a file into NewX's media store).
"""
import asyncio
import http.server
import io
import pathlib
import socketserver
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'user_tools'))

import utils.public_fetch as pf  # noqa: E402
import fetch_image_tool as fit  # noqa: E402

CFG = {'enabled': True, 'max_bytes': 200_000, 'max_pixels': 4_000_000, 'max_side': 64, 'timeout_seconds': 5,
       'max_caption_chars': 40}


def _png(w, h):
    from PIL import Image
    b = io.BytesIO()
    Image.new('RGB', (w, h), (200, 30, 30)).save(b, 'PNG')
    return b.getvalue()


@pytest.fixture
def env(monkeypatch):
    body = {'data': _png(300, 200), 'ctype': 'image/png'}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', body['ctype'])
            self.end_headers()
            self.wfile.write(body['data'])

        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    published = []

    def fake_publish(png, hint='chart', timeout=None):
        published.append(png)
        return '/static/images/media/picture_test.png'
    monkeypatch.setattr(fit, 'publish_chart', fake_publish)
    monkeypatch.setattr(fit, 'load_settings', lambda: dict(CFG))
    monkeypatch.setattr(pf, 'settings', lambda: {'max_redirects': 3, 'timeout_seconds': 5})
    monkeypatch.setattr(pf, '_is_public', lambda ip: ip == '127.0.0.1')     # this loopback server only
    yield {'url': f"http://127.0.0.1:{srv.server_address[1]}/cover.png", 'body': body, 'published': published,
           'monkeypatch': monkeypatch}
    srv.shutdown()
    srv.server_close()


def run(**kw):
    return asyncio.run(fit.FetchImageTool().execute(**kw))


def test_a_real_picture_is_reencoded_published_and_credited(env):
    out = run(url=env['url'], source_page='https://publisher.example/book', caption='Cover of the book')
    assert out['success'] is True, out
    assert '[[chart:/static/images/media/picture_test.png|' in out['result']
    assert 'source: publisher.example' in out['result'] and 'https://publisher.example/book' in out['result']
    from PIL import Image
    im = Image.open(io.BytesIO(env['published'][0]))
    assert im.format == 'PNG' and max(im.size) <= CFG['max_side'], 'not re-encoded / not shrunk'
    assert env['published'][0] != env['body']['data']


def test_disabled_switch_refuses_and_publishes_nothing(env):
    env['monkeypatch'].setattr(fit, 'load_settings', lambda: dict(CFG, enabled=False))
    out = run(url=env['url'], source_page='https://p.example/')
    assert out['success'] is False and 'not enabled' in out['error'] and not env['published']


def test_internal_address_is_refused_and_says_so(env):
    out = run(url='http://169.254.169.254/latest/meta-data/', source_page='https://p.example/')
    assert out['success'] is False and 'refused' in out['error'] and not env['published']
    assert 'could not bring in a real picture' in out['error'], 'the model is not told what to say next'


def test_a_non_picture_is_refused(env):
    env['body'].update(data=b'<html>not a picture</html>', ctype='text/html')
    out = run(url=env['url'], source_page='https://p.example/')
    assert out['success'] is False and 'not a readable picture' in out['error'] and not env['published']


def test_an_oversized_file_is_refused(env):
    env['body']['data'] = b'\x89PNG' + b'0' * (CFG['max_bytes'] + 10)
    out = run(url=env['url'], source_page='https://p.example/')
    assert out['success'] is False and 'larger than' in out['error'] and not env['published']


def test_a_pixel_bomb_is_refused_before_decoding():
    """A small file declaring a huge canvas: refused from the header, the pixels are never allocated."""
    with pytest.raises(ValueError, match='too large'):
        fit.to_png(_png(3000, 3000), max_pixels=1_000_000, max_side=64)


def test_caption_cannot_break_the_marker():
    assert '|' not in fit._caption('a | b ]] [[chart:x', 40) and ']]' not in fit._caption('a ]] b', 40)


def test_caption_is_plain_text_cut_on_a_word():
    """Run 1 (2026-11-09) showed '*Inventing God's Law* … (Oxford Universit': markdown shown literally, a word cut."""
    c = fit._caption("Cover of *Inventing God's Law* (Oxford University Press, 2009)", 40)
    assert '*' not in c and c.endswith('…') and c[:-1].split()[-1] in "Cover of Inventing God's Law (Oxford University".split()


def test_a_publish_failure_is_a_reason(env):
    env['monkeypatch'].setattr(fit, 'publish_chart', lambda *a, **k: None)
    out = run(url=env['url'], source_page='https://p.example/')
    assert out['success'] is False and 'could not be published' in out['error']
