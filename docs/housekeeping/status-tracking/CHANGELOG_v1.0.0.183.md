# Changelog — v1.0.0.183

**Date:** 2026-07-12
**Scope:** Re-baseline the Tier-1 quality benchmark at the current hardened state. Test-data only; no code/behavior change (no server restart).

## Changed — `tests/benchmark/baseline.json` re-captured at v1.0.0.182
- **Why:** the previous baseline was measured at **v1.0.0.131 (2026-06-18)** — 45 versions stale. It predated the citation-specificity hardening, the DR grounding/liveness work, the `retrieval_gate` enforce, and the model/latency gains, so it **false-flagged `S1_news_citation.citation_count` as a REGRESSION on every run**. A baseline that always cries REGRESSION is a cry-wolf risk — it can mask a *real* regression.
- **New baseline:** re-measured against the local v1.0.0.182 server (`--update-baseline --reason …`, a deliberate signed bump; `_meta` records the reason + timestamp). S1/S3 are medians of 3 runs, S2 a single DR run. The suite scores **PASS against itself**.
- **Notable shifts vs the v131 baseline:** `S1 citation_count` 12 → **10** (median-of-3; specificity now 100% vs 83%), DR latencies reflect the current pro-model path (`dr_synthesize_s` 71.6 → 23.2, `dr_verify_s` 82.6 → 20.8, `dr_latency_s` 230 → 265), vision faster.
- All CODE invariants unchanged (`vision_ran`, `dr_completed`, `attachment_count=2`, `pdf_valid`, `html_self_contained`, `doc_title_is_section=False`).

## No code / config / dependency changes.
