# CHANGELOG v1.0.0.75

**Date:** 2026-06-04
**Previous:** v1.0.0.74
**Trigger:** UX polish for the v1.0.0.74 transient-5xx retry — stream a keepalive during each retry
wait instead of going silent.

---

## Summary

The retry added in v1.0.0.74 waited `delay_seconds` (120s) between attempts. With normal progress
framing suppressed (`stream_progress: false`, the default), that wait was a silent gap — the user saw
nothing and, on a large run, the extended silence risked tripping a client read-timeout. This release
streams a keepalive notice during the wait: the user sees the retry is happening, and bytes flow at
least every ~20s so the connection stays warm.

## Changes

- **`research/engine.py`:**
  - New per-run retry-notice channel via `contextvars` (`set_retry_notice_callback`) — concurrency-safe
    (each run sets it in its own task context, no cross-talk between simultaneous research runs).
  - `_collect_stream` retry now emits, via that callback, an initial `⏳ retrying (attempt N/M) in
    ~Ns…` notice and then a `⏳ still waiting… retrying in ~Ns` heartbeat every ~20s during the wait.
- **`research/pipeline.py`:** `run_deep_research_pipeline` gains a `retry_notice` param and registers
  it (in the task's own context) at run start.
- **`fastapi_server_complete.py`** (DR branch): a dedicated retry-notice queue, drained ALWAYS — even
  when normal progress framing is off — so retry notices reach the client (a provider retry is
  exceptional and worth surfacing). The progress-drain loop was restructured to merge both channels.

## Verification

- Unit test: 5xx → retry succeeds and the notice callback fires; 4xx → fails fast (no retry); the 5xx
  detector classifies 500 vs 400 correctly.
- No regression: a full deep-research run completed cleanly (153.9s, 66 claims) and the client received
  the complete paper + audit footer through the restructured drain loop. (The keepalive path itself
  activates on a live upstream 5xx, which isn't reproducible on demand while the provider is healthy.)

## Dependencies / Migration

- None. Behavior change only when a transient 5xx triggers a retry; non-deep-research paths unaffected.

## Files

- `research/engine.py`, `research/pipeline.py`, `fastapi_server_complete.py`,
  `version.py` (→ 1.0.0.75), `README.md`, this changelog.
