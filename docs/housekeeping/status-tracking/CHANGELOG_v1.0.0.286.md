# CHANGELOG v1.0.0.286 — SI-050: the arbitrator retry path never resolved data references

**Date:** 2026-08-15 · **Against:** v1.0.0.285

## Symptom

**58 `UFuncTypeError`** across 3 E2E runs, and 2 of 3 answers opening with *"I cannot complete
this request … no figures were actually calculated"* — for a dataset that fetches in 0.92 s.

```
UFuncTypeError: ufunc 'greater_equal' … (StrDType, _PyFloatDType)
UFuncTypeError: ufunc 'subtract' … (dtype('<U4'), dtype('<U6'))
```

## The first hypothesis was wrong, and measurement is what killed it

SI-050 was originally recorded against the silent text fallback in
`utils/tool_output_reference.py:344-346` — a column whose cells fail numeric parsing is returned
as text. That explanation *fit*: it produces exactly this class of error.

Reproduced through the real path instead — `lookup_website` → `build_reference_index` →
`extract_column('mag')`:

```
mag cells: 225   parse OK: 225   rate=100.0%
>>> extract_column('mag') -> 225 values, types={'float'}
```

**The fallback never fired.** Hypothesis refuted before a line of code was changed.

## Actual root cause — identified from the dtype widths

`<U4` and `<U6` are exactly `len('from')` and `len('column')`.

`_execute_corrected_tools` (`fastapi_server_complete.py:5237`) — the arbitrator's regeneration
path — called `tool_manager.safe_function_call()` **directly, skipping
`_resolve_call_references()`** that every other execution path uses. So the raw reference dict
`{"from": "lookup_website#1", "column": "mag"}` reached `compute`, and numpy converted it to an
array of its **keys**.

Confirmed by exact reproduction:

```python
np.asarray(list({'from': 'lookup_website#1', 'column': 'mag'}))
# -> array(['from', 'column'], dtype='<U6')
arr >= 5.5   # UFuncTypeError: ufunc 'greater_equal' … (StrDType, _PyFloatDType)
```

Byte-for-byte identical to the production error, including both dtype widths.

## Change

`_execute_corrected_tools` now runs regenerated calls through the **existing**
`_resolve_call_references()` (reused, not reimplemented) and accepts `arguments` as either a dict
or a JSON string. The caller passes `prior_results=list(zip(tools_called, tools_results_list))`.

## Verification

`tests/unit/test_corrected_tools_resolve_references.py` — 3 tests, **2 fail on pre-fix code**
(verified by reverting the hunks and re-running). Full unit suite **530 passed**, 4 pre-existing
failures unchanged. Version sync 5/5.

**E2E, real path, 3 runs, NewX live:**

| | v1.0.0.285 | v1.0.0.286 |
|---|---|---|
| `UFuncTypeError` | **58** | **0** |
| answers refusing outright | 2/3 | **0/3** |
| n=225 in the answer | 0/3 | **3/3** |
| markdown table | 0/3 | **3/3** |
| statistics reported | none | 5.87 / 5.80 / 0.42 / 7.80 |

## Generalization — because 3 runs of ONE prompt is not verification

Three runs of the same USGS prompt measure stochastic variance, not generality. Two additions:

**1. A matrix over the retry path** — `tests/unit/test_corrected_tools_generalization.py`, 12 tests,
**all 12 fail on pre-fix code**. Covers the same variety the resolver suites feed
`resolve_references`, but driven through `_execute_corrected_tools`: wrapped CSV, JSON records,
computed series, integer histogram counts, date column (text, not None), gaps preserved as None,
case-insensitive column match, multi-source concatenation, literal args untouched, and both error
paths (unknown id, missing column) returning `_reference_error` rather than the raw dict.

It immediately earned its keep: it surfaced **SI-053**, a column-less reference form that is not
recognised and degrades to the same numpy-key-array signature. Logged, pinned by a test, and
deliberately NOT "fixed" by widening the predicate — that would capture legitimate arguments like
`{"from": "2026-01-01", "to": "2026-06-30"}`.

**2. A structurally different E2E** — US Treasury 2025 daily yields: date x-axis, TWO numeric
series, line chart (vs USGS: one float column, distribution). Result: `📊 plot_data: 2 series x
249 points`, chart serves **HTTP 200, 68 KB, image/jpeg**, **0 UFuncTypeError**, 12-row table,
no refusal, 22.7 s. The SI-050 fix holds on a different source, format, column set and chart kind.

That run also exposed **SI-048 as P1** (below) — which the single-prompt verification never would.

## Still open — this was NOT the last gate

- **SI-051 — the chart still never reaches the user.** 0/3 answers carried a `[[chart:…]]` marker.
  One run published a real chart server-side while its answer stated *"no chart-generation tool
  produced an image marker for this analysis"* — the marker dies between tool result and synthesis.
- **SI-052 — NEW, found by this run.** With no marker available the model hand-draws an ASCII chart
  and the padding runs away: one answer streamed **2,924,215 chars, 99.8% whitespace** (2,152 runs
  of 200+ spaces) around 6,393 chars of content. Needs an output-size/degenerate-repetition guard
  independent of SI-051.
- **SI-048 — ESCALATED TO P1, mechanism proven.** Not rounding and not a compute bug: `compute`
  returned `np.max(y10)` = **4.79** and `np.mean(y10)` = **4.29321** over all 249 rows, and the
  ANSWER reported **4.62** and **4.27**. No Treasury column has a max of 4.62, so the reported
  triple is partly transcribed and partly invented. Minima transcribe exactly, means run low, one
  maximum is badly wrong — and exact extremes are what stop a reader noticing. Reproduced on two
  unrelated datasets.
