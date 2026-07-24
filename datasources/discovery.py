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
