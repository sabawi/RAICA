# CHANGELOG v1.0.0.126

**Date:** 2026-06-16
**Previous:** v1.0.0.125 (suppress Google News)
**Theme:** **Citation grounding — Phase 0 (SHADOW).** Output-side safety net that catches FABRICATED citation
links (the reply-409 failure), deployed in shadow to baseline the live fabrication rate before enforcing.

---

## Why

A live `@Ask` Deep-Research answer cited BBC + Al Jazeera URLs that **404** and that were **never in the
gathered evidence** — the model **fabricated** them. Operator findings narrowed it sharply: the failure is
concentrated on **real-time news** (article URLs have opaque, random IDs the model can't reconstruct, so when
the exact URL is lost upstream it invents one), while **history/science/biography citations are perfect**
(those URLs — wikipedia/papers — are reconstructable). And hot news is volatile: a real, verified URL can be
re-titled/moved/pulled by the provider within minutes (provider "rot", not model error).

Full design rationale + the phased plan: `docs/RAICA_CITATION_GROUNDING_BY_REFERENCE.md`.

## What's in this release (Phase 0 — shadow, zero user impact)

- **`research/citation_grounding.py` (NEW, pure, offline):** `ground_citations(answer, evidence_urls, …)`
  classifies every cited URL against the gathered-evidence set:
  - **FABRICATED** (not in evidence) → strip the link, keep the visible text;
  - **ROTTED** (in evidence but now dead) → distinguished as provider decay, not a lie;
  - **VALID** (in evidence) → kept.
  Plus a per-block **quorum** (flag/drop a block left with 0 valid sources). LOSSLESS when nothing is wrong
  (output == input byte-for-byte); handles HTML and Markdown; `shadow=True` returns the original answer with
  stats only.
- **Wired into the Deep-Research pipeline** (`research/pipeline.py`, after synthesis, before the audit footer)
  in **SHADOW** mode: it logs `🔗 citation-grounding [SHADOW]: fabricated=… rotted=… unsourced=… stripped=…`
  but **does not alter the answer**. Grounding is wrapped so it can NEVER discard a hard-won answer.
- **Config** `deep_research.engine.citation_grounding` (`enabled`, `shadow: true` default, `on_unsourced: flag`).

This Phase exists to **measure the live fabrication rate** before flipping `shadow: false` (enforce). It is a
**no-op on the healthy paths** (wiki/papers/static — every cited URL is in evidence) and only logs on news.

## Not in this release (next, per the phased plan)
- Non-DR primary-path wiring; news-block tightening (one-headline↔one-URL↔one-snippet + ≥2 corroborating
  sources + timestamp); serve-time liveness re-check for rotted detection; flip to enforce after baseline.
- The general synthesis prompt is **deliberately untouched** (operator finding: that path is healthy).

## Tests
- `tests/integration/test_citation_grounding.py` (NEW, 8 cases incl. the reply-409 golden: fabricated
  BBC/Al Jazeera stripped, real Wikipedia kept verbatim; lossless-when-clean; rotted-vs-fabricated;
  normalization; quorum; shadow). All citation/delivery tests green.

## Files
- `research/citation_grounding.py` (new), `research/pipeline.py` (shadow wiring), `config/llm_config.yaml`
  (`citation_grounding` block), `tests/integration/test_citation_grounding.py` (new),
  `docs/RAICA_CITATION_GROUNDING_BY_REFERENCE.md` (proposal), `version.py` (→ 1.0.0.126), `README.md`, this changelog.
