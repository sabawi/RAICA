"""
Retrieval-quality audit — output-side, PURE, offline-testable (no network, no LLM).

Measures BODY-RETRIEVAL EXPOSURE: for each URL the answer actually cites, did RAICA hold *real retrieved
page body* for it, or only a title/snippet / an extraction-error / nothing at all? This is the substrate for
the "citation groundedness" question — a live URL (even one that resolves with a real title) can have reached
synthesis as a 403 error page, a paywall/JS-shell stub, or a cross-reference URL that was never fetched. When
that happens, a fact attributed to it is coming from the model's prior, not the page → hallucination risk.

This module ONLY quantifies (shadow); it never changes the answer. It reports how each cited URL was backed:

  • real          — the URL is a fetched source block whose body is substantial (>= min_body_chars).
  • thin          — a fetched source block, but the body is a snippet/sparse (< min_body_chars).
  • error         — the source block body is RAICA's own extraction-error marker (403/paywall/5xx/exception).
  • over_captured — the URL is cited but is NOT any block's primary CITATION URL: it entered the evidence
                    URL set only by appearing inside some other page's text (engine.py `_URL_RE`), so no body
                    was ever fetched for it.
  • absent        — the URL is cited but not in the gathered evidence at all (fabricated / dropped upstream).

Signals are STRUCTURAL (RAICA's own source-block markers + a length threshold), not semantic keyword lists —
this measures retrieval quality, it does not interpret meaning/intent (LLM-Policy Gate compliant). Soft-404s
that return a real-looking 200 body are a known blind spot here (fixed at source, e.g. EuropePMC).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from research.citation_grounding import extract_cited_urls, extract_cited_links, normalize_url

# Source-block markers. RAICA has TWO block formats: fastapi_server_complete._format_source_block
# (search_web / news) uses "🔗 CITATION URL:" + "─" dividers; user_tools/citation_mastery.format_source_block
# (published_papers_search) uses "🔗 MANDATORY CITATION URL:" + "═" dividers. Recognize both, or papers
# citations (which DO carry abstracts) get misread as over_captured.
_BLOCK_SPLIT = re.compile(r'🔗 (?:MANDATORY )?CITATION URL:\s*')
_CONTENT_MARK = re.compile(r'CONTENT:\s*(.*)', re.DOTALL)
_EXTRACTED_MARK = re.compile(r'Extracted Content:\s*(.*)', re.DOTALL)
_DIVIDER = re.compile(r'\n[─═]{5,}')
# RAICA's own extraction-error marker (fastapi_server_complete get_text_from_url_simplified except-branch).
_ERROR_MARK = "Error extracting content:"
# The block's TITLE (what RAICA gathered for the URL) sits on the line IMMEDIATELY before its CITATION URL,
# as "📄 SOURCE: {title}" (search_web/news) or "Title: {title}" (papers/citation_mastery).
_TITLE_URL = re.compile(r'(?:📄 SOURCE:|Title:)[ \t]*(.+?)[ \t]*\n🔗 (?:MANDATORY )?CITATION URL:\s*(\S+)')
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "how", "what", "why"}


def _title_tokens(s: str):
    """Significant lowercased word tokens of a title/headline (drops punctuation, html entities, stopwords,
    and very short tokens) — for a lenient, order-independent comparison."""
    s = re.sub(r'&[a-z]+;', ' ', (s or "").lower())
    return {t for t in re.split(r'[^a-z0-9]+', s) if len(t) > 2 and t not in _STOP}


def _headline_matches(cited: str, gathered_title: str) -> bool:
    """True if the cited headline is consistent with the title RAICA gathered for that URL. Lenient: the
    model routinely drops a " - site name" suffix or lightly rewords, so we require only that the two
    share a majority of significant tokens (relative to the shorter). A TRUE mispairing (a headline from
    a different source) shares almost none. NOTE: this compares to the GATHERED title, so a page whose
    on-page <h1>/slug differs from its <title> is correctly NOT flagged (RAICA gathered the <title>)."""
    a, b = _title_tokens(cited), _title_tokens(gathered_title)
    if not a or not b:
        return True   # can't judge → don't flag (fail-safe: no false alarm)
    return len(a & b) >= 0.5 * min(len(a), len(b))


def _parse_blocks(content: str) -> List[Tuple[str, str]]:
    """Split one evidence item's content into (primary_url, body) source blocks. Best-effort, never raises."""
    blocks: List[Tuple[str, str]] = []
    if not content:
        return blocks
    for part in _BLOCK_SPLIT.split(content)[1:]:      # [0] is the preamble before the first block
        m = re.match(r'(\S+)', part)
        if not m:
            continue
        url = m.group(1)
        cm = _CONTENT_MARK.search(part)
        body = cm.group(1) if cm else ""
        body = _DIVIDER.split(body)[0].strip()        # trim at the block's closing divider
        blocks.append((url, body))
    return blocks


def _classify_body(body: str, min_body_chars: int) -> str:
    """Return 'real' | 'thin' | 'error' for a source block's body."""
    b = (body or "").strip()
    if not b or _ERROR_MARK in b:
        return "error"
    # For search_web blocks, isolate the FETCHED body ("Extracted Content:") from the search snippet
    # ("Description:") so a failed/sparse fetch isn't masked by a long snippet. Other tools have no such
    # marker → the whole CONTENT is the retrieved body.
    em = _EXTRACTED_MARK.search(b)
    fetched = em.group(1).strip() if em else b
    if _ERROR_MARK in fetched:
        return "error"
    return "real" if len(fetched) >= min_body_chars else "thin"


