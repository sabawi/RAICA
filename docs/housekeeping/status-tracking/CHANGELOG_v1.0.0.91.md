# CHANGELOG v1.0.0.91

**Date:** 2026-06-06
**Previous:** v1.0.0.90 (coherent policy-language delivery directives)
**Theme:** **Delivery deliverables fixed: LLM writes cited markdown (system formats the file); filenames
de-hardcoded** — applying the new LLM-Policy Gate (no keywords, no conflicting policies)

---

## Bugs (live dev validation, @Ask "email me an HTML file of the news")

1. **No NewX post** — Ask's reply was a raw HTML dump (no markdown citations) → NewX citation guard discarded it.
2. **Hardcoded filename** — got `financial_analysis_…html` for a news briefing.
3. **Document body contained the LLM's preamble + ```` ```html ```` fence** instead of clean content.
4. **No citations in the file** — the HTML dump dropped the `[Title](URL)` links.

## Root cause (one conflict + hardcoding)

RAICA told the primary LLM *"Your response will be used as the file content… ACTUALLY CREATE IT"* (a
file-content instruction) **and** had an `HTML GENERATION RULES` block telling it to *produce HTML* —
while the platform needs a **cited markdown answer**. **Conflicting policy** → the LLM emitted raw HTML
(bad for the post AND the file). The HTML converter (`sandboxed_executor._create_real_html_file`,
markdown→HTML preserving links) was bypassed. Filenames were chosen by **hardcoded keyword maps**
(`_generate_dynamic_filename`, `_generate_dynamic_title`, and an inline `gaza/financial/news` block in
the interceptor).

## Fix (gate-aligned: policy language + de-hardcoding + conflict removal)

- **Policy keystone** (`_build_enhanced_primary_system_prompt` workflow instructions): the LLM now
  produces its **normal answer in MARKDOWN with `[Title](URL)` citations**, NOT raw file markup, no code
  fences, no "I'll create…" preface. *The system formats the markdown into the requested file.* Fixes
  #1 (cited post passes the guard), #3 (clean content → converter makes clean HTML), #4 (citations
  preserved by the markdown→HTML converter).
- **NO-INCONSISTENCY:** removed the conflicting `HTML GENERATION RULES` block from
  `primary_model_system_prompt.txt` (formatting is the converter's job, not the LLM's).
- **De-hardcoded filenames (#2):** the interceptor now names the file from the **content** — the
  model-set email subject, else the document's own first heading — never topic keywords.
  `_generate_dynamic_filename` rewritten to derive from the request subject (no keyword map, no
  `financial_analysis`/`news_analysis`/`calendar_report` hardcodes).

## Files
- `fastapi_server_complete.py` — workflow instruction → cited-markdown policy; interceptor filename
  content-derived; `_generate_dynamic_filename` de-hardcoded.
- `primary_model_system_prompt.txt` — removed conflicting `HTML GENERATION RULES`.
- `version.py` (→ 1.0.0.91), `README.md`, this changelog.

## Re-test expectation (@Ask "email me an HTML file of the news")
- A NewX **post** appears (cited markdown answer, passes the guard).
- The email arrives with an HTML attachment whose **filename reflects the content** (e.g.
  `breaking_news_briefing_…`), whose **body is clean** (no preamble/fence), and which **contains the
  citation links**.
- Any delivery note is in the message/email body, not inside the document.

## Remaining gate debt (flagged, not on the tested path)
`_generate_dynamic_title` still contains a topic keyword map (used for some titles/subjects, not the
filename anymore). Same anti-pattern — clean when its callers are revisited (ideally derive titles from
the document's own heading).

## Status
Dev: RAICA v1.0.0.91 (`mode: llm`). NewX unchanged this round. Reversible. Not committed.
