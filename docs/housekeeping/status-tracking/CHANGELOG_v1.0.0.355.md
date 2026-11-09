# CHANGELOG v1.0.0.355 — 2026-11-09

## SI-116: search, news and citation checks reach only the public internet

1.0.0.354 put `lookup_website` and `fetch_image` behind `utils/public_fetch.py`. The other fetchers of URLs that the
web or a model chooses still used the shared pooled client with no address check. Owner: "go ahead with SI-116, guard
the other fetchers too". Design: `docs/DESIGN_fetch_image_and_public_fetch.md` §7.

### Reproduced first (tests/utilities/test_si116_fetchers_public_only.py, on 1.0.0.354)
A loopback-only service, pointed at by a stubbed search result, a feed address and a citation:
- `search_web` fetched the internal page (1 request reached it);
- the news feed reader (`_get_news_content_with_article_urls`) fetched the internal feed;
- `research/link_liveness.verify_url_live` requested the internal address and KEPT it as a live citation.

### Security — moved to `utils/public_fetch`
- `search_web` page extraction (`get_text_from_url_simplified`): a refused address is a failed fetch, so the source is
  dropped and counted, as any other failure is. A DNS failure (`HostUnresolved`) counts as transient.
- `get_news_summaries`: the feed reader `_get_news_content_with_article_urls`, and the nested `get_text_from_url`
  (not called today; guarded so it is safe if it is).
- `research/link_liveness.verify_url_live` (non-DR news and search, Deep Research output): a cited non-public address
  is never requested and is DROPPED, since no reader can open it. A host that does not resolve is KEPT, as before.
  The check now reads only the status and final address (`stream=True`, closed unread).
- Removed `lookup_website_old`: unreferenced since `lookup_website` replaced it, and its fetches were unguarded.

### Kept — connection retries
The pooled session retried failed connections 3 times (`http_helpers`, `max_retries=3`). `public_fetch` now does the
same: `public_fetch.connect_retries` (3). A refusal is not a connection error, so it is never retried (test).

### Added — `public_fetch.HostUnresolved`
A subclass of `PublicFetchRefused` for a name that does not resolve: not known to be internal, only unreachable now.
lookup_website and fetch_image treat it as before (a refusal with the reason).

### Not changed (checked, not model- or web-chosen)
`datasources/discovery.py` and `declarative_adapter.py` (configured API bases, FRED/World Bank), the academic paper
clients (fixed API endpoints), `sec_edgar_client` (SEC endpoints). `utils/enhanced_rss_processor.py` fetches article
URLs but nothing in the server imports it (tests only).

### Tests
- New: `tests/utilities/test_si116_fetchers_public_only.py` (6): the three reproductions, the lenient DNS case, a
  positive control (loopback counted public → the same calls reach the service), and an AST guard (no direct client
  in the three server functions, `lookup_website_old` absent, link_liveness on `public_fetch.get`).
- `test_public_fetch.py`: + retries from config, refusal not retried (24).
- Moved to the `utils.public_fetch.get` seam (same assertions; fakes gained `close()`):
  `test_dr_liveness_headers.py`, `test_dr_citation_liveness.py`, `test_citation_link_verification.py`,
  `test_citation_source_filtering.py` (now restores the patch after each test).

### Evidence
- Planted defects, each RED, restored from disk and `cmp`-checked: link_liveness on plain requests; link_liveness
  keeping a refused address; search_web on the pooled client; news reader on the pooled client; retries dropped.
- Real network, no model: a DuckDuckGo search extracted page text from real results; the BBC world feed gave 4
  articles; liveness kept a live Open Library page, dropped a real 404, dropped `http://169.254.169.254/…` without
  requesting it, kept an unresolvable host. A skipped GitHub result was a real 404 with both clients.
- Real entry point (local server, `/v1`, one request needing news and search): the model called get_news_summaries
  and search_web; 4 feeds fetched (BBC, Guardian, Al Jazeera, DW); the answer cited 22 article URLs. No fetch failure.
- `make smoke` passed; Tier 0 10/10.

### Config
`config_migrate` adds `public_fetch.connect_retries` to an existing site file (addition, config_version unchanged).
