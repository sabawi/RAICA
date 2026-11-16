"""Generated documents carry only safe content; their PDF renderer never reads the server's disk (SI-119, v1.0.0.358).

The failure these prevent, measured 2026-11-16 on v1.0.0.357: a document whose content held
`<a rel="attachment" href="file:///…">` came out of services/pdf_service.create_pdf (THE single PDF entry point) with
that server file embedded in it, and `<script>` / `<img onerror=…>` stayed live in the .html file. On production the
readable file would be RAICA's .env, emailed to whoever asked a bot for the PDF.

Real entry points: CentralizedPDFService.create_pdf and SandboxedExecutorTool._create_real_html_file (what the
create_file tool runs for .html). Files are written to a temp dir or deleted at once. No network: the public-fetch
case is patched, the refused ones are refused before any connection.
Run: ./venv/bin/python -m pytest tests/unit/test_document_safety.py -q
"""
import asyncio
import os
import re
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils import document_safety  # noqa: E402
from utils.html_generator import html_generator  # noqa: E402

DATA_PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
            '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


def _pdf_holds(path, needle):
    raw = Path(path).read_bytes()
    if needle in raw:
        return True
    for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream', raw, re.S):
        try:
            if needle in zlib.decompress(m.group(1)):
                return True
        except zlib.error:
            pass
    return False


def _body(html):
    return re.search(r'<body[^>]*>(.*)</body>', html, re.S | re.I).group(1)


@pytest.fixture
def canary(tmp_path):
    p = tmp_path / 'secret.txt'
    p.write_text('CANARY-SI119-SECRET')
    return p


def test_pdf_does_not_embed_a_local_file(tmp_path, canary):
    """The SI-119 exploit through the real PDF entry point: the server file must not reach the PDF, and the PDF must
    still be built (a refused resource is skipped, not fatal)."""
    from services.pdf_service import CentralizedPDFService
    out = tmp_path / 'doc.pdf'
    content = (f'## Notes\n\n- one\n- two\n\n<a rel="attachment" href="file://{canary}">appendix</a>\n'
               f'<img src="file://{canary}">\n')
    r = CentralizedPDFService().create_pdf(content=content, output_path=str(out), title='t')
    assert r['success'], r
    assert not _pdf_holds(out, b'CANARY-SI119-SECRET')
    assert b'/EmbeddedFile' not in out.read_bytes()


def test_fetcher_never_reads_the_disk_or_an_internal_address(canary):
    """Even if markup survived the sanitizer (CSS url(), a future template), the renderer's own reads are guarded."""
    for url in (f'file://{canary}', 'http://127.0.0.1:5000/health', 'http://169.254.169.254/latest/meta-data/',
                'ftp://example.com/x'):
        with pytest.raises(document_safety.DocumentFetchRefused):
            document_safety.url_fetcher(url)


def test_fetcher_keeps_inline_and_public_pictures(monkeypatch):
    """Charts arrive as data: images and web pictures as public https: both must still load in the PDF."""
    got = document_safety.url_fetcher(DATA_PNG)
    raw = got.get('string') or got['file_obj'].read()
    assert raw.startswith(b'\x89PNG'), got

    class R:
        url = 'https://example.org/p.png'
        headers = {'Content-Type': 'image/png'}
    from utils import public_fetch
    monkeypatch.setattr(public_fetch, 'get', lambda url, headers=None, stream=False: R())
    monkeypatch.setattr(public_fetch, 'read_capped', lambda r, n: (b'\x89PNGdata', False))
    got = document_safety.url_fetcher('https://example.org/p.png')
    assert got['string'] == b'\x89PNGdata' and got['mime_type'] == 'image/png'
    monkeypatch.setattr(public_fetch, 'read_capped', lambda r, n: (b'x' * n, True))
    with pytest.raises(document_safety.DocumentFetchRefused):
        document_safety.url_fetcher('https://example.org/huge.png')


def test_html_file_has_no_active_content():
    """The .html attachment: no script, no event handler, no javascript: link, in either the plain-text branch (where
    a single '#' heading made the raw body pass straight through) or the markdown branch."""
    from user_tools.sandboxed_executor import SandboxedExecutorTool
    tool = SandboxedExecutorTool()
    cases = {
        'plain': "# <script>alert('t')</script> Title\n\nBody <img src=x onerror=alert(1)> and "
                 "<a href=\"javascript:alert(2)\">link</a>.\n",
        'markdown': "## Report\n\n- item <script>alert(3)</script>\n- <svg onload=alert(4)></svg>\n"
                    "- <iframe src=\"https://example.org\"></iframe>\n",
    }
    for name, content in cases.items():
        r = asyncio.run(tool._create_real_html_file(f'si119_{name}.html', content))
        p = r['result']['full_path']
        try:
            body = _body(Path(p).read_text())
        finally:
            os.remove(p)
        low = body.lower()
        assert '<script' not in low and '<svg' not in low and '<iframe' not in low, (name, body)
        assert not re.search(r'\son\w+\s*=', low), (name, body)
        assert 'javascript:' not in low, (name, body)


def test_ordinary_formatting_survives():
    """The guard must not cost real documents their formatting: headings, tables, links, code, inline charts."""
    # (no fenced code block here: one sends the whole document to the fallback converter, SI-120, pre-existing)
    md = ("## Results\n\n| Name | Value |\n|---|---|\n| A | 1 |\n\n**bold** and *em* and "
          "[a source](https://example.org/a) and `print('x')`\n\n"
          f"![chart]({DATA_PNG})\n")
    body = _body(html_generator.generate_html_report(content=md, title='T', force_template=True))
    for needle in ('<h2', '<table', '<td>', '<strong>bold</strong>', '<em>em</em>',
                   'href="https://example.org/a"', "print(", 'src="data:image/png;base64,'):
        assert needle in body, (needle, body)


def test_a_failing_sanitizer_writes_the_escaped_fallback(monkeypatch):
    """The template's catch-all used to return the RAW body; with the sanitizer inside that try, a sanitizer failure
    must never emit unfiltered content."""
    def boom(_html):
        raise RuntimeError('sanitizer down')
    monkeypatch.setattr(document_safety, 'sanitize_body', boom)
    out = html_generator.generate_html_report(content="## H\n\n- <script>alert(1)</script>\n", title='<b>T</b>',
                                              force_template=True)
    assert '<script' not in out.lower() and '&lt;script&gt;' in out and '<b>T</b>' not in out


def test_custom_css_cannot_close_the_style_block():
    """custom_css is inserted raw into <style>: a value carrying '</style><script>' must be dropped."""
    out = html_generator.generate_html_report(content='## H\n\ntext\n', title='T', force_template=True,
                                              custom_css='body{color:red}</style><script>alert(1)</script>')
    assert '<script' not in out.lower()
    assert document_safety.safe_css('body { color: red; }') == 'body { color: red; }'
