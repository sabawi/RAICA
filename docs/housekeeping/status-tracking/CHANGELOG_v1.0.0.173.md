# Changelog — v1.0.0.173

**Date:** 2026-07-11
**Theme:** Finance hardening **Phase P1 (Seamless Recovery)** — route every yfinance fetch through a bounded retry so a transient Yahoo blip never fails a ticker. First execution phase of `docs/RAICA_FINANCE_HARDENING_AUDIT.md` (signed off v172).

## Added
* **`utils/yf_retry.configured_fetch(fn, label, log)`** — convenience wrapper over `fetch_with_retry` that reads `stock_analyzer.fetch_retries` / `fetch_backoff_seconds` from config, so every finance fetch site is a one-liner sharing one retry policy.

## Fetch sites now retried (were single-shot)
* **`financial_statements_extractor.extract_financials`** — the 7-statement build (`financials`, `quarterly_financials`, `balance_sheet`, `quarterly_balance_sheet`, `cashflow`, `quarterly_cashflow`, `info`) is wrapped as one retried unit. **Highest blast radius**: previously a transient blip on any one → `return {}` → every downstream calculator (DCF/ratios/projections) silently starved.
* **`analyst_estimates.get_estimates`** — `t.info` fallback + `get_earnings_estimate` + `get_revenue_estimate` + `get_growth_estimates` (the forward EPS/revenue consensus fetches).
* **`technical_indicators.get_indicators`** — the `t.history(period="2y")` fetch.
* **`comprehensive_stock_analyzer`** — the chart-history fetch (`:783`). (The `.info`/`.history` quote gate was already retried in v172.)

## Behavior
* Retry triggers **only on a thrown transient error**; genuinely-absent data (empty/None return) is **not** retried and skips exactly as before (no wasteful retries, no latency added for tickers that legitimately lack a field).
* Every attempt is logged (transparent); on exhaustion the last exception re-raises → existing except path → clear error (P2 will make that error a distinguishable, labeled sentinel instead of `{}`/blank).
* Config: `stock_analyzer.fetch_retries: 3`, `fetch_backoff_seconds: 0.8` (already present from v172).

## Verification
* Unit: `test_yf_fetch_retry` + new `test_finance_fetch_retry_p1` (extractor recovers on attempt 3 from a transient statement-fetch failure → real dict, not `{}`). Full finance suite **22/22 PASS**.
* Live smoke: AVGO `extract_financials` + `AnalystEstimates.get_estimates` (target $523.7, fwd rev +62.4%) + `TechnicalIndicators.get_indicators` (SMA50 405.98, RSI 53.7) all fetch through the retry path.
* RAICA restarted, health 200, no startup errors.

## Next (per audit doc)
* **P2 (Transparency):** replace failure-as-`{}`/`None` with a distinguishable `{"_error":…}` sentinel + formatter label "⚠️ unavailable — fetch failed"; kill bare `except:`.
* **P3 (Data-integrity):** shared `_safe_div` sweep across the ~108 division sites.

## No dependency changes · not pushed.
