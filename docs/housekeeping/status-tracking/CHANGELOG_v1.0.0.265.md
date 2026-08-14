# CHANGELOG — v1.0.0.265

**Date:** 2026-08-14
**Type:** Bug fix (P1) — a quoted CSV field silently truncated every dataset
**Found by:** a second test prompt (USGS earthquake catalogue) chosen to exercise a source unlike
the Treasury CSV every prior test used

---

## The bug

A 226-line file was parsed as a **14-line block whose "header" was a data row**, so every derived
figure was computed over **13 of 225 events**:

| figure | reported | true |
|---|---|---|
| mean magnitude | 5.71 | **5.883** |
| mean depth | 32.6 km | **60.461 km** |
| deepest event | 629 km | **636.265 km** |
| correlation(depth, magnitude) | 0.43 | **0.1214** |
| events ≥ M7.0 | "at least 8" | **8** |

**Cause:** `_locate_table` found the tabular region by counting **raw delimiters** to identify rows
of equal width. A quoted field may legitimately contain the delimiter — USGS place names look like
`"22 km ENE of Baculin, Philippines"` — so raw comma counts vary line to line and the longest
matching run collapsed to whichever 13 lines happened to agree.

**Why it survived five releases:** the Treasury CSV used by every earlier test has no quoted
fields. The bug was structurally invisible to it, and would have silently corrupted almost any
real-world CSV that is less plain.

## The fix

Field counts now come from a **CSV parse** (`csv.reader`), which honours quoting, instead of
counting delimiter characters. Verified against the live USGS file: 226 lines detected, 225 rows
extracted, and every figure above matches ground truth computed independently.

## Note on the model's behaviour

The answer **disclosed** the problem — *"this compute was run on a subset — the full 225-event mean
would require a complete computation pass"* — and repeated the caveat for each figure. That honesty
is what made the bug catchable. But it still reported the subset figures **as the answer**, which is
the failure that matters: a disclosed wrong number is still a wrong number. It also listed 11 events
in a table of "M7.0 or greater" including M6.5, M6.4 and M6.9, under its own stated threshold.

This strengthens the case for failing closed on a failed or partial `compute` rather than reporting
with a caveat.

## Verification

| check | result |
|---|---|
| new regression tests | 4, all **failing on pre-fix code** |
| reference suite | 23 passed |
| unit suite | **422 passed**, 4 pre-existing failures unchanged |
| live USGS file | 225/225 rows; mean 5.883, depth 60.461, corr 0.1214, ≥M7.0 = 8 — all exact |
