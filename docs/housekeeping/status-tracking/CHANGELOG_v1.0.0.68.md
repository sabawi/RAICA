# CHANGELOG v1.0.0.68

**Date:** 2026-06-02
**Previous:** v1.0.0.67
**Trigger:** Deep Research reliability — enumeration stability, planner hardening, model split, and a per-request opt-out (driven by live NewX testing)

---

## Summary

Hardens the Deep Research pipeline against the run-to-run inconsistency and failures surfaced by extensive live testing through the NewX `@Ask` bot: enumeration could stop gathering too early (thin roster), the planner LLM call could crash the whole run on a transient empty response, and the heavily-loaded `deepseek-v4-pro:cloud` endpoint caused throttling. Adds a model split (deep research → flash, normal chat → pro) and a server-authoritative opt-out so scheduled bots don't trigger the expensive pipeline.

---

## New Features / Changes

- **Enumeration gather floor (`min_rounds`):** the planner now sets a minimum number of gather rounds (≥2 for list/table/"earliest" requests). The loop refuses to stop early even if the gap-assessor says "sufficient" before the floor — fixing the dominant cause of incomplete rosters (a single thin round → 5-item answer). Simple/factual requests keep `min_rounds: 1` (fast path unchanged).
- **Planner hardening (retry + fallback):** the planner LLM call now retries up to 3× with 3s/6s backoff (to ride out transient cloud blips), then falls back to a minimal single-sub-question plan rather than crashing the run. Fixes observed `Expecting value: line 1 column 1` crashes from transient empty responses.
- **Roster self-audit pass:** after the initial roster extraction, a second pass re-scans the breadth-first evidence for qualifying items MISSING from the roster and merges them (observed adding 5-16 genuinely-valid items per run). Roster `max_tokens` raised so long rosters aren't clipped. Raises the completeness floor (catastrophic 5-item rosters → reliable 13-19+, with the genuinely-earliest boundary items reliably captured). Note: exact counts still vary run-to-run (inherent LLM nondeterminism); completeness, not a fixed count, is the goal.
- **Grounding caveat:** the audit footer now warns when ≥30% of an answer's claims are unverified/contradicted (signals the answer over-reached its evidence, e.g. a roster padded beyond what sources support). Silent on healthy runs.
- **Model split — deep research uses `deep_research.engine.model`:** all deep-research pipeline LLM calls (gate, planner, roster, grade, synthesize, verify) now use a dedicated model (`deepseek-v4-flash:cloud`) while the global `primary` (`deepseek-v4-pro:cloud`) still serves the normal chat path. A/B testing showed flash is equal-or-better AND 2-3× faster on the factual/structured research tasks, and moving the high-frequency calls off the overloaded pro endpoint eliminated the throttling — while pro is preserved for normal multi-step reasoning (where flash is weaker). `null` → use primary.
- **Per-request deep-research opt-out:** `/v1` honors `{"deep_research": false}` in the request body to skip the gate entirely (server-authoritative). Lets quick-scope clients (e.g. NewX scheduled news/science bots) avoid the multi-minute pipeline. Default true = unchanged.

## Verification (live, via NewX @Ask + isolated A/B)

- **Flash split run** (15-civ enumeration): 318s total, planner succeeded on attempt 1 (no throttling), self-audited 15-civ roster, 42,675-char synthesis, **161 claims checked / 156 supported (97% grounded)** — equal-or-better than pro, faster, untruncated. User confirmed no truncation.
- **A/B (flash vs pro)** across planner/roster/verify/synthesis: flash equal-or-better and 2-3× faster on all four (synthesis with the mandatory-citation prompt: 38 citations vs pro's 7). Pro retained for normal chat: flash fails a hard multi-step reasoning puzzle that pro solves — hence the split, not a blanket swap.
- Gather floor, planner retry+fallback, and grounding caveat all observed firing correctly on real runs.

## Known Issues / Follow-ups

- **Roster near-duplicate entries:** dedup is exact-match only, so alias/near-duplicate pairs can both appear (observed: "Hittites" and "Hattians"; earlier "Urartu"/"Kingdom of Urartu"). A semantic/fuzzy dedup pass in the roster self-audit is the planned fix. (Non-blocking.)
- **Run-to-run roster membership varies** (intrinsic LLM nondeterminism); completeness floor is solid, exact set is not deterministic.
- `deep_research.engine.model: deepseek-v4-flash:cloud` is a dev-server choice for load/speed; revert to pro (or null) if research quality regresses on harder topics.

## Dependencies

- None new.

## Migration

- None required. New config: `deep_research.engine.model` (deep-research model override; null→primary). Behavior change: deep research now runs on flash by default; set to null to use the global primary.

## Files

- `research/engine.py` — min_rounds gather floor, planner retry+backoff+fallback
- `research/synthesis.py` — roster self-audit pass, raised roster tokens
- `research/pipeline.py` — grounding caveat
- `fastapi_server_complete.py` — deep-research model-split wrapper, `deep_research` request opt-out
- `config/llm_config.yaml` — `deep_research.engine.model`
- `version.py` (→ 1.0.0.68), `README.md`, this changelog
