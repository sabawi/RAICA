"""
Tests for research/retrieval_quality.assess_retrieval — the body-retrieval exposure audit (v1.0.0.137).

PURE, offline. Builds evidence in RAICA's _format_source_block shape and asserts each cited URL is classified
by what RAICA actually held: real / thin / error / over_captured / absent.

Run: python -m pytest tests/integration/test_retrieval_quality.py -q
 or: python tests/integration/test_retrieval_quality.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from research.retrieval_quality import assess_retrieval

LONG = "Substantial article body text. " * 12          # > 200 chars of real body
DIV = "───────────────────────────"


def _block(url, content, title="T"):
    return f"\n{DIV}\n📄 SOURCE: {title}\n🔗 CITATION URL: {url}\nCONTENT: {content}\n{DIV}\n"


REAL = "https://ex.com/real-article"
THIN = "https://ex.com/thin-snippet"
ERR = "https://ex.com/blocked-403"
WIKI = "https://en.wikipedia.org/wiki/Thing"
OVERCAP = "https://ex.com/only-mentioned-in-body"
ABSENT = "https://ex.com/never-gathered"


def _evidence():
    return [
        {"content": _block(REAL, f"Description: snip.\n\nExtracted Content: {LONG}"), "urls": [REAL]},
        {"content": _block(THIN, "Description: a snippet.\n\nExtracted Content: too short to be a body"),
         "urls": [THIN]},
        {"content": _block(ERR, "Description: s.\n\nExtracted Content: Error extracting content: 403 Forbidden"),
         "urls": [ERR]},
        {"content": _block(WIKI, LONG), "urls": [WIKI]},                       # no "Extracted Content:" marker
        # OVERCAP appears only inside another block's BODY (and thus in that item's regex-extracted urls),
        # never as a primary CITATION URL → over_captured.
        {"content": _block(REAL, f"Description: s.\n\nExtracted Content: see also {OVERCAP}. {LONG}"),
         "urls": [REAL, OVERCAP]},
    ]


def _answer(urls):
    return "## A\n\n" + " ".join(f"[cite]({u})" for u in urls)


def test_each_class_counted():
    res = assess_retrieval(_answer([REAL, THIN, ERR, WIKI, OVERCAP, ABSENT]), _evidence(), min_body_chars=200)
    st = res["stats"]
    assert st["real"] == 2, st          # REAL + WIKI (both substantial body)
    assert st["thin"] == 1, st          # THIN (snippet-only)
    assert st["error"] == 1, st         # ERR (extraction-error marker)
    assert st["over_captured"] == 1, st # OVERCAP (in evidence urls but never a fetched source)
    assert st["absent"] == 1, st        # ABSENT (not in evidence at all)
    assert st["cited_total"] == 6, st
    verdicts = {v for v, _ in res["flagged"]}
    assert verdicts == {"thin", "error", "over_captured", "absent"}


def test_all_real_when_bodies_substantial():
    res = assess_retrieval(_answer([REAL, WIKI]), _evidence(), min_body_chars=200)
    assert res["stats"]["real"] == 2
    assert res["flagged"] == []


def test_html_answer_and_dedupe():
    # HTML citations + a duplicate cited URL counts once.
    ans = f'<p>x <a href="{REAL}">a</a> and <a href="{REAL}">a again</a> and <a href="{ERR}">b</a>.</p>'
    st = assess_retrieval(ans, _evidence())["stats"]
    assert st["cited_total"] == 2 and st["real"] == 1 and st["error"] == 1


def test_no_citations():
    st = assess_retrieval("plain prose, no links", _evidence())["stats"]
    assert st["cited_total"] == 0


# ---- papers-tool block format (user_tools/citation_mastery.format_source_block) must ALSO be recognized ----
DDIV = "═══════════════════════════"


def _papers_block(url, content, title="Paper"):
    return (f"\n{DDIV}\n📄 SOURCE BLOCK #1 [REQUIRED CITATION: {url}]\n{DDIV}\n"
            f"Title: {title}\n🔗 MANDATORY CITATION URL: {url}\n📅 Retrieved: now\n{DIV}\n"
            f"CONTENT: {content}\n{DDIV}\n")


def test_papers_mandatory_marker_counts_as_real_not_overcaptured():
    paper_url = "https://europepmc.org/article/MED/42273255"
    ev = [{"content": _papers_block(paper_url, f"Abstract: {LONG}"), "urls": [paper_url]}]
    res = assess_retrieval(_answer([paper_url]), ev, min_body_chars=200)
    st = res["stats"]
    assert st["real"] == 1, st            # recognized as a fetched paper with a body (abstract)
    assert st["over_captured"] == 0, st   # NOT misread as over_captured
    assert res["flagged"] == []


# ---- headline↔URL consistency (mispairing detection) ----
def test_headline_benign_title_suffix_matches():
    # gathered <title> has a " - site" suffix; the model cites it without the suffix → MATCHED (not a
    # mispairing). This is the philippdubach case: <title> gathered, on-page <h1>/slug differs, still fine.
    url = "https://philippdubach.com/posts/the-last-architecture-designed-by-hand/"
    gathered = "What Comes After Transformers: Hybrid AI Architecture in 2026 - philippdubach.com"
    ev = [{"content": _block(url, f"Description: s.\n\nExtracted Content: {LONG}", title=gathered),
           "urls": [url]}]
    ans = f"See [What Comes After Transformers: Hybrid AI Architecture in 2026]({url})."
    hl = assess_retrieval(ans, ev)["headline"]
    assert hl["checked"] == 1 and hl["matched"] == 1 and hl["mismatched"] == 0, hl


def test_headline_true_mispairing_flagged():
    # cited headline belongs to a DIFFERENT article than the gathered title for this URL → MISMATCHED.
    url = "https://example.com/article-a"
    ev = [{"content": _block(url, f"Description: s.\n\nExtracted Content: {LONG}",
                             title="Deep Learning for Protein Folding: A 2026 Review"), "urls": [url]}]
    ans = f"[Quarterly Earnings Report of Acme Corporation]({url})"
    hl = assess_retrieval(ans, ev)["headline"]
    assert hl["mismatched"] == 1 and hl["matched"] == 0, hl
    assert hl["flagged"][0][1] == url


def test_headline_papers_format_matches():
    url = "https://europepmc.org/article/MED/42273255"
    title = "CRISPR base editing for sickle cell disease: current progress"
    ev = [{"content": _papers_block(url, f"Abstract: {LONG}", title=title), "urls": [url]}]
    hl = assess_retrieval(f"[{title}]({url})", ev)["headline"]
    assert hl["checked"] == 1 and hl["matched"] == 1, hl


def test_headline_not_judged_without_gathered_title():
    # over_captured / absent URLs have no gathered title → not counted in the headline check.
    hl = assess_retrieval(_answer([OVERCAP, ABSENT]), _evidence())["headline"]
    assert hl["checked"] == 0, hl


if __name__ == "__main__":
    test_each_class_counted();          print("PASS: each retrieval class counted")
    test_all_real_when_bodies_substantial(); print("PASS: all-real when bodies substantial")
    test_html_answer_and_dedupe();      print("PASS: HTML + dedupe")
    test_no_citations();                print("PASS: no citations")
    test_papers_mandatory_marker_counts_as_real_not_overcaptured(); print("PASS: papers block format")
    test_headline_benign_title_suffix_matches(); print("PASS: headline benign title-suffix matches")
    test_headline_true_mispairing_flagged();     print("PASS: headline true mispairing flagged")
    test_headline_papers_format_matches();       print("PASS: headline papers format matches")
    test_headline_not_judged_without_gathered_title(); print("PASS: headline not judged without title")
    print("ALL TESTS PASSED")
