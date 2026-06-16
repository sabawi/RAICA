# CHANGELOG v1.0.0.125

**Date:** 2026-06-16
**Previous:** v1.0.0.124 (tool selection: search_web for specific-subject news)
**Theme:** **Suppress Google News in favor of search_web** — fixes confusing "every citation points to the
same URL" links in news-bot posts.

---

## Why (the bug)

A live `@raicaNews` post had 15 citation links but only **5 distinct URLs** — four Google News redirect
links (`news.google.com/rss/articles/CBM…`) were each reused across multiple outlet names, e.g. `[PBS]`,
`[CNN]`, `[The New York Times]`, `[Al Jazeera]`, `[The Washington Post]` **all pointed to the same URL**.
Every click in a news item went to the same place. The one real RSS article (`bbc.com/news/articles/…`)
was cited correctly, once — so Google News was the sole cause.

**Root cause:** the v1.0.0.123 change accepted Google News `/rss/articles/…` links as "specific articles."
But those links are story **aggregators** — one shared `google.com` redirect spanning many outlets, whose
"Full Coverage" content lists several publishers. The synthesis model attributes each outlet to the one
shared URL → collapsed, misleading citations (plus a bare `google.com` host, not the publisher).

## Change

`_validate_article_url` (fastapi_server_complete.py) — **reverts the `/rss/articles/` exemption**: all
google-news URLs (article redirects AND feeds) are rejected again. Google News is now SUPPRESSED.

This is safe because **v1.0.0.124 already made `search_web` the path for specific-subject lookups**, and
`search_web` returns clean, specific PUBLISHER URLs (ESPN, FIFA.com, LA Times, …). The autonomous news bots
fall back to the real RSS feeds (BBC, DW, Guardian, Al Jazeera, CBS, NBC, …) which give clean,
one-article-one-URL citations. Net: no reused URLs, no bare `google.com` links, no aggregator confusion —
at the cost of a little breadth that `search_web` now covers.

## Tests
- `tests/integration/test_citation_source_filtering.py`: `test_google_news_urls_suppressed` (was
  `…_accepted_but_feeds_rejected`) now asserts google-news article redirects are REJECTED, real publisher
  article URLs still accepted. All citation/delivery tests green.

## Files
- `fastapi_server_complete.py` — `_validate_article_url` revert.
- `tests/integration/test_citation_source_filtering.py`, `version.py` (→ 1.0.0.125), this changelog.
