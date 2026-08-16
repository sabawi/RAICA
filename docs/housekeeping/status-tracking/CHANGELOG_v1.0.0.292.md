# CHANGELOG v1.0.0.292 — per-scenario throttle attribution + the repeat guard that never matched

**Date:** 2026-08-16 · **Against:** v1.0.0.291

## Why

v1.0.0.291 taught the benchmark to REPORT throttling (SI-055). It did not tell us WHERE the
throttling came from, and my attempt to work that out from the log after the fact produced
**contradictory answers**:

- a coarse window split attributed **451 of 488 events (92%)** to S4
- slicing by S4's actual inbound requests found **2 and 6** events inside them
- a robust per-5-minute distribution showed throttling **spread across the whole run**
  (07:40 → 38, 07:45 → 75, 07:55 → 144, 08:05 → 42, 08:10 → 182)

So the "S4 is the main driver" conclusion was **not established**, and the fix proposed on
the back of it would have been sold on a wrong rationale. Guessing scenario boundaries out of
a shared log is not measurement.

## 1. Per-scenario throttle instrumentation

The runner marks the log position **before each scenario** and counts after it, so attribution
is exact rather than inferred. Reported in the scorecard and rendered:

```
  THROTTLE BY SCENARIO (events / repeats):
    S4_multi_ticker_8          300  (x1)  ########################################
    S1_news_citation            38  (x3)  #####
```

Costs nothing extra on a run that was happening anyway.

## 2. The repeat guard that matched nothing

```python
reps = 1 if mod.SCENARIO in ("S2_dr_delivery", "S4_multi_ticker_dr") else repeats
```

The module is named **`S4_multi_ticker_8`**. `"S4_multi_ticker_dr"` exists in no scenario file,
so the guard matched nothing and the **slowest** scenario ran **3× on every Tier-1 run** —
~45 min instead of ~15, and triple the outbound search volume. Confirmed by the runner's own
output: `▶ S4_multi_ticker_8  (x3)`.

**Fixed by removing the name list, not by correcting the string.** A list of names in the
runner cannot be kept in sync with constants in the scenario files — nothing fails when they
diverge; the scenario just silently runs the wrong number of times. Each scenario now declares
its own `MAX_REPEATS`, and the runner uses
`min(repeats, getattr(mod, "MAX_REPEATS", repeats))`.

| scenario | before | after |
|---|---|---|
| S1_news_citation | x3 | x3 |
| S3_vision | x3 | x3 |
| S2_dr_delivery | x1 | x1 |
| **S4_multi_ticker_8** | **x3** | **x1** |

## Verification

`tests/unit/test_benchmark_throttle_guard.py` — now 10 tests, **2 more fail on the reverted
runner**:

- slow scenarios declare `MAX_REPEATS`
- the runner does not gate repeats on a hardcoded scenario-name list (**and would have caught
  the original bug**: every scenario name the runner mentions must exist)
- the render shows per-scenario attribution

Both runner checks strip comments first — they are about CODE, and the fix's own explanatory
comment quotes the banned pattern verbatim, which flagged the documentation instead of a defect.

Tier-0 **10/10**, unit **562 passed** (4 pre-existing unchanged), version sync 5/5.

## What is still NOT claimed

Whether cutting S4 to 1 rep brings a Tier-1 run under the 150-event threshold is **unproven**.
The next run will answer it with real per-scenario numbers instead of an estimate.
