# Changelog — v1.0.0.160

**Date:** 2026-07-08
**Scope:** Root-cause fixes for the 9 financial-data-quality bugs found in the 5-stock @Ask audit
(META, AMZN, GOOGL, ORCL, MU). The v1.0.0.159 TTM-first retrofit fixed EPS/P/E/P/S/P-FCF/EV-EBITDA but
left **P/B, ROE/ROA/ROIC, interest coverage, and the entire DCF balance sheet on the stale annual
statement**, mis-formatted dividend yield, passed through an understated forward P/E, mislabeled
historical-CAGR projections as "3-Year Forward" analyst consensus, and printed a nonsensical >100%
DCF "downside" for negative-equity names. This version corrects all of them and tells the synthesis
LLM that DCF/projection blocks are RAICA **model estimates**, not Yahoo-sourced data.

## Problem (root cause — 9 bugs, each pinned to file:line)
| # | Bug | Symptom | Root cause |
|---|-----|---------|------------|
| 1 | Stale balance-sheet ratios | ROE/ROA/ROIC/liquidity/leverage from last fiscal year | `financial_ratio_calculator.py:338-340` read `.get('annual')` only; quarterly fetched (`extractor.py:85`) but never consumed |
| 2 | P/B stale | MU 19.78 (vs ~10.9), GOOGL 5.11 (vs ~9.2) | `financial_ratio_calculator.py:212,270-273` annual equity + TTM shares + live price; no `priceToBook` fallback |
| 3 | Dividend yield 6.00% | MU showed 6.00% (true ~0.06%) | `comprehensive_stock_analyzer.py:232,252-271` trusts `dividendYield`; 0.1-threshold heuristic sent mis-populated 0.06 → "6.00%" |
| 4 | ROE/ROA/ROIC ending-balance + net income | META ROIC 20.08% (vs 31.38%) | `financial_ratio_calculator.py:82-98` ending annual balances + net income (not NOPAT, not averages) |
| 5 | Forward P/E = FY+2 | understated for non-calendar fiscal years | `financial_ratio_calculator.py:264-267` pass-through of `info['forwardPE']` (yfinance next-fiscal-year, ~FY+2 for META/AMZN/ORCL/MU) |
| 6 | Interest coverage stale/tiny-denominator | GOOGL 175x | `financial_ratio_calculator.py:133-134,152-153` annual only; tiny residual interest expense |
| 7 | DCF mixes TTM FCF + stale annual balance sheet | META intrinsic ~$287 vs annual-FCF ~$483 | `dcf_calculator.py:139,286,390-397` annual balance sheet; net debt nets only Cash & Equivalents (omits marketable securities) |
| 8 | DCF "137% downside" | ORCL >100% downside (a long can't lose >100%) | `dcf_calculator.py:419,509,519-520` no guard for negative intrinsic; `abs()` prints >100% as "downside" |
| 9 | Projections mislabeled "3-Year Forward" + hidden caps | 4 of 5 stocks showed exactly "20.0%" earnings growth | `projection_engine.py:361,376,391,415,435,455` historical CAGR relabeled as forward; `min(growth,0.20)` cap piles high-growth names at the ceiling; `historical_growth` stored but never printed |

## Fix
### `utils/financial_ratio_calculator.py` (bugs 1, 2, 4, 5, 6)
- Added `_freshest_balance_sheet` / `_freshest_income_stmt` (prefer quarterly col 0 → annual fallback),
  `_avg_value` (average of n most-recent columns for balance-sheet stock items), `_ttm_value`
  (sum of n most-recent quarterly columns for flow items).
- `calculate_all_ratios` now feeds the **most-recent quarterly** balance sheet to all balance-sheet
  ratios (profitability/liquidity/leverage/efficiency/valuation) and passes `quarterly_income` through.
- **ROE/ROA**: TTM net income (`info['netIncomeToCommon']`) over **averaged** most-recent quarterly
  equity / total assets (not ending annual balances).
- **ROIC**: NOPAT (TTM operating income × (1−tax)) / averaged invested capital — not net income.
  Emits `roic_basis` so the LLM sees the basis.
- **P/B**: prefer `info['priceToBook']` (TTM, authoritative); fallback to most-recent quarterly equity
  per share with a `pb_note` staleness flag.
- **Forward P/E**: keeps `info['forwardPE']` but adds a `forward_pe_note` (may be next-fiscal-year/FY+2
  EPS for non-calendar fiscal years; treat as approximate, not a precise NTM multiple).
- **Interest coverage**: TTM (4-quarter sum) operating income / abs(TTM interest expense); annual
  fallback; `interest_coverage_note` when the denominator is negligible (interest income ≫ expense).
- Formatters render every `*_note` / `roic_basis` so they reach the LLM.

### `utils/dcf_calculator.py` (bugs 7, 8 + MODEL ESTIMATE label)
- `calculate_wacc` / `calculate_intrinsic_value` use the **freshest (quarterly) balance sheet** so
  debt/equity/cash are current and consistent with the TTM FCF base.
- **Net debt** now nets `Cash + Short Term Investments + Long Term Investments + Investments` against
  debt (large-cap tech holds tens of billions in marketable securities; omitting them understated
  intrinsic value). Stored as `cash_and_securities` / `net_debt` in `calculations`.
- **Negative-intrinsic guard**: when `equity_value ≤ 0` or intrinsic ≤ 0, sets `negative_equity=True`,
  `intrinsic_value=None`, `upside_downside=None`, and emits `negative_equity_note`. The formatter
  prints `INTRINSIC VALUE PER SHARE: N/M — model estimates negative equity value (net debt >
  enterprise value); DCF not meaningful for this name.` instead of a >100% "downside".
- `format_dcf_for_llm` labels the block **"RAICA MODEL ESTIMATE"** (title + content header: "not
  sourced from the URL; the URL is the stock's Yahoo page only"). DCF content cap raised 500→1000 so
  the intrinsic-value result / N/M line is never truncated.

### `utils/projection_engine.py` (bug 9)
- Titles relabeled: `"{ticker} … Projections (3-Year, Historical-CAGR Extrapolation — not analyst consensus)"`.
- Formatters now render **`Historical CAGR (raw, uncapped): X.X%`** alongside the **capped projected
  rate** (`Projected growth, capped at 20%/15%`), plus a content NOTE: "These projections extrapolate
  the historical CAGR forward; they are NOT analyst consensus estimates." The `historical_growth`
  value was already stored — it is now surfaced instead of hidden.

### `user_tools/comprehensive_stock_analyzer.py` (bug 3 + note surfacing)
- `_format_dividend_yield` rewritten: computes the authoritative yield as **`dividendRate / current_price`**
  when both are available (never divides by 100); falls back to `dividendYield` as a decimal fraction
  with a "verify, field is inconsistently populated" note. A >10% yield triggers a sanity note (not a
  silent cap). Backward-compatible with a bare-value call.
- Display block: dividend yield now passes the full `data` dict; Forward P/E line carries the
  non-calendar-fiscal-year caveat inline.

### `research/synthesis.py` (NO-INCONSISTENCY reconciliation)
- The system prompt's "NEVER invent/guess/estimate/extrapolate" rule (line ~692) conflicted with
  relaying DCF/projection model estimates. Added a reconciling directive: SOURCE blocks labeled
  "RAICA MODEL ESTIMATE" or "Historical-CAGR Extrapolation" ARE permitted to be relayed, but MUST be
  (a) attributed to the RAICA model — never cited as Yahoo-sourced data, (b) labeled as estimates in
  the answer, (c) never blended with sourced figures without distinguishing them. The "never estimate"
  rule applies to figures the LLM generates itself, not to clearly-labeled model estimates in evidence.

## Design constraints honored
- **LLM-Policy Gate**: no hardcoded keyword lists / regex / if-elif to decide meaning. All changes are
  numeric computations + factual policy-language notes (staleness/definition disclaimers the LLM reads),
  following the existing `pe_note` pattern. The synthesis directive is policy language, not routing.
- **No-Inconsistency Clause**: the synthesis prompt was audited and the model-estimate directive
  reconciled with the existing "never estimate" rule so the two speak with one voice.
- **No regression**: all new params have defaults; the existing 10 TTM tests still pass; annual
  fallback preserved when quarterly/TTM is absent.
- **Honesty over silence**: every stale-fallback or model-estimate figure carries an explicit note.

## Files changed
- `utils/financial_ratio_calculator.py` — quarterly balance sheet + TTM NI + NOPAT ROIC + priceToBook P/B + forward_pe_note + TTM interest coverage + notes.
- `utils/dcf_calculator.py` — quarterly balance sheet + marketable-securities net debt + negative-equity guard + MODEL ESTIMATE label.
- `utils/projection_engine.py` — relabeled titles + raw historical CAGR rendered + "not analyst consensus" NOTE.
- `user_tools/comprehensive_stock_analyzer.py` — authoritative dividend yield (dividendRate/price) + note surfacing.
- `research/synthesis.py` — model-estimate vs sourced-data directive (NO-INCONSISTENCY).
- `tests/utilities/test_financial_calculators_accuracy.py` — new deterministic unit tests (11 tests, no network).
- `tests/utilities/run_mu_e2e_verify.py` — extended to 5 tickers + v1.0.0.160 markers.
- `version.py` — 1.0.0.159 → 1.0.0.160.

## Verification
- **Unit (deterministic, no network):** `python tests/utilities/test_financial_calculators_accuracy.py` → 11/11 PASS. `python tests/utilities/test_dr_ttm_sourcing.py` → 10/10 PASS (no regression).
- **End-to-end (live data, 5 tickers):** `python tests/utilities/run_mu_e2e_verify.py`:
  - **MU** dividend yield 6.00% → **0.06%** `[computed: dividendRate / price]`; P/B 19.78 → **14.77** `[TTM (info.priceToBook)]`; ROIC **55.03%** `[NOPAT basis]`; interest coverage 257x with negligible-denominator note.
  - **GOOGL** P/B 5.11 → **9.16** (stale-annual fix).
  - **ORCL** "137% downside" → **`INTRINSIC VALUE PER SHARE: N/M — model estimates negative equity value…`** (TTM FCF is genuinely −$24.54B; model says N/M, not a fabricated >100% downside).
  - **All 5**: DCF block labeled **"RAICA MODEL ESTIMATE"**; projections relabeled **"Historical-CAGR Extrapolation — not analyst consensus"** with raw CAGR exposed (e.g. META earnings 37.6%, FCF 33.7%); forward P/E carries the FY+2 caveat.
- **End-user E2E (the real test, per CLAUDE.md):** VERIFIED 2026-07-09. User re-ran the 5-stock @Ask
  query (META/GOOGL/AMZN/MU/ORCL) through the local NewX server and supplied the full reply. Every
  fix is present in the user-facing output: MU dividend yield **0.06%** (was 6.00%), MU P/B **14.77**
  and GOOGL P/B **9.16** (priceToBook, was 19.78 / 5.11), ORCL DCF **"not meaningful"** (was "137%
  downside"), projections relabeled **"Historical-CAGR extrapolations (not analyst consensus)"** with
  raw CAGR + visible cap, ROIC on a NOPAT basis (META 19.74%, MU 55.03%), interest coverage with the
  negligible-denominator note (GOOGL 111.85x "effectively negligible"), and every DCF/projection figure
  attributed to the RAICA model — never cited as Yahoo-sourced data. Research audit: 179/179 claims
  evidence-supported.

## Open (documented, NOT changed in this version)
- **ROIC invested-capital definition**: this version uses NOPAT / (Total Debt + Equity). Trackers like
  stockanalysis.com use a broader invested-capital base (incl. lease liabilities / minority interest),
  so META ROIC is 19.74% here vs 31.38% there. The NOPAT fix (the confirmed bug — was net income) is
  applied; the remaining gap is a definitional modeling choice, not a data bug.
- **True NTM forward P/E**: yfinance exposes no clean next-12-month EPS; forward P/E is relayed with a
  caveat note rather than fabricated. A paid data provider would be needed for a precise NTM multiple.
- **NewX gunicorn `--max-requests` OOM hardening** and **`ollama rm` of 6 local non-cloud models** —
  offered separately, not yet approved.