# CHANGELOG v1.0.0.121

**Date:** 2026-06-15
**Previous:** v1.0.0.120 (delivery false-success reporting fix)
**Theme:** **Citation accuracy regression fix** — citations once again point to the SPECIFIC article, not a
publisher homepage / section page that lands on "Page not found." Three defense-in-depth layers.

---

## The regression

In non-Deep-Research paths (news bots and general `search_web` queries), many citation links had stopped
being specific — they pointed to general site/section pages (e.g. `cnn.com/world/middle-east`,
`reuters.com/business/`, a site root) that 404 or land on a generic page. Confirmed root causes (no single
"smoking gun"; it degraded cumulatively, mostly during the Deep-Research source-volume work):

1. `search_web` cited the **raw DuckDuckGo `href` with no validation** — homepages/feeds flowed straight
   through as citations.
2. The news tool's **non-RSS else-branch** emitted `📄 SOURCE: News from cnn.com / 🔗 CITATION URL: <section-url>`
   for HTML section pages in the source list — a bare-name + section-URL pseudo-citation.
3. The news **RSS-empty fallback** cited the **feed URL** when no article URL could be extracted.
4. The synthesis prompt (`primary_model_system_prompt.txt`) had only generic `[Title](URL)` guidance — no
   rule to use the **specific article headline**, to **never use the bare publisher name**, or to avoid
   **homepage/section URLs**.

(Ruled out with evidence: the context-compression engine — it is disabled on the server, so it was not
mangling source blocks.)

## The fix — three layers (defense-in-depth)

**Layer 1 — Source filtering (don't feed general URLs).** `fastapi_server_complete.py`
- `search_web` now gates each DuckDuckGo result through `_validate_article_url` (rejects feeds, bare
  homepages, invalid URLs) **before** fetching — non-article results are skipped, not cited.
- The news non-RSS **section/landing page** branch no longer emits a section-URL citation (it is skipped:
  the configured non-RSS sources are sections, not specific articles; the 30+ real RSS feeds + `search_web`
  supply the citable, specific-article sources).
- The news **RSS-empty fallback** no longer cites the feed URL — it skips (no feed-URL pseudo-citation).
- *Coverage check:* the news config is dominated by real RSS feeds (BBC, Al Jazeera, CBS, NBC, CNBC,
  Bloomberg/Yahoo RSS, …) with real article URLs; only ~5 section pages + Google News (which only ever
  emitted a placeholder block) are skipped — no meaningful coverage loss, verified live.

**Layer 2 — Prompt enforcement (the LLM cites specifically).** `primary_model_system_prompt.txt`
- New "CITATION SPECIFICITY RULES" (policy language — the LLM judges, no code keyword lists): link **text**
  must be the specific **article headline** (never a bare publisher/section name like `[CNN]`/`[Reuters]`);
  the **URL** must be that source block's exact deep link (never a homepage/section/feed); headline and URL
  must come from the **same** source block; a source whose title is a general site/section name is
  **non-citable** background only.

**Layer 3 — Lenient live verification (drop dead links).** `fastapi_server_complete.py` + config
- New `_verify_url_live` / `_filter_live_article_urls` / `_is_homepage_redirect` / `_citation_verify_cfg`.
- **Lenient by design:** a candidate URL is dropped ONLY when verified dead — a hard HTTP **404/410** or a
  redirect that lands on the site **homepage**. Everything else (200/403/paywall/JS shell/429/5xx/timeout/
  connection error) is **kept**, so a valid article that merely bot-blocks us is never dropped (fail-open).
- `search_web` piggybacks on its existing content fetch (no extra request); the news path verifies article
  URLs in **parallel** (bounded latency — ~0.6s for a 4-article BBC feed in testing).
- Config-gated: `deep_research.citation_verify` (`enabled`, `timeout_seconds`, `max_workers`); set
  `enabled: false` to turn the whole layer off.

## Tests (new, deterministic — only the network is faked)
- `tests/integration/test_citation_source_filtering.py` — RSS extracts specific URLs / skips no-URL items;
  section pages not cited; empty feed skipped (no feed-URL citation); valid article cited with its URL.
- `tests/integration/test_citation_link_verification.py` — lenient drop-only-dead (404/410/homepage-redirect),
  keep 403/paywall/5xx/timeout, fail-open on total verifier error, safe config defaults.
- Live sanity verified: BBC world RSS → 4 specific article URLs (0.6s, verify ON); `search_web` → 7
  specific article URLs, 0 homepage/section.

## Files
- `fastapi_server_complete.py` — `search_web` URL validation + dead-link skip; news else-branch / RSS-empty
  skip; Layer-3 helpers + parallel news verification.
- `primary_model_system_prompt.txt` — CITATION SPECIFICITY RULES.
- `config/llm_config.yaml` — `deep_research.citation_verify` block.
- `tests/integration/test_citation_source_filtering.py`, `tests/integration/test_citation_link_verification.py`
  (new), `version.py` (→ 1.0.0.121), this changelog.

## Known follow-ups (not in this commit)
- Google News RSS contributes nothing (its `/rss/articles/...` redirect URLs are rejected by
  `_validate_article_url`); it only ever emitted a placeholder block, so no loss — but recovering it (and
  APNews/ABC section pages) via article-link extraction is a future coverage enhancement.
- The two pre-existing `test_news_citations.py` / `test_web_search_formatting.py` assert an OLD source-block
  format (`"SOURCE BLOCK"`/`"MANDATORY CITATION URL"`) and are already stale vs the current
  `📄 SOURCE:` / `🔗 CITATION URL:` format; refresh them when convenient.

## Status
All three layers implemented and verified (deterministic tests + live news/search sanity, no regression).
**Citation-quality itself is for end-user verification on live** (it depends on real LLM behavior + live
sources).
