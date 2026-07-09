# Changelog — v1.0.0.162

**Date:** 2026-07-09
**Scope:** Hardening follow-ups from a code review of the v1.0.0.156–.161 financial/stocks/economy DR tools. Four fixes (F1–F4); one is a confirmed correctness bug (dividend-yield fallback 100× overstatement), three are edge-case hardening. No behavior change to the healthy primary paths.

## Fixes

### F4 — Dividend-yield fallback was 100× too high (confirmed bug)
`user_tools/comprehensive_stock_analyzer.py` — `_format_dividend_yield`.

The v1.0.0.160 fallback rendered yfinance's `dividendYield` with `f"{yf_yield:.2%}"` under the comment *"already a decimal fraction — do NOT divide by 100."* Verified empirically against the **pinned** yfinance `0.2.65` that this contract is the opposite of reality — `dividendYield` is a **percentage number**, not a 0..1 fraction:

| Ticker | `info['dividendYield']` | True yield (`dividendRate`/price) |
|---|---|---|
| AAPL | `0.34` | 1.08 / 316.22 = **0.34%** |
| KO | `2.54` | 2.12 / 82.63 = **2.54%** |
| VZ | `6.67` | 2.83 / 42.24 = **6.67%** |

Applying `:.2%` (×100) therefore printed AAPL as **"34.00%"** and VZ as **"667.00%"**. The authoritative primary path (`dividendRate / price`) is correct and masks this in most cases, but the fallback is reachable whenever `dividendRate` is absent (some ETFs / foreign issuers). Fixed the fallback **and** the bare-value backward-compat path to render `dividendYield` directly as a percent (`f"{v:.2f}%"`), with the contract tied to the pinned version in the docstring/comments.

### F1 — DCF marketable-securities: double-count guard + label-variant capture
`utils/dcf_calculator.py` — net-debt computation.

`_get_value` is an **exact** index match. Two consequences of the v1.0.0.160 net-cash change were addressed:
* **Silent no-op:** yfinance's short-term line is frequently named `Other Short Term Investments`, so the plain `Short Term Investments` lookup returned `None` for many issuers and marketable securities were dropped (net cash understated → intrinsic value depressed — the very thing the fix meant to correct). Now tries both label variants.
* **Double-count risk:** the `Investments` catch-all could coexist with `Long Term Investments` for the same issuer and be added twice (overstating net cash → overstating intrinsic value). The catch-all is now used **only** when neither specific investment row resolved.

### F2 — NOPAT tax rate clamped to a sane band
`utils/financial_ratio_calculator.py` — `calculate_profitability_ratios`.

`tax_rate = tax_prov / pretax` was unclamped. A one-time tax charge (`tax_prov > pretax`) could push the effective rate `> 1`, flipping NOPAT negative and reporting a **negative ROIC for a profitable company**. Clamped to `[0.0, 0.5]` (0.5 is above any real effective corporate rate; the 0.21 default is unaffected).

### F3 — ROE suppressed (with note) when book equity is negative
`utils/financial_ratio_calculator.py` — `calculate_profitability_ratios`.

Buyback-heavy names (HD/MCD/SBUX-style) can carry negative `Stockholders Equity`; `net_income / negative_equity` printed a **negative ROE for a profitable company**. ROE is now emitted only for positive equity; otherwise a `roe_note` ("ROE not meaningful: book equity is negative …") is set and rendered in the profitability block. Mirrors the existing ROIC `invested_capital > 0` guard.

## Files changed
* `user_tools/comprehensive_stock_analyzer.py` — F4 dividend-yield fallback + bare-path scale fix.
* `utils/dcf_calculator.py` — F1 double-count guard + `Other Short Term Investments` capture.
* `utils/financial_ratio_calculator.py` — F2 tax clamp; F3 negative-equity ROE guard + `roe_note` render.
* `tests/utilities/test_financial_calculators_accuracy.py` — corrected `dividend_yield` fallback test to the empirically-verified 0.2.65 percentage-number contract (renamed `..._decimal` → `..._percent_number`) + adjacent comment fix.
* `version.py` — `1.0.0.161` → `1.0.0.162`.

## Verification
* **Empirical:** yfinance `0.2.65` `dividendYield` confirmed a percentage number for AAPL/KO/VZ (table above).
* **Unit tests:** `pytest tests/utilities/test_financial_calculators_accuracy.py tests/utilities/test_dr_ttm_sourcing.py tests/utilities/test_dr_per_source_queries.py` → **27/27 PASS**.
* **Targeted edge-case checks:** F2 (tax `2.0` → ROIC positive 8.33%), F3 (negative equity → no `roe`, `roe_note` present), F1 (LTI+`Investments` → 150 not 200; `Other Short Term Investments` captured → 140; catch-all used only when alone → 170) — all PASS.

## Notes
* No server run in this pass; healthy primary paths (live-price dividend yield via `dividendRate/price`, quarterly-labeled TTM ratios) are unchanged. Recommend a live E2E (`run_mu_e2e_verify.py` + a multi-ticker @Ask) before deploying per the Deployment Protocol.
* **Watch item:** if yfinance is upgraded off the pinned `0.2.65`, re-verify the `dividendYield` scale contract (docstring/comments flag this).
