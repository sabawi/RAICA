# Changelog — v1.0.0.180

**Date:** 2026-07-12
**Scope:** Process guardrail — a pre-deploy **tool functional smoke test** — added in response to the v1.0.0.179 `search_web` incident (a swallowed `NameError` from a missing `import re` broke ALL web search for ~6 days while every offline gate stayed green). Test/tooling + docs only; **no server behavior change** (running servers need no restart for this commit).

## Added — `tests/smoke/tool_smoke.py` + `make smoke`
- **What it does:** actually **INVOKES** each core read/search tool through the real code path — `search_web`, `wikipedia_query`, `get_news_summaries`, `get_stock_and_company_data`, `lookup_website` — via `tool_manager.available_functions`, and asserts each returns real content without crashing. **Captures each tool's stdout**, so it catches an exception even when the tool **swallows** it into a generic string (which is exactly how the `search_web` `NameError` hid).
- **CODE vs ENV (never a flaky alarm):** HARD-FAILs (exit 1) only on a Python-exception signature (raised exception, or `NameError`/`is not defined`/`Traceback`/`UnboundLocalError`/… in the result or captured stdout). Empty / generic non-exception results are ENV **warnings** (network/egress/403) that do not block on their own.
- **Verified:** passes on current code (all 5 tools return real content); and the detector, fed the exact pre-fix output `DuckDuckGo Error: name 're' is not defined`, returns CODE-FAIL — i.e. it **would have caught the v179 bug on day one**.
- **Fast:** ~30s, no LLM.

## Changed — Deployment Protocol now mandates the smoke test
- `CLAUDE.md` Deployment Protocol step 6 now requires `make smoke` before any push/deploy; a CODE-FAIL blocks the deploy. `Makefile` gains the `smoke` target.

## Why (incident retro)
Offline/fixture gates (Tier-0) and even Tier-1 could not reliably catch "the tool crashes when invoked": the error was swallowed, and other tools kept returning citations, masking the failure. Tier-1 *did* surface a symptom (`S1_news_citation.citation_count` fell 12→8) that was wrongly filed as ENV noise instead of investigated. This smoke test closes the functional-coverage gap; the retro lesson (investigate a regressed metric, don't rationalize it) is recorded in agent memory.

## No dependency changes.