# Content-quality gate (docs/RAICA_DR_CITATION_LIVENESS.md §groundedness). Marks a source block whose page
# BODY could not be fetched (extraction-error / paywall / block) so the synthesizer knows it holds only the
# title, not the article — and won't attribute specific facts to it. Marks 'error' ONLY (a 'thin' abstract/
# snippet is short but REAL content). Inserted right after the block's CITATION URL line.
_GATE_MARKER = "⚠️ BODY-NOT-RETRIEVED (page body could not be fetched — TITLE/snippet only, not the article)"
# Capturing split on the CITATION URL marker → [preamble, marker, seg, marker, seg, ...] (lossless: the
# concatenation of all pieces == original). Each `seg` = "url\n…CONTENT: body…\n<next block's preamble>".
_BLOCK_SPLIT_CAP = re.compile(r'(🔗 (?:MANDATORY )?CITATION URL:\s*)')


def annotate_unretrieved_blocks(content: str, *, min_body_chars: int = 200,
                                marker: str = _GATE_MARKER) -> Tuple[str, int]:
    """Insert the BODY-NOT-RETRIEVED marker after the CITATION URL line of each source block whose body is an
    extraction-ERROR (RAICA holds no page body). Marks 'error' ONLY. Returns (annotated_content, n_marked).
    PURE, offline; LOSSLESS (output == input) when nothing is marked. Handles both source-block formats."""
    if not content:
        return content, 0
    parts = _BLOCK_SPLIT_CAP.split(content)   # parts[0] = preamble; then (marker, seg) pairs
    out = [parts[0]]
    n = 0
    i = 1
    while i < len(parts):
        delim = parts[i]
        seg = parts[i + 1] if i + 1 < len(parts) else ""
        # `seg` holds this block's body (up to the NEXT block's CITATION URL); "Error extracting content:"
        # in it => this source is an extraction error. Insert the marker just after the url (first line).
        if _classify_body(seg, min_body_chars) == "error":
            n += 1
            nl = seg.find("\n")
            seg = (seg + "\n" + marker) if nl == -1 else (seg[:nl + 1] + marker + "\n" + seg[nl + 1:])
        out.append(delim)
        out.append(seg)
        i += 2
    return "".join(out), n


_RANK = {"error": 0, "thin": 1, "real": 2}


def assess_retrieval(answer: str, evidence: List[Dict[str, Any]], *, min_body_chars: int = 200) -> Dict:
    """
    For every URL cited in `answer`, classify what RAICA actually held for it, AND whether the cited
    HEADLINE (link text) matches the title RAICA gathered for that URL (mispairing detection).

    Returns {"stats": {real, thin, error, over_captured, absent, cited_total},
             "flagged": [(verdict, url), ...],                          # body verdict != 'real'
             "headline": {"matched", "mismatched", "checked",
                          "flagged": [(cited_headline, url), ...]}}     # cited headline != gathered title
    """
    cited = extract_cited_urls(answer)

    block_quality: Dict[str, str] = {}   # normalized primary URL -> best body verdict
    block_title: Dict[str, str] = {}     # normalized primary URL -> title RAICA gathered for it
    ev_urls: set = set()                 # every URL anywhere in evidence (for over-capture detection)
    for e in (evidence or []):
        content = e.get("content") or ""
        for u in (e.get("urls") or []):
            if u:
                ev_urls.add(normalize_url(u))
        for burl, body in _parse_blocks(content):
            n = normalize_url(burl)
            q = _classify_body(body, min_body_chars)
            if n not in block_quality or _RANK[q] > _RANK[block_quality[n]]:
                block_quality[n] = q     # keep the BEST body seen for a URL fetched more than once
        for title, burl in _TITLE_URL.findall(content):
            block_title.setdefault(normalize_url(burl), title.strip())

    stats = {"real": 0, "thin": 0, "error": 0, "over_captured": 0, "absent": 0, "cited_total": len(cited)}
    flagged: List[Tuple[str, str]] = []
    seen: set = set()
    for u in cited:
        n = normalize_url(u)
        if n in seen:
            continue
        seen.add(n)
        if n in block_quality:
            verdict = block_quality[n]
        elif n in ev_urls:
            verdict = "over_captured"
        else:
            verdict = "absent"
        stats[verdict] = stats.get(verdict, 0) + 1
        if verdict != "real":
            flagged.append((verdict, u))
    stats["cited_total"] = len(seen)

    # ── Headline↔URL consistency: does the cited headline match the title RAICA GATHERED for that URL? ──
    # Only judged for URLs we hold a gathered title for. A benign <title>≠<h1>/slug page is NOT flagged
    # (RAICA gathered the <title>, the model used it). A TRUE mispairing (headline from another source) is.
    hl = {"matched": 0, "mismatched": 0, "checked": 0, "flagged": []}
    hl_seen: set = set()
    for text, url in extract_cited_links(answer):
        n = normalize_url(url)
        if n in hl_seen or n not in block_title or not text:
            continue
        hl_seen.add(n)
        hl["checked"] += 1
        if _headline_matches(text, block_title[n]):
            hl["matched"] += 1
        else:
            hl["mismatched"] += 1
            hl["flagged"].append((text, url))
    return {"stats": stats, "flagged": flagged, "headline": hl}
