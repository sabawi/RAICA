"""
research/nondr_citation_audit.py — OFFLINE, SHADOW audit of NON-DR answer citations.

The non-Deep-Research answer path (NewX bots + @Ask, served through
``fastapi_server_complete.llama_stream``) has NO output-side citation grounding — unlike Deep
Research, which strips fabricated/dead links after synthesis. This module computes, PURELY and
OFFLINE (no network, never raises), the *structural* citation defects in a finished non-DR answer,
so we can baseline them in SHADOW before enforcing anything.

See docs/RAICA_NONDR_CITATION_GROUNDING.md.

Phase-0 signals (all definitive / structural — no keyword lists, no meaning-decisions, LLM-Policy clean):
  - ``fabricated`` : a cited URL is NOT among the URLs the model was actually shown (the tool-result
                     evidence in the prompt) — e.g. a hallucinated ``houseofsud.com/...``.
  - ``reuse``      : one URL is cited under MULTIPLE distinct headlines (e.g. ``middleeasteye.net/`` ×11)
                     — structurally, at most one of those headlines is correctly sourced.
  - ``bare_home``  : a cited URL has no article path (path is '' or '/') — a homepage, not an article.

Section-page detection (paths like ``/world/middle_east``) and dead-link liveness are deferred to
later phases (they need a proper section detector / network fetch); Phase 0 stays offline.

Reuses ``research.citation_grounding.extract_cited_links`` + ``normalize_url``.
"""
from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlsplit

from research.citation_grounding import extract_cited_links

# Any URL appearing in the evidence text (the prompt/context the model was shown).
_URL_RE = re.compile(r'https?://[^\s<>"\')\]}]+')


def _bare_homepage(url: str) -> bool:
    """True if the URL points at a site root (no article path). Structural — no keyword list."""
    try:
        return (urlsplit(url.strip()).path or "") in ("", "/")
    except Exception:
        return False


def _norm_match(url: str) -> str:
    """Match key = scheme + host(no 'www.') + path(no trailing slash), lowercased, NO query/fragment.

    A news article is identified by its host+path; query params (?traffic_source=rss, utm_*, etc.) are
    tracking noise that DIFFERS between the tool-returned URL and the model's cited URL. Ignoring them
    prevents false 'fabricated' flags (a path-identical, in-evidence article looking un-sourced).
    Distinct articles never share a host+path, so this cannot create false negatives.
    """
    try:
        s = urlsplit((url or "").strip())
        host = (s.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (s.path or "").rstrip("/")
        return f"{(s.scheme or 'https').lower()}://{host}{path}"
    except Exception:
        return (url or "").strip().lower()


def audit_citations(answer: str, evidence_text: str) -> Dict[str, Any]:
    """Classify every cited link in ``answer`` against the evidence URLs found in ``evidence_text``.

    Pure and offline. Returns counts + offender details. Never raises.
    """
    try:
        cited = extract_cited_links(answer or "")            # [(headline_text, url)]
    except Exception:
        cited = []

    evidence = set()
    try:
        for u in _URL_RE.findall(evidence_text or ""):
            n = _norm_match(u.rstrip('.,);]'))
            if n:
                evidence.add(n)
    except Exception:
        pass

    # normalized url -> set of distinct headline texts it is cited under
    per_url: Dict[str, set] = {}
    for text, url in cited:
        per_url.setdefault(_norm_match(url), set()).add((text or "").strip().lower())

    fabricated, bare = set(), set()
    for text, url in cited:
        n = _norm_match(url)
        # fail-safe: only call it fabricated if we actually extracted an evidence set
        if evidence and n and n not in evidence:
            fabricated.add(n)
        if _bare_homepage(url):
            bare.add(n)

    reuse_detail = {u: len(hdls) for u, hdls in per_url.items() if len(hdls) > 1}

    return {
        "cited": len(cited),
        "distinct_urls": len(per_url),
        "evidence_urls": len(evidence),
        "fabricated": len(fabricated),
        "fabricated_urls": sorted(fabricated),
        "reuse": len(reuse_detail),                 # count of URLs reused across >1 distinct headline
        "reuse_detail": reuse_detail,               # {normalized_url: distinct_headline_count}
        "bare_homepage": len(bare),
        "bare_homepage_urls": sorted(bare),
    }


def format_shadow_line(a: Dict[str, Any]) -> str:
    """One-line SHADOW log summary (safe on a partial/empty audit dict)."""
    worst_reuse = max(a.get("reuse_detail", {}).values(), default=0)
    return (
        f"🩹 nondr-citation [SHADOW]: cited={a.get('cited', 0)} "
        f"distinct={a.get('distinct_urls', 0)} evidence={a.get('evidence_urls', 0)} | "
        f"fabricated={a.get('fabricated', 0)} "
        f"reuse={a.get('reuse', 0)}(max×{worst_reuse}) "
        f"bare_homepage={a.get('bare_homepage', 0)}"
    )
