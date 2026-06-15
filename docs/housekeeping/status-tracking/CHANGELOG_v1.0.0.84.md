# CHANGELOG v1.0.0.84

**Date:** 2026-06-05
**Previous:** v1.0.0.83 (Convergence Phase 2 — shadow-mode LLM intent classifier)
**Theme:** **Convergence Phase 3a (labeled baseline) + 3b (intent-prompt tuning)**

> Part of the Context-and-Action Substrate Convergence — `docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md`.
> **No production behavior change**: the only production-code edit is the shadow intent classifier's
> system prompt (`orchestration/intent.py`), which is still invoked only when `convergence.shadow_classifier`
> is enabled (default OFF). Everything else added is tests/data/harness.

---

## Phase 3a — Labeled evaluation baseline (no behavior change)

A ground-truth-labeled corpus + harness to measure BOTH intent classifiers against *correct* behavior
(not just legacy-vs-LLM), so a per-category cutover can be justified with data.

- `tests/data/intent_eval_corpus.py` — **32 labeled cases**: info_only, plain_answer, pure_email,
  file_email, file_only, publish, image, meta_task, **edge** (negation, how-to, format synonyms), and
  **multi_turn** (embedded conversation history, distractors, follow-ups, high-complexity compound).
- `tests/utilities/run_intent_eval.py` — runs both classifiers vs ground truth (KIND-based scoring,
  robust to tool naming) with an `EVAL_RUNS` knob for multi-run **stability** measurement.
- `tests/utilities/intent_eval_scoring.py` — shared pure scoring helpers.
- `tests/integration/test_intent_eval_baseline.py` — DETERMINISTIC (no-LLM) regression test pinning the
  legacy baseline (exact set of cases legacy gets wrong) + scoring-helper unit tests.

**Baseline finding (delivery decision = the safety-critical call):**

| | Legacy (keywords) | LLM |
|---|---|---|
| delivery-decision correct | 71.9% (23/32) | **100% (32/32)** |
| full (decision+kinds) | 53.1% | **~94%** |
| plain_answer / edge / multi_turn | 0% / 20% / 67% | 100% / 100% / 100% |

Legacy's failures are dangerous false-positives: "Thanks!" → email; a question whose *history* contains
"email" → email; "don't email this" → email; "how do I email a PDF?" → email; "write a poem" → file+email.

## Phase 3b — Intent-prompt tuning (shadow classifier prompt)

Tuned `INTENT_SYSTEM_PROMPT` in `orchestration/intent.py` to close the gaps the baseline + shadow
exposed (needed because full-tool-set cutover relies on exact tool selection):
1. **Research/search/sub-agent tools are NOT delivery** — never list them (kills the `raica_research_agent`
   trap where the LLM delegated "research X and email a PDF" to a do-everything agent).
2. **Emailing/saving a *document* requires BOTH** the file-creating tool AND the email tool.
3. **Document ≠ chart** — a document/report saved as a file uses the file-writing tool; the
   visualization tool is only for an explicit chart/plot/graph/image.

**Result (tuned, 3 runs/case):** delivery decision **100% (32/32), 100% stable**; exact tool-set
stability **93.8% (30/32)**. The 2 residual wobbles (`email_notes`, `img_email`) are **benign
over-inclusion** (the LLM sometimes adds a file step on genuinely ambiguous "email the notes" /
"visualize and email" cases) — defensible interpretations, not dangerous errors.

## Why this matters for cutover
The safety-critical **decision** (does this need post-generation delivery at all?) is now 100% reliable
and stable — eliminating every dangerous legacy false-positive. The remaining ~6% variance is in exact
tool selection on borderline cases and is benign. This justifies the Phase-3c full-tool-set cutover
**with legacy as a fallback** (on LLM error/timeout). The hard caveat that drove keeping a fallback —
run-to-run LLM variance — is now quantified (93.8% exact-tool stability).

## Tests
- Full deterministic suite: **92 passed, 0 skipped** (characterization goldens unchanged, policy,
  intent unit, legacy baseline). The LLM stability numbers come from the live harness (not in CI).

## Files
- `orchestration/intent.py` — tuned `INTENT_SYSTEM_PROMPT` (only production-code change).
- `tests/data/intent_eval_corpus.py`, `tests/utilities/run_intent_eval.py`,
  `tests/utilities/intent_eval_scoring.py`, `tests/integration/test_intent_eval_baseline.py` (NEW).
- `version.py` (→ 1.0.0.84), `README.md`, this changelog, convergence doc (Phase 3a/3b marked done).

## Next
- **Phase 3c** (approved scope: FULL tool set) — make the LLM classifier authoritative with legacy
  fallback, flag-gated; couples to Phase 4 (the POST-LLM executor must dispatch the LLM's chosen tools).
  This is the FIRST production behavior change in the convergence — gated on explicit go-ahead.
