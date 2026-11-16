# CHANGELOG v1.0.0.358 — 2026-11-16

## Generated documents are safe: PDFs never read server files, bodies carry no active content (SI-119); SI-118 resolved

### Why
Triaging SI-118 (four failing unit tests) showed that one stale test had been the only guard against raw HTML in
generated documents. Measured on 1.0.0.357, locally, through `services/pdf_service.CentralizedPDFService.create_pdf`
(the single PDF entry point): content containing `<a rel="attachment" href="file:///…">` produced a PDF with that file
embedded (WeasyPrint was called with no `url_fetcher`, so it read `file://` and any network address the document
named). The same content rendered to `.html` kept `<script>` and `<img onerror=…>` live. On production the readable
file would be RAICA's `.env`, and a NewX member whose bot can deliver could have it emailed to their own address.
Production was deliberately not used to test this.

### Fixed — security (SI-119)
- **New `utils/document_safety.py`:**
  - `url_fetcher` for WeasyPrint: `data:` URLs, and http(s) only through `utils/public_fetch` (public addresses,
    every redirect hop checked), each capped at `document_safety.fetch_max_bytes`. Anything else is refused and
    logged `[DOC-SAFETY]`; WeasyPrint skips it and still builds the PDF.
  - `sanitize_body`: the body cut to the configured allow-list (tags, attributes, link and picture protocols, inline
    CSS through bleach's CSS sanitizer). `remove_with_content` elements (script, style, iframe, svg, form…) are
    dropped whole.
  - `safe_css`: caller `custom_css` containing `<` (could close the `<style>` block) is dropped.
- `services/pdf_service.py`: both WeasyPrint calls pass the fetcher; the unreferenced `_create_pdf_with_weasyprint`
  sanitizes its body too.
- `utils/html_generator.generate_html_report`: body sanitized before either format is written; the template
  catch-all now writes an ESCAPED fallback (it returned the raw body, so a sanitizer failure would have emitted
  unfiltered content).
- **Not changed (scope):** complete HTML passed without `force_template` is still returned as-is (background agents'
  email bodies; never a PDF).

### Fixed — coding agent (SI-118 weak spots, owner decision)
- `agents/coding_agent/autonomous/debug_controller._apply_unit_fix`: the unit's test is now in the fix instruction
  (the `test_code` parameter was unused, so the model never saw the test it had to pass).
- Modified files are found by a before/after snapshot (newly dirty files, or files whose content hash changed),
  united with what the tools reported writing. Before, every already-dirty file counted as "modified", so a dirty
  tree read as a successful fix, and `edit_file`'s "Edited …" result was never parsed.

### Configuration
- New section `document_safety` in `config/llm_config.defaults.yaml` (fetch_max_bytes, allowed_tags,
  allowed_attributes, link_protocols, image_protocols, remove_with_content). Added to each site's
  `config/llm_config.yaml` automatically by the structure migration at startup (an addition; no site value changes).
  Fail-fast when missing: documents then come out as the escaped fallback.

### Tests
- New `tests/unit/test_document_safety.py` (7): PDF does not embed a local file and still builds; fetcher refuses
  file://, loopback, metadata address, ftp; data: and public pictures still load, size cap; no script / on* /
  javascript: / svg / iframe in the .html file (plain and markdown branches); ordinary formatting survives; failing
  sanitizer → escaped fallback; custom_css cannot close `<style>`. 4 of them FAIL on 1.0.0.357.
- `tests/unit/test_phase5_integration.py`: expectations matched to the real prompt; +3 (pre-dirty file not counted,
  edit to a dirty file detected, no empty test section). 3 FAIL on 1.0.0.357.
- `tests/unit/test_html_entities.py`: quote-escaping expectation corrected (quotes in text are valid HTML).
- `tests/unit/test_title_escaping.py` removed: a script (asserted nothing, imported from another project).
- `tests/unit`: 1166 passed, 9 skipped, 0 failed (1.0.0.357: 1153 passed, 4 failed).

### Found, not fixed (logged)
- SI-120: `pygments_style: 'github'` does not exist in Pygments 2.19, so any document with a fenced code block falls
  back to the plain converter and loses tables/lists/images formatting. Pre-existing.

### Dependencies / migration
- `tinycss2>=1.2` now listed in requirements.txt (bleach's CSS sanitizer; it was already installed as a weasyprint dependency, prod has 1.5.1). bleach 6.3.0 present on prod. No breaking API change.
