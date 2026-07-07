"""
Citation grounding — output-side, PURE, offline-testable (no network, no LLM).

The structural fix for fabricated citation links (see docs/RAICA_CITATION_GROUNDING_BY_REFERENCE.md and the
operator findings: failures are concentrated on REAL-TIME NEWS, where article URLs have opaque, random IDs
the model cannot reconstruct — so when the exact URL is lost upstream it invents a plausible-but-fake one).

Every cited URL is classified against the set of URLs the tools ACTUALLY returned (the gathered evidence),
which lets us tell apart two very different failures:

  • FABRICATED — URL is NOT in the gathered evidence  → the model invented it (e.g. a 404 BBC article never
                 returned by any tool).  → STRIP the link, keep the visible text.
  • ROTTED     — URL WAS in the evidence but is now dead → a real source the provider morphed/pulled (hot
                 breaking-news stories get re-titled, moved, or removed within minutes).  This is NOT a lie;
                 it's source decay.  → keep the attribution; drop only the now-dead link.
  • VALID      — URL is in the evidence (and not known-dead) → keep as-is.

A per-block QUORUM then flags/drops any block left with zero VALID sources (anti-"fake-news": no claim
should survive on only fabricated/dead links).

Design guarantees:
  - LOSSLESS when nothing is wrong: if every cited URL is in evidence, output == input byte-for-byte.
  - Works on BOTH HTML (`<a href=...>text</a>`, as NewX bot replies render) and Markdown (`[text](url)`).
  - shadow=True computes the stats but returns the ORIGINAL text unchanged (for safe live baselining).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Tracking/redirect params that don't change the article identity — dropped before matching so a cited
# `bbc.com/news/articles/x` matches the gathered `bbc.com/news/articles/x?at_medium=RSS&at_campaign=rss`.
_TRACKING_PARAMS = {
    "at_medium", "at_campaign", "oc", "utm_source", "utm_medium", "utm_campaign", "utm_term",
    "utm_content", "cmp", "ref", "ito", "ns_campaign", "ns_mchannel", "fbclid", "gclid",
}

_FLAG_MARKER = "⚠️ [unverified — no working source] "

# Citation link patterns. HTML `<a ... href="URL" ...>TEXT</a>` (attrs may precede/follow href);
# Markdown `[TEXT](URL)`.
_HTML_LINK = re.compile(r'<a\b([^>]*?)href="(https?://[^"]+)"([^>]*)>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_MD_LINK = re.compile(r'\[([^\]]*)\]\((https?://[^)\s]+)\)')


def extract_cited_urls(answer: str) -> List[str]:
    """Return the URLs cited as links in an answer (HTML `<a href>` or Markdown `[text](url)`),
    de-duplicated in first-seen order. Reuses the SAME patterns ground_citations acts on, so 'cited'
    means exactly the links grounding/liveness will consider. PURE, offline — no network."""
    seen: Set[str] = set()
    out: List[str] = []
    for pat in (_HTML_LINK, _MD_LINK):
        for mo in pat.finditer(answer or ""):
            u = mo.group(2)
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return out


_TAG = re.compile(r'<[^>]+>')


def extract_cited_links(answer: str):
    """Like extract_cited_urls, but returns (link_text, url) pairs — the clickable HEADLINE and its URL.
    HTML anchor text has any nested tags stripped. De-duplicated by (text, url). PURE, offline."""
    seen = set()
    out = []
    for mo in _HTML_LINK.finditer(answer or ""):
        url = mo.group(2)
        text = _TAG.sub("", mo.group(4) or "").strip()
        key = (text, url)
        if url and key not in seen:
            seen.add(key)
            out.append((text, url))
    for mo in _MD_LINK.finditer(answer or ""):
        url = mo.group(2)
        text = (mo.group(1) or "").strip()
        key = (text, url)
        if url and key not in seen:
            seen.add(key)
            out.append((text, url))
    return out


# Block boundaries for the quorum (split losslessly: concatenation of pieces == original).
_HTML_BLOCK_CLOSE = re.compile(r'(</(?:p|li|h[1-6]|blockquote|div)>)', re.IGNORECASE)
_HTML_BLOCK_OPEN = re.compile(r'^(\s*<(?:p|li|h[1-6]|blockquote|div)\b[^>]*>)', re.IGNORECASE)


def normalize_url(url: str) -> str:
    """Canonical key for matching: lowercase scheme+host, drop 'www.', drop fragment, drop tracking
    params, strip a trailing slash. Best-effort — never raises."""
    if not url or not isinstance(url, str):
        return ""
    try:
        s = urlsplit(url.strip())
        scheme = (s.scheme or "https").lower()
        host = (s.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
             if k.lower() not in _TRACKING_PARAMS]
        path = (s.path or "").rstrip("/")
        return urlunsplit((scheme, host, path, urlencode(q), ""))
    except Exception:
        return url.strip().lower()


def _classify(url: str, allowed: Set[str], dead: Set[str],
              off_topic: "Set[str]" = frozenset()) -> str:
    """Return 'valid' | 'rotted' | 'fabricated' | 'off_topic' for a cited URL."""
    n = normalize_url(url)
    if n not in allowed:
        return "fabricated"
    if n in off_topic:          # in evidence, but judged not about the topic (homonym/domain collision)
        return "off_topic"
    if n in dead:
        return "rotted"
    return "valid"


def _split_blocks(text: str) -> List[str]:
    """Split into 'item' blocks LOSSLESSLY (''.join(result) == text). HTML: after each block-closing tag;
    Markdown: on blank lines."""
    if _HTML_BLOCK_CLOSE.search(text):
        parts = _HTML_BLOCK_CLOSE.split(text)
        blocks, buf = [], ""
        for p in parts:
            buf += p
            if _HTML_BLOCK_CLOSE.fullmatch(p):
                blocks.append(buf)
                buf = ""
        if buf:
            blocks.append(buf)
        return blocks
    parts = re.split(r'(\n\s*\n)', text)
    blocks, buf = [], ""
    for p in parts:
        buf += p
        if re.fullmatch(r'\n\s*\n', p):
            blocks.append(buf)
            buf = ""
    if buf:
        blocks.append(buf)
    return blocks


def _flag_block(block: str, marker: str = _FLAG_MARKER) -> str:
    """Insert the unverified marker just inside the block's opening tag (HTML) or at its start (Markdown)."""
    m = _HTML_BLOCK_OPEN.match(block)
    if m:
        return block[:m.end()] + marker + block[m.end():]
    return marker + block


