# CHANGELOG v1.0.0.282

**Date:** 2026-08-15
**Focus:** SI-044 — a tool could not read an output produced by its own batch, and the gate ended on a self-contradictory verdict.

## Found in production, not in a test

The SI-041 re-test on v1.0.0.281 computed everything correctly — 225 events, correct std-dev,
Gutenberg-Richter tails — and still produced **no chart**. Two defects, both in RAICA:

```
round=1 executing ['compute' x14, 'plot_data', 'plot_data']
second-round-args: tool=plot_data available=['lookup_website#1']
  -> Tool 'plot_data' error: unknown output reference(s) ['compute#9']

round=2 verdict=sufficient
  missing='The plot_data tool failed ... A valid plot_data call is needed to produce the [[chart:...'
  next=['plot_data']
```

1. **Intra-batch dependency.** `plot_data` read `compute#9` — a compute in the *same* batch.
   References resolve once, before the batch runs in parallel, so the id could not exist yet. The
   next round had all fourteen: the data was fine, merely one round early.
2. **Incoherent verdict.** The gate returned `sufficient` while naming what was missing *and* the
   tool to fix it — ending the loop exactly one round before success.

## Changes

**`_split_calls_awaiting_batch_output`** partitions a batch into runnable calls and ones whose
references name a tool scheduled alongside them. The gate loop flushes deferred calls at the **top**
of the next round, *before* assessing — assessing first could return `sufficient` and exit with the
chart still unmade.

Deferral rather than topological ordering: it keeps parallel execution, reuses the loop that already
exists, and per-tool ids stay stable because `asyncio.gather` preserves order, so `compute#9` still
means the 9th compute of that batch. A reference to a tool **not** in the batch still fails loudly —
deferral must not become a way to swallow a bad reference and run a tool on missing data.

`_reference_ids_in` walks arguments at any depth and reuses `_is_reference`, so the shape rule lives
in one place. compute's references sit nested inside `data`, which is precisely why an earlier
shallow check never saw them.

**Coherence guard** in `_gather_gate_assess`: `sufficient` + non-empty `missing` + non-empty
`next_tools` becomes `needs_more`. This reads two fields the model already returns — structural, not
keyword matching. Both signals are required; escalating on `next_tools` alone would drive every
request to `max_rounds`.

## Tests

`tests/unit/test_intra_batch_references.py` (7), reproducing the prod batch shape.

Honest discrimination, since these are not all equal:

| Test | On pre-fix code |
|---|---|
| `sufficient` naming a gap becomes `needs_more` | **FAILS by assertion** — exercises existing `_gather_gate_assess` |
| consumer scheduled with its producer is deferred | fails on missing attribute (new helper) |
| deferred call resolves once its producer ran | fails on missing attribute |
| reference to a tool not in the batch still fails loudly | fails on missing attribute |
| nested references are seen | fails on missing attribute |
| clean verdict stays sufficient | passes both ways (over-escalation guard) |
| stray `next_tools` alone stays sufficient | passes both ways (over-escalation guard) |

Suite: **495 passed**, 4 pre-existing failures unchanged.

## Status

**NOT validated end-to-end.** The unit tests reproduce the prod batch shape, but no real request has
been run since the change. The USGS prompt that exposed it is the correct re-test.

## Files

- `fastapi_server_complete.py` — `_reference_ids_in`, `_split_calls_awaiting_batch_output`, gate-loop
  deferral flush, verdict coherence guard
- `tests/unit/test_intra_batch_references.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-044
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.282
