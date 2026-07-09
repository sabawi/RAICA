# Changelog — v1.0.0.159

**Date:** 2026-07-08
**Scope:** Surgical fix for the catastrophic accuracy bug in the Deep-Research stock-analysis pipeline where **stale last-fiscal-year annual statement data was mixed with the live market price**, producing wildly wrong P/E and DCF for cyclicals. The pipeline now sources the current-period base from yfinance's trailing-twelve-month (TTM) `info` fields (which are internally consistent with the live price) and falls back to the annual statement only when TTM is unavailable — with an explicit staleness flag so the LLM and the user are never silently misled.

## Problem (root cause)
A review of a 5-stock OpenWebUI DR run (META, GOOGL, AMZN, MU, ORCL) found that the stock analyzer was **mixing two inconsistent time bases**:

- The **live market price** (`current_price`, `market_cap`) — real-time, today.
- The **annual income / cash-flow statement** (`ticker.financials`) — the last **fiscal year**, which can be months stale.

For a cyclical like Micron (MU) — where the memory cycle just turned and TTM earnings are ~6× the last fiscal year — this mismatch produced catastrophically wrong figures:

| Metric | Before (stale annual × live price) | After (TTM) | Correct |
|---|---|---|---|
| P/E | **125.49** | **21.23** | ~21 |
| EPS | $7.56 | $44.69 | $44.69 |
| P/S | 28.67 | 11.87 | ~11.9 |
| EV/EBITDA | 109.82 | 15.79 | ~15.8 |
| Current FCF | $1.67B | $7.64B | $7.64B |
| DCF intrinsic value | **$2.37** (→ "99.8% downside") | **$28.71** | sane |

The annual statement had NI=$8.54B (last FY) while TTM NI is $50.47B. Dividing the stale $8.54B by the live-share-count-implied EPS and then dividing the live $948.80 price by that stale EPS gave P/E 125. The DCF projected from a stale $1.67B FCF base against a live price → $2.37 intrinsic value → "99.8% downside" (a false signal). META, GOOGL, AMZN, ORCL looked "coherent" only by accident — their annual statement was not as far from TTM, so the error was masked, not absent.

This was an **accuracy** bug, not a formatting bug. It silently corrupts any valuation the DR pipeline emits for tickers whose fiscal year is not the current calendar period — especially cyclicals and companies whose fiscal year ended months ago.

## Fix (surgical — 3 data-sourcing points, no formatter/URL/liveness/planner changes)
The yfinance `info` dict carries **trailing-twelve-month** fields (`trailingEps`, `trailingPE`, `forwardPE`, `netIncomeToCommon`, `freeCashflow`, `totalRevenue`, `ebitda`, `sharesOutstanding`) that are **internally consistent with the live price**. The fix makes the three downstream calculators prefer TTM and fall back to the annual statement only when TTM is absent, tagging every figure with its source and emitting a staleness note when the two diverge.

### 1. `utils/financial_ratio_calculator.py` — `calculate_valuation_ratios`
- Signature now accepts `ticker_info: Dict = None`.
- **EPS**: prefer `ticker_info['trailingEps']` (TTM); fall back to `net_income / shares` (annual) only if absent.
- **P/E**: prefer `ticker_info['trailingPE']` (TTM, authoritative); fall back to `current_price / eps`.
- **Forward P/E**: pass through `ticker_info['forwardPE']`.
- **Shares**: prefer `ticker_info['sharesOutstanding']` (TTM) over annual-derived.
- **P/S**: use `ticker_info['totalRevenue']` (TTM) as denominator, else annual revenue.
- **P/FCF**: use `ticker_info['freeCashflow']` (TTM), else annual-computed FCF.
- **EV/EBITDA**: use `ticker_info['ebitda']` (TTM), else annual operating-income proxy.
- **Staleness flag** (`pe_note`): when the live-price-vs-annual P/E diverges >20% from TTM, emit an explicit note — e.g. for MU: *"⚠️ P/E staleness: live price vs annual-figure P/E = 125.5 diverges 491% from TTM P/E 21.2. The annual income statement is stale; USE the TTM P/E 21.2."* The LLM sees this and surfaces it to the user instead of silently reporting the stale number.
- `calculate_all_ratios` reads `financials['ticker_info']` and passes it through.
- `_format_valuation_ratios` prints `Forward P/E`, the `pe_note`, and a `[source]` tag on each ratio.

