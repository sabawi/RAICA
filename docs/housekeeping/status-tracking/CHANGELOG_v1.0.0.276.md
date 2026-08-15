# CHANGELOG — v1.0.0.276

**Date:** 2026-08-14
**Type:** Bug fix — the model was reading our own label as the observation count
**Issue:** SI-041(c)

---

## The bug, seen twice on unrelated datasets

| dataset | our note said | truth | the answer reported |
|---|---|---|---|
| Treasury 2025 | `[CSV file: **250** lines retrieved]` | 249 rows | "**250** daily observations" |
| USGS H1-2026 | `[CSV file: **226** lines retrieved]` | 225 events | "**226** events" |

**The model was not miscounting.** `lines = text.splitlines()` includes the header, and the model
read our label and trusted it — reporting exactly our number both times. "N lines" was true and
misleading, and it is the one figure in the payload that carries authority *because we wrote it*.

### The asymmetry that hid it

`describe_reference` already reported "**N data rows**" correctly, so the gather gate and the
second-round selector always saw the right count. Only the synthesis model — reading the raw tool
output — saw the inflated one. Every mechanism built to check the data was looking at the correct
number while the answer used the wrong one.

## The fix

The note leads with data rows and keeps the line total, so nothing is lost:

```
[CSV file: 249 data rows (plus 1 header line; 250 lines total) retrieved (complete)]
[CSV file: 225 data rows (plus 1 header line; 226 lines total) retrieved (complete)]
```

Non-tabular payloads (JSON, XML, plain text) have no header row, so they still report lines — the
honest statement for them. The structured `lines` field in the result dict is unchanged; only the
human-readable label moved.

## Verification

| check | result |
|---|---|
| Treasury CSV, live fetch | "249 data rows" — matches truth |
| USGS CSV, live fetch | "225 data rows" — matches truth |
| new regression test | fails on pre-fix code |
| JSON payload still reports lines | ✓ |
| unit suite | **470 passed**, 4 pre-existing failures unchanged |

### A test whose premise changed

`test_passthrough_labels_type_and_line_count` asserted the note read `[CSV file: 3 lines
retrieved]`. That assertion was correct for the old contract and wrong for the new one; it now
pins the data-rows form, with the reason recorded in place rather than quietly rewritten.
