# CHANGELOG v1.0.0.311 — a missing observation is a gap, and charts render

**Date:** 2026-08-18 · **Against:** v1.0.0.310 · **Closes:** SI-082 · **Opens:** SI-083, SI-084

## The change

Real series have holes. FRED writes market holidays into DGS10 as `"."`, which becomes NaN the
moment the column is numeric, and every chart of it was refused outright:

```
plot_data: temporal x values must all be finite numbers
plot_data: quantitative x values must all be finite numbers
```

The model had done nothing wrong — it computed NaN-aware statistics exactly as asked, then handed
over the series it was told to plot.

**Policy (user-specified):** a NaN y is SKIPPED in the drawing but KEPT in the series; the line
joins Y(n-1) to Y(n+1) across it; every surviving point keeps its OWN true x — the date axis is
never re-indexed.

Implemented in `plot_data._coerce`: a point with no finite x cannot be placed by any series and is
dropped; a non-finite y becomes a hole; an x position is dropped only when no series can draw it.

### The distinction that makes this safe

`_segments` (`data_chart_generator.py:59`) **breaks** a line at a `None`, deliberately, for a
declared discontinuity (SRS↔NIBRS). A public holiday is not a discontinuity, and drawing it as one
would state something false. So:

| hole | origin | behaviour |
|---|---|---|
| NaN / inf | found in the numbers | skipped — neighbours join |
| explicit `null` | declared by the caller | preserved — the line breaks |

Both are `None` by the time the drop decision runs, so the origin is carried explicitly rather than
re-derived. **This was caught by the existing suite**: a first draft collapsed the two and broke
`test_gaps_are_preserved_not_zero_filled` (SI-028), which has guarded that invariant since the tool
was built. The regression was real and the pre-existing test found it.

## Verification

| | |
|---|---|
| `test_plot_data_missing_observations.py` | 14 tests, **9 fail on pre-fix** |
| Unit suite | **702 passed**, same 4 pre-existing failures |
| Tier-0 | 10/10 |
| Version sync | 19/19 |

Honesty note: `test_a_nan_y_no_longer_kills_the_chart` passes both ways — `_coerce` never rejected
NaN, `DatasetSeries` did, later — so it documents the symptom without discriminating.

## Measured end-to-end: charts now render

Five runs of the DGS10 regression testcase through the real `/v1` path. **Charts published 5/5**,
against **0 in the previous 18 runs**. Real JPEGs, 44–56 KB, in NewX's media directory. The gap
handling is visible in the log:

```
📊 plot_data: 1 series x 192 points (8 skipped, no value) → /static/images/media/b636fda9….jpg
```

## Two defects this exposed, both found by LOOKING at the pictures

**SI-084 (P1) — the model invents a marker instead of relaying the real one.** A real marker
reached the answer in only **2 of 5** runs; the others carried `[[chart:full-series` or a fake
sequential hex id, while the tool had returned a correct `/static/images/media/<real>.jpg` marker.
The user sees a broken image either way, so a rendered chart is worth nothing until this holds.
This is SI-078 recurring at a later stage: the cause recorded there (no tool could mint a marker)
was necessary but not sufficient.

**SI-083 (P2) — the wrong series gets plotted, and labelled convincingly.** Of three inspected
charts, one was correct (daily-change distribution, x −0.75…+0.64, sharp peak at zero), one was a
real histogram of yield LEVELS mislabelled as changes, and one was a perfect y=x diagonal — the
same series passed as both x and y. **All three logged as successful publishes.** No log check
could have caught this; only opening the image did.

## Docs

Reviewed README + `config/logging_config.json` (version), SUSPECTED_ISSUES (SI-082 resolved,
SI-083/084 opened), and this changelog. `DESIGN_unified_artifact_pathway.md` §6 already documents
the marker-relay machinery SI-084 concerns and needs no change.

## Tier-1 — REGRESSION verdict, cleared (second consecutive confirmation of SI-063)

`SUITE: REGRESSION` on the same two S2_dr_delivery PERF rows as v310 (`dr_synthesize_s` 112.5 vs
base 42.4; `dr_latency_s` 289.5 vs base 141). **Zero CODE regressions.** Cleared on evidence:

1. **This change cannot reach those metrics** — it is confined to `plot_data._coerce`, and
   `dr_synthesize_s` measures the synthesis stage.
2. **Control group across six releases** puts this run mid-range, not at an extreme:

   | run | S2 latencies |
   |---|---|
   | v301 | 61.7, 84.7, 344.8 |
   | v302 | 39.6, 81.5, 197.5 |
   | v303 | 92.4, 138.0, 321.6 |
   | v306 | 70.0, 75.9, 264.7 |
   | v310 | 74.2, 88.5, 278.7 |
   | **v311** | 88.7, 112.5, 289.5 |

3. **The run logged 283 rate-limit responses — ELEVATED** (v310's comparable run: 142).

The 42.4 / 141 baseline has now produced a REGRESSION verdict on two consecutive releases whose
code cannot affect it. **SI-063 (stale S2 PERF baseline) should be rebaselined on a rested run
before the next release** — a gate that cries wolf twice is one that will be ignored the third
time, which is exactly how a real regression ships.
