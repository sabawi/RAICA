# CHANGELOG v1.0.0.129

**Date:** 2026-06-17
**Previous:** v1.0.0.128 (tool-calling 5xx retry + LLM re-prompt fallback)
**Theme:** **Deep-Research document title fix.** The email subject + filename for a DR delivery were taken
from the document's first heading — which, for a report that opened with a numbered section, was the
*section* heading. Two layers fix it: synthesis emits a real top-level title, and delivery refuses to use an
enumerated section heading as the title.

---

## Symptom

A live `@Ask` DR request ("…history of street gangs… email as PDF and HTML") was delivered with email
subject + filenames of **`1. The Deep Roots: Slavery, Reconstruction, and the First Black Communities`** —
the first *section* of the report. The report had **no document-level title**, so the delivery grabbed the
first heading (`# 1. The Deep Roots…`) as the title AND stripped it from the PDF body (so section 1 also
lost its heading). The email *itself* delivered correctly (PDF+HTML, one message, via Gmail) — only the
title/subject/filename were wrong.

## Root cause

1. `research/synthesis.py` told the synthesizer to *"open with a TL;DR, then sections…"* — never a
   document **title**. So the first markdown heading was the first section.
2. `fastapi_server_complete.py` `_run_dr_delivery` took the **first heading** as `doc_title` (→ subject +
   filename slug) and stripped it from the body, with a keyword-map fallback (`_generate_dynamic_title`,
   itself a CLAUDE.md violation) only when there was no heading at all.

## Fix (two layers)

- **Synthesis emits a title** (`research/synthesis.py`): the STRUCTURE directive now requires the report to
  BEGIN with a single top-level `# <Title-Case name of the overall topic>` (one H1, not numbered, not a
  section), then the TL;DR, then `##` sections. So the first heading is the real title.
- **Delivery rejects enumerated section headings as the title** (`_run_dr_delivery`): a first heading that
  looks like a section (`1. …`, `2) …`, `Part 3 …`, `Section 4 …`, `Chapter 5 …`) is NOT used as the
  title (and NOT stripped from the body). Instead the title is derived from the **research request** via a
  new LLM helper `_llm_title_from_request(user_prompt, content, generate_stream)` — topic-accurate,
  heading-independent, policy-gate compliant (no keyword/topic map). Replaces the broken
  `_generate_dynamic_title` keyword fallback on the DR path.

## Verified

- **Unit** `tests/integration/test_dr_title_extraction.py`: the enumerated-section discriminator rejects
  `1.`/`2)`/`Part 3`/`Section 4`/`Chapter 5` headings and accepts real titles (incl. `2026 Iran War …`,
  `U.S. Government …`); `_llm_title_from_request` derives a clean title from the request (mocked stream),
  never echoing the section heading; None-stream is safe. All green.
- **End-to-end (local DR run)**: "history of jazz music… save as PDF" → synthesis produced
  `# A History of Jazz Music in America` (a real title, not a numbered section) → delivery filename
  `a_history_of_jazz_music_in_america_….pdf`. Subject/filename now reflect the topic.

## Not in this release (noted)
- The non-DR POST-LLM arbitrator deep-fallback (`fastapi_server_complete.py:~8754`) still uses the
  keyword-based `_generate_dynamic_title`; left for a separate, scoped change (out of the reported DR path).

## Files
- `research/synthesis.py` (title directive), `fastapi_server_complete.py` (`_llm_title_from_request` +
  `_run_dr_delivery` title logic), `tests/integration/test_dr_title_extraction.py` (new),
  `version.py` (→ 1.0.0.129), `README.md`, this changelog.
