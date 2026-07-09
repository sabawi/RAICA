"""
Deterministic unit test for the v1.0.0.158 link-liveness browser-headers fix.

Proves (without hitting the network — `requests_compatible_get` is monkeypatched):
  1. The liveness check now sends a BROWSER-LIKE header set (UA + Accept + Accept-Language),
     not UA-only. Yahoo Finance (and other bot-guarded hosts) gate on the missing
     Accept/Accept-Language and false-404 a UA-only fetch; the browser set flips that to 200.
  2. A URL that the bot-guard serves as 404 to UA-only but 200 to browser-style is classified
     LIVE (the false-negative is cured) — the exact case behind the `[unverified — no working
     source]` tags on DR stock-data blocks.
  3. A genuinely dead page (404 even with browser headers) is still classified DEAD — the
     hard-dead drop rule is preserved (no regression in the drop direction).
  4. A redirect to the site homepage is still classified DEAD (removed/moved article) — the
     homepage-redirect rule still fires under the new headers.

NOTE (CLAUDE.md): this tests the liveness DECISION + header shape only — it does NOT verify
live HTTP. The end-to-end proof is the live multi-stock prompt against the running server
(`[unverified]` count → ~0 while deep links /financials /key-statistics /analysis stay).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import research.link_liveness as ll


class _FakeResp:
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url


def _make_fetch(table):
    """table: dict url -> (status_for_browser_headers, final_url). Returns a fake fetch fn."""
    calls = []

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers or {}})
        entry = table.get(url)
        if entry is None:
            return _FakeResp(200, url)
        status, final = entry
        return _FakeResp(status, final)

    fake_get.calls = calls
    return fake_get


def test_browser_headers_sent():
    """The fetch MUST send Accept + Accept-Language alongside the UA (not UA-only)."""
    fetch = _make_fetch({"https://finance.yahoo.com/quote/PLTR/financials": (200,
                          "https://finance.yahoo.com/quote/PLTR/financials/")})
    orig = ll.requests_compatible_get
    ll.requests_compatible_get = fetch
    try:
        assert ll.verify_url_live("https://finance.yahoo.com/quote/PLTR/financials", reverify=False) is True
    finally:
        ll.requests_compatible_get = orig
    h = fetch.calls[0]["headers"]
    assert "User-Agent" in h, ("missing UA", h)
    assert "Accept" in h, ("liveness must send Accept header", h)
    assert "Accept-Language" in h, ("liveness must send Accept-Language header", h)
    assert "text/html" in h["Accept"], ("Accept must prefer html", h)
    print("PASS test_browser_headers_sent")


def test_bot_guarded_false_404_now_live():
    """A bot-guarded subpage that false-404s under UA-only is now LIVE under browser headers.
    This is the exact case behind the `[unverified — no working source]` tags."""
    # Our liveness check only makes ONE fetch (with browser headers). Under those headers the
    # bot-guard returns 200 → the URL must be classified live.
    fetch = _make_fetch({"https://finance.yahoo.com/quote/PLTR/analysis": (200,
                         "https://finance.yahoo.com/quote/PLTR/analysis/")})
    orig = ll.requests_compatible_get
    ll.requests_compatible_get = fetch
    try:
        assert ll.verify_url_live("https://finance.yahoo.com/quote/PLTR/analysis", reverify=False) is True
    finally:
        ll.requests_compatible_get = orig
    print("PASS test_bot_guarded_false_404_now_live")


def test_genuinely_dead_still_dead():
    """A page that 404s even with browser headers is still DEAD — drop rule preserved."""
    fetch = _make_fetch({"https://finance.yahoo.com/quote/ZZZZZZ/gone": (404,
                         "https://finance.yahoo.com/quote/ZZZZZZ/gone")})
    orig = ll.requests_compatible_get
    ll.requests_compatible_get = fetch
    try:
        assert ll.verify_url_live("https://finance.yahoo.com/quote/ZZZZZZ/gone", reverify=False) is False
    finally:
        ll.requests_compatible_get = orig
    print("PASS test_genuinely_dead_still_dead")


def test_homepage_redirect_still_dead():
    """An article path that redirects to the site homepage is still DEAD (removed/moved)."""
    fetch = _make_fetch({"https://example.com/article/removed-article": (200,
                         "https://example.com/")})  # 200 but lands on homepage
    orig = ll.requests_compatible_get
    ll.requests_compatible_get = fetch
    try:
        assert ll.verify_url_live("https://example.com/article/removed-article", reverify=False) is False
    finally:
        ll.requests_compatible_get = orig
    print("PASS test_homepage_redirect_still_dead")


if __name__ == "__main__":
    test_browser_headers_sent()
    test_bot_guarded_false_404_now_live()
    test_genuinely_dead_still_dead()
    test_homepage_redirect_still_dead()
    print("\n✅ All link-liveness browser-headers tests passed")