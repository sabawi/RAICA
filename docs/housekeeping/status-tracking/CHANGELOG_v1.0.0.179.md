# Changelog — v1.0.0.179

**Date:** 2026-07-12
**Scope:** Critical production hotfix — `search_web` was fully broken (every call errored) — plus a bundled reasoning-directive tweak (TWEAK-001).

## Fixed — CRITICAL: `search_web` failed on every call (`NameError: name 're' is not defined`)
- **Symptom:** every web search returned *"An error occurred during the web search query"* — observed across `@Ask`, Deep Research, and news/finance bots (49 failures in one day on live). `published_papers_search` / `wikipedia_query` / `document_search` were unaffected.
- **Root cause:** this file imports `re` **per-function** (there is no module-level `import re`). The citation guard `_is_specific_article_url` (`fastapi_server_complete.py`), added during the citation-specificity hardening, calls `re.search` but was written **without** a local `import re`. `search_web` invokes that guard on **every** candidate result (default-on), so the first result raised `NameError`, which the search handler swallowed into the generic error string — total failure of web search.
- **Not the cause:** the `mojeek 403` lines in the log are a separate, pre-existing datacenter-egress issue; ddgs aggregates other backends (google/yahoo/wikipedia return 200), so 403s alone never fail a search. The `NameError` was the killer.
- **Fix:** added `import re` inside `_is_specific_article_url`, matching the file's per-function import convention (one line, zero blast radius).
- **Verified:** (1) isolated call of the patched function — no `NameError`, correct section-vs-article classification; (2) real ddgs query through the full path (`_validate_article_url` → `_is_specific_article_url`) returned 6/6 kept results, guard raised `NameError` 0 times. Full user-facing confirmation on redeploy.

## Changed — TWEAK-001: sharpened the `NO STAGED EVIDENCE` reasoning clause (conditional → affirmative)
- **Files:** `research/synthesis.py` (`REASONING_DIRECTIVE` → DR synthesis + arbitration), `primary_model_system_prompt.txt` (@Ask path).
- **Why:** a live hard-reasoning reply (Fibonacci) presented a **fabricated Python `Output:` block** — the RAICA log confirmed only `wikipedia_query` + `search_web` ran (no code-execution tool exists on the @Ask path), so the "output" was staged. The v178 conditional wording (*"…unless you genuinely did"*) couldn't be self-evaluated by a model unaware it can't run code, and collided with the user's *"use python"* instruction.
- **Change:** affirmative statement of the environment fact + rule: *"you CANNOT execute code in this answer… never append an 'Output:'/'Result:'/console block as if it ran… compute the result yourself and show the ACTUAL arithmetic. A shown 'output' you did not truly produce is fabricated evidence, even if the number happens to be right."* Policy-language only; accurate for both prose nodes (neither executes code inline).
- **Post-deploy validation:** re-run the Fibonacci "use python" prompt and confirm no `Output:` block appears.

## Verification
- Local server healthy on v1.0.0.179; imports clean; Tier-0 benchmark expected green (no CODE regression).
- No config / dependency changes.
