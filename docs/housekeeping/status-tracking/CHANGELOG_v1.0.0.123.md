# CHANGELOG v1.0.0.123

**Date:** 2026-06-15
**Previous:** v1.0.0.122 (Deep Research citation link-text = specific headline)
**Theme:** **Restore Google News coverage** for specific-topic news queries, + a clearer `search_web`
description.

---

## Why

Testing "show me the latest FIFA scores as of now" on the non-DR path returned general UK news, not
football: the tool-calling model used `get_news_summaries`, whose only keyword-search path (Google News)
contributed **nothing** because Google News per-article links (`/rss/articles/…`) were rejected by
`_validate_article_url`'s `/rss` feed indicator (they look like a feed but are specific articles). So
specific-topic news (a team, company, event) couldn't be found via the news tool.

## Changes

1. **Google News article URLs accepted (`_validate_article_url`).** A `/rss/articles/…` URL is now treated
   as a specific article (it resolves, in a browser, to the publisher's page via Google's redirect),
   exempted from the `/rss` feed rejection. All true feeds (`.xml`, `/rss/headlines`, `/rss/search`, other
   `/rss`) are STILL rejected. This is a URL-structure distinction (article path vs feed endpoint), not
   content/intent classification. Verified: a Google News FIFA search went 0 → 4 specific articles
   (e.g. "World Cup 2026 schedule, live updates: … Cape Verde stuns Spain; Belgium, Egypt draw").
   - **Note:** Google News URLs do NOT resolve server-side (JS redirect, confirmed empirically), so the
     cited URL is a `news.google.com/rss/articles/…` link — specific per-article, real headline as link
     text, resolves to the publisher when clicked in a browser, but the visible host is Google's.

2. **`search_web` description clarified** (clean/additive, no aggressive or redirecting language per the
   multi-tool-calling caution): it now states it is for SPECIFIC, CURRENT, or less-common information —
   live scores/results, a specific event/match/person/team/company/product/price/statistic, any precise or
   just-happened fact a broad news-category feed would not surface. (Goal: nudge tool selection toward
   `search_web` for specific lookups. NOTE: in testing this did NOT yet change the model's choice — it still
   picks `get_news_summaries`, which now succeeds via Google News; improving `search_web` *selection* is a
   tracked follow-up.)

## Tests
- `tests/integration/test_citation_source_filtering.py` — added `test_google_news_article_redirect_accepted_
  but_feeds_rejected`. All citation/delivery tests green.

## Files
- `fastapi_server_complete.py` — `_validate_article_url` Google-News exemption; `search_web` description.
- `tests/integration/test_citation_source_filtering.py`, `version.py` (→ 1.0.0.123), this changelog.

## Follow-up (in progress)
- Make the tool-calling model actually reach for `search_web` on specific/uncommon lookups (scope
  `get_news_summaries`' "use for ANY news" description and/or the tool-calling guidance) — gives clean
  publisher URLs and covers topics Google News misses. (User-approved to pursue.)
