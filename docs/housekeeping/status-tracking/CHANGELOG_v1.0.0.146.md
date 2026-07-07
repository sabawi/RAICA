# CHANGELOG — RAICA v1.0.0.146

**Date:** 2026-07-07
**Type:** Feature — Deep Research domain-fit paper-source routing (layer A judge)

## Summary
Completes the source↔topic relevance work (layers B + repos already shipped in .144/.145). Before
`published_papers_search` runs in a DR round, an LLM judges the topic's PRIMARY field and routes the search
to the DOMAIN-APPROPRIATE corpora — so a humanities/history query no longer hits the STEM-only databases
(arXiv/PubMed/bioRxiv) that produced the "Byzantine Empire → CS Byzantine-Agreement papers" homonym.

## Changes (`fastapi_server_complete.py`, `config/llm_config.yaml`)
- **`_judge_paper_corpora(user_prompt, generate_stream)`** — LLM domain-fit judge (STEM / HUMANITIES / BOTH),
  returns a `sources` subset for published_papers_search:
  - **STEM** → broad (OpenAlex/Crossref/CORE/Semantic Scholar) + arXiv/PubMed/Europe PMC/bioRxiv
  - **HUMANITIES** → broad + DOAJ/DOAB/Internet Archive (SKIPS arXiv/PubMed/bioRxiv)
  - **BOTH / any error / config-off** → None (search all — fail-open)
  No keyword lists (LLM-Policy Gate). Config: `source_relevance.domain_fit_judge` (default true).
- **`_dr_dispatch`** — for `published_papers_search`, judges the run's domain ONCE (cached), and passes the
  chosen `sources` via JSON args (`execute(**json.loads(args))`). Fail-open: any error → all corpora.

## Verification (local, e2e — the Byzantine DR)
- Layer A logged **`🎯 dr-domain-fit (layer A): HUMANITIES → paper sources=[openalex, crossref, core,
  semantic_scholar, doaj, doab, internet_archive]`** (arXiv/PubMed/bioRxiv correctly excluded), 0 judge errors.
- **The arXiv CS-"Byzantine" homonym papers are gone** — the paper search now returns real academic works
  (e.g. it surfaced "The 7th-Century Restoration of the Acheiropoietos Basilica", genuine Byzantine history).
- Layer B (shadow) now flags residual *topically-broad* matches (crossref/openalex military-strategy papers),
  which is accurate signal for the future B-enforce phase.

## Bug fixed during rollout
- First attempt: `_judge_paper_corpora` raised `name 're' is not defined` (module `re` not in the helper's
  scope) → fell open to all corpora (arXiv still searched). Fixed with a local `import re`; re-verified.

## Risk / rollback
- Fail-open (all corpora on any error); broad cross-disciplinary corpora kept for BOTH so a misjudged STEM
  query still reaches OpenAlex/Crossref/CORE/Semantic Scholar. Reversible: `domain_fit_judge: false`.
  Version → 1.0.0.146. (Minor: on round 1, concurrent paper searches may each run the judge before the cache
  is set — a few redundant 60-token calls; result is deterministic.)
