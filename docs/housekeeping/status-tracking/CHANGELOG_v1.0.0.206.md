# Changelog — v1.0.0.206

**Date:** 2026-07-20
**Scope:** NEW FEATURE — **data-charting**: when a query asks to plot/chart numeric data, RAICA now gathers
a REAL dataset from a curated authoritative source and injects an actual chart into the answer. Generalizes
the stock-only inline-chart path to arbitrary datasets. Shipped **OFF by default** (flag-gated); prod behavior
is unchanged until enabled. Built + validated in isolation on branch `feature/data-charts`.
**Design:** `docs/DESIGN_data_charts.md`. **Trigger:** a prod query ("chart US crimes since the 1970s") got a
text-only answer because charts were only a side-effect of the stock analyzer — there was no general
"user asked for a chart → get a data series → render it" path.

## The load-bearing principle — NUMBERS-BY-REFERENCE
The LLM NEVER generates or transcribes a data point. A data-source tool stores the real series out-of-band
keyed by an id; the LLM sees a compact **digest** (schema, units, source, range, a few sample points),
SELECTS a dataset by id, and only COMMENTS on it; the renderer plots the STORED payload. Fail-closed: no
trusted dataset → no chart (never a fabricated/illustrative one). This mirrors the yfinance→chart_generator→
narrate path that makes the stock charts trustworthy.

## New — data acquisition (config-driven, KEY-AGNOSTIC)
- **`datasources/` package**: `base.py` (adapter contract + `DatasetRequest`), `declarative_adapter.py`
  (ONE generic engine — URL/param/auth templating, response-shape unwrap, declarative field maps, rate
  derivation, discontinuity + methodology metadata → validated `DatasetSeries`), `shapes.py` (reusable
  response-envelope handlers `flat_json` + `worldbank`), `registry.py` (loads the catalog from config),
  `data_chart_builder.py` (`build_data_chart`: request → extract → store → render → publish → `[[chart:]]`
  marker + digest, the render-at-gather core).
- **Adding a source is now pure config** — no per-site Python — via the catalog (below). A novel response
  envelope needs one small reusable `shapes.py` handler.
- **Sources shipped:** `world_bank` (KEYLESS open API — population, GDP, GDP/capita, CO₂/capita, life
  expectancy, unemployment, inflation) and `fbi_cde` (FBI Crime Data Explorer, needs `DATA_GOV_API_KEY` /
  `FBI_CDE_API_KEY`; SRS→NIBRS 2021 discontinuity carried as metadata). Key-agnostic: keyless open sources
  are first-class and preferred at equal quality.

## New — rendering & pipeline wiring
- **`utils/dataset_block.py`**: `DatasetSeries` (validated, fail-closed) + out-of-band payload store
  (register/get by id, TTL, content-dedup) + `format_digest`.
- **`utils/data_chart_generator.py`**: general line/bar/scatter renderer, NewX-styled, thread-safe, never
  raises; **segments at discontinuities** (never silently bridges) with labelled markers.
- **`user_tools/search_datasets_tool.py`**: the `search_datasets` deep-research SOURCE (auto-discovered).
  Self-disables unless enabled; runs `build_data_chart`, returns marker+digest like the stock analyzer.
- **`research/engine.py`**: when enabled, the planner offers `search_datasets` and its prompt injects the
  source **catalog + chart-intent routing** (LLM picks source+measure — no keyword lists); the dispatch
  allow-set permits it. All **no-ops when disabled** (prompt byte-identical, source absent).

## Config — `config/llm_config.yaml` (SINGLE source of truth)
New `deep_research.data_charts` block: `enabled` (master, **false**), `sources.allowed`, the full
`sources.catalog` (declarative source definitions — moved here from a separate file per the config
directive), `max_per_response`, `render`. **Env override** `RAICA_DATA_CHARTS_ENABLED` (mirrors
`RAICA_CHARTS_ENABLED`) for a per-environment toggle without editing the committed config.

## Verification
- **43 offline unit tests** (`tests/utilities/test_data_charts.py`, `test_declarative_adapter.py`,
  `test_data_chart_builder.py`, `test_search_datasets_tool.py`, `test_planner_data_charts.py`): validation
  fail-closed, store round-trip/dedup/TTL, digest, render + discontinuity segmentation, FBI + World Bank
  parse via one engine, builder chain, tool contract + self-disable, planner flag-gating.
- **Live-validated** (real `glm-5.2` LLM + real keyless World Bank API): planner routes "chart US population
  since 1970" → `search_datasets{world_bank,population,…}` → real fetch (56 pts, 205M→341M) → chart; full
  `run_deep_research_pipeline` reproduced the `[[chart:]]` marker in the final answer. World Bank wire shape
  confirmed against production; FBI CDE shape still to confirm on first keyed fetch.

## Breaking changes
None. Feature is additive and OFF by default; the entire pipeline is unchanged when
`deep_research.data_charts.enabled` is false (and `RAICA_DATA_CHARTS_ENABLED` unset).

## Migration / enablement
Set `RAICA_DATA_CHARTS_ENABLED=true` (or `deep_research.data_charts.enabled: true`) + restart. FBI/crime
charts additionally require `DATA_GOV_API_KEY` (or `FBI_CDE_API_KEY`) in `.env`; World Bank needs no key.

## Known follow-ups
- Prose-table refinement: the answer's chart is exact, but the LLM may over-tabulate per-year values in
  prose from only the digest's sample points — add a synthesis directive to describe-and-cite, not tabulate.
- FBI CDE wire-shape confirmation on first live keyed fetch.

## No new dependencies (matplotlib, numpy, requests, PyYAML already required).
