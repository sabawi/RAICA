# CHANGELOG — RAICA v1.0.0.143

**Date:** 2026-07-06
**Type:** Follow-ups to v1.0.0.142 — harden the non-DR `fabricated` shadow signal + delete the retired keyword classifier

## 1. Non-DR citation shadow: fix `fabricated` false positives
The Phase-0 non-DR shadow was flagging **real, in-tool, resolving** URLs as `fabricated` — it compared cited
vs evidence URLs including query strings, but the news tool returns article URLs with tracking params
(`?traffic_source=rss`, `utm_*`) while the model cites the CLEAN URL. Same article, different query → false
"not in evidence".
- `research/nondr_citation_audit.py`: added `_norm_match` (scheme + host-without-`www` + path, **no query /
  fragment**) and use it for the evidence set, reuse grouping, and the fabricated check. A news article is
  identified by host+path; distinct articles never share one, so this removes the false positives with no risk
  of false negatives. Dropped the now-unused `normalize_url` import.
- `tests/integration/test_nondr_citation_audit.py`: +1 test (`traffic_source`/`utm`/`www`/trailing-slash all
  match) — suite **6/6**.
- Verified live-shape: an ME news query that previously logged `fabricated=4` (all real URLs) now logs
  `fabricated=0`.

## 2. Delete the retired hardcoded keyword news-classifier
v1.0.0.142 replaced the keyword classifier with LLM-driven category selection but left the old code as dead
code. Now removed:
- `fastapi_server_complete.py`: deleted **305 lines** — `ENHANCED_CATEGORY_MAPPING` + `find_category_intelligent`
  + `find_category` + `find_categories_ranked` + `find_keyword_sources` (all no longer invoked). `get_union_sources`
  (still used, maps LLM-chosen categories → RSS URLs) preserved.
- `config/news_sources.yaml`: deleted **386 lines** — the inert `category_mapping` (primary_terms /
  compound_phrases / weights / fallback_categories) and `keyword_mappings` sections. The file is now RSS source
  lists only (12 categories, unchanged); the category names are the LLM's selection whitelist. Header updated.

## Verification
- Syntax OK; `test_nondr_citation_audit.py` 6/6.
- Restart clean (health 200, 0 startup errors). `get_news_summaries` fully functional after the deletion:
  ME query → LLM selects `['world']`, `Starting news fetch: 1 categories, 2 Google News feeds, 11 other RSS
  sources`, shadow `cited=7 distinct=7 fabricated=0 reuse=0 bare_homepage=0`.

## Risk / rollback
- No behavior change vs .142 (LLM-driven selection already active there); this only removes dead code + fixes a
  shadow (log-only) false positive. Version → 1.0.0.143.
