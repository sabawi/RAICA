# Changelog — v1.0.0.196

**Date:** 2026-07-19
**Scope:** Multi-stock chart budget — fair per-stock allocation. Found by an 8-stock stress test
(KO, JPM, BRK-B, CROX, RIVN, PLUG, FUBO, RBRK): the old flat `max_per_response: 10` total cap let the
first-racing stocks (BRK-B, CROX) grab 4 charts each (main + 3 sub-charts), exhausting the budget so
5 of 8 stocks — including KO/JPM — got **zero** charts. Chart coverage was lopsided and order-dependent
(parallel analyzer calls race for the shared budget).

## Changed — `utils/chart_publisher.py` per-response budget
Replaced the flat total cap with a fair, per-stock allocation (`_budget_cfg`, `_Budget` now tracks
per-ticker counts + total):
- **Each stock GUARANTEED `min_charts_per_stock`** (default 2 = its main chart + 1 event sub-chart),
  reserved before the shared pool. The main chart is requested first, so it's always reserved — every
  stock gets at least a main chart regardless of processing order.
- **EXTRA sub-charts** (beyond the minimum) come from a shared **soft pool** (`max_per_response`, 10) —
  a few-stock query draws rich extras; a big basket mostly gets the guaranteed minimum.
- **Hard ceiling** (`hard_cap_per_response`, 30) bounds the total for a huge basket.
- Effect on the 8-stock case: all 8 now get main + ≥1 sub (~16–20 charts), instead of 3 fully-charted
  and 5 blank.

## Config — `config/llm_config.yaml` charts
`min_charts_per_stock: 2`, `hard_cap_per_response: 30` added; `max_per_response: 10` re-documented as the
shared soft pool for extras (was the flat total cap).

## Verification
`tests/utilities/test_financial_calculators_accuracy.py::test_chart_cache_and_cap` rewritten for the new
semantics: per-stock minimum honored even when the soft pool is exhausted by an earlier stock; extras
capped by the pool; total bounded by the hard cap; failed render releases the slot; reset zeroes the
budget. Full Phase-5 suite (technical_events + event_charts) 19/19 green; variant-cache test updated to
`_budget_cfg`. (The `test_chart_generator_and_publisher` "charts default OFF" assertion fails only in this
dev box because the local `.env` sets `RAICA_CHARTS_ENABLED=true` for integration testing — passes in a
clean env.)

## No new dependencies.
