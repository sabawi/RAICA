# CHANGELOG v1.0.0.64

**Date:** 2026-05-31
**Previous:** v1.0.0.63
**Trigger:** Deep Research enhancement — Stages 1 & 2 (engine + synthesis/verification/arbitration) and `/v1` integration

---

## Summary

Adds the full **Deep Research** capability (Stages 1–2 of `docs/DEEP_RESEARCH_MULTIMODAL_PLAN.md`): an LLM-driven, multi-round research engine that plans sub-questions, fans out across existing tools, grades source credibility, synthesizes across multiple models with arbitration, and verifies every claim against the gathered evidence. It is **auto-detected** by a high-precision gate and runs from Open-WebUI with live progress streaming. Verified end-to-end through the live server.

---

## New Features

- **Deep Research engine** (`research/` package — new, decoupled, dependency-injected, unit-testable):
  - `gate.py` — high-precision, LLM-driven detector deciding whether a request warrants deep research (only fires on a high-confidence "deep" verdict; biased toward the fast path). Calibrated with contrastive examples — **not** keyword matching.
  - `engine.py` — **Stage 1**: LLM planner (sub-questions + per-question source strategy) → concurrent multi-backend dispatcher over the existing `AsyncToolManager.available_functions` → iterative gather loop with LLM gap-assessment, bounded by config ceilings.
  - `synthesis.py` — **Stage 2**: LLM source-credibility grading (peer_reviewed/reputable/popular/low_credibility) → grounded, credibility-aware synthesis → multi-model arbitration that surfaces source conflicts → claim extraction + cross-source verification.
  - `pipeline.py` — orchestrates Stage 1→2 and appends a **Research Audit** footer (sources, credibility tiers, claims-checked verdicts).
- **`/v1` auto-routing** — `generate_stream` calls the gate; on a high-confidence trigger it streams live progress (`> Planning… > Round k… > Verifying…`) and the audited answer, bypassing the normal flow. Opt-in by intent — no model alias to remember, no keyword routing.
- **Config** (`config/llm_config.yaml → deep_research.engine`): planner breadth, loop ceilings, allowed sources, credibility grading, `evidence_token_budget`, verification, and arbitration model list.

## Changes / Fixes

- **Context-overflow fix (critical):** a deep run can gather >1 MB of evidence, which overflows the model window. The evidence fed to each LLM call is now **token-budgeted** (tiktoken, `evidence_token_budget: 110000`), shared fairly across sources (small kept whole, large truncated only as needed). Prevents the `prompt too long` failure observed pre-fix.
- **Output structure fix:** synthesis/arbitration prompts now require a **TL;DR** at the top and a **## Conclusion** before the optional **## Notable Source Conflicts** appendix (a Conclusion/TL;DR was missing in the first integrated run).
- Engine moved out of `user_tools/` into the `research/` package so tool-discovery no longer mis-scans it.

## Verification (end-to-end, live server via Open-WebUI)

- **Gate precision:** 12/12 on an offline battery (incl. tricky negatives like "research the best laptop under $1000" → fast path); in live use, 4/4 normal queries → no trigger, 1/1 deep query → trigger, all high-confidence.
- **Full deep run** ("dark matter vs. modified gravity"): gate fired → 6 sub-questions → 3 rounds → **21 evidence items / 220 unique sources / 575 KB** → 2-model synthesis (deepseek-v4-pro + gpt-oss:120b) → arbitration → **28/28 claims supported** → audited answer streamed cleanly (no errors, clean `EXITING GENERATE_STREAM`). ~4m16s total.
- Output was even-handed (both paradigms), surfaced model-draft conflicts in a dedicated section, kept low-credibility sources out of the authoritative body, and (post-fix) leads with a TL;DR and ends with a Conclusion.
- **No regression:** normal queries skip the deep branch and take the existing path unchanged.

## Known Issues / Follow-ups

- **System prompts:** research LLM calls pack instructions into the user prompt and call `generate_stream` without a `system_prompt` (Ollama logs `⚠️ NO SYSTEM PROMPT`). Benign and output-verified, but moving instructions to a real system prompt is a tracked robustness polish (its own test pass).
- **Verifier threshold:** single-source claims are currently labeled "supported"; calibrating the supported/unverified boundary against `min_corroborating_sources` is future tuning.
- **Optimization-safety engine** (Option B) remains deferred per `docs/OPTIMIZATION_SAFETY_REBUILD_SCOPE.md`.

## Dependencies

- None new. `tiktoken` (already a dependency) is now also used by `research/synthesis.py` for evidence budgeting.

## Migration

- None required. Deep research is enabled by default (`deep_research.engine.enabled: true`) and auto-detected; set `enabled: false` to disable, or `arbitration.enabled: false` to use faster single-model synthesis.

## Files

- `research/` (new): `__init__.py`, `gate.py`, `engine.py`, `synthesis.py`, `pipeline.py`
- `fastapi_server_complete.py` — `/v1` deep-research branch in `generate_stream`
- `config/llm_config.yaml` — `deep_research.engine` block
- `version.py` — 1.0.0.63 → 1.0.0.64
- `README.md` — Deep Research feature + version sync
- `docs/DEEP_RESEARCH_MULTIMODAL_PLAN.md` — Stage 1–2 marked complete
- `docs/housekeeping/status-tracking/CHANGELOG_v1.0.0.64.md` (new)
