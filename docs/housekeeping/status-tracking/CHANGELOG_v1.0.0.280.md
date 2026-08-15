# CHANGELOG v1.0.0.280

**Date:** 2026-08-15
**Focus:** SI-042 — DEGRADED was detected on every boot and actioned never; automatic rebuilds had no damper.

## What was wrong

`_check_embedding_consistency` flagged `EMBEDDING_INCONSISTENCY` on every production boot. That set
status `DEGRADED`, which appended `SCHEDULED_REBUILD_RECOMMENDED` — a string **nothing in the
codebase ever read** — and never set `rebuild_required`. `check_and_repair` then returned
`status in ['HEALTHY','DEGRADED']`, so the startup log announced *"FAISS integrity check passed -
system is healthy"* for a degraded index.

## Why the obvious fix would have been a disaster

Setting `rebuild_required = True` for DEGRADED was the tempting one-liner. Measurement first showed
it would have been an undamped control loop:

**`_check_embedding_consistency` never consults the index.** It embeds 5 sample chunks twice
through the live API and compares. A rebuild re-embeds through that same API, so it **cannot change
the verdict by construction** — it would have rebuilt ~2 minutes on every boot, forever.

And the verdict was a near-certain false positive. The test was `np.allclose(rtol=1e-10)`, far
tighter than float32 carries. Measured on real prod content (`text-embedding-3-small`):

| sample | max abs diff | cosine |
|---|---|---|
| 0, 2, 3 | 0.0 | 1.00000000 |
| 1 | 1.2e-04 | 0.99999961 |
| 4 | 3.4e-04 | 0.99999426 |

Ordinary batched-inference jitter between replicas — semantically identical for retrieval.

## The change

1. **Cosine-based consistency.** Judged by cosine similarity against a configured floor (0.999)
   rather than element-wise equality. A changed model, wrong dimension, or mismatched text still
   collapses cosine far below the floor — pinned by its own test so the looser tolerance cannot
   quietly blind the check.

2. **DEGRADED is surfaced.** `check_and_repair` no longer folds DEGRADED into "healthy": it logs an
   explicit operator WARNING naming the issue and metrics, and states that the condition is not
   auto-repairable. The startup log no longer overrides that verdict.

3. **A damper on every automatic rebuild.** Attempts are recorded in a new `integrity_rebuilds`
   table and capped at `max_per_window` per `window_hours`. **The line that makes cycle N+1
   impossible** is the `recent >= limit` guard in `automatic_rebuild_if_needed`, which returns
   before the rebuild regardless of what the detector says. The attempt is recorded **before** the
   rebuild runs, so a rebuild that crashes still counts — otherwise the error path would
   reintroduce the loop. Suppression logs loudly rather than silently declining.

   This protects the CORRUPTED path too, which previously rebuilt three times in three days with
   nothing stopping it had the rebuild been ineffective.

4. **Config, not literals.** `corruption_threshold` moved out of code; new
   `document_interrogator.integrity` block holds it plus the cosine floor and damper settings.
   Missing config now fails fast.

## Verification against the real production index

```
status          : HEALTHY
issues          : []
recommendations : ['NO_ACTION_REQUIRED']
embedding_consistency: consistent=True, min_cosine=1.0, min_cosine_required=0.999
```

## Tests

`tests/unit/test_integrity_rebuild_damper.py` (new, 6 tests):

| Test | On pre-fix code |
|---|---|
| a rebuild that never fixes its cause stops repeating | **FAILS** — `rebuild executed 5 times against a limit of 2` |
| a rebuild that CRASHES still counts against the damper | new mechanism |
| the suppressed branch reports why and does not rebuild | new mechanism |
| provider jitter is NOT called inconsistent | **FAILS** |
| a genuinely different embedding is still caught | guard against over-loosening |
| DEGRADED is no longer reported as healthy | **FAILS** |

Suite: **484 passed**, 4 pre-existing failures unchanged. Version sync 5/5.

## Files

- `tools/faiss_integrity_monitor.py` — cosine check, damper, DEGRADED surfacing, config-driven
- `document_interrogator.py` — startup log no longer overrides the verdict
- `config/llm_config.yaml` — `document_interrogator.integrity` block
- `tests/unit/test_integrity_rebuild_damper.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-042 resolved
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.280
