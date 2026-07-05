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

from research.citation_grounding import extract_cited_urls, normalize_url

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


_RANK = {"error": 0, "thin": 1, "real": 2}


def assess_retrieval(answer: str, evidence: List[Dict[str, Any]], *, min_body_chars: int = 200) -> Dict:
    """
    For every URL cited in `answer`, classify what RAICA actually held for it.

    Returns {"stats": {real, thin, error, over_captured, absent, cited_total},
             "flagged": [(verdict, url), ...]}   # everything that is NOT 'real'
    """
    cited = extract_cited_urls(answer)

    block_quality: Dict[str, str] = {}   # normalized primary URL -> best body verdict
    ev_urls: set = set()                 # every URL anywhere in evidence (for over-capture detection)
    for e in (evidence or []):
        for u in (e.get("urls") or []):
            if u:
                ev_urls.add(normalize_url(u))
        for burl, body in _parse_blocks(e.get("content") or ""):
            n = normalize_url(burl)
            q = _classify_body(body, min_body_chars)
            if n not in block_quality or _RANK[q] > _RANK[block_quality[n]]:
                block_quality[n] = q     # keep the BEST body seen for a URL fetched more than once

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
    # cited_total counts links; recompute over unique for a clean denominator
    stats["cited_total"] = len(seen)
    return {"stats": stats, "flagged": flagged}
