# CHANGELOG v1.0.0.291 — SI-055: the benchmark was failing itself

**Date:** 2026-08-16 · **Against:** v1.0.0.290 · **Closes:** SI-055

## The defect

Tier-1 runs S1 ×3, S3 ×3 and S4 ×3 over 8 tickers across several search engines. That volume
trips the engines' own rate limiters, the scenarios then return empty, and the harness scored
the emptiness as **CODE regressions**:

```
S1 citation_count      0     (base 13)     REGRESSION  CODE
S2 dr_completed        False (base True)   REGRESSION  CODE
S3 vision_ran          False (base True)   REGRESSION  CODE
SUITE: REGRESSION
```

Measured the same night, on the **same build**:

| window | throttle events | what ran |
|---|---|---|
| 23:00–23:30 | **0** | 6 E2E runs — all correct |
| 00:00–00:30 | **1,015** | benchmark |
| 00:30–01:00 | **976** | benchmark |

Zero throttling while it worked; ~2,600 events while it "regressed". **The benchmark was
failing itself**, and its ENV-vs-CODE classifier caught only one metric.

This is a measurement-integrity defect in *both* directions: a false CODE-REGRESSION blocks a
good deploy, and a suite people learn to distrust is how a real regression eventually gets
waved through. It also meant no valid baseline could be captured at all.

## The fix — report that the run could not measure

Not an excuse mechanism. A third suite verdict:

- **NEW `tests/benchmark/lib/throttle.py`** counts HTTP 429 / captcha / "unusual traffic"
  responses in the server-log slice covering the run. The position is marked BEFORE the
  scenarios, so a run is judged on the throttling *it* provoked, not what it inherited.
- **`INCONCLUSIVE`** — a run whose retrieval was rate-limited into the ground cannot tell a
  code regression from the environment, so it reports neither. PASS would hide a real
  regression; REGRESSION would block a good deploy.
- **Per-metric verdicts are NOT rewritten.** They are the raw observation and stay visible;
  only the *conclusion* changes, flagged `unreliable: True`.
- **`--update-baseline` is refused** on a degraded run — baking those numbers in would make
  every future comparison meaningless.
- **Exit code 2** for INCONCLUSIVE, distinct from pass (0) and regression (1), so CI can tell
  "we did not measure" from "we measured and it is fine".

### Threshold derived, not chosen

From the measured distribution across every archived run:

| runs | events |
|---|---|
| normal | 2, 5, 5, 10, 15, 17 |
| heavy-search but usable | 55, 92, 99 |
| **the failed Tier-1** | **2,806** |

**150** sits above the heaviest run that still measured correctly and an order of magnitude
below the one that measured nothing. Set deliberately high — over-triggering would call
healthy runs inconclusive, which is its own way of destroying trust. The count is **always**
reported, so drift toward the limit is visible before it crosses.
Tunable via `RAICA_BENCH_THROTTLE_LIMIT`.

## Verification — no paid runs required

`tests/unit/test_benchmark_throttle_guard.py`, 6 tests, **3 fail on pre-fix code**:

- a **healthy** run with the identical collapsed metric still reports REGRESSION — the guard
  is not a blanket excuse
- a **throttled** run with those same metrics reports INCONCLUSIVE
- the raw per-metric verdicts survive and are flagged unreliable
- the rendered output shows the evidence and says the run must not be baselined
- the detector, run against the **real archived logs**, flags the 2,806-event run and clears
  every healthy one

Tier-0 **10/10**, unit **558 passed** (4 pre-existing unchanged), version sync 5/5.

## What this unblocks

A Tier-1 run can now be trusted to say something meaningful, or to admit it cannot. The
baseline can be captured the first time a run completes with healthy retrieval.
