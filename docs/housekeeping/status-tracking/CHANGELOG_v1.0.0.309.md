# CHANGELOG v1.0.0.309 — a computed series can be charted, because it now says so

**Date:** 2026-08-18 · **Against:** v1.0.0.308 · **Closes:** SI-075 · **Corrects:** v1.0.0.308 prompt advice

## The user's question that found it

> *"Shouldn't the aggregation happen on the resultant series of compute, and before it is sent to
> plot_data?"*

Yes — and it turned out the plumbing for exactly that **already existed and was invisible**.

## The defect: the bridge had no signpost

`extract_column` has resolved `compute` results since SI-047, through a purpose-built
`computed_series()` helper. But `describe_reference` — the function that tells the model what it
may reference — classified those same results as prose:

```
=== compute#1 === text, 180 characters
- [74, 62, 17, 32, 11]
computed as: np.histogram(mag, bins=5)[0]
```

So the model was never told the values were referenceable. To chart a histogram **it had already
computed correctly**, it re-sent the raw 16,859-point source column instead.

Measured on the DGS10 prompt, four runs: **ten `plot_data` attempts, ten rejections**
(`x has 16859 points, over the 5000 limit` ×5, `x must be a list` ×8), **zero charts** — for a
chart that needed 50 points.

Same shape as SI-073 and SI-069: *the right thing was computed, then the wrong thing was passed.*

## The fix

`describe_reference` gains a computed-series branch, keyed off the **same** `computed_series()`
helper the resolver uses — so description and resolution cannot drift apart:

```
=== compute#1 === computed series, 5 value(s)
expression: np.histogram(mag, bins=5)[0]
values: 74, 62, 17, 32, 11
REFERENCE THESE VALUES — do not retype them and do not re-send the source column:
{"from": "compute#1", "column": "value"}
```

Section N documents it: every compute call becomes its own output id, and a histogram, a thinned
series or any derived quantity reaches a chart by being referenced.

## I withdrew my own advice from v1.0.0.308

That release told the model to *"aggregate FIRST with compute … (e.g. monthly mean)"*. **That is
impossible.** `compute` is pure numpy over numeric arrays with no grouping and no date handling —
verified: `np.mean(np.array(y).reshape(48, 20), axis=1)` is rejected by the fence
(`only np.<function> attribute access is permitted`). I had instructed the model to do something
the toolset cannot do.

Replaced with what is actually supported, and tested: **slicing** — `y[::20]` → 50 points,
`y[-500:]` → 500. Section N now shows slicing x and y the same way so they stay aligned, and says
plainly not to attempt calendar bucketing.

## Result on the failing testcase

| | before | after |
|---|---|---|
| `over the 5000 limit` rejections | 5 | **0** |
| `x must be a list` rejections | 8 | **0** |
| `compute#` references used | 0 | **32** |
| charts produced | 0 of 4 runs | **2 in run A** |

**Partial: 1 of 2 runs.** Run B made 42 compute calls and attempted no chart at all — unexplained,
and not claimed as fixed.

## Verification

- **10 tests** (`test_computed_series_reference.py`); **6 fail pre-fix**.
- Controls hold: prose is still described as text and still fails to resolve; a real table is still
  described as a table. The branch is not over-eager.
- Tier-0 **10/10**, unit **671 passed** (same 4 pre-existing), `make smoke` **PASSED**, sync 19/19.

## Standing

DGS10 statistics remain **22/22 exact** — that half was never in question. Charts are improved but
not reliable, and the residual variance is unexplained.
