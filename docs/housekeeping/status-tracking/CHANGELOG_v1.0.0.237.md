# CHANGELOG — v1.0.0.237 (2026-08-09)

**Theme:** truncation detection — plan step **4.2** of
`docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md`.

**Additive only. No lane repointed, no model changed, no payload altered.**

---

## The problem

A response cut off by `max_tokens` arrives as a **normal HTTP 200** with
well-formed JSON. The only signal that the body is incomplete is
`finish_reason == "length"` — and nothing in RAICA read that field. It appeared
in the codebase *exclusively* where RAICA **writes** it for its own clients.

So a truncated reply was indistinguishable from a model that produced bad output.
The log blamed the model; the real cause — a cap set too low — was invisible.

**Measured instance.** The arbitrator is capped at `max_tokens: 1024`
(hardcoded, `manager.py:317`). At ≥4 tool results the `tasks[]` JSON exceeds it:

| batch | gpt-oss-120b | GLM-5.2 |
|---|---|---|
| 1–2 | complete | complete |
| **4** | complete | **50% truncated** |
| **6** | complete | **0% — every run truncated** |

Production has run batches of 4, 5 and 6 (`logs/archive`), so this has been
failing silently on real turns. On a live call at batch 6, GLM-5.2 returned
**0 characters** — the entire budget went to reasoning before any JSON was
emitted — with no error anywhere.

## The change

`llm_providers/openai.py`

- new `_warn_if_truncated()` — one place, used by both request paths
- `generate_stream()` now tracks `finish_reason` across SSE chunks and reports it
- `generate_tools()` reports it **and returns `truncated: bool`**, so callers can
  branch rather than guess from malformed `arguments`
- the warning names the **model**, the **cap that was hit**, and the remedy —
  a message that says "something broke" would not be actionable
- incidental hardening in the same loop: `.get('choices') or []`,
  `.get('delta') or {}`, `.get('content') or ''` (the SI-013 null-vs-absent
  pattern, applied to the streaming path)

**Deliberately a WARNING, not an exception.** Truncated output is often partially
usable; raising would convert a degraded response into an outage. The caller
decides — this only makes the decision possible.

## Verification

- `tests/unit/test_openai_provider_truncation_detection.py` — 5 tests;
  **4 FAIL on pre-4.2 code** (verified via `git stash`), all pass after.
  Includes negative cases so a complete response never warns.
- **Real-path proof:** a live DeepInfra call (GLM-5.2, batch 6, production
  `max_tokens=1024`) emitted the warning and returned unparseable output —
  the exact silent failure, now stated.
- Tier-0 9/9. Full unit set 9/9.

## What this does NOT fix

The truncation itself. The cap is still hardcoded at `manager.py:317`, so
`llm_config.yaml`'s `max_tokens` remains inert for the arbitrator. That is plan
step **4.3** (make it config-driven, set 4096) and lands next.

Until 4.3, the arbitrator is **more correct but still token-capped** — the
v1.0.0.236 SI-014 fix made it emit the full schema, which is what exceeds the cap.
**Do not deploy .236/.237 without 4.3.**

## Dependencies

None.
