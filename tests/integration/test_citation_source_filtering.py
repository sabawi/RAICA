"""
Regression tests for citation source filtering (Layer 1 of the citation-accuracy fix).

Guards that:
  * the RSS path still extracts SPECIFIC article URLs and skips items without a valid URL,
  * a non-RSS section/landing page is NOT cited (returns no source block), and
  * an RSS feed that yields no citable article is skipped (no feed-URL pseudo-citation),
  * _validate_article_url still rejects feeds / bare homepages and accepts real article URLs.

These hit the real functions in fastapi_server_complete; only the network fetch is faked.

Run: python -m pytest tests/integration/test_citation_source_filtering.py -q
 or: python tests/integration/test_citation_source_filtering.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import fastapi_server_complete as F


class _FakeResp:
    def __init__(self, text, content_type, status=200):
        self.text = text
        self.headers = {"content-type": content_type}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def _patch_fetch(resp):
    F.requests_compatible_get = lambda *a, **k: resp


def test_validate_article_url_baseline():
    assert F._validate_article_url("https://www.bbc.com/news/world-middle-east-67890123")
    assert not F._validate_article_url("https://feeds.bbci.co.uk/news/world/rss.xml")   # feed
    assert not F._validate_article_url("https://x.co")                                   # too short / bare
    assert not F._validate_article_url("not-a-url")
    assert not F._validate_article_url("")


def test_google_news_urls_suppressed():
    # Google News is SUPPRESSED in favor of search_web (v1.0.0.125): ALL google-news URLs are rejected —
    # the article redirects (/rss/articles/…) AND the feeds (/rss/headlines, /rss/search) — because the
    # /rss/articles/ redirects are story AGGREGATORS that collapse many outlets onto one shared google.com
    # URL (confusing "every citation points to the same URL" links). Real publisher article URLs are kept.
    assert not F._validate_article_url("https://news.google.com/rss/articles/CBMiYkFVX3lxTFBRb1lveXZVdjZ")
    assert not F._validate_article_url("https://news.google.com/rss/headlines/section/topic/WORLD")
    assert not F._validate_article_url("https://news.google.com/rss/search?q=fifa")
    assert not F._validate_article_url("https://www.theguardian.com/world/rss")
    assert F._validate_article_url("https://www.bbc.com/news/articles/cd0p8me2m5do")


def test_rss_extracts_specific_urls_and_skips_no_url_items():
    rss = ('<?xml version="1.0"?><rss><channel>'
           '<item><title>Ceasefire reached after talks</title>'
           '<link>https://www.bbc.com/news/world-middle-east-67890123</link>'
           '<description>Story.</description></item>'
           '<item><title>Has no usable link</title><guid>not-a-url</guid>'
           '<description>x</description></item>'
           '</channel></rss>')
    arts = F._parse_rss_articles(rss, "https://feeds.example.com/rss.xml", max_articles=5)
    assert len(arts) == 1, "the item without a valid URL must be skipped"
    assert arts[0]["url"] == "https://www.bbc.com/news/world-middle-east-67890123"


def test_non_rss_section_page_is_not_cited():
    _patch_fetch(_FakeResp("<html><body>AP Top News section listing</body></html>", "text/html"))
    content, n = F._get_news_content_with_article_urls("https://apnews.com/hub/ap-top-news", 1)
    assert n == 0 and content.strip() == "", "a section/landing page must not be cited"


def test_rss_feed_yielding_no_article_is_skipped_not_feed_cited():
    # RSS that parses but has no item with a valid URL → must skip, NOT cite the feed URL.
    rss = ('<?xml version="1.0"?><rss><channel>'
           '<item><title>Only a relative or junk link</title><guid>xyz</guid></item>'
           '</channel></rss>')
    _patch_fetch(_FakeResp(rss, "application/xml"))
    content, n = F._get_news_content_with_article_urls("https://news.google.com/rss/search?q=x", 1)
    assert n == 0 and content.strip() == "", "must not fall back to citing the feed URL"
    assert "news.google.com/rss" not in content


def test_rss_feed_with_valid_article_is_cited_with_specific_url():
    rss = ('<?xml version="1.0"?><rss><channel>'
           '<item><title>Markets rally on rate news</title>'
           '<link>https://www.reuters.com/markets/us/markets-rally-2026-06-15-abc123</link>'
           '<description>Detail.</description></item>'
           '</channel></rss>')
    _patch_fetch(_FakeResp(rss, "application/rss+xml"))
    content, n = F._get_news_content_with_article_urls("https://feeds.example.com/rss.xml", 1)
    assert n == 1, "a valid article must be cited"
    assert "https://www.reuters.com/markets/us/markets-rally-2026-06-15-abc123" in content
    assert "🔗 CITATION URL:" in content


if __name__ == "__main__":
    test_validate_article_url_baseline();                       print("PASS: _validate_article_url baseline")
    test_google_news_urls_suppressed();                         print("PASS: Google News URLs suppressed (favor search_web)")
    test_rss_extracts_specific_urls_and_skips_no_url_items();   print("PASS: RSS extracts specific URLs / skips no-URL")
    test_non_rss_section_page_is_not_cited();                   print("PASS: section page not cited")
    test_rss_feed_yielding_no_article_is_skipped_not_feed_cited(); print("PASS: empty feed skipped (no feed-URL citation)")
    test_rss_feed_with_valid_article_is_cited_with_specific_url(); print("PASS: valid article cited with specific URL")
    print("ALL TESTS PASSED")
