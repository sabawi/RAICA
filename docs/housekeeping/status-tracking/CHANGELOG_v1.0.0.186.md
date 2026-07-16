# Changelog — v1.0.0.186

**Date:** 2026-07-16
**Scope:** Deep Research — **Adversarial Balance, Phase 2 / Cluster B (gather quality)**. Makes the *planner* reach PRIMARY peer-reviewed scholarship instead of tertiary wikis/SEO on scholarly/historical/humanities questions, and decompose adversarially. Design: `docs/RAICA_DR_ADVERSARIAL_BALANCE.md`.

## Changed — planner source strategy (`deep_research.engine.planner.gather_quality`, gated, default on)
The planner's prior guidance was a weak, STEM-framed hint that *blessed* wikipedia "for background" and search_web "for general coverage" — which routed the live Jewish-origins gather to **Grokipedia / wikis / advocacy sites** for load-bearing archaeological claims (the "grounded in a user-wiki" weakness), even though the paper-search tool already reaches the right literature. Replaced with a strong, gated directive (policy language, LLM-judged, no hardcoded topic lists):
- For any **scholarly / historical / scientific / humanities** claim — or any request asking for evidence-based/researched/peer-reviewed grounding — route the **load-bearing** sub-questions to `published_papers_search` (**the citation of record**).
- `wikipedia` / `search_web` are for **orientation only**, or where the scholarly literature is genuinely thin — **never** the source of record for a claim the academic literature covers; a tertiary wiki or advocacy/SEO page is not acceptable ground for a load-bearing scholarly claim.
- **Seek the competing models + the historiography** of a debate (rival schools, who argues what on what evidence, how the debate developed), not just the topline finding.
- **Adversarial decomposition:** for a contested / prove-or-disprove / worldview question, add sub-question(s) that deliberately seek the **strongest opposing** and critical scholarship — so the pool isn't one-sided from the start.

## Note — source coverage was already there
`published_papers_search` already searches the full spectrum: STEM (arXiv, PubMed, Europe PMC, bioRxiv) **and** cross-disciplinary/humanities (Semantic Scholar, OpenAlex, Crossref, CORE, DOAJ, DOAB, Internet Archive). The prior "add humanities repos" item was done; this change makes the planner actually **use** them for humanities/history instead of defaulting to wikis.

## Verification
Gating unit (strong directive present on / weak fallback on off) + E2E DR on the live Jewish-origins prompt (credibility mix shifts toward peer-reviewed; the load-bearing archaeology cited to journal literature rather than Grokipedia).

## Next
Cluster B also feeds the assess-loop echo-chamber breakout (P2) and primary-first provenance; Cluster C (deeper genetics/fringe balance). No dependency changes.
