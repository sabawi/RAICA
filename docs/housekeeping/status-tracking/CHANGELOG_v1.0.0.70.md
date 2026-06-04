# CHANGELOG v1.0.0.70

**Date:** 2026-06-03
**Previous:** v1.0.0.69
**Trigger:** Phase 0 of the Deep Research → Orchestration integration. A compound prompt
("do a deep research … produce a ≥1500-word academic paper … generate PDF … email it") was
fully refused — the synthesizer, handed the delivery directives it can't satisfy, refused the
*entire* task including writing the paper.

**Design reference:** `docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md` (Phase 0).

---

## Summary

Deep Research must produce **content**; delivery/packaging (PDF, HTML, file, email, social/publishing)
is handled downstream by POST-LLM execution / the orchestrator. Phase 0 enforces that separation at
the **research stage**: before researching, an LLM call normalizes a possibly-compound request down to
its research-and-writing intent, **stripping delivery/action directives and recipient addresses**. The
research engine and synthesizer therefore never see "generate PDF / email it" and can no longer refuse
the whole task on those grounds. This is the smallest, lowest-risk step of the orchestration retrofit;
it does NOT yet generate PDFs or send email (that is Phase 2).

---

## Changes

- **LLM-driven research-request normalization** (`research/pipeline.py`):
  - New `_normalize_research_request(generate_stream, config, user_request)` — an LLM call that returns
    `{"research_request": "<cleaned>"}` (STRICT JSON), keeping topic/scope/sections/length/citation
    requirements while removing delivery, file-format (PDF/HTML), save, email, and posting directives
    plus recipient addresses. Reuses `_collect_stream` + `extract_json_object` from `research.engine`
    (no new parsing code). Uses the deep-research engine model via the injected `generate_stream`.
  - Wired into `run_deep_research_pipeline`: the normalized request drives **both** `engine.run` and
    `synthesizer.run`. The full original request stays with the caller for the future
    orchestrator/POST-LLM action phase (Phase 2).
  - **Graceful, no-regression:** on any failure (LLM error or empty result) it falls back to the
    original request unchanged, logged as a warning. Never aborts a research run.
- **Config toggle** (`config/llm_config.yaml`): `deep_research.engine.normalize_request: true`
  (set `false` for legacy raw-request behavior).

## Compliance with CLAUDE.md

- LLM decides, returns JSON — RAICA only parses. **No keyword stripping / pattern matching** for meaning.
- Config-driven (toggle in YAML), not hardcoded.
- No regression: empty `actions`/normal research prompts behave as before; failure path = legacy behavior.

## Verification (live, user-confirmed via OpenWebUI)

Re-ran the exact failing prompt (Middle/Near-Eastern food + Islam academic paper, ≥1500 words, PDF, email):

| Metric | Before (v1.0.0.69) | After (Phase 0) |
|--------|--------------------|-----------------|
| Normalization | — | `🔬 Research request normalized (delivery/action directives stripped)` |
| Synthesis | 9.4s → **refusal** | 54.4s → **34,862-char paper (~7,392 tokens)** |
| Claims verified | 0 (n/a, refusal) | **71 claims — 63 supported / 8 contradicted** |
| Evidence | 30 items / 183 URLs | 32 items / 221 URLs (papers search succeeded) |
| Pipeline | refusal | `🧪 complete in 239.1s` |
| "I cannot create PDF / send email" | present | **gone** |

User confirmed: paper delivered, no refusal. PDF/email correctly **deferred** (Phase 2), not attempted.

## Known limitations / follow-ups

- **No delivery yet.** PDF generation, file save, and email are **Phase 2** (bridge research output →
  existing POST-LLM execution `_execute_missing_tools_post_llm` :7200 / call :10531).
- **Research-backend reliability (independent):** Semantic Scholar `429` / DOAJ `404` / some arXiv
  errors still occur; affects evidence depth, not the refusal fix.
- **Gate over-fire** on OpenWebUI title/tag housekeeping calls — cross-cutting, not addressed here.
- **Email channel** still `enabled: false` in `communication_hub.yaml` — Phase 2 needs client-scoped re-enable.

## Dependencies

- None new.

## Migration

- None required. New optional config key `deep_research.engine.normalize_request` (default behavior =
  enabled). Set `false` to restore the pre-Phase-0 raw-request path.

## Files

- `research/pipeline.py` — `_normalize_research_request()` + wiring into `run_deep_research_pipeline`.
- `config/llm_config.yaml` — `deep_research.engine.normalize_request`.
- `version.py` (→ 1.0.0.70), `README.md`, this changelog.
