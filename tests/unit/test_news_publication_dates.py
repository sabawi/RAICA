"""News sources must carry the publication date the feed already gave us.

FAILURE THIS PREVENTS
---------------------
On 2026-08-17 a live news bot was asked for a briefing on the last 8 hours and answered:

    "the tool results I received do not contain any news items with publication timestamps
     from the last 8 hours ... the news summaries provided are undated aggregates"

It was telling the truth. `get_news_summaries` had fetched 24 genuinely fresh articles in
under 3 seconds -- retrieval was fine -- but every one arrived WITHOUT a timestamp, so the
bot could not show any of them fell inside the window and correctly refused to fabricate one.

The RSS parser had already extracted the feed's date into `article['pub_date']`
(fastapi_server_complete.py:3131). Nothing read it. That name occurred four times in the
file and all four were writes. The date printed in a source block came only from
`_extract_content_date`, which regex-hunts the article BODY for a literal
"Published: August 17, 2026" string that RSS descriptions essentially never contain.

Measured locally through the real tool call: 1 of 16 articles carried a date. After the fix,
16 of 16 -- and 13 of them were inside the 8-hour window the bot had been asked about.

Fresh content, made unusable by dropping the one field that proved it was fresh.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import fastapi_server_complete as F  # noqa: E402


# ───────────────────────────────────────────── the date normaliser
def test_rfc822_feed_date_keeps_its_TIME():
    """A bare day cannot answer "the last 8 hours" -- the time is the point."""
    out = F._normalize_pub_date("Mon, 17 Aug 2026 15:16:00 GMT")
    assert out == "August 17, 2026 15:16 UTC", out


def test_offset_timezones_are_converted_to_utc():
    """Feeds publish in local zones; comparing them needs one frame of reference."""
    assert F._normalize_pub_date("Mon, 17 Aug 2026 11:16:00 -0400") == "August 17, 2026 15:16 UTC"


def test_iso8601_is_accepted_too():
    """Atom feeds use ISO-8601, not RFC-822."""
    assert F._normalize_pub_date("2026-08-17T15:16:00Z") == "August 17, 2026 15:16 UTC"


def test_an_unparseable_date_is_passed_through_rather_than_dropped():
    """A feed's own string, shown verbatim, still beats NO date.

    Dropping it is what caused the outage; being strict here would recreate it for every
    feed with an unusual format.
    """
    assert F._normalize_pub_date("last Tuesday-ish") == "last Tuesday-ish"


def test_empty_input_yields_no_date():
    for empty in (None, "", "   "):
        assert F._normalize_pub_date(empty) is None


# ───────────────────────────────────────────── the source block
def _block(**kw):
    kw.setdefault("source_url", "https://example.test/a")
    kw.setdefault("title", "T")
    kw.setdefault("content", "body with no date in it")
    kw.setdefault("source_num", 1)
    return F._format_source_block(**kw)


def test_a_feed_date_reaches_the_source_block():
    """FAILS PRE-FIX: _format_source_block took no pub_date and emitted no date line."""
    out = _block(pub_date="Mon, 17 Aug 2026 15:16:00 GMT")
    assert "📅 Published: August 17, 2026 15:16 UTC" in out


def test_without_a_feed_date_the_body_scrape_still_works():
    """The old path must survive -- some callers have no structured date."""
    out = _block(content="Published: August 17, 2026 -- something happened")
    assert "📅 Published:" in out


def test_the_feed_date_WINS_over_the_body_scrape():
    """The feed is authoritative; body text can quote any date at all.

    A story published today may discuss events of 1995; scraping the body would date the
    source 1995.
    """
    out = _block(content="Published: January 02, 1995 -- a retrospective",
                 pub_date="Mon, 17 Aug 2026 15:16:00 GMT")
    # Assert on the DATE LINE, not the whole block: the body is echoed verbatim under
    # CONTENT:, so "1995" legitimately appears there. An earlier version of this test
    # checked the whole block and failed on correct code -- a convenient proxy instead of
    # the actual invariant.
    date_line = [ln for ln in out.splitlines() if ln.startswith("📅 Published:")]
    assert date_line == ["📅 Published: August 17, 2026 15:16 UTC"], date_line


def test_no_date_anywhere_emits_no_date_line():
    """Never invent one. An absent date must stay absent."""
    assert "📅 Published:" not in _block()


def test_existing_callers_are_unaffected():
    """pub_date is optional; the three other call sites pass positionally."""
    out = F._format_source_block("https://example.test/a", "T", "body", 1)
    assert "📄 SOURCE: T" in out and "🔗 CITATION URL:" in out


# ───────────────────────────────────────────── the wiring
def test_the_news_path_actually_passes_the_feed_date():
    """Guards the WIRING, which is where this bug lived -- the formatter was always able to
    print a date; nobody handed it one.

    FAILS PRE-FIX: the call site passed no pub_date and carried the comment
    "date will be extracted by _format_source_block".
    """
    src = open(os.path.join(ROOT, "fastapi_server_complete.py")).read()
    i = src.index("formatted_source = _format_source_block(")
    call = src[i:i + 400]
    assert "pub_date=article.get('pub_date')" in call, \
        "the news call site does not forward the feed's date"


def test_pub_date_is_no_longer_a_dead_write():
    """It was parsed, stored, and never read -- 4 occurrences, all writes."""
    src = open(os.path.join(ROOT, "fastapi_server_complete.py")).read()
    assert len(re.findall(r"\bpub_date\b", src)) > 4, "pub_date still has no readers"
