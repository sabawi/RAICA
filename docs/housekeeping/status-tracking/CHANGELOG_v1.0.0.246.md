# CHANGELOG v1.0.0.246 — three gate failures found by one 404

**Date:** 2026-08-10
**Previous:** v1.0.0.245
**Type:** bug fixes (1 self-inflicted regression, 2 pre-existing latent defects)

---

## Summary

A user query on the DeepInfra configuration produced a flood of
`❌ Embedding generation failed: 404`. Tracing it surfaced three separate defects, each
of which had been invisible for a different reason:

| id | defect | why it stayed hidden |
|---|---|---|
| **SI-018** | `convert` rewrote non-LLM service endpoints | a denylist that had to be kept in sync with discovery, and wasn't |
| **SI-019** | embedding recovery retried forever | the retry budget lived inside the loop it was meant to bound |
| **SI-020** | the version-sync gate passed while stale | its checks printed but never asserted under pytest |

SI-019 and SI-020 are **pre-existing** and independent of SI-018 — that one only supplied
the trigger that exposed them.

---

## SI-018 — `convert` rewrote NON-LLM service endpoints (P1, self-inflicted)

`config_server_cli.py convert --to <provider>` scoped transport rewrites with a
**denylist**, `_INERT_SEGMENTS = {model_presets, fallback, providers}` — treating every
other block carrying a `base_url` as an LLM lane. The config also holds non-LLM services.
A real conversion rewrote **10 lines across 5 services**:

- `document_interrogator.embedding.service` → DeepInfra, while `model_name:` stayed
  `text-embedding-3-small`. Lane discovery matches `model` / `*_model` / `selected_model`
  and **not** `model_name`, so the model was left behind while its endpoint moved —
  DeepInfra does not serve that model at that path, so **every embedding call 404'd**.
- `flight_search.apis.{amadeus,skyscanner,serpapi,rapidapi_skyscanner}` → vendor API keys
  overwritten with `${DEEPINFRA_API_KEY}`.

**Root defect:** `_discover_lanes` and `_write_conversion` disagreed about what a lane is.

**Fix:** the transport allowlist is derived from the conversion plan itself — a block is
transport-converted only if a model *inside it* is being converted. The two halves now
agree by construction rather than via two lists kept in sync by hand.

**Verified through the real command:**

```
convert --revert       → byte-identical to HEAD
convert --to deepinfra → 10 LLM-lane transport lines converted, 0 non-LLM lines touched
embedding endpoint     → HTTP 200, 1536-dim vector (invoked directly)
```

Suspected but **disproved**: the FRED / World-Bank `discovery.type` lines were never
corrupted — `_KNOWN_PROVIDERS` already excluded them. Checked by diff before claiming it.

---

## SI-019 — Embedding recovery was an unbounded control loop (P1, pre-existing)

**6,614 recovery cycles / 9.1 MB of log** from one bad endpoint, at
`Progress: 0/5 embeddings processed` the entire time.

`for restart_attempt in range(2)` sits **inside** the `while processed_count` batch loop
it is meant to bound, so it resets to 1 every iteration.
`_restart_embedding_service()` returns `True` unconditionally for any non-Ollama provider
("cloud-based, no restart needed") **without verifying anything** — so the loop logged
`✅ Embedding service recovered successfully` 6,614 times against a dead service, then
retried. A detector with no damper.

**Fix:**
- `recovery_cycles` scoped to the whole call (initialised before the `while`), checked
  **before** recovery is attempted, and it `return`s rather than `continue`s.
- Bound is config-driven: `batch_processing.max_recovery_cycles: 3`.
- The false-success line is now
  `↩️ ready to retry (recovery reported OK — not yet verified)`.
- The give-up message names the likely cause: a `base_url` / `model_name` mismatch.

Fires on **any** persistent embedding failure — vendor outage, expired key, quota wall.

---

## SI-020 — The version-sync gate did not gate under pytest (P2, pre-existing)

`pytest tests/integration/test_version_sync.py` reported **5 passed** while `README.md`
was a build stale and `logging_config.json` had drifted. As a script the same file
correctly printed 5 ✗ and exited 1.

`check()` prints and bumps a counter but never asserts — deliberate, so script mode
reports every drifted surface instead of stopping at the first. Nothing then consumed
that counter, so under pytest each test returned normally no matter what.

**Fix:** a `@gates` decorator on all 5 test functions asserts the counter did not move.
Chosen over an autouse fixture because a fixture asserts in TEARDOWN, which pytest renders
as `5 passed, 1 error` — the same misreadable green. Script mode is unchanged.

---

## Files changed

| file | change |
|---|---|
| `config_server_cli.py` | SI-018: transport allowlist derived from the conversion plan |
| `document_interrogator.py` | SI-019: call-scoped recovery damper + honest recovery log + diagnostic give-up message |
| `config/llm_config.yaml` | SI-019: `batch_processing.max_recovery_cycles: 3` |
| `tests/integration/test_version_sync.py` | SI-020: `@gates` decorator |
| `tests/unit/test_config_convert_command.py` | +1 test (21 total) |
| `tests/unit/test_embedding_recovery_damper.py` | **new** — 7 tests |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.245 → 1.0.0.246 |

## Verification

- `tests/unit/test_config_convert_command.py` — **21 passed**; the new test FAILS on pre-fix code.
- `tests/unit/test_embedding_recovery_damper.py` — **7 passed**; **6 of 7 FAIL** on pre-fix code.
- `tests/integration/test_version_sync.py` — 5 passed synced; **1 failed** when the badge is
  broken (falsified); script mode exit 0.
- `tests/unit` — 193 passed, 4 failed. Those 4 (`test_html_entities`, `test_phase5_integration` ×2,
  `test_title_escaping`) fail **identically on the committed baseline** — pre-existing, not a
  regression from this change.
- Embedding service invoked directly: HTTP 200, 1536-dim vector.

## Breaking changes

None.

## Migration

None. `config/llm_config.yaml` gains one optional key
(`document_interrogator.embedding.batch_processing.max_recovery_cycles`), which defaults
to `3` if absent.

**Operational note:** if you ran `convert --to <provider>` on a build before this one,
run `convert --revert` and re-convert. The old command left non-LLM service endpoints
pointed at the LLM provider — check `document_interrogator.embedding.service.base_url`
and `flight_search.apis.*.api_key` specifically.
