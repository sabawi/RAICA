# CHANGELOG v1.0.0.359 — 2026-11-16

## Documents with a code block keep their formatting (SI-120)

### Why
`utils/html_generator._convert_markdown_to_html` configured codehilite with `pygments_style: 'github'`. Pygments
2.19.2 (installed locally and on production) has no style by that name (it ships `github-dark`), so any document
containing a fenced code block raised "Could not find style module 'pygments.styles.github'" and the WHOLE document
went to the fallback converter: tables, lists and inline charts came out as plain text (`| Name | Value |`,
`!<a>chart</a>`). Documents without fenced code were unaffected, which is why it went unseen. Found while writing
the SI-119 tests.

### Fixed
- The `pygments_style` setting is removed; codehilite uses its built-in default. With `noclasses: False` the style
  only names CSS classes, and no document stylesheet (`config/pdf_styles.css`) defines them, so output is unchanged
  apart from no longer failing. One fewer hardcoded value.
- When the markdown library fails for any other reason, the fallback is now also logged at ERROR
  (`[HTML-GEN] markdown library failed … rendered by the fallback converter`), not only printed.

### Tests
- New `tests/unit/test_markdown_code_blocks.py` (2), through `generate_html_report`: a document with a table, list,
  inline chart and fenced code keeps all of them and logs no fallback; a library failure is logged. Both FAIL on
  1.0.0.358.
- `create_pdf` with the same document builds with no fallback. `tests/unit`: 1168 passed, 9 skipped, 0 failed.

### Found, not fixed (logged)
- SI-121: `_clean_html_content` unwraps every `<pre>`, so code samples lose their line breaks and indentation. It
  predates this release and may be deliberate (answers wrapped in one big code fence); owner's call.

### Also in this commit
- `SUSPECTED_ISSUES.md`: SI-119 marked deployed and verified on production (1.0.0.358, canary check on the server).

### Dependencies / migration
- None. No configuration change.
