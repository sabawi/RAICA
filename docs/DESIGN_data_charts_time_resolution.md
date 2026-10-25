# DESIGN: Dataset time resolution, and catching the data sources up

**Status:** Phase 1 BUILT in v1.0.0.351 (2026-10-25), with fix A (`RAICA_NONDR_GATHER_GATE.md` §11). Phases 2–4 not
started. Results and the fixes found while measuring: §8.
**Owner request (2026-10-25):** "do A then B — also consider updating data sources to catch up with what was not
available in the past." A = the gather-loop fixes (`docs/RAICA_NONDR_GATHER_GATE.md`); this document is B.
**Parent design:** `docs/DESIGN_data_charts.md` (numbers by reference, fail closed, digest to the LLM).
**Risk class:** MEDIUM — `search_datasets` / `compare_datasets` also serve Deep Research and the chart cards.

---

## 1. The defect, measured

`@Ask plot the monthly changes in Brent oil prices in USD since the US/Israel made their first attack on Iran this
year until now`: 0 charts in 7 runs (study 2026-10-25, both models, plus 3 diagnosis runs on the pro config).

The authoritative series was fetched every time it was asked for: FRED `DCOILBRENTEU`, daily, 45 KB. Then
`datasources/shapes.py:89` `fred_observations` averaged it to ONE VALUE PER YEAR, so the model received two points:

```
Series 'Crude Oil Prices: Brent - Europe' [$ per Barrel] — FULL series, 2 pts: (2025, 69.1426), (2026, 95.3423)
Methodology: FRED series, aggregated to annual means from the published frequency.
```

This is not a FRED quirk. Every source in the catalog is annual-only by construction:

| layer | year assumption |
|---|---|
| `datasources/base.py` `DatasetRequest` | `from_year` / `to_year` are the only window |
| `config … data_charts.sources.catalog.*.params` | `observation_start: '{from_year}-01-01'` etc. |
| `datasources/shapes.py` | `fred_observations` → annual mean; `fbi_cde_summarized` → monthly summed to annual; `worldbank` annual |
| `declarative_adapter._build` | filters and keys rows by integer year (`rows[xi]`) |
| `utils/dataset_block.format_digest` | "give a number for a YEAR only if it is listed" |
| `data_chart_builder` (`compare_datasets`) | aligns series on the union of YEARS; correlation on consecutive years |

What is already right, and stays: `DatasetSeries` takes numeric temporal x, `plot_data_tool._to_decimal_year` maps a
date to a decimal year, and `data_chart_generator._apply_temporal_ticks` (SI-091) labels a sub-year axis with calendar
dates while leaving whole-year catalog charts unchanged. The renderer needs no work.

**Verified against the source (2026-10-25):** `series/observations?series_id=DCOILBRENTEU&frequency=m&aggregation_method=avg`
returns Jan 66.60, Feb 70.89, Mar 103.13, Apr 117.29, May 107.14, Jun 85.40, Jul 83.76, Aug 91.08, Sep 114.16, Oct `.`
(month not complete) — the same figures the answer's table quoted from a web page. Asking a monthly series for
`frequency=d` returns `Bad Request. Value of frequency is not one of: 'm', 'q', 'sa', 'a'.` FRED aggregates on its own
side and refuses an upward conversion; RAICA never interpolates.

## 2. Principle

The LLM decides the resolution the request needs; the SOURCE says which resolutions it has; RAICA passes the
choice through and never invents points. No keyword reads the request ("monthly", "weekly"): the tool advertises a
parameter, the model sets it, exactly as it sets `measure` today (LLM-policy gate, no-hardcoding clause).

## 3. Design

### 3.1 Request

`DatasetRequest` gains two optional fields; existing callers are unchanged.

- `frequency` — one of the source's advertised resolutions (`annual` default, so every current call keeps its
  meaning).
- `start` / `end` — ISO dates or `YYYY-MM`, for windows inside a year. `from_year` / `to_year` stay and still work;
  when both forms are given, the dates win.

Tool schemas (`search_datasets`, `compare_datasets`) gain `frequency`, `start`, `end`, with descriptions stating the
rule in language: choose the resolution the question needs; a source refuses one it does not publish, and the
refusal lists what it has.

### 3.2 Source capability, declared in config (no code per source)

Each catalog entry may declare:

```yaml
frequencies:                 # what this source can return, and how to ask for it
  annual:    {param_value: a}
  quarterly: {param_value: q}
  monthly:   {param_value: m}
  weekly:    {param_value: w}
  daily:     {param_value: d}
frequency_params:            # merged into params when a frequency is requested
  frequency: '{frequency}'
  aggregation_method: avg
params:
  observation_start: '{start_date}'     # derived: start, else from_year-01-01
  observation_end:   '{end_date}'
```

A source with no `frequencies` block is annual-only and answers any other request with a plain error naming what
it has. World Bank stays annual (that is what it publishes). FBI CDE is natively monthly and can declare `monthly`
once its shape stops summing (Phase 3).

### 3.3 Shapes emit dated records

A shape returns `{x, value}` records with x as an ISO date when the request is sub-annual, and keeps today's
`{year, value}` when it is annual. `fred_observations` stops averaging when FRED already aggregated (any explicit
frequency); its annual path is unchanged byte for byte, so every current chart is identical.

### 3.4 Build, digest, compare

- `_build` keys rows by the x value, filters by the date window, converts dates with the SAME helper `plot_data`
  uses (`_to_decimal_year` moves to `utils/dataset_block.py`, imported by both — one copy, not two).
