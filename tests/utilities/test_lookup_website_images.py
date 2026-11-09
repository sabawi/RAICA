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
    code = "import logging\nlogger = logging.getLogger('t')\nclass S:\n    @staticmethod\n" + SRC[i:j]
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
    exec("import logging\nlogger = logging.getLogger('t')\nclass S:\n    @staticmethod\n" + SRC[i:j], ns)
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
