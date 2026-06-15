"""
Unit tests for Layer 3 (lenient live link verification) of the citation-accuracy fix.

Verifies the LENIENT contract: a candidate citation URL is dropped ONLY when verified dead (hard
404/410 or a redirect to the site homepage). Everything else — 200, 403, 401, 429, 5xx, timeouts,
connection errors — is KEPT, so a valid article that merely bot-blocks us is never dropped.

Only the network call (requests_compatible_get) is faked.

Run: python -m pytest tests/integration/test_citation_link_verification.py -q
 or: python tests/integration/test_citation_link_verification.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import fastapi_server_complete as F

_ORIG_GET = F.requests_compatible_get


class _FakeResp:
    def __init__(self, status, final_url):
        self.status_code = status
        self.url = final_url
        self.ok = 200 <= status < 400


def _set(fn):
    F.requests_compatible_get = fn


def _restore():
    F.requests_compatible_get = _ORIG_GET


def test_homepage_redirect_detection():
    assert F._is_homepage_redirect("https://site.com/news/article-123", "https://site.com/") is True
    assert F._is_homepage_redirect("https://site.com/news/article-123", "https://other.com") is True
    assert F._is_homepage_redirect("https://site.com/news/article-123",
                                   "https://site.com/news/article-123") is False
    assert F._is_homepage_redirect("https://site.com/", "https://site.com/") is False  # orig had no path


def test_verify_url_live_lenient():
    art = "https://site.com/news/world-middle-east-123"
    try:
        _set(lambda u, **k: _FakeResp(404, u));                 assert F._verify_url_live(art) is False  # gone
        _set(lambda u, **k: _FakeResp(410, u));                 assert F._verify_url_live(art) is False  # gone
        _set(lambda u, **k: _FakeResp(200, "https://site.com/")); assert F._verify_url_live(art) is False  # → home
        _set(lambda u, **k: _FakeResp(200, u));                 assert F._verify_url_live(art) is True   # ok
        _set(lambda u, **k: _FakeResp(403, u));                 assert F._verify_url_live(art) is True   # bot-block → keep
        _set(lambda u, **k: _FakeResp(401, u));                 assert F._verify_url_live(art) is True   # paywall → keep
        _set(lambda u, **k: _FakeResp(500, u));                 assert F._verify_url_live(art) is True   # server err → keep
        def _boom(*a, **k):
            raise Exception("network down")
        _set(_boom);                                            assert F._verify_url_live(art) is True   # transient → keep
        assert F._verify_url_live("not-a-url") is False
    finally:
        _restore()


def test_filter_live_batch_drops_only_dead():
    def fake(u, **k):
        return _FakeResp(404, u) if "dead" in u else _FakeResp(200, u)
    try:
        _set(fake)
        urls = ["https://s.com/news/good-1", "https://s.com/news/dead-2", "https://s.com/news/good-3"]
        kept = F._filter_live_article_urls(urls, timeout=3, max_workers=4)
        assert "https://s.com/news/good-1" in kept
        assert "https://s.com/news/good-3" in kept
        assert "https://s.com/news/dead-2" not in kept
    finally:
        _restore()


def test_filter_live_batch_fail_open_on_total_error():
    def boom(*a, **k):
        raise Exception("everything down")
    try:
        _set(boom)
        urls = ["https://s.com/news/a-1", "https://s.com/news/b-2"]
        kept = F._filter_live_article_urls(urls, timeout=2, max_workers=4)
        assert kept == set(urls), "on verifier failure, KEEP all (fail-open, never drop everything)"
    finally:
        _restore()


def test_config_defaults_safe():
    cv = F._citation_verify_cfg()
    assert set(cv.keys()) == {"enabled", "timeout", "max_workers"}
    assert isinstance(cv["enabled"], bool) and cv["timeout"] > 0 and cv["max_workers"] >= 1


if __name__ == "__main__":
    test_homepage_redirect_detection();             print("PASS: homepage-redirect detection")
    test_verify_url_live_lenient();                 print("PASS: verify_url_live lenient (drops only dead)")
    test_filter_live_batch_drops_only_dead();       print("PASS: batch drops only dead")
    test_filter_live_batch_fail_open_on_total_error(); print("PASS: batch fail-open on total error")
    test_config_defaults_safe();                    print("PASS: config defaults safe")
    print("ALL TESTS PASSED")
