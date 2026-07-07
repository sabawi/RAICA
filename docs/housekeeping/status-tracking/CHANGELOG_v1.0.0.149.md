# CHANGELOG — RAICA v1.0.0.149

**Date:** 2026-07-07
**Type:** Feature — structural chase_primary + Layer-B judge hardening (over-flag regression fix)

## Summary
Adds the provenance ladder's **chase_primary** (Phase 2): the coverage assessor now drives the gather loop to
find the ORIGIN (primary source) for sub-questions resting only on secondary coverage. During testing this
exposed a **Layer-B regression**: with a large gather (chase pulled 95 URLs), B's single-call relevance judge
OVER-FLAGGED (off_topic=65, including on-topic Wikipedia gang articles), and B-enforce then stripped good
sources → answer destroyed (52/56 unsourced). Fixed here before any deploy.

## Changes
- **`research/engine.py`** + config `source_provenance.chase_primary: true` — coverage assessor gets a
  PRIMARY-SOURCE CHASE directive: for each sub-question judge primary vs only-secondary coverage; for
  secondary-only ones, `needs_more` + a next_query aimed at the primary (name the document/author where
  possible). LLM-judged, no source lists; "do not invent a primary that doesn't exist". Bounded by
  `loop.max_rounds_ceiling`.
- **`research/synthesis.py`** — B relevance judge now **BATCHED (≤18 sources/call) + CONSERVATIVE** ("KEEP
  broad/tangential/background/partial-overlap; flag ONLY clearly-unrelated; when in doubt KEEP"). A single big
  list was making the model over-flag at scale (the root cause). Per-batch fail-safe.
- **`research/pipeline.py`** — B-enforce SAFETY NET: if enforcing would strip >75% of the answer's citations
  (judge over-flag OR junk-heavy gather), SKIP the drop and warn — a thin-but-honest answer beats a
  citation-stripped one. Guarantees no answer destruction regardless of judge error.

## Verification (local, e2e)
- Pre-fix (chase + old B): gangs DR → off_topic=65 (incl. on-topic Wikipedia) → 52/56 unsourced (DESTROYED).
- Post-fix: gangs DR → `off_topic=0/5`, answer intact (5 distinct sources, 16 cites). Grounding tests 3/3.
- Safety net bounds the worst case: over-flag → skip strip → citations kept (never gutted).

## Risk / rollback
- chase_primary reversible (`chase_primary: false`); B-enforce reversible (`source_relevance.shadow: true`).
  Safety net makes B-enforce non-destructive by construction. Version → 1.0.0.149.
