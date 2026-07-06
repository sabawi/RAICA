"""Offline unit tests for research/nondr_citation_audit.py (Phase 0 shadow).

Mirrors the two real production failures:
  - @raicaMiddleEast post 5564: fabricated houseofsud.com URL (not in tool results).
  - @raicaMiddleEast post 5572: middleeasteye.net/ homepage reused under 11 distinct headlines.
And asserts a clean answer produces zero flags (no false positives).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from research.nondr_citation_audit import audit_citations, format_shadow_line


def test_fabricated_url_flagged():
    # Model cites a URL that no tool ever returned → fabricated.
    evidence = "🔗 CITATION URL: https://www.bbc.co.uk/news/articles/cdejj44kl70o\n"
    answer = (
        "[Khamenei funeral](https://www.bbc.co.uk/news/articles/cdejj44kl70o) drew crowds. "
        "[Riyadh sent the deputy](https://houseofsud.com/riyadh-said-no-then-sent-the-deputy/)."
    )
    a = audit_citations(answer, evidence)
    assert a["fabricated"] == 1, a
    assert any("houseofsud" in u for u in a["fabricated_urls"]), a
    # the BBC article IS in evidence → not fabricated
    assert not any("bbc" in u for u in a["fabricated_urls"]), a


def test_reuse_and_bare_homepage_flagged():
    # One homepage URL stapled onto 3 distinct headlines (the 5572 glitch, shrunk).
    url = "https://www.middleeasteye.net/"
    evidence = f"🔗 CITATION URL: {url}\n"
    answer = (
        f"[Iran begins six-day funeral]({url}) ... "
        f"[Israel eyes return to Gaza war]({url}) ... "
        f"[NATO meets in Turkiye]({url})."
    )
    a = audit_citations(answer, evidence)
    assert a["reuse"] == 1, a                         # one URL reused
    assert max(a["reuse_detail"].values()) == 3, a    # across 3 distinct headlines
    assert a["bare_homepage"] == 1, a                 # path is '/'
    assert a["fabricated"] == 0, a                    # it WAS in evidence → not fabricated


def test_clean_answer_no_flags():
    e = (
        "🔗 CITATION URL: https://www.aljazeera.com/news/2026/7/6/israels-smotrich-declares-revolution\n"
        "🔗 CITATION URL: https://www.dw.com/en/hamas-to-dissolve-gaza-governing-body/a-77847836\n"
    )
    answer = (
        "[Smotrich declares revolution](https://www.aljazeera.com/news/2026/7/6/israels-smotrich-declares-revolution) and "
        "[Hamas to dissolve Gaza body](https://www.dw.com/en/hamas-to-dissolve-gaza-governing-body/a-77847836)."
    )
    a = audit_citations(answer, e)
    assert a["fabricated"] == 0 and a["reuse"] == 0 and a["bare_homepage"] == 0, a
    assert a["cited"] == 2 and a["distinct_urls"] == 2, a


def test_empty_evidence_is_failsafe():
    # If evidence extraction yields nothing, do NOT flag everything as fabricated.
    answer = "[some story](https://example.org/article/x)"
    a = audit_citations(answer, "")
    assert a["fabricated"] == 0, a


def test_never_raises_and_formats():
    for bad in (None, "", 123, "no links here"):
        a = audit_citations(bad if isinstance(bad, str) or bad is None else str(bad), "")
        assert isinstance(a, dict)
        assert isinstance(format_shadow_line(a), str)


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  ✗ {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
