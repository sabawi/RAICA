# CHANGELOG v1.0.0.298 — the degradation gate measures the thing, not a proxy for it

**Date:** 2026-08-17 · **Against:** v1.0.0.297 · **Closes:** the SI-055 threshold half

## The defect

v1.0.0.291 declared a Tier-1 run unmeasurable whenever throttle events crossed a single
threshold (150). It was built to stop throttled runs being scored as CODE regressions, and it
did — but it over-fired, and it over-fired on the runs that mattered.

**Four false INCONCLUSIVEs.** The clearest is v1.0.0.297, at 164 events:

```
33 of 33 rows PASS
citation_count  samples [14, 14, 14]   baseline 13     <- zero within-arm variance
specific_url_ratio [1.0, 1.0, 1.0]
claims_unsupported_ratio 0.0 across 330 claims checked
chart markers 20 emitted -> 20 reaching synthesis, placed_ratio 1.0
```

The guard's own stated premise was *"under this much throttling an empty result is
indistinguishable from a real regression."* Nothing was empty. The premise was refuted by the
run's own data.

**A false INCONCLUSIVE is not a safe failure.** It blocks a good deploy, and it teaches the
reader to discount the suite — which is how a real regression eventually gets waved through.
That is the same harm the original guard was written to prevent, arriving from the other
direction.

## Why one number could never work

A throttle count is a **proxy**. What actually invalidates a run is retrieval **collapsing**,
and that is directly observable in the metrics. The proxy was being asked to answer a
question only the metrics can answer.

## The fix: conjunctive degradation

| throttle | metrics | verdict | why |
|---|---|---|---|
| above CEILING | anything | INCONCLUSIVE | count alone is disqualifying |
| elevated | collapsed | INCONCLUSIVE | genuinely cannot attribute the cause |
| elevated | healthy | **scored normally** | noisy is not broken |
| normal | collapsed | **REGRESSION** | no environmental excuse — this is the bug |
| normal | healthy | scored normally | the ordinary case |

The bottom-left row is the one the old rule **could not express at all**: a genuine collapse
during quiet traffic used to be reported as INCONCLUSIVE, handing a real bug a free pass.

### `scoring.retrieval_collapsed(rows)`

The collapse signature is taken from the run where retrieval actually died (2,806 events):
`citation_count 0` against a baseline of 13, `answer_chars 0`, `dr_completed False`. Not
"worse than baseline" — **zero, where the baseline was not**.

Deliberately **not** a list of metric names: any CODE metric that is higher-better with a
non-zero baseline qualifies, so a metric added tomorrow is covered with no edit. (A name list
in one file tracking constants in another is the exact class of bug that made the runner run
S4 three times per run.) Metrics with no baseline are skipped — without one, zero cannot be
distinguished from a legitimately-zero measurement; that gap is covered by the ceiling.

### Two levels instead of one

- `ELEVATED_AT = 150` — reporting only. Never degrades a run on its own.
- `CEILING = 800` — throttle so extreme nothing is trustworthy, however good the numbers look.

**Ceiling derivation, honest about a wide unknown.** Measured: usable results at 164 (33/33
PASS) and 226; no results at all at 2,806. Nothing was ever measured between 226 and 2,806,
so any value in that gap is a judgement call. The geometric mean of the two boundaries —
`sqrt(226 × 2806) ≈ 796` — sits at the proportional midpoint of what is genuinely unknown
rather than implying a precision the data does not support. Rounded to 800.

`render` now names the collapsed metrics, so INCONCLUSIVE shows its evidence instead of
looking like the suite giving up.

## Verification

- **Re-scored the REAL v297 archive** through the new gate: `INCONCLUSIVE → PASS`
  (`collapsed=False`, `elevated=True`) — the noise is still reported, it just no longer
  invalidates a healthy run.
- **Truth table exercised end to end:**
  `@164 healthy → PASS` · `@164 collapsed → INCONCLUSIVE` · `@3 collapsed → REGRESSION` ·
  `@2806 healthy-looking → INCONCLUSIVE`.
- **Behavioural falsification on pre-fix code:** the identical input (164 events,
  `citation_count 14` vs baseline 13) returns **INCONCLUSIVE** at HEAD and **PASS** now.
  Recorded explicitly because most of the new tests fail pre-fix by *crashing* on an absent
  API, and a crash is weaker evidence than a behavioural failure.
- **13 new tests** (`test_benchmark_degradation_gate.py`), all 13 failing on pre-fix code.
  The pre-existing `test_benchmark_throttle_guard.py` still passes unchanged — the
  `assess()[0]` contract is preserved, with its meaning narrowed to "ceiling exceeded".
- Version sync 19/19.

## A note on how this change was justified

Raising a threshold because your own run tripped it is exactly the "soften the metric that
moved against you" failure this repo has been burned by before. The distinction here is that
the recalibration is driven by a **refuted premise**, not by preference: the guard asserted
the results would be indistinguishable from empty, and they were `[14, 14, 14]` with zero
variance. The fix also makes the gate **stricter** in a case it previously excused
(collapse without heavy traffic is now a REGRESSION), which a purely self-serving change
would not do.
