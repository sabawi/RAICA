# CHANGELOG v1.0.0.65

**Date:** 2026-06-01
**Previous:** v1.0.0.64
**Trigger:** Deep Research tuning, hardening, and system-prompt refactor (post-v1.0.0.64 iteration)

---

## Summary

Iterative refinement of the Deep Research pipeline (Stages 1–2 shipped in v1.0.0.64) based on extensive live testing: depth/quality tuning, exhaustive claim verification with a clear accuracy audit, output controls, per-phase timing, a robustness/hardening pass, and a system-prompt refactor of all research LLM calls. Verified end-to-end.

---

## New Features

- **Clean-output controls** (`deep_research.engine.output`): `stream_progress` (header + live `> Planning…` lines) and `include_audit_footer` (the `🔎 Research Audit` block) can each be disabled so a client gets only the answer.
- **Per-phase timing audit**: the footer (and logs) now report `Total Xs — plan · gather · grade · synthesize · arbitrate · verify`, so bottlenecks are visible. Stage-1 split into `plan` vs `gather`.
- **Output-token logging**: each synthesize/arbitrate call logs `~N output tokens / cap (X% of cap)` with an `AT CAP` warning, making truncation visible.
- **Split verification audit** — the footer now distinguishes:
  - **⚠️ Claims to scrutinize** — `contradicted_by_evidence` / `not_in_evidence` (the answer may be wrong/ungrounded), vs.
  - **ℹ️ Attributed to low-credibility sources** — `attributed_to_low_credibility` (the answer is correctly attributing a claim to a weak source; a feature, not a defect), vs.
  - **✅ all checked claims are evidence-supported**.
- **Per-phase model knobs**: `arbitration.arbitration_model` and `verification.verify_model` (null → primary) for speed/quality experiments; `synthesis.max_answer_tokens` and `verification.max_tokens` are config-driven.

## Changes / Tuning (driven by live testing)

- **Single-model synthesis is now the default** (`arbitration.enabled: false`). Two-model arbitration was found to (a) receive the drafts but NOT the evidence pool, making its "enrich against evidence" instructions impossible, and (b) collapse rich drafts (~31–33K chars) to ~21K regardless of input. Single-model synthesis on the primary (full evidence in-context) + verification preserves depth and is ~125s faster. Arbitration remains available; revisit only with on-par draft models.
- **Depth-maximizing synthesis prompt** — the synthesis directive now leads with "MAXIMIZE DEPTH AND COVERAGE: cover every substantive point, expand don't trim, maintain 100% of the evidence's detail, depth only from MORE evidence (never padding)." Raised answer quality from terse (~17K) to rich (~37–47K) on complex topics without sacrificing accuracy.
- **Exhaustive verification** — verify prompt now demands complete claim extraction (not sampling) and `verification.max_tokens` raised 4000 → 12000. Result: ~50+ claims checked on long answers (was ~12), so the accuracy audit actually covers the whole answer.
- **`max_answer_tokens` 8000 → 16000** — 8000 was truncating drafts mid-output on rich topics.
- **System-prompt refactor (all 6 research calls)**: gate, planner, gap-assessment, credibility grading, synthesis, arbitration, and verification now pass their instructions via `system_prompt` (data stays in the user prompt). Eliminates the `⚠️ NO SYSTEM PROMPT` warning and improves instruction-following. Verified: research calls now log `📋 SYSTEM PROMPT: N chars`; quality held (31/31 claims supported on the regression e2e).

## Hardening (robustness pass)

Eight issues found and fixed so failures degrade gracefully instead of crashing or discarding work:
- `/v1` gate/import/tool-load failures now fall through to the normal flow (previously could 500 the request despite the comment claiming otherwise).
- **Verification failure no longer discards a successful answer** — wrapped; degrades to no-audit.
- **Credibility-grading and gap-assessment LLM-call failures** no longer kill the run/loop — both fall back gracefully (grading → "unknown"; assessment → stop loop with evidence kept).
- **User-facing footer is crash-proof** against malformed verifier JSON (non-dict claims, non-list citations, None sub-dicts) — fuzz-tested with 11 malformed-input cases, all pass; footer render is wrapped so a footer error never discards the answer.
- Per-tool dispatch errors caught in the `/v1` hot path; the terminating `done` stream chunk is always sent.

## Known Issues

- **`RAICA-Model1 not found` 404 on the no-tools path (pre-existing, NOT introduced here)**: when a request needs no tools, the public model alias `RAICA-Model1` is passed literally to Ollama instead of being resolved to the configured primary, causing a 404 + empty fallback. This lives in the normal-flow model-resolution code (outside the deep-research diff) and does not affect Open-WebUI traffic or deep-research queries (which use real model names). Tracked for a separate fix.

## Dependencies

- None new. `tiktoken` (already required) used for token budgeting.

## Migration

- None required. Deep research stays auto-detected and enabled. Notable default change: `arbitration.enabled: false` (single-model synthesis). Set `true` to restore two-model arbitration. All tuning knobs live in `config/llm_config.yaml → deep_research.engine`.

## Verification (live + e2e)

- Multiple live Open-WebUI deep queries across topics: depth markedly improved (e.g. 47K-char answer, 58 claims checked / 55 supported / 3 correctly bucketed as low-cred attributions); clean-output flags, timing footer, and split audit all rendered correctly.
- System-prompt refactor e2e: 17K answer, **31/31 claims supported**, zero `NO SYSTEM PROMPT` on research calls.
- No regression: normal queries skip the deep branch (`gate trigger=false`).

## Files

- `research/engine.py`, `research/synthesis.py`, `research/pipeline.py`, `research/gate.py` — tuning, hardening, system-prompt refactor
- `fastapi_server_complete.py` — `/v1` hot-path hardening + output flags
- `config/llm_config.yaml` — output flags, timing, model knobs, token budgets, single-model default
- `version.py` (→ 1.0.0.65), `README.md`, this changelog
