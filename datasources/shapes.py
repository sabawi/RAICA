"""
Response-shape handlers (design: docs/DESIGN_data_charts.md).

Each handler unwraps ONE family of API response envelopes down to a flat ``List[dict]`` of records; the
DeclarativeAdapter then applies the (declarative) field maps uniformly. This is the small, reusable library
that absorbs structural variety so that most sources are pure config — a source picks a handler via
``shape:`` and reuses it. Add a new handler only for a genuinely new envelope; never per-site code.

A handler raises ``DatasetError`` on an unrecognized envelope (fail-closed).
"""
from typing import Any, Dict, List

from utils.dataset_block import DatasetError


def flat_json(raw: Any, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Records live at ``cfg['records_path']`` (dotted) inside a dict, or ``raw`` is already a list.
    Falls back to common array keys. Covers most REST JSON APIs (FBI CDE, FRED-style, many gov endpoints)."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        path = cfg.get("records_path")
        if path:
            node: Any = raw
            for part in str(path).split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, list):
                return node
        for k in ("results", "data", "observations", "estimates", "rows"):
            if isinstance(raw.get(k), list):
                return raw[k]
    raise DatasetError("shape flat_json: no records list found")


def worldbank(raw: Any, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """World Bank v2 wraps data as ``[ <metadata dict>, [ <record>, ... ] ]``; the data is element [1]."""
    if isinstance(raw, list) and len(raw) >= 2 and isinstance(raw[1], list):
        return raw[1]
    # WB returns a 1-element list with a 'message' when the query is bad → fail-closed
    raise DatasetError("shape worldbank: expected [metadata, data] envelope")


def fbi_cde_summarized(raw: Any, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """FBI Crime Data Explorer `summarized/national/{offense}` envelope (discovered live 2026-07-21; the old
    `estimate/national` endpoint + all public docs are dead — see SUSPECTED_ISSUES SI-004). Shape:
        {"offenses": {"rates":   {"United States Offenses": {"MM-YYYY": rate_per_100k_monthly, ...}, ...},
                      "actuals": {"United States Offenses": {"MM-YYYY": absolute_count_monthly,  ...}, ...}}}
    The series is MONTHLY; we AGGREGATE to ANNUAL (sum the 12 monthly values → annual rate per 100k / annual
    count) and emit one record per COMPLETE (12-month) year, so a partial current year never shows as a cliff.
    Coverage ~1985–present. Returns records {year, rate, count} the declarative field maps then pick from."""
    if not isinstance(raw, dict):
        raise DatasetError("shape fbi_cde_summarized: expected a JSON object")
    off = raw.get("offenses")
    if not isinstance(off, dict):
        raise DatasetError("shape fbi_cde_summarized: no 'offenses' block")
    rates = ((off.get("rates") or {}).get("United States Offenses")) or {}
    actuals = ((off.get("actuals") or {}).get("United States Offenses")) or {}
    if not rates and not actuals:
        raise DatasetError("shape fbi_cde_summarized: no 'United States Offenses' series")

    def _year(mkey: str):
        try:
            _mm, yyyy = str(mkey).split("-")
            return int(yyyy)
        except (ValueError, AttributeError):
            return None

    by_year: Dict[int, Dict[str, Any]] = {}
    for mkey, val in rates.items():
        y = _year(mkey)
        if y is None or val is None:
            continue
        d = by_year.setdefault(y, {"rate": 0.0, "count": 0.0, "months": 0})
        d["rate"] += float(val)
        d["months"] += 1                      # completeness tracked on the rate series
    for mkey, val in actuals.items():
        y = _year(mkey)
        if y is None or val is None:
            continue
        by_year.setdefault(y, {"rate": 0.0, "count": 0.0, "months": 0})["count"] += float(val)

    records = [{"year": y, "rate": round(d["rate"], 2), "count": int(d["count"])}
               for y, d in sorted(by_year.items()) if d["months"] == 12]
    if len(records) < 2:
        raise DatasetError("shape fbi_cde_summarized: fewer than 2 complete years of data")
    return records


_SHAPES = {"flat_json": flat_json, "worldbank": worldbank, "fbi_cde_summarized": fbi_cde_summarized}


def get_shape(name: str):
    handler = _SHAPES.get(name or "flat_json")
    if handler is None:
        raise DatasetError(f"unknown response shape {name!r} (known: {sorted(_SHAPES)})")
    return handler
