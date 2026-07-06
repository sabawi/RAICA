# CHANGELOG — RAICA v1.0.0.141

**Date:** 2026-07-06
**Type:** Feature (shadow / observability) — non-DR output-side citation grounding, Phase 0

## Summary
The non-Deep-Research answer path (NewX bots + `@Ask`, served through
`fastapi_server_complete.llama_stream`) never had the **output-side citation grounding** that Deep Research
got this cycle. As a result, bot posts could carry **fabricated URLs** (e.g. a hallucinated
`houseofsud.com/...` that doesn't resolve — 0 occurrences in any log, so invented in the model's output) and
**reused generic links** (e.g. `middleeasteye.net/` stapled onto 11 unrelated headlines in `@raicaMiddleEast`
post 5572). Gather-time filtering cleans *tool results*; nothing checked the *finished answer*. Prompt rules
alone don't hold (raicaMiddleEast already had "never fabricate / never homepage / one URL per story" and the
model violated all three).

This ships **Phase 0 (SHADOW, log-only)**: it AUDITS every finished non-DR answer for structural citation
defects and logs them, **without modifying the answer**, to baseline the real rate before any enforcement.

## Changes
- **NEW `research/nondr_citation_audit.py`** — pure, offline, never-raises audit. Reuses
  `research.citation_grounding.extract_cited_links` + `normalize_url`. Phase-0 signals (all
  definitive/structural — LLM-Policy-clean, no keyword lists, no meaning-decisions):
  - `fabricated` — cited URL not among the URLs the model was shown (the tool-result evidence in the prompt).
  - `reuse` — one URL cited under multiple distinct headlines (structurally, ≤1 can be correct).
  - `bare_homepage` — cited URL has no article path (`''`/`/`).
  - (section-page detection + dead-link liveness deferred to later phases — they need a proper section
    detector / network fetch; Phase 0 stays offline = zero added latency.)
- **`fastapi_server_complete.py`** — at the post-primary-LLM seam in `llama_stream` (the single completion
  point that `/v1/chat/completions` and `/api/generate` both reach), added a **fail-open, DR-excluded**
  shadow call: `audit_citations(complete_llm_response, stream_payload['prompt'])` → logs
  `🩹 nondr-citation [SHADOW]: cited=… fabricated=… reuse=…(max×N) bare_homepage=…` (+ an offenders line when
  fabricated/reuse > 0). Answer is never touched. Gated on `non_dr.citation_grounding.enabled` and skipped
  when `_dr_on` (DR has its own grounding).
- **`config/llm_config.yaml`** — new top-level `non_dr.citation_grounding` `{enabled: true, shadow: true}`.
- **NEW `tests/integration/test_nondr_citation_audit.py`** — 5 offline tests mirroring the real failures
  (houseofsud fabrication, middleeasteye ×N reuse + bare-homepage, clean-answer no-false-positives,
  empty-evidence fail-safe, never-raises). All pass.
- **`docs/RAICA_NONDR_CITATION_GROUNDING.md`** — design/rollout doc; status → Phase 0 implemented.

## Verification
- Unit: `tests/integration/test_nondr_citation_audit.py` — **5/5**.
- E2E (local): non-DR `/v1/chat/completions` request (`deep_research:false`, tools) hit the seam and logged
  `🩹 nondr-citation [SHADOW]: cited=5 distinct=5 evidence=18 | fabricated=0 reuse=0(max×0) bare_homepage=0`;
  DR gate confirmed; **answer unchanged** (5 citations delivered normally).

## Risk / rollback
- Log-only; no answer modification; fail-open (any error → today's behavior). Disable via
  `non_dr.citation_grounding.enabled: false`. No latency added (offline audit).

## Next
- Accrue live shadow baseline (esp. `@raicaMiddleEast` reuse). Then Phase 1: enforce fabricated + reuse
  (strip the bad link, keep the headline text); later add section-page detection + dead-link liveness.
