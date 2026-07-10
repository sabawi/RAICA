# Changelog — v1.0.0.165

**Date:** 2026-07-10
**Scope:** Drop the dead/redundant `mullvad_*` search backends from `ddgs` so every web search stops wasting a failed connect on them. Small, self-contained fix isolated from the broader search-egress work.

## Problem
`search_web` (and the stock analyzer's news search) call `ddgs.text(query)` with the default `backend="auto"`, which queries ALL text engines — including `mullvad_brave` and `mullvad_google`. Those route through `https://leta.mullvad.net`, which **fails DNS resolution in every environment we run** (verified: `Name or service not known` on both the live AWS box and locally). Each multi-round Deep Research run logged **10–18** such failures (`engine:mullvad_google: DDGSException … dns error`), wasting a connect-timeout per search. The two mullvad engines are also **redundant** — they are privacy-proxy fronts to the same `google`/`brave` providers already queried directly, so they add zero coverage.

Surfaced while diagnosing why one live 5-stock @Ask run had a higher search-failure rate than a prior run (429s tripled) — the mullvad DNS failures were a constant contributor separate from the variable rate-limiting.

## Fix
Pass an explicit `backend=` to `ddgs.text()` listing all working text engines **except** the `mullvad_*` ones, discovered **dynamically** from ddgs's own registry (`ddgs.engines.ENGINES["text"]`, filtering names starting with `mullvad`) so newly-added engines are auto-included. Falls back to `"auto"` (prior behavior) on any introspection error, so it can never regress search. Resolves to `brave,google,mojeek,wikipedia,yahoo,yandex` on the pinned ddgs 9.4.3.

- `user_tools/comprehensive_stock_analyzer.py` — new module fn `ddgs_working_backends()`; used in the news search.
- `fastapi_server_complete.py` — same dynamic exclusion inlined in `search_web`'s `ducducgo()` (kept inline to avoid a core→user-tool import; comment cross-references the analyzer helper).

## Files changed
* `fastapi_server_complete.py` — `search_web` passes the mullvad-excluded backend.
* `user_tools/comprehensive_stock_analyzer.py` — `ddgs_working_backends()` + news-search call.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_ddgs_backends_exclude_mullvad`.
* `version.py` — `1.0.0.164` → `1.0.0.165`.

## Verification
* **Structural:** ddgs `_get_engines(category, backend)` uses exactly the passed backend list when not `auto`, so an excluded engine is never instantiated. `ddgs_working_backends()` → `brave,google,mojeek,wikipedia,yahoo,yandex` (no `mullvad`).
* **ddgs call:** `ddgs.text(query, backend=<no-mullvad>)` returns results (3/3).
* **E2E through the running server (v1.0.0.165):** a real `search_web`-driving `/v1/chat/completions` request produced **0** `mullvad` log lines (was 10–18/run) while still returning 19 successful (HTTP 200) searches.
* **Unit tests:** 30/30 PASS (was 29).

## Notes
* This does NOT address the separate live-egress rate-limiting (403/429 from Brave/Google on the shared AWS IP) — that remains the standing `search_web` proxy-egress action item and affects all DR topics.
* To re-enable mullvad (e.g. if `leta.mullvad.net` becomes reachable), delete the `startswith("mullvad")` filter.
