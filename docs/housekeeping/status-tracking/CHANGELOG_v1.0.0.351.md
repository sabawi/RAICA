# CHANGELOG v1.0.0.351 — 2026-10-25

## Charts at the resolution the question needs, and a gather loop that sees its own results

Model study, 2026-10-25: *"@Ask plot the monthly changes in Brent oil prices in USD since the US/Israel made their first
attack on Iran this year until now"* produced 0 charts in 7 runs through the real NewX path. Every link was traced
(`docs/RAICA_NONDR_GATHER_GATE.md` §11, `docs/DESIGN_data_charts_time_resolution.md`).

### Added — dataset time resolution (`search_datasets`)
- `frequency` (annual · quarterly · monthly · weekly · daily) plus `start` / `end` dates. The model picks the
  resolution; each source declares in config what it publishes (`frequencies`, `frequency_params`, `window_params`);
  RAICA never resamples. FRED declares all five (it aggregates on its side); World Bank and FBI stay annual and refuse
  anything else before fetching. Annual requests are unchanged, parameter for parameter.
- Sub-annual digests list periods as `2026-03`; monthly/quarterly chart axes are labelled by period.
- A source's 4xx refusal is not retried and its reason reaches the model (was: five retries, "400 Bad Request").
- FRED: an exact series id is looked up directly before searching; a search that matches nothing tells the model
  FRED needs every word.

### Changed — gather loop (fix A)
- Every round's output is described to the gate and selector (fair-share preview); before, early long outputs used
  the whole budget and later pages were omitted.
- The gate's finding reaches the tool selector (as advice) in the loop and in the final round; the gate is told
  today's date.
- Selector directive reconciled: tables by reference; figures that exist only in text may be given as values.

### Changed — answers
- A series is shown once: the marker repair no longer appends a second drawing of a series already in the answer
  (digests carry a `Series key:`); the writer is told the same. Distinct charts are still restored.
- SI-027 granularity directive and `compare_datasets` description point to `frequency` for finer data.

### Verified (local, real NewX path, pro config)
Brent: 0/7 before → 2/3 charts, one chart each, FRED monthly values. Controls unchanged: annual FBI crime chart,
SPX MACD, plotted curve, compound interest. Open: SI-112 (1/3 served from web pages, no chart).

### Tests
New: `tests/unit/test_dataset_time_resolution.py` (19), `tests/unit/test_gather_round_visibility.py` (9); each defect
test fails with its fix removed. `test_chart_granularity_policy.py` guard rewritten. Unit + dataset suites:
1152 passed; 14 failures are pre-existing and identical on 1.0.0.350 (4 = SI-107; 10 in the older dataset suites,
SI-113, cause not yet traced).

### Config
New keys in `llm_config.defaults.yaml` (FRED `frequencies`, `frequency_params`, `window_params`,
`frequency_methodology`, `discovery.series_endpoint`, `discovery.miss_hint`); the site file is migrated at start.
