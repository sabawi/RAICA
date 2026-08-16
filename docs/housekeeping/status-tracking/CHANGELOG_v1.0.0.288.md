# CHANGELOG v1.0.0.288 — SI-056: the migration left two lanes behind

**Date:** 2026-08-16 · **Against:** v1.0.0.287 · **Closes:** SI-056

## How it was found

The user asked whether the Ollama→DeepInfra switch had accounted for the vision models,
which are on Ollama. It had not — and the arbitrator was worse.

## What was wrong

| lane | model | base_url | state |
|---|---|---|---|
| **arbitrator** | `zai-org/GLM-5.2` (DeepInfra slug) | **127.0.0.1:11434/v1** (local Ollama) | **404 every call** |
| **vision** | minimax-m3:cloud + kimi-k2.6:cloud | 127.0.0.1:11434 | **429 quota, primary AND fallback** |

Verified by invoking, not by reading a catalog:
`HTTP 404 {"message":"model 'zai-org/GLM-5.2' not found"}`.

Measured over one night: **178 arbitrator attempts, 1 success, 34 runs exhausting all 5 tries.**

**This was the cause of the trigger behind SI-048/051/052.** A failing arbitrator regenerates
tools up to 5× per request, and the regeneration path discarded every prior result.
v1.0.0.287 made the system *resilient* to that loop; this stops the loop from firing.

## Changes

1. **Arbitrator** → `base_url: https://api.deepinfra.com/v1/openai` + `api_key: ${DEEPINFRA_API_KEY}`
   (model was already correct and already proven on that endpoint). One-line revert recorded inline.
2. **Vision** → `type: openai`, `Qwen/Qwen3-VL-235B-A22B-Instruct` primary +
   `meta-llama/Llama-3.2-90B-Vision-Instruct` fallback on DeepInfra. Both verified **by invocation**
   (each was shown a test image and named its colour). Deliberately two different families, preserving
   the existing fallback-diversity rationale. `image_to_text.py` already had a correct
   OpenAI-compatible vision branch and dispatches on the config `type`, so no code change was needed.
3. **NEW Tier-0 gate** `tests/integration/test_lane_transport_consistency.py` — asserts every lane's
   model belongs to its own base_url's transport (`vendor/model` never at a local Ollama endpoint;
   `name:tag` never at a remote API), that remote lanes carry an api_key, and that every lane declares
   a base_url. **Structural and offline on purpose:** a live probe in Tier-0 would make commits fail on
   someone else's rate limiter (the SI-054 trap); live reachability stays in `make smoke`.

## Why nothing caught it before

The parity contract asserts a provider *consumes* the parameters callers pass. Nothing asserted a
lane's model is *served by* its endpoint. That is a reachability check, and it now runs pre-commit.

## Verification

- **Tier-0 10/10** (new gate included). Falsified: reverting the arbitrator config makes it fail with
  `lane(s) point a vendor/model slug at the LOCAL OLLAMA endpoint`.
- **Vision, real entry point, 3/3 runs** — each named red, blue, **SEVEN**, circle and square from a
  generated test image (genuine OCR + shape recognition), 1,601–2,261 chars.
- **Arbitrator, 3/3 runs:** **3 attempts, 3 validated OK, 0 exhausted, 0 regenerations**
  (was 178 / 1 / 34, with 5 regenerations per request). Latency **27–33 s**, previously 300 s+.
- **Answers, 3/3:** every statistic correct (4.29 / 4.79 / 3.97 / 4.77 / 4.41 / 5.08), **zero**
  fabricated values, 1 chart marker each, all three serving **HTTP 200 image/jpeg 66–68 KB**.
- **Unit 552 passed**, 4 pre-existing failures unchanged. **`make smoke` PASSED** (6/6 tools).
  Version sync 5/5.

## Test-coupling defect fixed alongside

Three `image_to_text` unit tests patched `_process_with_ollama` and so were coupled to whatever the
production config said — they passed by accident and broke the instant the lane moved. They now pin
`vision_config['type'] = 'ollama'` explicitly, stating the transport they exercise.

## Caveat carried forward

Every E2E in v1.0.0.285–287 ran with a dead arbitrator. Those fixes stand on their own evidence, but
this is the first build where system behaviour with a WORKING arbitrator has been measured — and it
is materially different: no regeneration at all, and ~10× faster.

## Still open

SI-052 (no output-size guard), SI-053 (latent reference form), SI-054 (flaky smoke gate),
SI-055 (Tier-1 self-throttles; **still blocks capturing a new baseline**).
