# Changelog — v1.0.0.178

**Date:** 2026-07-12
**Scope:** Phase-2 reasoning decision + directive hardening. Resolves the "should native `think` go back on?" question with an A/B, and hardens the `REASONING_DIRECTIVE` against the two failure modes observed with `think` OFF.

## Decision: native `think` stays OFF (evidence-based)

A controlled A/B — same model (`deepseek-v4-pro:cloud`), same system prompt carrying the deployed `REASONING_DIRECTIVE`, varying only `think` — was run on three prompts with checkable ground truth (a river-crossing logic puzzle → 7 trips; a self-contained DCF → intrinsic ≈ $51.61; the NVDA 3-signal reconcile → decisive call):

| Prompt | think OFF (directive only) | think ON (fair 8192-token budget) |
|---|---|---|
| Puzzle | ✅ correct (7 trips) + self-initiated optimality check | ❌ **empty answer** — 5,611 words of hidden reasoning consumed the whole budget |
| DCF | ✅ $51.61 (= ground truth) | ✅ $51.61 — **identical**, but 4× latency + hidden token tax |
| NVDA | ✅ decisive HOLD, self-consistent | ⚠️ decisive SELL — different, not better (lateral variance) |

Findings: **zero quality gain**, an **unbounded reasoning stream** that returns empty answers on the hardest prompts (the model exposes `think` as a bare boolean — no `reasoning_effort` cap), and **3–10× latency plus ~1,300–7,500 hidden reasoning tokens per call** (which, under a hide-and-log design, are paid for but never shown). This corroborates prior operator experience of worse results with other thinking models — the reasoning value must come from the **directive**, not native `think`. `config: think: false` is retained on all nodes.

## Added — two hardening clauses in the canonical `REASONING_DIRECTIVE`

Both target failures seen in a live/`think`-off reply (the puzzle answer) and are **policy language only** (LLM decides — no hardcoded logic), so they inherit into every node that already uses the directive:

1. **ONE COMMITTED ANSWER** — reconcile to a SINGLE final figure/verdict and state it once; scrub any superseded value so it cannot survive into the answer contradicting the conclusion. *(Kills the "ghost" — a stale earlier number, e.g. an old "11 trips", surviving next to the correct "7".)*
2. **NO STAGED EVIDENCE** — never present code, a script, or a computation as though it was executed and its output quoted unless it genuinely was; show the ACTUAL arithmetic instead of dressing up unexecuted code or an invented "output" as verification. *(Kills "evidence theater" — presenting a BFS script + a fabricated result that was never run.)*

Wired into (unchanged mechanism — one voice across layers, the no-inconsistency clause):
* **`research/synthesis.py`** — the `REASONING_DIRECTIVE` module constant → flows automatically to **DR synthesis** and **DR arbitration**.
* **`primary_model_system_prompt.txt`** — the non-DR **@Ask** answer path, using that file's `tool results` vocabulary; placed above CORE RULES, fully consistent with the existing anti-hallucination/citation rules.

## Verification
* Imports clean; both clauses present in the synthesis constant and the primary prompt; CORE RULES intact and still after the inserted clauses. RAICA healthy on v1.0.0.178.
* Controlled re-test (puzzle, `think` OFF + hardened directive): complete answer, committed to **7 trips**, **no ghost-11**, **no staged code/fabricated output**, no regression.
* Definitive validation: operator re-run of the live prompt on sabawi.net (the "before" showed the ghost-11 + fabricated BFS output).

## No config / dependency changes.

## Deferred / noted
* **Fix 1 (de-inline Ollama's `thinking` field in `llm_providers/ollama.py`)** — now dormant since `think` is OFF everywhere (the re-inlining code never fires), but retained as a latent-bug note: any future `think:true` (or a model that emits inline think markers) would contaminate downstream parsing. Low priority while `think` stays off.
