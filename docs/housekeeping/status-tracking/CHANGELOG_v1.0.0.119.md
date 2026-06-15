# CHANGELOG v1.0.0.119

**Date:** 2026-06-15
**Previous documented:** v1.0.0.93 (delivery file-attachment path fix)
**Spans:** v1.0.0.94 → v1.0.0.119
**Theme:** **One delivery substrate + one document-rendering pipeline.** Unify how RAICA produces and
delivers documents so PDF and HTML are byte-for-byte consistent, retire keyword-driven decision code in
the delivery/intent path, and add an end-to-end delivery regression harness.

---

## 1. Single-source document rendering pipeline (the big one)

**Problem:** PDF and HTML were produced by **two different pipelines** — `utils/html_generator.py`
(its own `markdown` converter + the template's minimal CSS) for `.html`, and
`services/pdf_service.CentralizedPDFService` (a *different* `markdown.Markdown` config + `config/pdf_styles.css`)
for `.pdf`. Different converters **and** different CSS → the two formats could never be guaranteed to match,
and a fix in one never reached the other (recurring "the PDF looks different from the HTML" reports).

**Fix:** ONE pipeline.
- `templates/html_report_template.html` is now a thin shell: a single title `<h1>` + the shared CSS slot
  (its built-in minimal CSS removed).
- `html_generator` injects `config/pdf_styles.css` as **the** document stylesheet (`_load_document_css`).
- `CentralizedPDFService.create_pdf` now = `weasyprint.HTML(string=html_generator.generate_html_report(...)).write_pdf()`
  — the PDF is weasyprinted from the **exact same HTML** the `.html` file uses.

→ One markdown→HTML converter, one stylesheet, one structure. **`.pdf` and `.html` are now identical**, and
every future formatting/normalization fix lands in both automatically.

## 2. Unified delivery substrate

- New `_deliver_document(content, title, slug, formats, …)` — the single robust delivery core: renders
  **every requested format** (one file per format via `sandboxed_executor.create_file`), emails ALL files in
  ONE message through the recipient-lock chokepoint, with content-keyed idempotency.
- **Both** the NewX/@Ask POST-LLM path **and** Deep Research (`_run_dr_delivery`) now call it. The fragile,
  single-format, keyword-laden POST-LLM branches are bypassed by a "unified delivery" block.
- Fixes: multi-format ("PDF and HTML" → 2 files), valid PDFs (no more intermittent corruption), and
  consistent content-derived titles.

## 3. Legacy keyword classifier retired (intent is LLM-decided)

- `_verify_task_completion` shrank from ~302 lines of keyword/pattern classification (`task_patterns`,
  `email_keywords`, `exclusion_patterns`, …) to a slim deterministic OpenWebUI meta-task envelope guard +
  fail-safe. The LLM intent classifier (`convergence.intent_classifier.mode: llm`) is now the sole
  delivery-intent decider, falling back safely (no keyword guessing) when unavailable.
- Format selection now LLM-decided (`_llm_requested_formats`) reading a head+tail window of the prompt, not
  substring matching (which falsely matched "text" in "context" → spurious `.md`/`.txt`).
- Document title from the content's first heading, else an LLM-named title (`_llm_document_title`) — replacing
  the `_extract_subject_from_prompt` regex and the `_generate_dynamic_title` hardcoded region→title table at
  the delivery sites.

## 4. Delivery-content normalization

`_normalize_delivery_markdown` + helpers tidy the model's markdown before rendering so non-content isn't
mis-rendered:
- strip a model code-fence/preamble wrapper ("Here is the HTML document: ```html …```"),
- strip the content's own leading title heading + preamble (title is rendered once by the template),
- demote `#`-headings that are really body **sentences** (incl. those ending in a citation link),
- drop trailing social-hashtag lines (so `#Tag #Tag` isn't promoted to an `<h1>`).

## 5. Delivery hardening (selected)

- **Sandbox path mismatch fixed:** all delivery sites resolve the workspace via `_delivery_sandbox_dir()`
  (config/home-driven), never `os.getcwd()/sandbox_workspace` (a path that did not exist → silently dropped
  attachments + false "✅ sent").
- Email tool: `(get(x) or "").strip()` so a `None` recipient/subject/body can't crash a send.
- Content-keyed email idempotency replaced the global, content-blind `/tmp/last_email_sent.txt` 60s guard.
- Delivery system prompt: produce the finished content directly — never reply with a plan / "need to
  research" / meta-commentary (which would be packaged AS the document).

## 6. Tests

- New `tests/integration/test_delivery_regression.py` — drives the **real** entry points (`/v1` NewX @Ask,
  `/v1/chat/completions` OpenWebUI/DR) and asserts on the server-log delta **and the actual artifacts**
  (PDF `%PDF…%%EOF`, single `<h1>`, no code fence, no sentence/hashtag headings) when run with
  `RAICA_KEEP_DELIVERY_FILES=1`. Fast lane (NewX) + slow lane (`--slow`, DR). Recipients come from env
  (`DELIVERY_TEST_RECIPIENT` / `DELIVERY_TEST_THIRD_PARTY`) — no PII committed.
- Validated end-to-end with the live LLM: fast lane 4/4 + DR, PDF≡HTML.

## Files
- `fastapi_server_complete.py` — `_deliver_document`, unified delivery block, gutted verifier, content
  normalization, LLM title/format helpers, sandbox-path + email-None hardening, delivery prompt directive.
- `utils/html_generator.py`, `templates/html_report_template.html`, `config/pdf_styles.css` — single-source rendering.
- `services/pdf_service.py` — `create_pdf` now weasyprints the html_generator output.
- `user_tools/secure_email_sender.py`, `user_tools/sandboxed_executor.py`, `research/synthesis.py`,
  `orchestration/` (shared policy + intent), `version.py` (→ 1.0.0.119), `README.md`, this changelog.

## Known follow-ups (tracked, NOT in this commit)
- Delete the now-dead code: old `pdf_service` conversion methods, the bypassed POST-LLM file/email branches,
  dead `_execute_missing_tools` / `_detect_*`, and refactor the remaining `_generate_dynamic_title` /
  `_extract_subject_from_prompt` callers off the keyword tables.
- Pre-existing hardcoded user paths (`fastapi_server_complete.py:2683/:9558-9566`) → installer `.env`
  (existing action item) + remove the hardcoded special-case file block.
- Standing anti-keyword test gate.

## Status
Delivery + rendering unification **validated end-to-end** (live LLM, real artifacts, PDF≡HTML across NewX
@Ask single/multi-format/"above" and Deep Research). Committing the validated working state; the dead-code
cleanup follows as a separate, tested change.
