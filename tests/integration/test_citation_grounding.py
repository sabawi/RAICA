"""
Tests for research/citation_grounding.ground_citations — the output-side fabricated/rotted link guard.

Includes the GOLDEN reply-409 scenario (live @Ask answer that cited two fabricated BBC URLs + one
fabricated Al Jazeera URL — none in evidence, all 404 — alongside two real Wikipedia URLs).

Run: python -m pytest tests/integration/test_citation_grounding.py -q
 or: python tests/integration/test_citation_grounding.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.citation_grounding import ground_citations, normalize_url


def _a(url, text):
    return f'<a target="_blank" href="{url}" rel="noopener noreferrer">{text}</a>'


# ---- GOLDEN: reply-409 ----
WIKI1 = "https://en.wikipedia.org/wiki/2026_Iran_war"
WIKI2 = "https://en.wikipedia.org/wiki/Gaza_peace_plan"
FAKE_BBC1 = "https://www.bbc.com/news/articles/c4g0n1v7n5eo"
FAKE_BBC2 = "https://www.bbc.com/news/articles/c5y6v5p0zrvo"
FAKE_AJ = "https://www.aljazeera.com/news/2026/6/16/iran-says-israeli-occupation-in-lebanon-would-breach-us-deal"


def test_golden_reply409_strips_fabricated_keeps_real():
    answer = (
        f"<p>Iran signed the deal {_a(WIKI1, '2026 Iran war - Wikipedia')} and a Gaza plan "
        f"{_a(WIKI2, 'Gaza peace plan - Wikipedia')}.</p>"
        f"<p>The BBC reported it {_a(FAKE_BBC1, 'BBC story 1')} and {_a(FAKE_BBC2, 'BBC story 2')}, "
        f"with Al Jazeera adding {_a(FAKE_AJ, 'Al Jazeera report')}.</p>"
    )
    evidence = [WIKI1, WIKI2]  # only the real Wikipedia URLs were gathered
    res = ground_citations(answer, evidence, on_unsourced="flag")
    out, st = res["text"], res["stats"]
    # real Wikipedia links survive verbatim
    assert _a(WIKI1, "2026 Iran war - Wikipedia") in out
    assert _a(WIKI2, "Gaza peace plan - Wikipedia") in out
    # fabricated links are gone, but their visible text stays
    for u in (FAKE_BBC1, FAKE_BBC2, FAKE_AJ):
        assert f'href="{u}"' not in out
    assert "BBC story 1" in out and "Al Jazeera report" in out
    assert st["fabricated"] == 3 and st["valid"] == 2 and st["rotted"] == 0
    # the 2nd paragraph had links but 0 valid after grounding -> flagged
    assert st["items_unsourced"] == 1 and "⚠️" in out


def test_lossless_when_all_valid():
    answer = f"<p>A {_a(WIKI1, 'one')} and B {_a(WIKI2, 'two')}.</p>"
    res = ground_citations(answer, [WIKI1, WIKI2])
    assert res["text"] == answer  # byte-for-byte unchanged when nothing is wrong
    assert res["stats"]["fabricated"] == 0 and res["stats"]["items_unsourced"] == 0


def test_rotted_vs_fabricated():
    # WIKI1 was gathered but is now dead (provider rotted) -> 'rotted'; FAKE_BBC1 never gathered -> 'fabricated'
    answer = f"<p>X {_a(WIKI1, 'real-but-dead')} Y {_a(FAKE_BBC1, 'invented')}.</p>"
    res = ground_citations(answer, [WIKI1], dead_urls=[WIKI1])
    st = res["text"], res["stats"]
    assert res["stats"]["rotted"] == 1 and res["stats"]["fabricated"] == 1 and res["stats"]["valid"] == 0
    assert 'href="' not in res["text"]  # both links dropped
    assert "real-but-dead" in res["text"] and "invented" in res["text"]  # attributions kept


def test_url_normalization_matches_tracking_and_www():
    cited = "https://www.bbc.com/news/articles/cXYZ?at_medium=RSS&at_campaign=rss"
    gathered = "https://bbc.com/news/articles/cXYZ"
    assert normalize_url(cited) == normalize_url(gathered)
    answer = f"<p>News {_a(cited, 'headline')}.</p>"
    res = ground_citations(answer, [gathered])
    assert res["stats"]["valid"] == 1 and res["stats"]["fabricated"] == 0
    assert f'href="{cited}"' in res["text"]  # kept (tracking params on the cited form preserved)


def test_markdown_links():
    answer = f"Real [wiki]({WIKI1}) and fake [bbc]({FAKE_BBC1})."
    res = ground_citations(answer, [WIKI1])
    assert res["stats"]["valid"] == 1 and res["stats"]["fabricated"] == 1
    assert f"[wiki]({WIKI1})" in res["text"]   # valid markdown link kept verbatim
    assert FAKE_BBC1 not in res["text"]        # fabricated url stripped
    assert "fake bbc." in res["text"]          # fabricated link -> its plain text "bbc"


def test_quorum_drop_removes_unsourced_block():
    answer = f"<p>Sourced {_a(WIKI1, 'w')}.</p><p>Unsourced {_a(FAKE_BBC1, 'f')}.</p>"
    res = ground_citations(answer, [WIKI1], on_unsourced="drop")
    assert "Sourced" in res["text"] and "Unsourced" not in res["text"]
    assert res["stats"]["items_unsourced"] == 1


def test_shadow_returns_original_with_stats():
    answer = f"<p>{_a(FAKE_BBC1, 'f')}</p>"
    res = ground_citations(answer, [WIKI1], shadow=True)
    assert res["text"] == answer  # unchanged in shadow
    assert res["stats"]["fabricated"] == 1  # but the problem is measured


def test_no_links_is_noop():
    answer = "<p>Just prose, no citations.</p>"
    res = ground_citations(answer, [WIKI1])
    assert res["text"] == answer and res["stats"]["items_total"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
