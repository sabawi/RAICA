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


_SHAPES = {"flat_json": flat_json, "worldbank": worldbank}


def get_shape(name: str):
    handler = _SHAPES.get(name or "flat_json")
    if handler is None:
        raise DatasetError(f"unknown response shape {name!r} (known: {sorted(_SHAPES)})")
    return handler
