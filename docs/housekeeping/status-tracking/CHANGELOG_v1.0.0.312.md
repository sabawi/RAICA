# CHANGELOG v1.0.0.312 — a failure signal is not a result, and a prefix is not the series

**Date:** 2026-08-18 · **Against:** v1.0.0.311 · **Closes:** SI-085, SI-086

Two defects of one shape: **a value that could not be honoured was quietly replaced by a different
one**, and every step logged success. Both were found by looking at the artifact the user receives
— a rendered chart, a delivered answer — never at the logs, which were green throughout.

---

## SI-086 — the arbitrator DESTROYED the results it failed to correct

`arbitrator_validate_tasks` returns a short sentinel string when it cannot correct a tool error.
The caller applied anything that was not `None`:

```python
if corrected_tools_results is not None:
    tools_results = corrected_tools_results     # <- a failure SIGNAL, applied as a RESULT
```

`logs/archive/server_complete_20260818_163048.log:66164`:

```
BEFORE applying corrected results - tools_results length: 302181
Corrected results length: 558
AFTER  applying corrected results - tools_results length: 558
PARSED RESULTS: Generated 0 tool entries
📜 Prompt: 986 bytes | Context: 0
```

302,181 characters — a fetched CSV and ten successful `compute` results — were replaced by "could
not be corrected". The context block came out empty, so the synthesis prompt was the user's
question alone, and the delivered answer was 105 characters:

> "I'll fetch the DGS10 series from FRED and perform the full analysis. Let me start by retrieving
> the data."

Every figure the user asked for had in fact been computed. **Two failing tools discarded the twelve
that worked.**

### Scope — measured, not assumed

The entry that opened SI-086 called this "intermittent" and estimated "at least 3 times". Both were
wrong. The branch is **deterministic**; what varies is only whether the arbitrator fails to correct.
Counting every apply-event in the 2026-08-18 logs:

| | |
|---|---|
| arbitrator apply-events | 44 |
| **destroyed >50% of results** | **6 (13.6%)** |

```
10:09:16   293,192 ->   558   (99.8% lost)
11:38:23   290,464 ->   987   (99.7% lost)
11:40:10   293,033 ->   558   (99.8% lost)
12:32:03   110,085 -> 3,640   (96.7% lost)
16:08:37    51,635 -> 1,446   (97.2% lost)
16:12:05   302,181 ->   558   (99.8% lost)
```

**1 in 7 arbitrator corrections threw everything away**, and it is not chart-specific — the 12:32
event was a MENA news + social-media request. The `prompt_len=986` discriminator recorded when
SI-086 was opened is fully explained: the context was empty because the results had been deleted.

### The fix

The sentinel is **appended, never substituted**. Its purpose — stop the model citing figures from
tools that failed — is preserved; the successful results survive alongside it, and the model can
report both. Deleting the evidence is not a way of protecting the reader from it.

The marker is now **one shared constant**, `_ARBITRATOR_CORRECTION_FAILED`, because a producer and a
consumer that drift on that string silently destroy data — which is precisely what happened.

---

## SI-085 — a reference that could not be honoured RESOLVED to something else

**(1) Wrong selection.** A chart asked `compute#5` for `d[::60]`, correctly naming the thinned DATES
for its x-axis. That output held one series, and the SI-047 contract — *"with one series the output
IS the answer, the column name is ignored"* — returned HOUSING STARTS instead. The chart rendered a
y=x diagonal with an axis labelled "Date" showing 600–1800. Three charts across two datasets failed
this way, each plausible, each wrong.

The fix could not be a whitelist: `test_integer_counts_stay_usable` legitimately passes
`"column": "count"`. The discriminator is **shape** — an expression-shaped name (`d[::60]`,
`np.mean(y)`) is a SELECTION and must match; a plain label (`value`, `count`) is the habit SI-047
exists to tolerate. Syntax, not meaning, so no keyword list is involved.

**(2) A prefix is not the series.** `compute` renders at most 200 values and appends
`[TRUNCATED: showing the first 200 of 943 values]`. Both parsers dropped that line and returned the
200 as if they were the series. A Phillips-curve answer reported inflation mean 2.00% and max 10.24%
"in January 1948" — months 1–200 of a 943-month series whose true maximum is ~14.8% in March 1980 —
while narrating the full 1948–2026 history around those figures. 36 truncation markers in one run.

Truncation is now carried through the parser (`values, truncated, total`), **announced** in the
reference description as `NOT referenceable`, and **refused** at resolution with an actionable
message.

---

## Verification

Every figure below was re-run for this changelog.

| | |
|---|---|
| `test_reference_fails_closed.py` | 12 tests, **6 fail on pre-fix** |
| `test_arbitrator_never_destroys_results.py` | 6 tests, **3 fail on pre-fix** |
| Unit suite | **720 passed**, same 4 pre-existing failures |
| Tier-0 | **10/10** |
| Version sync | **19/19** |

Falsification was done by reverting *only* `utils/tool_output_reference.py` and
`fastapi_server_complete.py` and re-running: **9 failed, 20 passed**. The 20 that pass are the
controls — the plain-label habit, a matching expression, index reference, untruncated output, a
genuine correction still being applied, and the `None` path. The 4 suite failures
(`test_html_entities`, `test_phase5_integration` ×2, `test_title_escaping`) were confirmed
pre-existing by running them against the reverted source: identical 4 failures.

`test_the_failure_is_still_reported_to_the_model` passes both ways — pre-fix the sentinel *replaced*
the results, so the marker was trivially present. It documents intent without discriminating.

### End-to-end status — stated precisely

**SI-085 was measured end-to-end** (3 regression testcases through the real path, recorded in
SUSPECTED_ISSUES): the Treasury four-tenor chart is now correct — x-axis real decimal years
2026.0–2026.63, 157 points at full resolution, all four series in the right order, 30Yr ending at
5.31 exactly as the verified statistics say. A side effect worth noting: being *refused* a truncated
reference pushed the model to read the source CSV directly, which is why the dates are right.

**SI-086 has NOT been verified end-to-end.** The guard's log line has never fired — the failure path
has not recurred since the fix went in, so the repaired branch has been exercised only by unit test.
Watch for `🚨 ARBITRATOR: correction FAILED — keeping the N chars` and confirm the answer is complete
when it appears.

### What this does NOT fix, by construction

The second Treasury chart still plots the wrong data, because the reference was *valid*:
`{"column": "10 Yr"}` labelled "10Y-2Y Spread". The layer honoured exactly what was named. Guarding
a name cannot catch naming the wrong real thing — that is **SI-083**, still open.

---

## Docs

Reviewed README + `config/logging_config.json` (version badges → 1.0.0.312), SUSPECTED_ISSUES
(SI-085 recorded FIXED; **SI-086 rewritten** — it was still marked `P1 — OPEN` with "do not ship a
fix with it" while the fix was already in the working tree, and its scope corrected from "at least
3 times, intermittent" to the measured 6-of-44 deterministic figure), and this changelog.
