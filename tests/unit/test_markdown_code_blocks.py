"""A fenced code block must not cost the rest of the document its formatting (SI-120, v1.0.0.359).

The failure it prevents: codehilite was configured with pygments_style 'github', which Pygments 2.19 (local and prod)
does not ship. Any document containing a fenced code block raised "Could not find style module
'pygments.styles.github'", and the WHOLE document went to the fallback converter: tables, lists and inline charts
came out as plain text. Documents without fenced code were unaffected, which is why it went unseen.

Real entry point: html_generator.generate_html_report (what every .html and .pdf document goes through).
Run: ./venv/bin/python -m pytest tests/unit/test_markdown_code_blocks.py -q
"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.html_generator import html_generator  # noqa: E402

DATA_PNG = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
            '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')

DOC = ("## Results\n\n| Name | Value |\n|---|---|\n| A | 1 |\n\n- first\n- second\n\n"
       "```python\ndef add(a, b):\n    return a + b\n```\n\n"
       f"![chart]({DATA_PNG})\n")


def _body(html):
    return re.search(r'<body[^>]*>(.*)</body>', html, re.S | re.I).group(1)


def test_document_with_a_code_block_keeps_its_formatting(caplog):
    with caplog.at_level(logging.ERROR, logger='utils.html_generator'):
        body = _body(html_generator.generate_html_report(content=DOC, title='T', force_template=True))
    assert not [r for r in caplog.records if 'fallback converter' in r.getMessage()], caplog.text
    for needle in ('<table', '<td>A</td>', '<li>first</li>', 'src="data:image/png;base64,', 'class="highlight"'):
        assert needle in body, (needle, body)
    from bs4 import BeautifulSoup
    assert 'return a + b' in BeautifulSoup(body, 'html.parser').get_text(), body   # highlighting splits it into spans
    assert '```' not in body and '|---|' not in body, body


def test_markdown_library_failure_is_logged(monkeypatch, caplog):
    """If the library fails for any other reason, the fallback must be visible in the log, not only on stdout."""
    import markdown
    monkeypatch.setattr(markdown, 'Markdown', lambda **k: (_ for _ in ()).throw(RuntimeError('broken')))
    with caplog.at_level(logging.ERROR, logger='utils.html_generator'):
        html_generator._convert_markdown_to_html("| a |\n|---|\n| 1 |\n")
    assert any('fallback converter' in r.getMessage() for r in caplog.records), caplog.text


CODE_DOC = ("## Example\n\nCall `add(1, 2)` like this:\n\n```python\ndef add(a, b):\n    total = a + b\n"
            "    return total\n```\n")


def test_code_block_keeps_its_lines_and_indentation():
    """SI-121 (v1.0.0.360): _clean_html_content unwrapped every <pre>/<code>, so a code sample's newlines and
    indentation collapsed into one run-on line in the .html and the PDF. The <pre> must survive with its lines, and
    inline code must stay <code>."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_body(html_generator.generate_html_report(content=CODE_DOC, title='T', force_template=True)),
                         'html.parser')
    pre = soup.find('pre')
    assert pre is not None, soup
    assert pre.get_text().splitlines()[:3] == ['def add(a, b):', '    total = a + b', '    return total'], pre
    assert any(c.get_text() == 'add(1, 2)' for c in soup.find_all('code') if not c.find_parent('pre')), soup


def test_code_block_lines_survive_into_the_pdf(tmp_path):
    """What the reader receives: the PDF's own text keeps the three code lines apart (pdftotext; skipped if absent)."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which('pdftotext'):
        pytest.skip('pdftotext not installed')
    from services.pdf_service import CentralizedPDFService
    out = tmp_path / 'code.pdf'
    assert CentralizedPDFService().create_pdf(content=CODE_DOC, output_path=str(out), title='T')['success']
    text = subprocess.run(['pdftotext', '-layout', str(out), '-'], capture_output=True, text=True).stdout
    lines = [ln.rstrip() for ln in text.splitlines()]
    i = next(n for n, ln in enumerate(lines) if 'def add(a, b):' in ln)
    assert 'total = a + b' in lines[i + 1] and 'return total' in lines[i + 2], lines[i:i + 3]
    assert 'total' not in lines[i], lines[i]          # not run together on one line
