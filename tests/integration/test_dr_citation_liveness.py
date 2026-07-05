"""
Phase 0 tests for the Deep-Research citation-liveness fix (docs/RAICA_DR_CITATION_LIVENESS.md, v1.0.0.134).

Covers the new/changed units WITHOUT network or LLM:
  - research.citation_grounding.extract_cited_urls  — cited-link extraction (HTML + Markdown)
  - research.engine.salvage_json_map                — tolerant partial JSON recovery (G1 grading fix)
  - research.link_liveness.filter_live_article_urls — lenient drop-only-dead (verify monkeypatched)
  - research.citation_grounding.ground_citations(dead_urls=...) — dead cited link stripped as ROTTED
    (headline text kept) — the enforce path the Phase-1 flip will use

Run: python -m pytest tests/integration/test_dr_citation_liveness.py -q
 or: python tests/integration/test_dr_citation_liveness.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from research.citation_grounding import extract_cited_urls, ground_citations
from research.engine import salvage_json_map
import research.link_liveness as ll


DEAD = "https://www.cnbc.com/2026/07/02/jobs-report-june-2026.html"        # verified 404 in the real incident
LIVE = "https://en.wikipedia.org/wiki/2026_Iran_war"
BLOCKED = "https://www.reuters.com/business/energy/some-article-2026"      # 403 bot-block → must be KEPT


# ---- extract_cited_urls ----
def test_extract_cited_urls_markdown_and_html():
    md = f"Claim A [Jobs report](  {DEAD} ) wait no.\n\nClaim B [Iran war]({LIVE})."
    # note: markdown URL must not contain spaces; keep it clean
    md = f"Claim A [Jobs report]({DEAD}).\n\nClaim B [Iran war]({LIVE})."
    got = extract_cited_urls(md)
    assert got == [DEAD, LIVE], got

    html = (f'<p>Claim A <a href="{DEAD}">Jobs report</a>.</p>'
            f'<p>Claim B <a target="_blank" href="{LIVE}" rel="noopener">Iran war</a>.</p>')
    assert extract_cited_urls(html) == [DEAD, LIVE]


def test_extract_cited_urls_dedupes_in_order():
    md = f"[a]({LIVE}) then [b]({DEAD}) then [c]({LIVE})."
    assert extract_cited_urls(md) == [LIVE, DEAD]


def test_extract_cited_urls_empty():
    assert extract_cited_urls("") == []
    assert extract_cited_urls("no links here, just prose.") == []


# ---- salvage_json_map (G1) ----
def test_salvage_recovers_good_entries_when_one_is_malformed():
    # Middle entry has an UNESCAPED quote in the reason → whole json.loads() fails, but the two
    # well-formed entries must still be recovered (not all collapsed to unknown).
    raw = (
        '{"arxiv.org": {"tier": "peer_reviewed", "reason": ""}, '
        '"bad.com": {"tier": "low_credibility", "reason": "says "hi" unescaped"}, '
        '"nature.com": {"tier": "peer_reviewed", "reason": ""}}'
    )
    import json
    try:
        json.loads(raw)
        assert False, "raw should be invalid JSON for this test"
    except Exception:
        pass
    data = salvage_json_map(raw)
    assert data.get("arxiv.org", {}).get("tier") == "peer_reviewed"
    assert data.get("nature.com", {}).get("tier") == "peer_reviewed"
    # the broken entry is skipped (absent or not a usable dict) → caller maps it to 'unknown'
    assert "bad.com" not in data or not isinstance(data.get("bad.com"), dict)


def test_salvage_handles_truncated_output():
    raw = '{"a.com": {"tier": "reputable", "reason": ""}, "b.com": {"tier": "popu'  # cut off mid-value
    data = salvage_json_map(raw)
    assert data.get("a.com", {}).get("tier") == "reputable"
    assert "b.com" not in data  # truncated entry not recovered


def test_salvage_empty_or_garbage_returns_empty():
    assert salvage_json_map("") == {}
    assert salvage_json_map("not json at all") == {}


# ---- link_liveness.filter_live_article_urls (lenient; verify monkeypatched, no network) ----
def test_filter_live_drops_only_verified_dead(monkeypatch):
    # verify_url_live: False == verified dead (drop). True == keep (incl. bot-blocks/timeouts).
    def fake_verify(url, timeout=6.0):
        return url != DEAD  # only DEAD is verified-dead
    monkeypatch.setattr(ll, "verify_url_live", fake_verify)
    live = ll.filter_live_article_urls([LIVE, DEAD, BLOCKED], timeout=1, max_workers=4)
    assert LIVE in live and BLOCKED in live
    assert DEAD not in live


def test_filter_live_keeps_all_when_none_dead(monkeypatch):
    monkeypatch.setattr(ll, "verify_url_live", lambda url, timeout=6.0: True)
    live = ll.filter_live_article_urls([LIVE, BLOCKED], timeout=1)
    assert live == {LIVE, BLOCKED}


def test_filter_live_empty():
    assert ll.filter_live_article_urls([]) == set()


# ---- ground_citations(dead_urls=...) → ROTTED strip keeps the headline (Phase-1 enforce path) ----
def test_dead_url_stripped_as_rotted_keeps_text():
    # DEAD is IN evidence (so not 'fabricated') but supplied as dead → classified ROTTED → link removed,
    # headline text preserved; the live link is untouched.
    answer = (f'<p>Jobs weakened <a href="{DEAD}">June jobs report</a>.</p>'
              f'<p>Context <a href="{LIVE}">2026 Iran war</a>.</p>')
    res = ground_citations(answer, [DEAD, LIVE], dead_urls=[DEAD], shadow=False)
    out, st = res["text"], res["stats"]
    assert st["rotted"] == 1 and st["fabricated"] == 0
    assert f'href="{DEAD}"' not in out          # dead link removed
    assert "June jobs report" in out            # headline text kept
    assert f'href="{LIVE}"' in out              # live link untouched


def test_shadow_leaves_answer_unchanged_even_with_dead():
    answer = f'<p>x <a href="{DEAD}">June jobs report</a>.</p>'
    res = ground_citations(answer, [DEAD], dead_urls=[DEAD], shadow=True)
    assert res["text"] == answer                # SHADOW → byte-for-byte unchanged
    assert res["stats"]["rotted"] == 1          # but stats still computed (baseline)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
