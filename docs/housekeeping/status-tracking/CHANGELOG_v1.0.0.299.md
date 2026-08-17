# CHANGELOG v1.0.0.299 — the harness must not blame the system for its own impatience

**Date:** 2026-08-17 · **Against:** v1.0.0.298

## How this was found

v1.0.0.298 fixed the degradation gate so a noisy-but-healthy run stops being called
INCONCLUSIVE. The very next Tier-1 run — the one validating that fix — came back
**REGRESSION**, with throttle at 135, *below* the elevated line. The new gate was not
hiding behind INCONCLUSIVE any more; it was making a claim. The claim was wrong, and
finding out why exposed three separate defects.

## What actually happened

```
S2_dr_delivery.dr_completed        False   (base True)
S2_dr_delivery.attachment_count    0       (base 2)
S2_dr_delivery.pdf_valid           False   (base True)
S2_dr_delivery.html_self_contained False   (base True)
S2_dr_delivery.dr_synthesize_s     None    (base 42.4)
S2_dr_delivery.dr_verify_s         None    (base 53.8)
S2_dr_delivery.dr_latency_s        700.1   (base 140.7)
```

`dr_latency_s` is **700.1** and the scenario's client timeout was **700**. It did not fail;
it ran out of clock. The server log settles it:

```
08:49:39  🧭 Deep research complete: 4 rounds, 53 evidence items, 314,098 chars, 177 unique URLs
08:57:36  📊 retrieval-audit: real=41 thin=30 error=0 / 71 cited
          ✅ PDF file verified: the_history_of_jazz_music_in_america_...pdf (107,956 bytes)
          ✅ AUTO-HTML: HTML file created successfully (72,405 bytes)
```

Both artifacts are on disk; the PDF begins `%PDF-1.7`. **The run succeeded and was scored a
seven-row CODE regression**, because the client stopped listening roughly 30 seconds before
the work landed. The measurement raced the thing it was measuring and lost.

## Three defects, not one

### 1. `verdict_for`: not measured was scored as failed

```python
if value is None:
    return WARN if cls == "ENV" else REGRESSION   # the run couldn't measure it
```

The comment states the correct fact and the code draws the opposite conclusion, in one
place. New `UNMEASURED` verdict: a metric the run never obtained is **never** a REGRESSION.
A run containing UNMEASURED rows reports **INCONCLUSIVE** — "we did not measure this" is not
evidence of health — while a genuinely measured REGRESSION still outranks it, so a hole can
never mask a real failure.

### 2. No scenario ever checked whether the request came back

`post_v1` returns `ok: False` on timeout. **Not one of the four active scenarios looked at
it.** They computed metrics from the empty response, making a client timeout indistinguishable
from a broken system.

New `raica_client.unmeasured_if_no_response(r, metrics)` nulls every value when the request
did not return — applied to S1, S2, S3 and S4. `dr_latency_s` is deliberately **kept**: how
long we waited before giving up is a real observation, and it is what makes the timeout
visible in the scorecard.

### 3. The collapse detector missed its own stated signature

`retrieval_collapsed` filtered to `higher_better`. But the signature quoted in its own
docstring — `dr_completed True → False`, `attachment_count 2 → 0` — is declared
`must_equal`. It could not see the exact rows it was written to describe. Now covers
`must_equal` too; `lower_better` stays excluded (a latency of 0 is suspicious, but it is not
"retrieval returned nothing").

Re-scoring the failed archive proves the gap closed: it now reports all four collapsed rows
where it previously reported none.

## S2's timeout: 700 → 1800

S4 asks for **more** work (8 tickers) and has always allowed 1800s. The 700 had no rationale
and cut a normal run off mid-flight.

Raising a limit your own run just tripped deserves suspicion, so to be explicit: **this is
not the safety net.** Defect 2 is. A genuinely stuck run now scores UNMEASURED →
INCONCLUSIVE and prompts a re-run, instead of a false CODE regression. The timeout change
only stops a normal run being severed.

## Verification

- **Re-scored the real failing archive:** the two `None` PERF rows move REGRESSION →
  UNMEASURED; collapse detection goes from 0 rows to all 4. Suite correctly stays REGRESSION
  on that data, because the archived CODE rows still hold the pre-fix fabricated values and
  traffic was not elevated — the scenario fix applies to future runs.
- **19 tests** in `test_benchmark_degradation_gate.py` (13 from v298 + 6 new), all passing;
  35 passing across the three benchmark test files.
- **Controls included:** a successful request passes through untouched; a measured regression
  still outranks an unmeasured row.
- Tier-0 **10/10**. Version sync **19/19**.

## The pattern across v297–v299

Three consecutive releases fixing the same class: **the harness attributing its own
limitations to the system under test.**

| release | the harness's limitation | what it reported |
|---|---|---|
| v297 | live's config was never read | "production is broken" |
| v298 | throttle count used as a proxy for retrieval health | INCONCLUSIVE on a 33/33-PASS run |
| v299 | client gave up before the server answered | REGRESSION on a verified-correct run |

Each was found only by asking what the measuring instrument was doing, not what the code was
doing. That question is now the first one to ask of any red benchmark result.
