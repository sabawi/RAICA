# Changelog — v1.0.0.182

**Date:** 2026-07-12
**Scope:** Deep Research veracity — enforce the **content-quality gate** (`retrieval_gate`), so synthesis never presents *unseen* specifics as sourced. DR initiative #1 (citation grounding), the true veracity lever.

## Changed — `deep_research.synthesis.retrieval_gate` → ENFORCE (`shadow: false`)
- **What it does:** source blocks whose page BODY could not be fetched (paywall/block/extraction-error — "title-only") are annotated `⚠️ BODY-NOT-RETRIEVED` in the evidence the writer sees, and an attribution rule is added to the synthesis prompt: *do NOT attribute any specific fact, quote, statistic, figure, date, or detail to a title-only source; reference it only for the existence of a topic or as further reading.* **Governs ATTRIBUTION, not exclusion** — title-only sources are still usable for background; nothing is dropped.
- **Why (veracity):** previously the synthesizer could pin a specific claim to a source it held only the *headline* of. This ensures a cited specific is backed by content we actually retrieved — directly raising the veracity of cited evidence (the operator's goal for this DR line).
- **Baseline (banked, live shadow logs):** ~10–21 title-only blocks per DR run; the retrieval-audit shows most *cited* URLs are body-fetched (e.g. real=24/29, 23/23, 36/37) — so enforcement is targeted and low-impact on healthy citations.
- **Risk:** low — additive (annotate + one rule), fail-open (`retrieval_gate` "must NEVER break synthesis"), attribution-not-exclusion, and only true no-body 'error' blocks are marked (a short abstract/snippet still counts as content). The enforce path was verified wired (`research/synthesis.py:734–757`, `research/retrieval_quality.py`) — not an inert flag.

## Documented — the misleading `citation_grounding.shadow: true` flag
Investigation found the by-reference grounding (strip a cited URL not in the gathered evidence / now-dead) is **already enforcing** regardless of its `shadow` flag: `pipeline.py` computes `_effective_shadow = shadow AND not verify_live.enforcing`, and `verify_live` enforces (v1.0.0.136), so grounding runs ACTIVE (log: `citation-grounding [ACTIVE] fabricated=… stripped=[…]`). The config flag now documents this so it isn't mistaken for shadow. (No behavior change — clarification only.)

## Validation
- Local: `retrieval-gate [ACTIVE]` on a live DR run; DR benchmark (Tier-1 S2) no-regression; tool smoke green.
- No dependency changes.
