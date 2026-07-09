# Changelog — v1.0.0.158

**Date:** 2026-07-08
**Scope:** Fix the false-positive `[unverified — no working source]` tag on Deep-Research stock-data blocks by making the citation liveness check fetch like a real browser (browser header set) instead of a UA-only bot. Deep links to the specific Yahoo Finance data pages (income statement → `/financials`, DCF → `/analysis`, ratios → `/key-statistics`, etc.) are kept intact and now resolve live.

## Problem
After v1.0.0.157 the DR stock report carried real structured figures (P/E, P/S, EV/EBITDA, DCF) sourced from `comprehensive_stock_analyzer`, but every stock-data paragraph was tagged `⚠️ [unverified — no working source]`. The `research/citation_grounding.py` output-side validator flags a block when it has citation links but **none** classify as valid (live).

Root cause is a **liveness false-negative**, not a dead link. The detailed formatters (`utils/financial_statements_extractor.py`, `utils/financial_ratio_calculator.py`, `utils/dcf_calculator.py`, `utils/projection_engine.py`) cite the Yahoo Finance deep-link subpages (`/financials`, `/balance-sheet`, `/cash-flow`, `/key-statistics`, `/analysis`). Those deep links are **live for a human browser** but our `research/link_liveness.py:_one_check()` fetched with a **User-Agent header only**. Yahoo Finance bot-guards (and other guarded hosts) gate on the missing `Accept` / `Accept-Language` that a real browser always sends and return **HTTP 404** for UA-only requests to those subpages. The liveness check then dropped them as dead → grounding saw `n_links > 0, n_valid == 0` → flagged the block.

Verified against the live server, same URL, same UA, same host:
```
=== liveness-style (UA only, as link_liveness.py did) ===
code=404          ← false negative → block flagged [unverified]
=== browser-style (UA + Accept + Accept-Language) ===
code=200          ← live → valid → no flag
```

## Fix (general, no hardcoded domain list — CLAUDE.md LLM-Policy Gate compliant)
In `research/link_liveness.py` `_one_check()`, send a browser-like header set alongside the User-Agent:
```python
headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
```

This is a **general** improvement — "fetch like a browser" — with no domain list and no per-site special-casing (passes the LLM-Policy Gate / generalization test). It cures the false-404 for Yahoo Finance **and** any other bot-guarded host.

Why it is safe:
- **Genuinely dead URLs are still caught.** A truly removed page returns 404/410 *regardless* of headers; the hard-dead drop rule (`status in (404, 410)`) still fires. Only false-404s (bot-guards) flip to 200.
- **The lenient policy is preserved.** Keep on 200/403/401/405/429/5xx/timeout/paywall/JS-shell; drop only on hard 404/410 or homepage-redirect. The drop set is unchanged — only the false-positive set shrinks.
- **Deep links stay intact.** The formatters are NOT touched. Income statement → `/financials`, DCF → `/analysis`, ratios → `/key-statistics` remain — the clickable citation deep-links to the specific data page, not a generic base (user requirement).

## Files changed
- `research/link_liveness.py` — `_one_check()` now sends browser-like header set (UA + Accept + Accept-Language) instead of UA-only.
- `tests/utilities/test_dr_liveness_headers.py` — new deterministic unit test (4 tests, monkeypatched `requests_compatible_get`): browser headers sent; bot-guarded false-404 now live; genuinely-dead still dead; homepage-redirect still dead. All pass.
- `version.py` — 1.0.0.157 → 1.0.0.158.

## End-to-end verification (live server, v1.0.0.158)
Multi-stock prompt: *"investigate and compare the valuation and 6-12 month prospects of PLTR and MSFT … full report"*.

Evidence from `logs/server_complete.log` + final answer:
- `comprehensive_stock_analyzer` succeeded for BOTH tickers (no "possibly delisted" on the data path):
  `Extracting financial statements for PLTR → Successfully extracted → Calculating DCF → Generating projections`
  (same for MSFT).
- `🩺 citation-liveness [ACTIVE]: dead=0/17 cited (verified 404/410/homepage-redirect)` — the deep-link URLs are now seen as LIVE (the false-404 is gone).
- Final answer: `[unverified — no working source]` count = **0** (was many before).
- Deep links to the SPECIFIC data pages remain and are live (not collapsed to base page):
  `finance.yahoo.com/quote/{PLTR,MSFT}/{financials,balance-sheet,cash-flow,key-statistics,analysis}` — 10 distinct deep links.
- Structured figures present in answer: P/E ×19, P/S ×10, EV/EBITDA ×9, DCF ×38, "intrinsic value" ×12.

| Metric | before (v1.0.0.157) | after (v1.0.0.158) |
|---|---|---|
| `[unverified — no working source]` in answer | many (every stock block) | **0** |
| Yahoo deep-link liveness | false-404 (UA-only) | live 200 (browser headers) |
| Deep links to `/financials` `/key-statistics` `/analysis` | stripped → generic | kept (specific page) |

Note: `📊 retrieval-audit` tags some Yahoo deep links `over_captured` (body not retrieved — Yahoo is a JS SPA, body extraction is thin) but the `🩺 citation-liveness` gate now classifies them as live, so they are no longer stripped. `over_captured` is a content-grounding signal tracked separately and does not trigger the `[unverified]` flag.

## Migration / rollback
- No schema / config change. No new config key.
- Rollback: revert `research/link_liveness.py` `_one_check()` to the UA-only header set (one block) → exact v1.0.0.157 behavior.

## Dependencies
- None new. `http_helpers.requests_compatible_get` already accepts a `headers` dict.