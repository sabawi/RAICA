# CHANGELOG — RAICA v1.0.0.144

**Date:** 2026-07-07
**Type:** Feature (shadow) — Deep Research SOURCE↔TOPIC relevance gate, Phase 0 (layer B)

## Summary
Post 5589 (a medieval-history DR: "why did the Byzantine Empire lose to Khalid ibn al-Walid… primary
sources") cited 8 real, live, in-evidence arxiv papers — 7 of them **computer-science** papers on the
"Byzantine Generals Problem" / Byzantine fault tolerance, a **homonym** of the Byzantine *Empire*. Liveness +
grounding passed them (real + in-evidence); nothing checked **topical relevance**. Root cause: DR reaches for
`published_papers_search` on "scholarly" queries, but its corpora (arXiv, PubMed, bioRxiv, Europe PMC) are
STEM/biomedical — a humanities topic has zero coverage, so the search returns homonyms/noise, and there is no
gate to reject off-topic sources.

This ships **layer B (SOURCE↔TOPIC relevance gate), Phase 0 = SHADOW**: an LLM judges whether each gathered
source (by title) is actually ABOUT the request, or only a keyword/homonym match. Log-only; zero answer change.
(Layer A — a pre-search domain-fit judge that routes humanities queries away from STEM corpora — is next, and
pairs with adding humanities repositories: OpenAlex, Crossref, CORE, DOAB, Internet Archive.)

## Changes
- **`research/synthesis.py`**: new `_grade_relevance_shadow(user_request, evidence)` + `_log_source_relevance_shadow`,
  mirroring the provenance shadow. Extracts (title, url) from evidence content source blocks and asks the LLM
  which sources are OFF-TOPIC (judge by MEANING, not word overlap — explicitly names the Byzantine-Empire /
  Byzantine-Generals and Mercury-planet / mercury-toxicity homonyms as examples). Wired into `synthesize` right
  after credibility grading, gated by `_source_relevance_on`, fail-open. No keyword lists (LLM-Policy Gate).
- **`config/llm_config.yaml`**: `deep_research.engine.synthesis.source_relevance {enabled: true, shadow: true}`.
- **`docs/RAICA_DR_SOURCE_RELEVANCE.md`**: design (layers A + B, rollout, the humanities-repo plan, the
  Semantic-Scholar-429 / arXiv-500 infra notes).

## Verification (local, e2e)
- Restart clean (health 200, 0 errors). Byzantine DR (`deep_research:true`, papers allowed) logged
  **`🎯 dr-source-relevance [SHADOW]: off_topic=15/15`** — all 15 gathered arxiv STEM papers (neutron stars,
  gamma-ray bursts, electroweak, plasma, military simulations) correctly flagged off-topic for a Byzantine
  history question. Answer unchanged (shadow).
- Title/URL extraction unit-checked against a real paper source block.

## Rollout / risk
- Phase 0 shadow: log-only, fail-open (any judge error → no-op). Disable via
  `source_relevance.enabled: false`. Phase 1 will drop off-topic sources from the citable set (keep the
  answer text). Version → 1.0.0.144.
