# CHANGELOG — v1.0.0.269

**Date:** 2026-08-14
**Type:** Correctness — fail closed when a calculation did not happen
**Issue:** SI-036, found by a SINGLE-FIGURE production request

---

## The failure

The request was "what was the average 10-year yield in 2025, and nothing else". The log, bounded to
that one request:

```
tool calls: ['search_datasets']
tool calls: ['search_web', 'lookup_website']      ← fetched the FRED CSV
tool calls: ['compute']
Expression rejected: comprehension is not permitted   ×4
"over n=… data point" matches: 0
```

`compute` was called and rejected **4/4**. No result ever existed. The answer nonetheless said:

> "4.30% … **computed as the arithmetic mean** of all available daily DGS10 observations … 251
> business-day observations"

The value was **right by luck** (true mean 4.2932) and indistinguishable from a grounded figure —
which makes it worse than a wrong one.

**Why it had been invisible:** every earlier test issued 3–12 compute calls, so a rejection was
covered by another attempt. A single-figure question removes that cushion, and the model fell back
to fluency rather than to honesty.

**Why the existing directive did not help:** `NEVER CLAIM A CALCULATION YOU DID NOT PERFORM` (NewX
v1.0.0.178) already forbade precisely this. A general system-prompt rule sits too far from the
moment of failure.

## Changes

**1. Fail closed — the prohibition travels with the failure.** Every `compute` failure path now
appends:

> NO FIGURE WAS CALCULATED. … You are therefore FORBIDDEN to state it — do not report the mean,
> minimum, maximum, total, correlation or any other derived number this call was for, and do not
> write "computed as", an expression, or an observation count for it. Say plainly that the
> calculation could not be completed, and why. If you can correct the expression, call compute
> again instead.

It closes the door without removing the route to success — the model is told to retry, not to give
up.

**2. Rejections name the idiom.** The model wrote `np.mean([float(v) for v in dgs10 if v != '.'])`
to skip FRED's `.` missing-value markers and was told only "comprehension is not permitted".
numpy already handles gaps, so the message now says so:

```
comprehension is not permitted — numpy works on whole arrays, so you do not need one: missing
values are already parsed as gaps, so use `np.nanmean(x)` / `np.nanmin(x)`, or mask with
`x[~np.isnan(x)]`
```

Also for generator, lambda, conditional expression and boolean operator.

**3. A SHADOW audit measures whether (1) works.** `audit_uncomputed_claim` compares the answer
against the tool results and logs `🧮 uncomputed-claim [SHADOW]` when a calculation is claimed but
every compute call failed. Log-only. Two prompt-only fixes in this same line of work already failed
under measurement, so this one is instrumented rather than trusted.

## Verification

| check | result |
|---|---|
| all four compute failure paths carry the notice | ✓ tested |
| a successful compute carries no notice | ✓ tested |
| the rejection still says how to fix it | ✓ tested |
| escape vectors vs permissive build | **12/12 still discriminate** |
| unit suite | **440 passed**, 4 pre-existing failures unchanged |

## What is still not guaranteed

The notice is a directive delivered in-band, not an output filter. It can still be ignored — which
is exactly why the shadow audit ships with it. The next question is its rate on real traffic, not
whether it exists.
