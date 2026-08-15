# CHANGELOG v1.0.0.284

**Date:** 2026-08-15
**Focus:** SI-047 — a computed series could not be charted at all.

## The defect

`extract_column` resolved every data reference through `_parse_table`, which requires a header and
at least two rows. A `compute` result is not a table — it is a labelled scalar or array followed by
its provenance:

```
25th, 75th, 90th, 95th percentiles: [5.6  , 6.   , 6.4  , 6.68 ]
computed as: np.percentile(mag, [25, 75, 90, 95])
over n=225 data point(s); inputs: mag
dtype: float64
```

So `{"from": "compute#9", …}` could **never** resolve, and anything the model calculated — a
histogram, a fitted curve, a transformed axis — was unchartable by construction. Every `plot_data`
call in the last production run failed with *"referenced output does not contain a table with a
header and rows"*.

## Why it surfaced only now

The defect predates the SI-046 directive. Earlier runs charted a **raw fetched column**, which *is*
a table and resolves fine — the one chart that succeeded did exactly that. Once the directive
started (correctly) pushing the model to plot computed things, every reference hit the wall. A
defect sitting behind a working feature until a *different* improvement exposed it.

## The change

`extract_column` now decides by **shape** before demanding a column:

1. JSON records → existing path, unchanged
2. Tabular text → existing path, unchanged
3. Anything else → offered to a new `computed_series()`

`computed_series()` parses what `compute_tool._format` emits: an optional label, then a scalar or a
numpy array string, up to the `computed as:` marker. Details that matter:

- A **column name passed out of habit is ignored, not rejected** — the model routinely supplies one,
  and erroring would fail a reference that is otherwise perfectly resolvable.
- The **`[TRUNCATED: showing the first N of M values]` note is excluded**, so its square brackets are
  not parsed as data and cannot poison the series.
- numpy's padded separator (`5.6  , 6.   `) and line-wrapping of long arrays are both handled.
- `_MAX_CELLS` still applies.

## Verified end-to-end at the tool boundary — no LLM required

```
🔗 SECOND ROUND: resolved data references for 'plot_data' → {'x': 5, 'series': 2}
   x                     -> [5.6, 5.9, 6.2, 6.5, 6.8]        (compute#1)
   Observed count        -> [74.0, 62.0, 17.0, 32.0, 11.0]   (compute#2)
   Gutenberg-Richter fit -> [1.88, 0.98, 0.51, 0.27, 0.14]   (compute#3)

plot_data success: True
[[chart:/static/images/media/3ab6194….jpg|align=center|caption="Earthquake magnitude distribution
 (H1 2026, M>=5.5)"]]
```

The rendered image was opened and inspected: both series drawn, axes labelled, source line present.

## Tests

`tests/unit/test_computed_series_reference.py` (11):

| Group | On pre-fix code |
|---|---|
| 6 × computed series resolve (array, int counts, scalar, unlabelled, truncation note, stray column) | **FAIL** — `a reference needs a 'column' naming which values to take` |
| 5 × existing paths unchanged (CSV, JSON, missing column errors, wrong column errors, non-compute prose) | pass both ways, by design |

Pre-fix: **7 failed, 4 passed**. `computed_series` is imported *inside* the one test that needs it —
at module level the file would ERROR at collection against pre-fix code, and an error proves
nothing.

Suite: **517 passed**, 4 pre-existing failures unchanged. Version sync 5/5.

## Still open

The chain is proven at the tool boundary, but **no real @Ask request has produced a chart of a
computed series since the fix**. That needs the Ollama quota reset — and it is the same run that
confirms SI-046 at n≥3.

## Files

- `utils/tool_output_reference.py` — `computed_series()`, shape-first `extract_column`
- `tests/unit/test_computed_series_reference.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-047
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.284
