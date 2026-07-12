# Changelog — v1.0.0.177

**Date:** 2026-07-12
**Scope:** Reasoning-elicitation audit + fix — push the prose-generating reasoning nodes to USE their full reasoning to get from the user's prompt to a **verifiable** answer, not just to convey/summarize evidence. Phase 1 of 2 (the prompt directive); Phase 2 (selectively enabling native `think` mode) is a separate A/B-tested decision.

## Background (the audit)
Two gaps found across the workflow's reasoning nodes:
1. **Prompts elicited *coverage*, not *reasoning*.** The DR synthesis prompt maximized depth/coverage ("use ALL evidence, expand/enrich, surface controversial points") but never told the model to weigh competing evidence, draw grounded inferences, resolve contradictions, and reach a verifiable conclusion that directly answers the question. Same for arbitration (union-of-drafts) and the coverage assessor; the non-DR base prompt was minimal.
2. **Native reasoning (`think`) is OFF** (`config: think: false` on the primary + DR-engine model) — deferred to Phase 2 (A/B test reasoning-gain vs latency before committing).

## Added — a single canonical REASONING DIRECTIVE, reused across the reasoning nodes
`research/synthesis.py` defines `REASONING_DIRECTIVE` (module constant) so every node speaks with one voice (the no-inconsistency rule). It instructs the model to: pin down what is TRULY being asked; decompose and reason through each part; **WEIGH competing/contradictory evidence** (which is better-supported and why) and reconcile or flag conflicts; **draw well-supported inferences** the evidence enables (never beyond it); reach a **CLEAR, VERIFIABLE conclusion** (every load-bearing claim checkable, every number arithmetically sound); and **SELF-CHECK** the chain for leaps/arithmetic slips/question-dodging before finalizing. Policy language only (LLM decides — no hardcoded logic).

Wired into:
* **DR synthesis** (`synthesis.py`) — the Primary's reasoning over evidence; + a note that depth and reasoning are complementary.
* **DR arbitration** (`synthesis.py`) — reconcile by reasoning about *why* drafts differ / which is better-grounded, not a blind union.
* **DR coverage assessor** (`engine.py`) — reason from the user's actual question backward; a gap is *unanswered reasoning*, not just an under-cited claim.
* **Non-DR Primary base prompt** (`primary_model_system_prompt.txt`) — the @Ask answer path; placed above CORE RULES, fully consistent with the existing anti-hallucination/citation rules (inferences capped at "never beyond the evidence").

## Verification
* Imports clean; directive present in all four nodes; anti-hallucination rules intact. RAICA healthy on v1.0.0.177.
* Live validation: continues on sabawi.net (watch for richer, more decisive, better-grounded answers with no regression).

## Next (Phase 2, per plan)
* **A/B `think` on/off** on a hard query — measure reasoning-gain vs latency/token cost, then decide whether to enable native reasoning selectively on the heavy calls (synthesis, arbitration, hard non-DR).

## No config / dependency changes.