### 2. `utils/dcf_calculator.py` — `calculate_intrinsic_value`
- Reads `financials['ticker_info']`.
- **Current FCF**: prefer `ticker_info['freeCashflow']` (TTM); fall back to the annual cash-flow statement **only** if TTM is absent. Tags `calculations['fcf_source']` (`'TTM (info.freeCashflow)'` or `'annual cash-flow statement (stale)'`).
- **Staleness note** (`assumptions['fcf_note']`): when falling back to the annual statement, emit *"⚠️ DCF based on last fiscal-year FCF (stale); TTM freeCashflow unavailable. The live price is being compared against a stale FCF base — treat the intrinsic value as directional only."*
- `format_dcf_for_llm` prints `[fcf_source]` and the `NOTE:`.

### 3. `utils/projection_engine.py` — `generate_revenue_projections` / `generate_earnings_projections` / `generate_fcf_projections`
- Each now accepts `ticker_info: Dict = None`.
- The **"current" base** for the 3-year projection path prefers TTM:
  - Revenue → `ticker_info['totalRevenue']` else `revenue_values[0]`.
  - Net income → `ticker_info['netIncomeToCommon']` else `earnings_values[0]`.
  - FCF → `ticker_info['freeCashflow']` (negative kept — valid for ORCL) else `fcf_values[0]`.
- Each result dict carries `current_source` (`'TTM (info.totalRevenue)'` or `'annual statement (stale)'`). The historical CAGR is still computed from the multi-year annual series (legit — that's what annual data is for); only the *current base* that the live price is compared against switches to TTM.
- `generate_projections` reads `financials['ticker_info']` and passes it through; formatters print `[current_source]`.

### 4. `user_tools/comprehensive_stock_analyzer.py` — `_get_real_time_data`
- The real-time display block now merges the raw `info` dict (`{**info, ...snake_keys...}`) so the camelCase fields the display reads (`forwardPE`, `totalRevenue`, `profitMargins`, `returnOnEquity`, `debtToEquity`, `bookValue`, `priceToBook`, `revenueGrowth`) resolve instead of `N/A`. Added `forward_pe` snake key. `pe_ratio` already used `trailingPE` (TTM) — unchanged.

## Design constraints honored
- **No hardcoded domain/ticker lists, no keyword/regex meaning-decision, no per-case if-elif** — passes the CLAUDE.md LLM-Policy Gate. The fix is a *data-source preference* (TTM field present → use it, else fall back), not a semantic classifier.
- **Surgical scope** — formatters, citation URLs, liveness, and the DR planner are untouched. Deep links still point to the specific Yahoo Finance data page (user requirement: the clickable citation goes to the source of the particular data, not a base page).
- **No regression** — when `ticker_info` lacks TTM fields (older tickers, thin coverage), the annual statement is used exactly as before; only the source tag and the optional staleness note are added.
- **Honesty over silence** — when the annual statement must be used, the LLM and user are told via `pe_note` / `fcf_note` rather than presented a confidently-wrong number.

## Files changed
- `utils/financial_ratio_calculator.py` — TTM-first valuation ratios + `pe_note` staleness flag + source tags.
- `utils/dcf_calculator.py` — TTM-first current FCF + `fcf_note` stale-fallback note + source tag.
- `utils/projection_engine.py` — TTM-first current base for revenue/earnings/FCF projections + `current_source` tags.
- `user_tools/comprehensive_stock_analyzer.py` — real-time display block merges raw `info` (camelCase fields resolve).
- `tests/utilities/test_dr_ttm_sourcing.py` — new deterministic unit test (10 tests, **no network** — mocked annual statements + ticker_info). Guards: TTM P/E preferred over annual (MU 125→21.23), EPS TTM, P/S TTM, fallback path, DCF TTM FCF + stale note, projection TTM base + annual fallback. All pass.
- `version.py` — 1.0.0.158 → 1.0.0.159.

## Verification
- **Unit (deterministic, no network):** `python tests/utilities/test_dr_ttm_sourcing.py` → 10/10 PASS.
- **End-to-end (ground-truth re-run, live data):** MU P/E 125.49 → 21.23; EPS $7.56 → $44.69; P/S 28.67 → 11.87; EV/EBITDA 109.82 → 15.79; FCF $1.67B → $7.64B; DCF $2.37 → $28.71; staleness flag fires ("diverges 491%"). META remains coherent. Real-time block now populated (Forward P/E 6.34, Revenue TTM $90.27B, ROE/margins).

## Open (documented, NOT changed in this version)
- ORCL "debt" = total liabilities (D/E 3.67 overstates financial leverage; real LT debt ~$90B) — separate fix.
- MU 6% dividend yield is a yfinance data glitch — separate fix.
- OpenWebUI tag/title-generation meta-request mis-fires the DR gate (wastes ~152s) — suggested policy-language gate fix, not applied.