- `format_digest` prints periods as dates (`2026-03: 103.13`) for sub-annual series, states the resolution and that
  FRED/the source aggregated it, and the grounding line says "period", not "year".
- `compare_datasets` aligns on the union of x at ONE resolution. Mixed resolutions are refused with a message asking
  for a common one; correlation runs on consecutive periods of that resolution.

### 3.5 What the answer gets

`search_datasets(source=fred, measure="Brent crude oil price", frequency=monthly, start=2026-02)` returns a rendered
monthly chart marker and a digest with every month listed. "Monthly CHANGES" is then a `compute` over the
referenced series, or the model states the changes from the listed values — the data arrives by reference, so no
web page has to be read and copied.

## 4. Catching the sources up (owner's second ask)

Invoked on 2026-10-25 from the dev host (a listing is not evidence; each was called):

| source | key | state | what it adds |
|---|---|---|---|
| ECB Data Portal (SDMX) | none | works, data to Sep 2026 | euro area: exchange rates, HICP, policy rates, money supply |
| Eurostat (JSON-stat) | none | works, updated 2026-10-21 | EU/euro area: unemployment, inflation, production, trade, energy |
| OECD (SDMX) | none | works (HTTP 200) | OECD countries: CPI, leading indicators, GDP, unemployment, monthly/quarterly |
| US Treasury FiscalData | none | works | daily debt to the penny, Treasury rates, receipts/outlays |
| Our World in Data | none | works after a redirect | energy, emissions, health, demographics (annual, long history) |
| EIA API v2 | free key (owner registers at eia.gov/opendata) | not tried — no key | US/world energy: spot prices (Brent `RBRTE`, WTI), production, inventories, daily/weekly/monthly |
| BLS API | optional key | "website busy" 503 at test time | CPI detail, payrolls by industry, wages |
| DBnomics | none | works but LAGS (euro area HICP ends 2025-12 while Eurostat has 2026) | one API over ~80 providers — fallback only, never primary |

Order, by reach and by fit with the existing engine: ECB + OECD share one SDMX shape; Eurostat needs a JSON-stat
shape; FiscalData is plain JSON (`flat_json` shape may already fit); EIA after the owner registers a key. Each is
config plus at most one shape, behind `data_charts.sources.allowed`, each with offline fixture tests and a live
smoke call. Brent itself is already in FRED (`DCOILBRENTEU`, monthly `MCOILBRENTEU`) — EIA adds depth, not the fix.

## 5. Phases (each independently testable and revertable)

1. **FRED sub-annual** — request fields, config `frequencies`, FRED shape, `_build`, digest. Brent ×3 through the
   real NewX path; controls: an annual FRED chart byte-identical to today, a World Bank chart, an FBI chart.
2. **`compare_datasets` at one resolution.**
3. **FBI monthly** (stop summing when monthly is asked).
4. **New sources**, one per step: ECB, OECD, Eurostat, FiscalData, then EIA (needs the key).

## 6. Risks, and what would refute this design

- **The model never sets `frequency`.** Then the parameter is inert and Brent stays annual. Refuted or confirmed by
  the Brent runs reading `frequency` in the logged call; if inert, the schema description is wrong, not the engine.
- **Deep Research regression.** DR's planner routes to `search_datasets`; default `annual` keeps its calls
  identical. A DR control prompt with a chart is part of Phase 1's acceptance.
- **Long daily series.** Daily over decades is ~10,000 points: the digest must summarise (it already caps the full
  listing at 80 points) and the chart stays readable; the request window is the model's to choose.
- **Mixed resolutions in one answer** are refused, not silently resampled.

## 7. Not in scope

Interpolation or disaggregation of any kind (annual → monthly is invented data). Web-table scraping stays with
`lookup_website` + `plot_data`.

## 8. Phase 1 as built (v1.0.0.351) and measured

Real NewX path, pro config, Brent prompt ×3 per build: before 0/7 charts; A alone 1/3; A + B 2/3; release candidate
(A + B + the fixes below) 2/3, one chart per answer, FRED's monthly values (Feb 70.89 … Sep 114.16). Controls
unchanged: annual FBI crime chart, SPX MACD (all distinct charts), a plotted curve, compound interest (6,847.26).

Found while measuring, fixed, each with a test that fails without it:

- **Axis.** A monthly chart was labelled with days between its points ("25 Feb, 21 Apr"). Monthly and quarterly
  axes now tick on the periods and name them ("Feb 2026", "Q1 2026").
- **A series id was "unknown".** FRED's full-text search for `DCOILBRENTEU` timed out at 12 s (reproduced 3/3);
  the adapter now asks FRED's exact series lookup first (`discovery.series_endpoint`, ~0.4 s; FRED answers 400 for
  anything that is not an id, and the search runs as before).
- **A description matched nothing.** FRED's search needs every word ("Brent crude oil spot price Europe" → 0); the
  refusal now carries `discovery.miss_hint` from config, which says so and suggests fewer words or the id.
- **The same series drawn three times.** The writer kept one Brent chart; the marker repair appended the two others
  (different windows). Every digest now carries a `Series key:` (source, resolution, series names and units — not the
  period); the repair does not append a second drawing of a key already shown, and the writer is told to show a
  series once. Markers without a digest (stock analyzer, plot_data, programs) are restored as before.
- **Config declaring a resolution without its code** is refused (it would have fetched native data under the
  requested label); **an annual request with only start/end dates** now honours that window.

Open: SI-112 (one run in three served from web pages; window started at the earlier war).