def _ground_block(block: str, allowed: Set[str], dead: Set[str], off_topic: Set[str],
                  stats: Dict) -> Tuple[str, int, int]:
    """Rewrite one block's links. Returns (new_block, n_links, n_valid)."""
    counts = {"links": 0, "valid": 0}

    def _sub_html(mo):
        verdict = _classify(mo.group(2), allowed, dead, off_topic)
        counts["links"] += 1
        if verdict == "valid":
            counts["valid"] += 1
            stats["valid"] += 1
            return mo.group(0)
        stats[verdict] += 1
        stats["stripped_urls"].append((verdict, mo.group(2)))
        return mo.group(4)  # keep the anchor's visible text, drop the link

    def _sub_md(mo):
        verdict = _classify(mo.group(2), allowed, dead, off_topic)
        counts["links"] += 1
        if verdict == "valid":
            counts["valid"] += 1
            stats["valid"] += 1
            return mo.group(0)
        stats[verdict] += 1
        stats["stripped_urls"].append((verdict, mo.group(2)))
        return mo.group(1)  # keep the link text

    new_block = _HTML_LINK.sub(_sub_html, block)
    new_block = _MD_LINK.sub(_sub_md, new_block)
    return new_block, counts["links"], counts["valid"]


def ground_citations(answer: str,
                     evidence_urls: Iterable[str],
                     *,
                     dead_urls: Optional[Iterable[str]] = None,
                     off_topic_urls: Optional[Iterable[str]] = None,
                     on_unsourced: str = "flag",
                     shadow: bool = False) -> Dict:
    """
    Ground an answer's citations against the gathered evidence.

    Args:
        answer:        the synthesized answer (HTML or Markdown).
        evidence_urls: URLs the tools actually returned (the real, gathered set).
        dead_urls:     OPTIONAL subset known to be dead now (provider-rotted) — those in evidence but dead
                       are classified 'rotted' (real source, link dropped) vs 'fabricated' (never gathered).
        on_unsourced:  'flag' (mark a block left with 0 valid sources), 'drop' (remove it), or 'off'.
        shadow:        True → return the ORIGINAL answer unchanged, with stats only (safe baselining).

    Returns:
        {"text": grounded_or_original, "stats": {valid, fabricated, rotted, links_total,
         items_total, items_unsourced, stripped_urls: [(verdict, url), ...]}}
    """
    allowed = {normalize_url(u) for u in (evidence_urls or []) if u}
    dead = {normalize_url(u) for u in (dead_urls or []) if u}
    off_topic = {normalize_url(u) for u in (off_topic_urls or []) if u}
    stats = {"valid": 0, "fabricated": 0, "rotted": 0, "off_topic": 0, "links_total": 0,
             "items_total": 0, "items_unsourced": 0, "stripped_urls": []}

    out_blocks: List[str] = []
    for block in _split_blocks(answer):
        new_block, n_links, n_valid = _ground_block(block, allowed, dead, off_topic, stats)
        stats["links_total"] += n_links
        if n_links > 0:
            stats["items_total"] += 1
            if n_valid == 0:
                stats["items_unsourced"] += 1
                if on_unsourced == "drop":
                    continue
                if on_unsourced == "flag":
                    new_block = _flag_block(new_block)
        out_blocks.append(new_block)

    grounded = "".join(out_blocks)
    return {"text": answer if shadow else grounded, "stats": stats}
