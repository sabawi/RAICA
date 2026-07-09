# Changelog — v1.0.0.161

**Date:** 2026-07-09
**Scope:** Hotfix for the critical data-quality fallback bug in the ROIC, Interest Coverage, and WACC calculations where multiple years of annual statements were summed up as TTM values if quarterly data was missing.

## Problem (root cause)
During the v1.0.0.140 to v1.0.0.160 code audit, a critical fallback bug was identified in `utils/financial_ratio_calculator.py` and `utils/dcf_calculator.py`. 

Both calculators load the freshest income statement using `_freshest_income_stmt(financials)`, which returns a tuple `(DataFrame, label)` where the label is `"quarterly"` or `"annual"`. However, the label was discarded in the calling scope.

When quarterly statements were missing (e.g., for thinly-covered tickers, private companies, or during network fetch glitches), the DataFrame fell back to the annual statements. The calculators subsequently called `_ttm_value(quarterly_income, ...)` on this annual DataFrame. Since `_ttm_value` sums the most recent `n` columns (default `n=4`), it summed up **up to 4 years** of Operating Income and Interest Expense instead of 1 year.

This had severe financial data quality impacts:
1. **ROIC Overstatement:** The ROIC numerator (NOPAT) was computed using a 4-year sum of operating income divided by a single year's average invested capital, inflating ROIC by up to **400%** (e.g. `26.3158%` instead of `9.5694%` for our test data).
2. **WACC Distortion:** WACC cost of debt was calculated using a 4-year sum of interest expense divided by 1 year of total debt, resulting in an artificially inflated `cost_of_debt` (e.g. `20%` instead of `5%`), distorting DCF intrinsic values.

## Fix
The fix ensures that the calculators check the dataset label returned by `_freshest_income_stmt` and conditionally sum TTM values only if the dataset represents true quarterly data. If the label is `"annual"`, it retrieves the single most recent year's value without summation.

### 1. `utils/financial_ratio_calculator.py`
* Signatures of `calculate_profitability_ratios` and `calculate_leverage_ratios` were updated to accept `inc_label` (defaulting to `'quarterly'` for backward compatibility and test-suite safety).
* The Operating Income TTM lookup (`op_income_ttm`) in `calculate_profitability_ratios` now checks `inc_label == 'quarterly'` before calling `_ttm_value`; otherwise, it retrieves the single most recent period using `_get_value`.
* The Interest Coverage calculations in `calculate_leverage_ratios` were updated with the same conditional label check for `op_income_ttm` and `int_exp_ttm`.
* `calculate_all_ratios` now extracts `inc_label` from `_freshest_income_stmt` and passes it down.

### 2. `utils/dcf_calculator.py`
* `calculate_wacc` now extracts `inc_label` from `_freshest_income_stmt` and performs the conditional check when looking up `interest_expense`, preventing multi-year summation for the cost of debt numerator.

## Files changed
* `utils/financial_ratio_calculator.py` — Pass `inc_label` and conditionally compute TTM values.
* `utils/dcf_calculator.py` — Pass `inc_label` and conditionally lookup WACC interest expense.
* `version.py` — Version bumped from `1.0.0.160` to `1.0.0.161`.
* `README.md` — Updated all version references to `1.0.0.161`.

## Verification
* **Unit Tests:** `pytest tests/utilities/test_dr_liveness_headers.py tests/utilities/test_dr_per_source_queries.py tests/utilities/test_dr_ttm_sourcing.py tests/utilities/test_financial_calculators_accuracy.py tests/integration/test_nondr_citation_audit.py` → 37/37 PASS.
* **E2E verification:** `python3 tests/utilities/run_mu_e2e_verify.py` → 5/5 tickers successfully evaluated with correct ratios and TTM values (MU ROIC `55.03%`, GOOGL ROIC `22.02%`, ORCL intrinsic value `N/M` negative equity guard, etc.).
