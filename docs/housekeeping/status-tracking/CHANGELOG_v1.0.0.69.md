# CHANGELOG v1.0.0.69

**Date:** 2026-06-03
**Previous:** v1.0.0.68
**Trigger:** Live NewX testing revealed the v1.0.0.68 deep-research opt-out never actually took effect on the OpenAI-compatible endpoint — scheduled bots (raicaNews, etc.) kept running the multi-minute pipeline despite `deep_research: false`.

---

## Summary

Completes (fixes) the per-request deep-research opt-out introduced in v1.0.0.68. That release added the gate-side read (`data.get('deep_research', True)`) but the flag never reached it on the `/v1/chat/completions` path — the only path NewX AI bots use. `OpenAIChatRequest` did not declare a `deep_research` field and the model has `extra = "ignore"`, so Pydantic silently dropped the flag; the value was then never threaded into the `native_request_data` dict that becomes the gate's `data`. Net effect: every bot that set `deep_research: false` (raicaNews, TechNews, scibot, raicaFinance, raicaMiddleEast, Just4laughs) still triggered deep research whenever its prompt wording tripped the semantic gate. This release plumbs the flag end-to-end so the opt-out is honored.

---

## Root Cause (confirmed from logs)

- NewX correctly sent the flag: `celery_llm_worker.log` shows `deep research DISABLED for RAICA-Model1 (plugin scope)` ×12.
- RAICA never saw it: `logs/server_complete.log` showed `Deep research disabled for this request` ×0 and `DEEP RESEARCH MODE engaged` ×9 (incl. news-bot prompts).
- Drop point: `OpenAIChatRequest` (no `deep_research` field + `extra = "ignore"`) → `openai_chat_completions` forwarded only `allowed_tools` → `openai_streaming_response` built `native_request_data` without `deep_research`. The gate at the generate-stream layer therefore always read the `True` default.
- Why only raicaNews visibly fired (not the other 5 bots): the gate is a semantic classifier and RAICA's OpenAI endpoint discards the `system` message, so the gate classifies only the user message (built from the bot's `agent.topic`). raicaNews put deep-research-y wording ("thorough briefing… very latest… 8 hours up to the minute… clickable verified citations") in its `topic` → tripped the gate. The others put such wording in the `system_prompt` (dropped) and/or used lighter topics → did not trip it.

## Changes

- **`OpenAIChatRequest` gains a `deep_research: Optional[bool]` field** (default `None`) so Pydantic stops dropping it. Documented as a deliberate exception to the zero-trust "ignore everything" policy, alongside `allowed_tools` — it can only RESTRICT (skip the gate), never enable anything not already enabled.
- **Flag threaded end-to-end:** `openai_chat_completions` → `openai_streaming_response` / `openai_non_streaming_response` (new `deep_research=None` param) → injected into `native_request_data` **only when explicitly provided** (`if deep_research is not None`). `None`/unset leaves the prior default (gate decides) completely unchanged.
- **Observability:** logs `🔬 Client deep_research flag forwarded to pipeline: <bool>` when the flag is present, so the opt-out is visible in `server_complete.log`.

## Verification (live, via NewX)

- User confirmed end-to-end: triggering a `deep_research: false` bot now logs the forwarded-flag line and `Deep research disabled for this request`, and produces **no** `DEEP RESEARCH MODE engaged` — the bot returns a normal (fast) tool-assisted answer instead of the multi-minute pipeline.
- No regression on interactive `@Ask` (no flag sent → `None` → gate decides, unchanged).

## Companion fix (separate repo: NewX)

Same session also fixed the `@Ask` double-response bug (two near-simultaneous post submissions created two posts → two AI replies). Root cause was a non-idempotent post-creation path with no submit lock; fixed in NewX with a frontend submit-lock + a server-side dedup guard. Tracked in the NewX repo (not this changelog).

## Dependencies

- None new.

## Migration

- None required. Bots already shipping `deep_research: false` in their plugin YAML now have it honored automatically. Clients that never send the flag are unaffected.

## Files

- `fastapi_server_complete.py` — `OpenAIChatRequest.deep_research` field; flag forwarded through `openai_chat_completions` / `openai_non_streaming_response` / `openai_streaming_response` into `native_request_data`.
- `version.py` (→ 1.0.0.69), `README.md`, this changelog.
