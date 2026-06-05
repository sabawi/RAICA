# CHANGELOG v1.0.0.77

**Date:** 2026-06-04
**Previous:** v1.0.0.76
**Trigger:** Bugfix found in live testing — the deep-research retry/keepalive worked, but the
graceful failure message crashed with `UnboundLocalError: cannot access local variable 're'`.

---

## What happened (live test)

A real upstream Ollama-cloud outage hit during a deep-research run. The v1.0.0.74/.75 mechanism
worked exactly as designed — it retried all 3 attempts and streamed the live keepalive
(`⏳ retrying (attempt 2/3)… still waiting…`) to OpenWebUI. But when the provider stayed down and
retries were exhausted, the graceful-message handler used `re.search(...)`, and because
`generate_stream()` contains later `import re` statements, `re` is a LOCAL there — so referencing it
earlier raised `UnboundLocalError`. That error escaped to the outer guard, so the user saw
`⚠️ Deep research could not be started: cannot access local variable 're'` instead of the intended
"temporarily unavailable, try again later" message.

## Fix (`fastapi_server_complete.py`)

- The DR-branch graceful-5xx handler no longer references `re` directly. It reuses the engine's
  already-tested `_is_transient_5xx()` (which owns `re` in its own module), so the
  "temporarily unavailable — please try again in an hour or so" message is shown correctly on a
  repeated provider 5xx (and detailed messages for other errors). Verified: `_is_transient_5xx` on the
  exact `Ollama API error: 500 …` returns True (→ graceful message); 4xx returns False.

## Polish (`research/engine.py`)

- Retry keepalive heartbeat interval raised 20s → 40s, so the live view shows ~2 lines per retry wait
  instead of ~6 (still well under client read-timeouts; for non-streaming clients these lines are
  stripped anyway). The user's test had surfaced the chattiness.

## Verification

- Retry + keepalive themselves are now PROVEN in production (the live outage exercised them).
- The `re` fix routes the exact failing error to the graceful message (unit-confirmed via
  `_is_transient_5xx`). The full graceful path activates on the next real exhausted-retry 5xx (not
  reproducible on demand now that the provider has recovered).

## Files

- `fastapi_server_complete.py` — graceful-5xx handler uses `_is_transient_5xx` (no local `re`).
- `research/engine.py` — heartbeat interval 20s → 40s.
- `version.py` (→ 1.0.0.77), `README.md`, this changelog.
