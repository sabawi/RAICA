# CHANGELOG v1.0.0.67

**Date:** 2026-06-02
**Previous:** v1.0.0.66
**Trigger:** Deep Research — enumeration completeness (two-pass) + critical token/context bug fixes

---

## Summary

Fixes enumeration-completeness gaps (list/table/"earliest" requests that dropped qualifying items) via a two-pass roster approach, and resolves a cluster of token-budget/context bugs uncovered during testing — including one that had been silently disabling all research output-length config since v1.0.0.65. Verified end-to-end: a "earliest Near East civilizations" table now enumerates the full set (Neolithic through the major empires) with complete depth AND a working accuracy audit (115 claims checked, vs 0 before the fixes).

---

## New Features

- **Two-pass enumeration completeness:** for LIST / TABLE / ENUMERATE / "earliest|all|every" requests, the synthesizer now:
  1. **Detects** the enumeration intent (LLM, config-gated `synthesis.enumeration_two_pass`).
  2. **Extracts the complete item roster** from a *breadth-first* view of ALL gathered sources (a bounded slice of every source) BEFORE the depth-oriented token budget can truncate boundary items.
  3. **Injects the roster** into synthesis as a required checklist ("produce a row for EVERY item").
  - Fully fail-safe: non-enumeration requests (or any detection/extraction failure) return `roster=None` and take the **byte-identical** existing single-pass path — no behavior change for prose/analysis queries.
  - Result: a "earliest civilizations" table went from ~6 rows (later empires only) to the full ~13–25 row set including the genuinely-earliest Neolithic cultures (Natufian, PPN, Hassuna, Samarra, Halaf, Ubaid…).
- **Planner enumeration awareness:** the planner now adds a sub-question to discover the COMPLETE roster of qualifying items (esp. boundary/less-famous cases) for list/table requests, so the gather phase pulls the full set.
- **Synthesis enumeration directive:** explicit "completeness = BREADTH OF ITEMS (rows), not depth on a few", "MATCH THE SCOPE QUALIFIER EXACTLY", "mine evidence for every qualifying item incl. ones mentioned in passing", "populate every column for every row ('unknown' if absent)".

## Critical Fixes (found during testing)

- **`max_tokens` was silently ignored on the Ollama path (latent since v1.0.0.65):** the Ollama provider reads only `num_predict`, but the research calls passed `max_tokens` — so ALL research output-length config (`max_answer_tokens`, `verify max_tokens`) was a no-op, every call falling back to the model default (16384). Fixed at the single chokepoint `research/engine._collect_stream`, which now maps `max_tokens → num_predict` (OpenAI/Gemini still read `max_tokens`; safe across providers). Verified live (`num_predict=321` from `max_tokens=321`).
- **Verification context-window starvation → 0 claims:** verify sent the answer + the FULL ~110K-token evidence document = ~125K input, leaving only ~5K of the 131K window for output, so the claim JSON truncated and parsing returned 0 claims. Fixed: verify now uses a SEPARATE, smaller evidence budget (`verification.evidence_token_budget: 60000`), leaving ~59K output room. Result: 0 → 115 claims on the same large table.
- **Verification all-or-nothing parsing:** a truncated verify JSON discarded the entire audit. Added `_salvage_claim_objects()` — recovers every COMPLETE claim object from a JSON cut off mid-array, so verify never returns 0 on a long answer.
- **YAML structure fix:** restored the `verification:` section header (an edit had collapsed it, orphaning verify config under `synthesis`). All 8 engine sections now nest correctly.

## Verification (live)

"Deep research — comprehensive table of the earliest Near East civilizations (Name, dates, age, location, …)":
- `📋 Enumeration detected: 13 … (earliest in the Near East) — roster extracted` (`roster` cost 4.6s)
- Synthesis 33K chars / 53% of cap (complete + deep); distinct budgets visible (synthesize ~110K evidence, verify ~61K)
- **Verified 115 claims: {supported: 104, unverified: 11}** — the most discriminating audit yet; the 11 unverified are thin-evidence boundary cells, surfaced in the ⚠️ scrutinize section
- User confirmed: completeness + depth achieved, nested-bullet formatting honored. (Total 498.7s; verify is now the dominant phase at 213s — the cost of a thorough audit on a large table.)
- Non-enumeration queries unaffected (roster=None → unchanged path; verified separately).

## Known / Follow-ups

- **Enumeration sort order** is not specified, so item ordering varies (by start date vs end date vs salience). Minor; a future tweak can pin chronological-by-start ordering in the enumeration prompt.
- Roster size varies run-to-run with the gathered evidence (6→25→13 across runs); inherent to evidence-driven extraction.
- Deep-research total time on large enumerations is high (~8 min), dominated by exhaustive verification.

## Dependencies

- None new.

## Migration

- None required. New config under `deep_research.engine`: `synthesis.enumeration_two_pass` (default true), `verification.evidence_token_budget` (default 60000). Set `enumeration_two_pass: false` to disable two-pass.

## Files

- `research/synthesis.py` — two-pass roster (`_extract_roster`, `_breadth_first_snippets`), separate verify evidence budget, salvage parser, enumeration synthesis directive
- `research/engine.py` — `_collect_stream` max_tokens→num_predict mapping; planner enumeration awareness
- `config/llm_config.yaml` — `enumeration_two_pass`, `verification.evidence_token_budget`, `verification.max_tokens`; restored `verification:` header
- `version.py` (→ 1.0.0.67), `README.md`, this changelog
