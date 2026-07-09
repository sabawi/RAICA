"""
Link liveness — LENIENT, empirical citation-URL verification (no keyword/domain lists).

Shared home for the live-link check so BOTH the non-DR gather path (fastapi_server_complete.py) and the
Deep-Research output path (research/pipeline.py) use ONE definition — avoiding a circular import
(`research/` must not import `fastapi_server_complete.py`). Depends only on `requests_compatible_get`
(http_helpers) + stdlib.

Policy (stated ONCE here, reused everywhere): drop a candidate citation URL ONLY when it is *verified dead*
— a hard HTTP 404/410, or a redirect that lands on the site homepage (article path → bare root = removed/
moved). Everything else — 200, 401/403 (bot-block/paywall), 405, 429, 5xx, JS shells, timeouts, connection
errors — is KEPT, so a valid article that merely blocks crawlers is never dropped. This is empirical
verification, NOT URL pattern-matching.

Moved verbatim (behavior-preserving) from fastapi_server_complete.py in v1.0.0.134; see
docs/RAICA_DR_CITATION_LIVENESS.md.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

from http_helpers import requests_compatible_get


def is_homepage_redirect(orig_url: str, final_url: str) -> bool:
    """True if a URL that HAD a real article path redirected to the site HOMEPAGE (empty/'/' path) —
    a strong, generic signal the article was removed/moved ('page not found → sent to home'). Same-host
    only is not required: a cross-host redirect to a bare homepage is still a dropped article."""
    try:
        o = urlparse(orig_url or "")
        f = urlparse(final_url or "")
        return bool((o.path or "").strip("/")) and (f.path or "").strip("/") == ""
    except Exception:
        return False


def verify_url_live(url: str, timeout: float = 6.0, reverify: bool = True) -> bool:
    """LENIENT liveness check for a candidate citation URL. Returns False (DROP) ONLY for a hard 404/410
    or a redirect to the site homepage; returns True (KEEP) for everything else — 200, 403, 401, 405,
    429, 5xx, paywalls, JS shells, timeouts, connection errors — so a valid article that merely blocks
    bots/crawlers is never dropped. This is empirical verification, not URL pattern-matching.

    reverify=True: a DEAD verdict is CONFIRMED with one more fetch (after a short pause) before it counts
    — a valid article can momentarily 404 (CDN/rate-limit flaps), and a citation must NEVER be stripped
    on a transient blip. A URL is declared dead only if it is dead on BOTH checks. Live URLs cost one
    fetch (no re-verify); only the rare dead-looking URL pays the second."""
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    def _one_check() -> bool:
        try:
            # Browser-like header set (v1.0.0.158). A UA-only fetch gets false-404'd by bot-guards
            # (e.g. Yahoo Finance deep-link subpages /financials, /key-statistics, /analysis) that
            # gate on the missing Accept / Accept-Language a real browser always sends. Sending the
            # full browser header set flips those false-404s to the true 200 a human sees, so a
            # genuinely-live citation is never stripped. A TRULY dead page still 404/410s regardless
            # of headers, so the hard-dead drop rule is unaffected. No domain list / special-casing —
            # this is a general "fetch like a browser" improvement (CLAUDE.md LLM-Policy Gate compliant).
            resp = requests_compatible_get(url, timeout=timeout, allow_redirects=True, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                               '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            })
            status = getattr(resp, "status_code", 0)
            final_url = getattr(resp, "url", "") or url
            if status in (404, 410):
                return False
            if is_homepage_redirect(url, final_url):
                return False
            return True
        except Exception:
            # Transient/blocked → lenient KEEP (never drop a possibly-valid article on a network hiccup).
            return True

    if _one_check():
        return True
    if not reverify:
        return False
    time.sleep(0.7)          # let a transient CDN/rate-limit flap clear before confirming dead
    return _one_check()      # dead only if the SECOND check also fails


def filter_live_article_urls(urls, timeout: float = 6.0, max_workers: int = 8):
    """Verify a batch of candidate article URLs in PARALLEL and return the set that are KEPT (live).
    Lenient: a URL is dropped ONLY when verify_url_live explicitly returns False (verified dead); a URL
    that errors or doesn't complete in time is KEPT. Bounded latency: ~one `timeout` window per batch."""
    urls = [u for u in (urls or []) if u]
    if not urls:
        return set()
    dropped = set()
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as ex:
            futs = {ex.submit(verify_url_live, u, timeout): u for u in urls}
            for fut in as_completed(futs, timeout=timeout + 5):
                u = futs[fut]
                try:
                    if fut.result(timeout=1) is False:
                        dropped.add(u)   # verified DEAD (hard 404/410 or homepage-redirect) → drop
                except Exception:
                    pass                 # didn't verify in time / error → lenient KEEP
    except Exception:
        # Batch verifier itself failed → KEEP everything (fail-open — never silently drop all sources).
        return set(urls)
    return set(u for u in urls if u not in dropped)
