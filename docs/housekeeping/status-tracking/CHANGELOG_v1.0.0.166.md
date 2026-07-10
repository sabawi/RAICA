# Changelog — v1.0.0.166

**Date:** 2026-07-10
**Scope:** Add a structured **analyst-consensus** block to the stock analyzer (real yfinance/Yahoo estimates), replacing the web-scraped analyst targets that drove the Buy/Hold/Sell ranking but degraded whenever live web search was rate-limited. (Item #1 of the finance-DR enhancement plan.)

## Problem
The Buy/Hold/Sell recommendation leaned heavily on **analyst price targets and upside %**, but those came from **web scraping** (search_web → Yahoo/MarketWatch/Benzinga pages) — the least-reliable input, and the first to thin out when the live AWS IP hits search rate-limits. The analyzer also had **no forward analyst view at all**: its 3-year projections are a historical-CAGR extrapolation explicitly labeled "not analyst consensus," so the report could never answer "what do analysts actually expect."

## What was added
New `utils/analyst_estimates.py` (`AnalystEstimates`), wired into `comprehensive_stock_analyzer` detailed mode as a SOURCE block, gated by `FeatureFlags.DETAILED_ANALYSIS_ANALYST_ESTIMATES`. From yfinance 0.2.65 it surfaces:
* **12-month price target** — mean / median / high–low range, # of analysts, and implied move vs current price (structured, cited to the Yahoo analysis page — no scraping).
* **Recommendation** — key (`strong_buy`…) + mean rating (1=Strong Buy … 5=Strong Sell) + the full **Strong Buy / Buy / Hold / Sell / Strong Sell distribution**.
* **Forward consensus (next FY)** — analyst **EPS** and **revenue** averages with **YoY growth** and analyst counts (genuinely new; e.g. NVDA fwd EPS $12.76 +42.2%, AMD fwd EPS $13.28 +79.3%). This finally sits alongside the RAICA historical-CAGR projections as a *real* forward view.
* **Long-term growth estimate** when available.

The block is explicitly self-labeled "REAL … market consensus; DISTINCT from the RAICA historical-CAGR projections and NOT web-scraped" so synthesis attributes it correctly instead of citing a scraped page. All yfinance growth fields are **fractions** and rendered ×100 (same scale gotcha as F4/F6); every endpoint is wrapped so a missing/flaky field never breaks the block, and no-data → empty string (never a half-rendered SOURCE).

## Files changed
* `utils/analyst_estimates.py` — **new** `AnalystEstimates` (get_estimates + format_for_llm).
* `user_tools/comprehensive_stock_analyzer.py` — import + gated detailed-mode block (reuses the already-fetched `ticker_info` to avoid a redundant `.info` fetch).
* `config/feature_flags.py` — `DETAILED_ANALYSIS_ANALYST_ESTIMATES = True`.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_analyst_estimates_scale_and_guards` (fraction→percent scaling + no-data guards, offline).
* `version.py` — `1.0.0.165` → `1.0.0.166`.

## Verification
* **Live analyzer (NVDA + AMD):** blocks render correctly — NVDA target mean $301.62 (range $180–$500, 58 analysts), +48.7% implied, dist 10/48/2/1/0, fwd rev $554.44B +41.2%, fwd EPS $12.76 +42.2%; AMD target $516.12, −5.6% implied, fwd EPS $13.28 +79.3%. Scales correct (growth as percent, not fraction).
* **Unit tests:** 31/31 PASS (was 30). New test covers `_pct` fraction→percent, `_num` NaN handling, no-data guards, and a populated-dict render.

## Notes
* Adds ~4 yfinance endpoint calls per stock (earnings/revenue/growth estimates + recommendations summary) — modest latency (~seconds/stock), hitting Yahoo data endpoints, not the rate-limited search engines.
* No synthesis-prompt change yet — the block is strongly self-labeling, so synthesis should prefer it over scraped targets; will confirm on the next live 5-stock @Ask and add a steering directive only if it still mis-attributes.
* No new dependency (yfinance/pandas already required).
