# CHANGELOG — RAICA v1.0.0.142

**Date:** 2026-07-06
**Type:** Fix (news gathering) — retire the keyword news-classifier + fix Middle-East misrouting + section guard

## Summary
Root-caused why `@raicaMiddleEast` cited generic/reused/section URLs while `@raicaFinance` was perfect —
**same code, a config relic + a tool asymmetry.** Three compounding defects, all fixed here:

- **A — hardcoded keyword news-classifier retired (policy-gate violation).** `get_news_summaries` selected RSS
  source categories with a hardcoded keyword→category scorer (`find_categories_ranked` / `find_keyword_sources`
  / `ENHANCED_CATEGORY_MAPPING`, mirrored in `news_sources.yaml`). Replaced with **LLM-driven category
  selection** (`_select_news_categories_llm`): the LLM picks the relevant categories from the query (no keyword
  lists, no scoring). Runs in the event loop before the sync executor task; **fails safe** to a broad
  general-news default (never empty, never the old classifier). The old classifier functions are left as
  dead code (no longer invoked) for a trivial revert; a follow-up will delete them.
- **B — `middle east` miscategorized as a `finance` keyword.** `news_sources.yaml` listed `middle east` as a
  **finance** `compound_phrase` (highest scoring tier), so every Middle-East query scored finance (2.7) over
  world/geo (1.35) and pulled **finance** RSS feeds. Removed it. Also cleaned non-RSS section/homepage entries
  from the `world` source list (`apnews.com/world-news`, `alarabiya` homepage, `bbc.com/news/world/middle_east`,
  `eurasianet.org` homepage) — the news tool only skips them.
- **C — search_web section/landing-page guard.** `get_news_summaries` already refuses non-article section
  pages, but `search_web` only used `_validate_article_url` (which **passes** sections like
  `bbc.com/news/world/middle_east`). Added `_is_specific_article_url` — a **structural** article-vs-section
  shape test (path must carry a date / story-id / multi-word slug; no keyword list) — applied in search_web,
  config-gated (`non_dr.search_article_guard.enabled`, default on, reversible).

## Verification (local, e2e)
- **A:** Middle-East query → LLM picks `['world']` (was misrouted to finance); Finance query → `['finance',
  'business', 'economy']` (**no regression**).
- **C:** 5 section/landing result URLs skipped by search_web on the ME query.
- **Shadow:** ME reuse **4→0**, bare_homepage **2→0**. ME response now cites **6 specific, real (all HTTP 200),
  Middle-East-relevant articles** (Macron-in-Syria, NATO summit, Sudan, quakes) — no sections, no reuse.
  Finance response clean (cited=8, fabricated=0, reuse=0).
- **Shadow finding (for Phase 1):** the non-DR `fabricated` signal has FALSE POSITIVES — 4 real, resolving,
  in-tool URLs were flagged (normalization/extraction gap). MUST be hardened before enforcing "strip
  fabricated". Reuse/bare-homepage signals are accurate.

## Config
- `config/llm_config.yaml`: `non_dr.search_article_guard.enabled: true`.
- `config/news_sources.yaml`: removed `middle east` from finance; cleaned `world` non-RSS sources.

## Risk / rollback
- A fails safe (broad default) on LLM failure; old classifier still present (one-line revert of the call site).
- C is config-reversible. B is data-only. Version → 1.0.0.142.
