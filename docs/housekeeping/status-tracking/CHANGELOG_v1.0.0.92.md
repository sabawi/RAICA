# CHANGELOG v1.0.0.92

**Date:** 2026-06-06
**Previous:** v1.0.0.91 (LLM writes cited markdown; filenames de-hardcoded)
**Theme:** **Classifier now picks the file-creation tool for "attachment/file" requests** — fixed via an
accurate tool DESCRIPTION (language), not keywords (LLM-Policy Gate)

---

## Bug (live dev validation)

@Ask "email me the above news in **html formatted attachment**" → the news arrived in the **email body,
not as a file attachment**. Log: `🧭 INTENT(llm) AUTHORITATIVE: missing_tools=['secure_email_sender']`
(legacy correctly had `['sandboxed_executor', 'secure_email_sender']`). With no file tool selected, no
file was created → body email.

## Root cause

The LLM intent classifier under-picked: it chose email but **no file-creation tool**. Confirmed it
wasn't a deferred-tool artifact (`tools_called` was `['comprehensive_stock_analyzer']`, not the delivery
tools). The reason was a **description gap**: for "create an HTML file," no tool's catalog description
fit — `pdf_generator` says *PDF*, and `sandboxed_executor` read as *"execute system commands, read/write
files, run code"* (its `create_file` capability was buried). So the classifier had nothing that clearly
*"creates an HTML/document file"* and picked only email.

## Fix (gate-aligned — accurate capability description, no keywords)

Rewrote `sandboxed_executor`'s description to LEAD with its document-creation capability:
> *"Create a DOCUMENT FILE (HTML, Markdown, text, or PDF) from content — use action 'create_file' to
> save the assistant's answer/report as a file for emailing as an attachment or for download (markdown
> auto-converts to a formatted HTML or PDF document). This is the tool to use whenever a
> file/attachment/'HTML file'/'PDF report' is requested. …"* (code-exec capabilities retained after).

The classifier (and any LLM) can now map "create an HTML file/attachment" → the file tool by reasoning
over the description — no keyword lists.

## Validation (smoke test, 2 runs/case)
- "email me … in html formatted attachment" → **file tool + email** (both runs) — was email-only.
- "email me the news as a PDF file" → file tool + email (both runs).
- "send me an email saying hi" → email only (correct — no file).

## Files
- `user_tools/sandboxed_executor.py` — document-creation-first description.
- `version.py` (→ 1.0.0.92), `README.md`, this changelog.

## Re-test expectation
@Ask "email me the above news in an HTML formatted attachment" → email arrives **with an HTML file
attachment** (content-named, clean body, citations inside), plus a NewX post.

## Notes / remaining nuance (flagged honestly)
- The classifier sometimes names `pdf_generator` vs `sandboxed_executor` as the file tool; the POST-LLM
  path determines the actual file extension from the requested format, so an "HTML" request still yields
  `.html`. Monitor on re-test.
- On a bare prompt with no conversation context, the classifier may also include a research tool (e.g.
  `get_news_summaries`) to fetch "the above news"; with real in-thread context this shouldn't occur.

## Status
Dev: RAICA v1.0.0.92 (`mode: llm`). NewX unchanged. Reversible. Not committed.
