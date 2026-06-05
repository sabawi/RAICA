# CHANGELOG v1.0.0.74

**Date:** 2026-06-04
**Previous:** v1.0.0.73
**Trigger:** Deep-research reliability + capacity — survive transient upstream LLM-provider 5xx
errors, and retain more evidence per run (the model has far more context headroom than we used).

---

## Background

Deep research failed several afternoon runs with `Ollama API error: 500 (Internal Server Error,
ref:…)`. Investigation (no guessing):
- The model's real context is **1,048,576 tokens (1M)** (`ollama show`); we were requesting only
  `num_ctx=131072` (12.5%). A live boundary probe handled a **140K-token request fine** — so size
  was not a hard ceiling.
- The 500s were a **transient upstream Ollama-cloud degradation window**, more likely to hit large/
  slow synthesis requests. Morning runs on the same code succeeded; a small probe to the same model
  worked throughout.

Conclusion: the incident is **provider reliability**, not our sizing — and we had large unused
context headroom. This release addresses both.

## Changes

- **+45% evidence budget** (`config/llm_config.yaml`, `deep_research.engine`):
  - synthesis `evidence_token_budget: 110000 → 160000`
  - verify `evidence_token_budget: 60000 → 87000`
  - provider `context_window_size: 131072 → 200000` (the window must hold the larger evidence doc +
    the generated answer; the cloud model handles it — cost negligible for `:cloud`).
- **Transient-5xx retry** for all deep-research LLM calls (`research/engine.py`):
  - `_collect_stream` (the shared chokepoint) now retries on genuine 5xx (`500/502/503/504` + their
    standard phrases) per a configurable policy, sleeping between attempts to let the provider
    recover. **4xx/other errors are NOT retried** (fail fast). Partial chunks from a failed attempt
    are discarded; the call restarts.
  - Config `deep_research.engine.retry: {max_attempts: 3, delay_seconds: 120}` (3 attempts = 2 retries;
    tuned so each silent wait stays under client read-timeouts). The pipeline applies it via
    `configure_retry()` at run start; default (no retry) for non-deep-research callers.
- **Graceful failure** (`fastapi_server_complete.py`, DR branch): after retries are exhausted on a
  provider 5xx, the user gets a calm, actionable message — *"The research model is temporarily
  unavailable … please try again in an hour or so"* — instead of a raw stack-trace string. Non-5xx
  errors keep the detailed message.

## Verification (live)

- A deep-research run now logs `num_ctx=200000` on all engine/synthesis/verify calls and
  `📐 Evidence budgeted to ~160000 tokens` (was 110000). Completed cleanly in 228s, 84 claims checked,
  richer 52K-char synthesis. Retained more evidence (truncated to 160K instead of 110K).
- Retry/graceful-message paths are config-driven and syntactically verified; they activate on the
  next genuine upstream 5xx (not reproducible on demand while the provider is healthy).

## Operational note (client timeouts)

The retry is tuned to fit under client **read** timeouts. NewX/`requests` and OpenWebUI use a *read*
timeout (max gap between received bytes), so the binding constraint is each **silent wait**, not the
total run time. `delay_seconds: 120` keeps every wait well under NewX `@Ask`'s `timeout: 900`s and
under shorter OpenWebUI defaults, so the connection survives each retry pause. `max_attempts: 3`
gives 2 recovery chances. If you later raise client timeouts, you can raise these for a wider retry
window. (Streaming a keepalive line during each wait — instead of going quiet — is a clean follow-up
for nicer UX.)

## Dependencies / Migration

- None new. All knobs live in `config/llm_config.yaml`; defaults preserve prior behavior for
  non-deep-research paths.

## Files

- `config/llm_config.yaml` — evidence budgets, `context_window_size`, `deep_research.engine.retry`.
- `research/engine.py` — `configure_retry`, `_is_transient_5xx`, retry loop in `_collect_stream`.
- `research/pipeline.py` — apply retry policy from config at run start.
- `fastapi_server_complete.py` — graceful provider-5xx message in the DR branch.
- `version.py` (→ 1.0.0.74), `README.md`, this changelog.
