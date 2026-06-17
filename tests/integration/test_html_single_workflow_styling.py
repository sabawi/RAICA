"""
Guards two delivery-rendering invariants:

1. SINGLE HTML WORKFLOW (design principle): every generated .html goes through the ONE shared template
   (html_generator.generate_html_report, force_template=True) — the SAME generator the .pdf uses. Even
   content that ARRIVES as a complete HTML document with its own styling is re-rendered through the
   standard template (its <body> is extracted), never saved raw. (The old _create_real_html_file
   short-circuit that saved raw HTML as-is is gone.)

2. ON-SCREEN STYLING: the single shared stylesheet (config/pdf_styles.css) carries an @media screen block
   so the standalone .html has proper page framing in a browser (the PDF's margins come from @page, which
   browsers ignore). WeasyPrint renders as print media, so @media screen never affects the .pdf.

Run: python -m pytest tests/integration/test_html_single_workflow_styling.py -q
 or: python tests/integration/test_html_single_workflow_styling.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils.html_generator import html_generator

_MD = ("# A Research Report\n\n## 1. Origins\nBody **bold** with a [link](https://example.com).\n\n"
       "- a\n- b\n\n| X | Y |\n|---|---|\n| 1 | 2 |\n")
_RAW_HTML = ('<!DOCTYPE html><html><head><style>body{color:red;font-family:Comic Sans}</style></head>'
             '<body><h1>Raw Doc</h1><p>raw body text</p></body></html>')


def _gen(content, title="Doc"):
    return html_generator.generate_html_report(content=content, title=title, header_title=title,
                                               header_subtitle="", include_disclaimer=False,
                                               force_template=True)


def test_markdown_goes_through_shared_template():
    out = _gen(_MD, "A Research Report")
    assert "<style" in out.lower() and "DejaVu Serif" in out   # standard stylesheet present
    assert "<h1" in out.lower() and "<table" in out.lower() and "<a href" in out.lower()


def test_raw_html_is_retemplated_not_saved_raw():
    """force_template re-renders an already-complete HTML doc through the standard template (extract body)
    — the standalone .html can't keep a model-pasted layout/style that forks from the standard."""
    out = _gen(_RAW_HTML, "Standard Title")
    assert out.strip() != _RAW_HTML.strip()              # not saved raw
    assert "raw body text" in out                          # body content preserved
    assert "DejaVu Serif" in out                           # STANDARD stylesheet applied
    assert "color:red" not in out.replace(" ", "")        # raw style dropped
    assert "comicsans" not in out.replace(" ", "").lower()


def test_screen_media_block_present_for_browser_view():
    out = _gen(_MD)
    assert "@media screen" in out, "browser view styling missing — .html will render edge-to-edge"
    assert "max-width: 8.5in" in out, "screen page-framing (centered letter width) missing"


def test_pdf_unaffected_by_screen_block():
    """WeasyPrint renders print media -> @media screen must not break/alter PDF generation."""
    import weasyprint
    out = _gen(_MD)
    pdf_path = "/tmp/_test_workflow.pdf"
    weasyprint.HTML(string=out).write_pdf(pdf_path)
    assert os.path.getsize(pdf_path) > 2000   # renders fine, non-trivial size


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
