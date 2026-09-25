# CHANGELOG v1.0.0.329

**Date:** 2026-09-25
**Theme:** Deep Research charts stocks and sectors again — and the benchmark can now notice when it doesn't

## Fixed (SI-104)

A finance @Ask asking to "chart some selected sectors" came back with one chart (the S&P 500 index, from FRED) and
no sector charts. Benchmark S4 had produced 20 chart markers across 8 tickers on every run from 08-17 to 08-30 and
**0 / 0** on the v1.0.0.324 run.

- **Cause:** in Deep Research, charts of anything that trades come only from `comprehensive_stock_analyzer` with
  `detailed=true`. The planner prompt described `detailed=true` purely as the fundamentals/DCF switch; the planner
  model since v324 (deepseek-v4.1-flash) followed it literally — `detailed:false` for every ticker, and for a sector
  request no stock tool at all. Captured from the planner's own output, not inferred.
- **Fix (policy language):** `research/engine.py` planner guidance — `detailed=true` is also the price-chart source;
  to chart stocks, sectors, indexes or the market, route each item to the analyzer with `detailed=true` (a sector or
  index through a representative traded fund such as its ETF). `user_tools/comprehensive_stock_analyzer.py` — the
  `detailed` parameter description says the same, so the planner and the tool model hear one voice.
- **After (planner, 3 runs each):** S4 → detailed=true on every analyzer call (16/16, 24/24, 16/16); the sector
  request → XLK, XLF, XLE, XLV, XLY, XLU plus index tickers, all detailed=true. The analyzer completes on an ETF
  and on indexes (^GSPC, ^VIX) in 11–13 s.

## Benchmark gate

`tests/benchmark/baseline.json`: `S4_multi_ticker_8.tickers_with_chart_emitted` (8, tolerance 2) and
`S4_multi_ticker_8.chart_markers_in_answer` (20, tolerance 8) are now baselined. They had no baseline, printed
as INFO, and could not flag the 20 → 0 collapse. Verified with the harness's own `verdict_for`: 0 → REGRESSION,
6 / 12 → PASS.

## Also logged

SI-103 — first Ollama 429 "too many concurrent requests" during a 28-source DR fan-out; both runs completed and
posted; cause undetermined (model change, fan-out size, weekly-quota state).

## Not yet verified

A chart rendering inside a real NewX post on this build — the owner's real traffic is the test.

## Breaking changes / migration

None.
