# Changelog — v1.0.0.163

**Date:** 2026-07-09
**Scope:** F5 — cap the revenue base-case projection growth (parallel to earnings/FCF), fixing facially-absurd revenue extrapolations for hyper-growth names. Surfaced during the sanity-check of a live 5-stock @Ask analysis (AMAT/AMD/AVGO/NVDA/QCOM).

## Problem (root cause)
`utils/projection_engine.py` caps the **earnings** base-case growth at 20% (`min(base_growth, 0.20)`) and the **FCF** base-case at 15% (`min(base_growth, 0.15)`), but the **revenue** base case used the raw historical CAGR with **no cap** (`base_growth = historical_growth`).

`calculate_historical_cagr` clamps the raw CAGR at 100% (`max(min(cagr, 1.0), -0.5)`), so a hyper-growth name inherited a 100% base-case revenue growth and projected revenue **doubling every year**. For NVDA (100% historical CAGR) this produced:

```
Current $253.49B → Y1 $506.98B → Y2 $1,013.96B → Y3 $2,027.93B
```

— a facially absurd path (larger than the entire global semiconductor market), and internally **inconsistent** with the same run's 20%-capped earnings (net income only $159.6B → $275.8B), i.e. an implied net-margin collapse from ~63% to ~14%. Worse, the SOURCE-block label already read **"capped"** even though the revenue base case was not actually capped.

## Fix
`utils/projection_engine.py` — `generate_revenue_projections`:
* Cap the revenue base-case growth at **20%** (`base_growth = min(base_growth, 0.20)`), applied **before** the best/worst scenarios are derived so the base case can never exceed the 25% best-case ceiling (best ≥ base preserved).
* 20% matches the earnings cap → a **flat-margin base case** (revenue and earnings grow together), removing the margin-collapse inconsistency.
* The raw historical CAGR is still surfaced verbatim (`Historical CAGR (raw, uncapped): …`) — nothing is hidden; only the extrapolation is bounded.
* Corrected the base-case label to the explicit, now-truthful `Base Case (Projected growth, capped at 20%: …)`, matching the earnings/FCF label style.

## Files changed
* `utils/projection_engine.py` — revenue base-case growth cap + label correction.
* `tests/utilities/test_financial_calculators_accuracy.py` — new `test_revenue_base_growth_capped` (100% historical → base ≤ 20%, best ≥ base, no doubling, raw CAGR preserved); fixed the `__main__` runner to call the renamed `test_dividend_yield_fallback_yfinance_percent_number` and the new test.
* `version.py` — `1.0.0.162` → `1.0.0.163`.

## Verification
* **Unit tests:** `pytest tests/utilities/test_financial_calculators_accuracy.py tests/utilities/test_dr_ttm_sourcing.py tests/utilities/test_dr_per_source_queries.py` → **28/28 PASS** (was 27; +1). Direct-run smoke of the test module also passes.
* **Live E2E (NVDA):** revenue projection now `Y1 $304.19B → Y2 $365.03B → Y3 $438.03B` at a truthful `capped at 20%: 20.0%`, with `Historical CAGR (raw, uncapped): 100.0%` still shown. The prior `$2,027.93B` path is gone.

## Notes
* Pre-existing defect (predates the v1.0.0.156–.161 finance work); not introduced by F1–F4.
* The projection growth caps (revenue 20% / earnings 20% / FCF 15% / best 25% / worst floor −10%) and the DCF model assumptions remain hard-coded instance defaults in `projection_engine.py` / `dcf_calculator.py`. Migrating these financial-model parameters into `config/llm_config.yaml` is a reasonable follow-up per the project configuration directive, but was kept out of scope to keep F5 minimal and consistent with the surrounding code.
* The locally-running server was started before F5; a restart is required for live @Ask/DR queries to pick up the cap (the E2E above ran the on-disk code directly).
