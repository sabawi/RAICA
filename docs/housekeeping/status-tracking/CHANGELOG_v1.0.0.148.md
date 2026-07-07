# CHANGELOG — RAICA v1.0.0.148

**Date:** 2026-07-07
**Type:** Feature — Deep Research Layer B ENFORCE (drop off-topic citations)

## Summary
Advances the source↔topic relevance gate (layer B) from shadow → **enforce**. B judges each gathered source's
topical relevance during synthesis; when enforcing, off-topic (homonym/domain-collision) cited sources are now
**dropped** from the answer — link stripped, headline text KEPT (lossless), exactly like fabricated/dead links.

## Changes
- `research/citation_grounding.py`: `ground_citations` gains `off_topic_urls=` → new `off_topic` verdict in
  `_classify`/`_ground_block` + stat (strip link, keep text). Backward-compatible (default None).
- `research/synthesis.py`: synthesize stores B's off-topic URL set on `self._last_off_topic_urls`.
- `research/pipeline.py`: passes `synthesizer._last_off_topic_urls` to `ground_citations` when B is enforcing
  (`source_relevance.shadow: false`); grounding log now reports `off_topic=N`.
- `config/llm_config.yaml`: `source_relevance.shadow: false` (Phase 1 ENFORCE).

## Verification (local, e2e — the gangs DR that had 24/30 off-topic)
- `🔗 citation-grounding [ACTIVE]: fabricated=0 rotted=0 off_topic=24 unsourced=7/13 valid=14` — 24 off-topic
  citations stripped (incl. a BBC football article, SSRN/escholarship STEM), answer now cites only on-topic
  doi.org + Wikipedia (no arXiv/europepmc/sports). Grounding tests 3/3, off_topic-strip unit-verified.
- Exposed (expected): where the paper gather is mostly off-topic, stripping leaves the answer thin (7/13
  paragraphs unsourced) — motivates `chase_primary` (next) to fill the gap with real on-topic primaries.

## Risk / rollback
- Lossless (keeps headline text); reversible via `source_relevance.shadow: true`. Version → 1.0.0.148.
