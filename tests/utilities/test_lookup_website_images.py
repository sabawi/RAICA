"""lookup_website lists the page's own pictures as data (docs/DESIGN_fetch_image_and_public_fetch.md §2.2).

Without it the model has no address to give fetch_image. Rebuilt from source (importing the server loads models).
"""
import pathlib
import re
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = (ROOT / 'fastapi_server_complete.py').read_text()


def _page_images():
    i = SRC.index("    def _page_images(")
    j = SRC.index("\n    def ", i + 10)
    code = "import logging, re\nlogger = logging.getLogger('t')\nclass S:\n    @staticmethod\n" + SRC[i:j]
    ns = {'config_loader': types.SimpleNamespace(load_config=lambda: {'lookup_website': {'max_images_listed': 3}})}
    exec(code, ns)
    return ns['S']._page_images


HTML = """<?xml version="1.0" encoding="utf-8"?><html><body>
<img src="/img/cover.jpg" alt="Cover of  the book">
<img data-src="https://cdn.example/lazy.png" alt="">
<img src="data:image/gif;base64,R0lGOD" alt="tracker">
<img src="/img/cover.jpg" alt="again">
<img src="b.png" alt="four"><img src="c.png" alt="five"></body></html>"""


def test_declared_picture_first_then_page_pictures_absolute_and_unique():
    out = _page_images()(HTML, 'https://pub.example/books/1', 'https://pub.example/og.jpg')
    assert [o['url'] for o in out] == ['https://pub.example/og.jpg', 'https://pub.example/img/cover.jpg',
                                       'https://cdn.example/lazy.png'], out
    assert out[1]['alt'] == 'Cover of the book'


def test_limit_from_config():
    assert len(_page_images()(HTML, 'https://pub.example/', None)) == 3


def test_an_unparseable_page_lists_nothing_and_does_not_raise():
    assert _page_images()('', 'https://pub.example/', None) == []


def test_the_listing_reaches_the_tool_output():
    """Data reaches the model only if lookup_website prints it."""
    assert "Pictures on this page" in SRC and "result.get('images')" in SRC
    assert re.search(r'"images": self\._page_images\(', SRC)


def test_missing_limit_lists_nothing_instead_of_failing_the_page():
    """The listing is extra; a missing setting must not turn a readable page into 'Error extracting content'."""
    i = SRC.index("    def _page_images(")
    j = SRC.index("\n    def ", i + 10)
    ns = {'config_loader': types.SimpleNamespace(load_config=lambda: {'lookup_website': {}})}
    exec("import logging, re\nlogger = logging.getLogger('t')\nclass S:\n    @staticmethod\n" + SRC[i:j], ns)
    assert ns['S']._page_images(HTML, 'https://pub.example/', 'https://pub.example/og.jpg') == []


def test_an_oversized_page_is_refused_not_read_whole(monkeypatch):
    """trafilatura.fetch_url refused pages over 20 MB; public_fetch replaced it, so the cap is ours to keep —
    otherwise an endless page fills memory. The fake body is one byte over the cap."""
    import utils.public_fetch as pf
    i = SRC.index("    def _extract_web_content(")
    j = SRC.index("\n    @staticmethod", i)
    ns = {'trafilatura': None}
    exec("class S:\n    def _lookup_website_page_bytes(self):\n        return 100\n"
         "    def _page_images(self, *a):\n        return []\n" + SRC[i:j], ns)
    reads = []

    class R:
        status_code, url = 200, 'https://pub.example/'
        raw = types.SimpleNamespace(read=lambda n, decode_content=True: reads.append(n) or b'x' * n)
        def close(self): pass
    monkeypatch.setattr(pf, 'get', lambda *a, **k: R())
    out = ns['S']()._extract_web_content('https://pub.example/')
    assert out['success'] is False and 'size limit' in out['error'], out
    assert reads == [101], 'the body was not read under the cap'


SIZED = """<html><head><meta property="og:image:width" content="729"><meta property="og:image:height" content="1200">
</head><body>
<img src="/thumb/cover-128.jpg" width="128" alt="Front cover">
<img src="/p/250.jpg" width="250" height="412" srcset="/p/500.jpg 2x, //cdn.example/p/960.jpg 960w" alt="Photo">
<img src="/logo.png" alt="logo"></body></html>"""


def test_the_size_the_page_declares_and_its_other_sizes_are_listed():
    """Production 2026-11-09: Ask posted Google Books' 128-wide thumbnail; the page itself said width=128, and
    Ask could not know. Each picture now carries the page's declared size and the larger versions it offers."""
    pi = _page_images()
    out = pi(SIZED, 'https://pub.example/b', 'https://pub.example/og.jpg')
    assert out[0]['size'] == '729×1200', 'og:image:width/height belong to the declared preview picture'
    assert out[1]['size'] == '128 wide'
    assert out[2]['size'] == '250×412'
    assert out[2]['versions'] == [('https://pub.example/p/500.jpg', '2x'), ('https://cdn.example/p/960.jpg', '960w')]
    assert pi(SIZED, 'https://pub.example/b', None)[2]['size'] == '', 'no size stated -> empty, not a guess'


def test_the_model_reads_size_and_versions_in_the_listing():
    i = SRC.index("def _describe_page_image(")
    j = SRC.index("\ndef ", i + 10)
    ns = {}
    exec(SRC[i:j], ns)
    d = ns['_describe_page_image']
    line = d({'url': 'https://p.example/250.jpg', 'alt': 'Photo', 'size': '250×412',
              'versions': [('https://p.example/960.jpg', '960w'), ('https://p.example/x.jpg', '')]})
    assert line == ('- https://p.example/250.jpg — Photo — 250×412; also offered: https://p.example/960.jpg (960w), '
                    'https://p.example/x.jpg')
    assert d({'url': 'https://p.example/a.jpg', 'alt': '', 'size': '', 'versions': []}) == \
        '- https://p.example/a.jpg — (no description) — size not stated'
    assert "_describe_page_image(im) for im in result['images']" in SRC, 'the listing must use it'


def test_only_pixel_sizes_and_wellformed_descriptors_reach_the_model():
    """Page markup is attacker text: width="100%" is not a pixel size, and a srcset descriptor must not carry
    arbitrary words into the prompt."""
    html = ('<html><body><img src="/a.jpg" width="100%" height="auto">'
            '<img src="/b.jpg" width="300px" height=" 450 " srcset="/c.jpg ignore_previous_instructions, /d.jpg 1.5x">'
            '</body></html>')
    out = _page_images()(html, 'https://pub.example/', None)
    assert out[0]['size'] == ''
    assert out[1]['size'] == '300×450'
    assert out[1]['versions'] == [('https://pub.example/c.jpg', ''), ('https://pub.example/d.jpg', '1.5x')]
