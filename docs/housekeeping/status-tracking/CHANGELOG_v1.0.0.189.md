# Changelog — v1.0.0.189

**Date:** 2026-07-17
**Scope:** Deep Research — the paired **Cluster-B / veracity** increment, completing Cluster B: (a) the assess-loop **source-quality breakout** gets the *right sources* on scholarly topics, and (b) **academic-abstract retrieval** gives those sources *groundable content* so the quality gain becomes *verified* claims (not prestigious-but-ungrounded DOIs). Design: `docs/RAICA_DR_ADVERSARIAL_BALANCE.md`.

## Changed — (1) assess-loop SOURCE-QUALITY breakout (`engine.py _assess` + `_coverage_summary`)
Gated by `deep_research.engine.planner.gather_quality`. The coverage assessor previously judged only *coverage*, so on a narrative history topic with thin journal coverage it declared "sufficient" over a popular/low-cred pool (Nicaea run: peer_reviewed 3, popular 15). Now:
- `_coverage_summary` exposes each block's source **domains** (up to 4) so the assessor can judge source *quality*.
- `_assess` gains a **SOURCE-QUALITY BREAKOUT** directive (policy language, LLM-judged): on a scholarly/historical/scientific/humanities topic, if a load-bearing sub-question rests on popular/tertiary sources and lacks peer-reviewed/reputable scholarship (esp. nothing via `published_papers_search`), set `needs_more` and add a next_query that upgrades quality. Bounded by `max_rounds`; not applied to current-events/quantitative-data/company topics.

## Changed — (2) academic-abstract retrieval (`published_papers_search_tool.py`)
`published_papers_search` extracted paper abstracts but **truncated them to 200 chars** (~2 sentences) across all 11 backends. That teaser can't ground a paper's findings, so the writer backfilled specifics from memory — surfaced when (1) pulled more academic DOIs (validation run: 38% of claims unverified, flagged as *"sources lack abstracts or full text"*). Raised the cap to **1800 chars** (`_ABSTRACT_MAX`, 16 truncation sites) so the **full abstract** — the groundable content — reaches the writer, and the citability-requires-retrieval rule (v1.0.0.188) has real content to bind claims to.

## Why paired
(1) alone traded low-cred-but-retrievable sources for peer-reviewed-but-metadata-only DOIs — better sources, *worse* groundedness (unverified-claim rate up). (2) closes that gap so the quality win yields **verified** claims. Held (1) until (2) was ready (operator decision).

## Verification
Unit: coverage summary renders domains; breakout directive gated; abstract cap raised (0 remaining 200-char truncations; syntax clean). E2E DR on the research-framed Nicaea prompt — expect the improved credibility mix to HOLD while the unverified-claim rate drops (fuller abstracts to ground claims in).

## Cluster B complete
Planner primary-source routing (v186) + citability-requires-retrieval (v188) + this paired increment (v189). No dependency changes.
