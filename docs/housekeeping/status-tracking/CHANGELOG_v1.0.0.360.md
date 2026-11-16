# CHANGELOG v1.0.0.360 — 2026-11-16

## Code samples in documents keep their line breaks and indentation (SI-121)

### Why
`utils/html_generator._clean_html_content` unwrapped every `<pre>` and `<code>` element (since the fork, b2beaa5, no
reason recorded). HTML collapses whitespace outside `<pre>`, so every code sample in a generated .html or PDF showed
as one run-on line, and inline code lost its monospace styling, although `config/pdf_styles.css` styles `pre`
(`white-space: pre-wrap`), `pre code` and `code` for exactly this content. Found while fixing SI-120.

### Checked before changing it
The likely reason for the unwrap, an answer wrapped in one big code fence, does not hold: on 1.0.0.359 such an
answer also came out as raw `## Report - point one` text (collapsed onto one line), so the unwrap never rendered it.
Now the same text keeps its lines inside a code box.

### Fixed
- `_clean_html_content` keeps `<pre>` and `<code>`; its fix for block elements nested in `<p>` is unchanged.

### Tests
- `tests/unit/test_markdown_code_blocks.py` +2: through `generate_html_report`, the `<pre>` keeps three code lines
  with their indentation and inline `<code>` survives; through `create_pdf`, `pdftotext -layout` of the real PDF
  shows the three lines apart (skipped where pdftotext is absent). Both FAIL on 1.0.0.359.
- `tests/unit`: 1170 passed, 9 skipped, 0 failed.

### Dependencies / migration
- None. No configuration change.
