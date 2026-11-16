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
