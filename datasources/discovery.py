"""
Dynamic dataset discovery — resolve a plain-language DESCRIPTION (or a provider series id) to a real,
fetchable series via the provider's own search API, so the catalog does not have to hand-list every series.

This is the generalization of the fixed catalog: the tool-calling LLM says WHAT it wants ("Case-Shiller home
price index", "homeownership rate", "30-year mortgage rate") and the provider search finds WHERE it lives.
NUMBERS-BY-REFERENCE is preserved — the LLM supplies only a search intent, never a data point; the resolver
returns an id + honest metadata (title, unit, coverage) and the adapter fetches the stored series.

Currently implements FRED (St. Louis Fed) `series/search` — a huge, uniformly-shaped US economic/financial/
housing/labor/demographic catalog. Other providers (World Bank indicator search, data.gov/CKAN, FBI) are
heterogeneous and are a documented next step, not half-built here.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _start_year(s: Dict[str, Any]) -> int:
    try:
        return int((s.get("observation_start") or "9999")[:4])
    except (ValueError, TypeError):
        return 9999


def fred_search(search_text: str, from_year: Optional[int], to_year: Optional[int],
                api_key: str, disc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve a description to the best-matching FRED series. Returns {path,label,unit,coverage,frequency}
    or None. Ranking (best first): NOT discontinued → COVERS the requested start year → higher popularity.
    Coverage-awareness is what makes a 40-year 'home prices' ask resolve to a long series (Case-Shiller 1987+)
    rather than a recent index. If a description is actually already a FRED series id, search returns it too."""
    import re
    import requests
    text = (search_text or "").strip()
    if not text:
        return None
    # FRED full-text search is punctuation-sensitive: a verbose official name with a slash returns garbage
    # (observed: "S&P/Case-Shiller U.S. National Home Price Index" → 1 obscure pop=1 discontinued series,
    # while "S&P Case-Shiller …" → CSUSHPINSA pop=84). Replace slashes/brackets with spaces so the tokens
    # match; keep '&', '-' and alphanumerics which FRED handles fine.
    text = re.sub(r"[/\\()\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    endpoint = disc.get("search_endpoint", "https://api.stlouisfed.org/fred/series/search")
    limit = int(disc.get("limit", 12))
    min_pop = float(disc.get("min_popularity", 5))   # reject near-zero-popularity matches (almost always wrong)
    params = {"search_text": text, "api_key": api_key, "file_type": "json",
              "limit": limit, "order_by": "popularity", "sort_order": "desc"}
    try:
        sess = requests.Session()
        resp = sess.get(endpoint, params=params, timeout=float(disc.get("timeout_seconds", 12)),
                        headers={"Connection": "close"})
        resp.raise_for_status()
        seriess = (resp.json() or {}).get("seriess", []) or []
    except Exception as e:  # noqa: BLE001 — scrub the key from any error before it can be logged upstream
        raise RuntimeError(f"fred search failed: {str(e).replace(api_key, '***')}") from None
    finally:
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass
    if not seriess:
        return None

    want = from_year
    def _covers(s):
        return want is None or _start_year(s) <= int(want) + 2   # small slack for annual boundaries

    ranked = sorted(
        seriess,
        key=lambda s: (
            1 if (s.get("title", "") or "").upper().rstrip().endswith("(DISCONTINUED)") else 0,
            0 if _covers(s) else 1,
            -float(s.get("popularity") or 0),
        ),
    )
    best = ranked[0]
    # Quality floor: a top match with near-zero popularity is almost never what the user meant (it's a
    # tokens-happened-to-match artifact). Fail-closed rather than chart a wrong series under the asked label.
    if float(best.get("popularity") or 0) < min_pop:
        logger.info("🔎 fred discovery: best match %s pop=%s below floor %s for %r — rejecting (fail-closed)",
                    best.get("id"), best.get("popularity"), min_pop, text)
        return None
    unit = best.get("units_short") or best.get("units") or None
    cov = f"{(best.get('observation_start') or '?')[:4]}–{(best.get('observation_end') or '?')[:4]}"
    return {
        "path": best["id"],
        "label": best.get("title") or best["id"],
        "unit": unit,
        "coverage": cov,
        "frequency": best.get("frequency_short"),
    }


# ── World Bank ────────────────────────────────────────────────────────────────────────────────────────
# WB has NO usable full-text search and NO popularity signal (unlike FRED), and thousands of near-duplicate
# indicators — so name-matching a description cannot RELIABLY pick the canonical indicator. The reliable path
# is the CODE: the LLM knows standard WB indicator codes (FP.CPI.TOTL.ZG, SL.UEM.TOTL.ZS, …) from training,
# and /v2/indicator/{code} validates them exactly. A description is BEST-EFFORT: IDF-ranked over the WDI list,
# accepted only above a relevance floor, and always reported (a wrong pick is visible in the chart caption),
# else fail-closed. So the honest contract: give a code for accuracy; describe for convenience.
_WB_CODE_RE = None
_WDI_CACHE: Dict[str, Any] = {"inds": None}


def _unit_from_name(name: str) -> Optional[str]:
    import re
    m = re.search(r"\(([^)]*(?:%|US\$|per |years|people|index|kg|sq\.|current|constant)[^)]*)\)", name or "")
    return m.group(1) if m else None


def _wdi_indicators(base: str):
    """WDI (source=2) indicator list with canonical dotted codes, fetched once and cached per process."""
    if _WDI_CACHE["inds"] is None:
        import re
        import requests
        std = re.compile(r"^[A-Za-z]{2,4}\.[A-Za-z0-9.]+$")
        try:
            r = requests.get(f"{base}/indicator", params={"source": 2, "format": "json", "per_page": 25000},
                             timeout=40, headers={"Connection": "close"})
            data = r.json()
            inds = data[1] if isinstance(data, list) and len(data) > 1 else []
            _WDI_CACHE["inds"] = [it for it in inds if std.match(it.get("id", ""))]
        except Exception:  # noqa: BLE001
            _WDI_CACHE["inds"] = []
    return _WDI_CACHE["inds"]


def _wb_code_has_data(base: str, code: str, from_year: Optional[int], to_year: Optional[int],
                      disc: Dict[str, Any]) -> bool:
    """True unless WB DEFINITIVELY returns no usable data for this code (archived/invalid). CONSERVATIVE:
    any network/timeout/parse ambiguity returns True (assume live — NEVER heal a good code over a transient
    hiccup). Only a clean error envelope ('Invalid value') or an all-null data page counts as dataless. USA
    is the canary (an archived indicator is archived for every country); source=2/WDI mirrors the adapter."""
    import requests
    params: Dict[str, Any] = {"format": "json", "source": 2, "per_page": 120}
    if from_year and to_year:
        params["date"] = f"{int(from_year)}:{int(to_year)}"
    try:
        r = requests.get(f"{base}/country/USA/indicator/{code}", params=params,
                         timeout=float(disc.get("timeout_seconds", 15)), headers={"Connection": "close"})
        d = r.json()
    except Exception:  # noqa: BLE001 — transient → assume live, do NOT heal a possibly-good code
        return True
    if isinstance(d, list) and d and isinstance(d[0], dict) and d[0].get("message"):
        return False                                   # error envelope (e.g. 'Invalid value') → dataless
    if isinstance(d, list) and len(d) > 1 and isinstance(d[1], list):
        return any(x.get("value") is not None for x in d[1])   # live iff ≥1 real value in range
    return True                                        # unexpected shape → assume live


def wb_search(search_text: str, from_year: Optional[int], to_year: Optional[int],
              disc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve a World Bank indicator from a CODE (exact, reliable) or a DESCRIPTION (best-effort). Returns
    {path,label,unit,coverage} or None (fail-closed).

    SELF-HEALING (v1.0.0.228): a code can be metadata-VALID yet ARCHIVED — WB keeps the definition but drops
    the data (e.g. EN.ATM.CO2E.KT/.PC were superseded by the EN.GHG.CO2.* AR5 series). Accepting such a code
    fails-closed SILENTLY downstream (empty series → skipped → no chart, no explanation). So when a code has no
    live data we re-resolve it to a LIVE sibling by its OWN metadata name — dimension-guarded (a 'per capita'
    code never heals to a 'total' series, and vice-versa) and re-verified to actually carry data, so the heal
    is either a correct live series or fail-closed, never a silently wrong one."""
    import re
    import requests
    text = (search_text or "").strip()
    if not text:
        return None
    base = disc.get("base", "https://api.worldbank.org/v2")

    # 1) exact code path — the reliable one (with archived-code self-heal)
    heal_dimension: Optional[str] = None    # None=normal; 'percapita'/'absolute' to preserve when re-resolving
    if re.match(r"^[A-Za-z]{2,4}\.[A-Za-z0-9.]+$", text):
        meta_name = None
        try:
            r = requests.get(f"{base}/indicator/{text}", params={"format": "json"},
                             timeout=float(disc.get("timeout_seconds", 15)), headers={"Connection": "close"})
            d = r.json()
            if isinstance(d, list) and len(d) > 1 and d[1]:
                meta_name = d[1][0].get("name") or text
        except Exception:  # noqa: BLE001 — invalid code → fall through to name search
            meta_name = None
        if meta_name is not None:
            if _wb_code_has_data(base, text, from_year, to_year, disc):
                return {"path": text, "label": meta_name, "unit": _unit_from_name(meta_name), "coverage": ""}
            # metadata-valid but ARCHIVED → re-resolve its own name to a live sibling, preserving dimension.
            logger.info("🔎 wb discovery: code %r (%s) archived/dataless — re-resolving to a live series",
                        text, meta_name)
            text = meta_name
            heal_dimension = "percapita" if "per capita" in meta_name.lower() else "absolute"
        # else: unknown code → fall through to name search with the original text

    # 2) description path — best-effort IDF match over the WDI list
    import math
    from collections import Counter
    inds = _wdi_indicators(base)
    if not inds:
        return None
    tok = lambda s: re.findall(r"[a-z0-9]+", (s or "").lower())  # noqa: E731
    df: Counter = Counter()
    for it in inds:
        for t in set(tok(it["name"])):
            df[t] += 1
    n = len(inds)
    idf = lambda t: math.log((n + 1) / (df.get(t, 0) + 1)) + 1  # noqa: E731
    qs = set(tok(text))
    if not qs:
        return None
    best, best_score = None, 0.0
    for it in inds:
        nm = it["name"].lower()
        # dimension guard (heal only): never swap a per-capita measure for a total one or vice-versa
        if heal_dimension == "percapita" and "per capita" not in nm:
            continue
        if heal_dimension == "absolute" and "per capita" in nm:
            continue
        ns = set(tok(it["name"]))
        matched = qs & ns
        if not matched:
            continue
        score = sum(idf(t) for t in matched) * (len(matched) / len(qs))
        if "total" in ns:                # nudge toward the headline "total" form over disaggregations
            score += 0.5
        score -= 0.08 * len(ns)          # prefer concise headline names
        if score > best_score:
            best, best_score = it, score
    floor = float(disc.get("min_score", 1.5))
    if best is None or best_score < floor:
        logger.info("🔎 wb discovery: no confident match for %r (best_score=%.2f < %.2f) — fail-closed",
                    text, best_score, floor)
        return None
    # when healing, the re-resolved pick must itself be LIVE — never heal one archived code into another.
    if heal_dimension is not None and not _wb_code_has_data(base, best["id"], from_year, to_year, disc):
        logger.info("🔎 wb discovery: heal candidate %s also dataless — fail-closed", best["id"])
        return None
    if heal_dimension is not None:
        logger.info("🔎 wb discovery: healed archived code → %s (%s)", best["id"], best["name"])
    return {"path": best["id"], "label": best["name"], "unit": _unit_from_name(best["name"]), "coverage": ""}
