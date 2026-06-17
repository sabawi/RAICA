# CHANGELOG v1.0.0.130

**Date:** 2026-06-17
**Previous:** v1.0.0.129 (Deep-Research document title fix)
**Theme:** **Delivered .html parity with .pdf.** The standalone `.html` rendered plainer than the `.pdf`,
and one `.html`-only code path could bypass the shared template. Two changes restore the single-workflow
design invariant and make the on-screen `.html` look right.

---

## Symptom

A DR delivery's `.pdf` looked well-formatted; the attached `.html` did **not** ("not as well formatted and
stylized"). The `.html` content, title and CSS were all correct, but it rendered plainer in a browser.

## Root cause

The single shared stylesheet `config/pdf_styles.css` is **print-optimized**: page margins come entirely
from `@page` rules (with `body { margin: 0 }`), and **browsers ignore `@page`**. So weasyprint (PDF) got
properly-margined pages while a browser opened the `.html` **edge-to-edge with no framing** — plainer, not
unstyled. There was **no `@media screen`** block styling the browser view.

Separately, an audit (operator concern about the "single HTML workflow" design principle) found one
pre-existing asymmetry: `_create_real_html_file` short-circuited *already-complete HTML* content and saved
it **raw**, bypassing the shared template — while the `.pdf` path always goes through it. And the `.html`
dispatch never passed the explicit `title` (only `.pdf` did), so `.html` re-derived a title from the
(title-stripped) DR body.

## Changes

- **`config/pdf_styles.css`** — added an `@media screen` block: the `.html` now gets letter-width, centered,
  margined "page" framing (6.5in text measure, same as the PDF) with a subtle page card. WeasyPrint renders
  **print** media, so `@media screen` is ignored for the `.pdf` → PDF visually unchanged. Still ONE
  stylesheet, ONE template — the screen rules live inside the single shared file (no per-format CSS).
- **`user_tools/sandboxed_executor.py`** — `_create_real_html_file`:
  - Removed the raw-HTML short-circuit. EVERY `.html` now renders through the shared template
    (`generate_html_report(force_template=True)` via `_convert_to_html_shared`) — the SAME generator the
    `.pdf` uses. Already-complete HTML is re-rendered through the standard template (its `<body>` is
    extracted by `force_template`), never saved raw. Restores the single-workflow invariant.
  - Accepts an explicit `title` (now passed by the `_create_file` dispatch, like `.pdf`); honors it,
    else derives from content. So `.html` and `.pdf` share the same title.

## Verified

- **Unit** `tests/integration/test_html_single_workflow_styling.py`: markdown → shared template; raw HTML →
  re-templated (body extracted, standard stylesheet applied, model style dropped — not saved raw);
  `@media screen` + screen page-framing present; PDF still renders (weasyprint unaffected). All green.
- Existing DR title / retry / grounding / delivery suites: green.

## Files
- `config/pdf_styles.css`, `user_tools/sandboxed_executor.py`,
  `tests/integration/test_html_single_workflow_styling.py` (new), `version.py` (→ 1.0.0.130), `README.md`,
  this changelog.
