"""
Dataset source block — the contract for RAICA's data-charting feature (design: docs/DESIGN_data_charts.md).

A dataset is a first-class evidence modality: REAL numeric series fetched from a curated authoritative
source, carried through the SAME gather→verify→synthesis pipeline as text evidence. This module owns the
three load-bearing pieces of that contract — nothing here touches the pipeline yet (increment 1, offline):

  1. ``DatasetSeries`` — the validated numeric payload + provenance/meta (single- OR multi-series).
  2. The out-of-band PAYLOAD STORE (``register_dataset`` / ``get_dataset``) keyed by a ``dataset_id``.
  3. ``format_digest`` — the compact, LLM-facing text block (the ONLY thing the model sees).

THE HARD RULE THIS MODULE ENFORCES — NUMBERS-BY-REFERENCE
--------------------------------------------------------
The full x/y arrays live ONLY in the payload store, reachable by ``dataset_id``. The LLM is given the
*digest* (meta + a handful of SAMPLE points to sanity-check) and selects a dataset BY ID; the chart
renderer reads the STORED payload via ``get_dataset`` — never anything the LLM typed. The model can select
and eyeball, but can never become the origin of a plotted number. (Exact mirror of the yfinance→
chart_generator→narrate path that makes the stock charts trustworthy.)

Fail-closed: a malformed/empty series raises ``DatasetError`` at construction, so a bad extraction can
never reach the renderer. See also the discontinuity metadata (``discontinuities``), which the renderer
uses to SEGMENT/annotate rather than silently bridge (e.g. FBI SRS→NIBRS 2021).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

XValue = Union[int, float, str]          # temporal/quantitative -> number; categorical -> label
YValue = Optional[float]                 # None == genuine gap (renderer skips; never invented)

_X_TYPES = ("temporal", "quantitative", "categorical")
_TIERS = ("structured_api", "bulk_file", "html_table", "unknown")  # extraction-fidelity, best→worst


class DatasetError(ValueError):
    """Raised on a malformed dataset (fail-closed: no chart is ever built from bad data)."""


def _is_real_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


@dataclass
class DatasetSeries:
    """One chart-ready dataset: a shared X axis plus one or more aligned Y series, with provenance.

    ``series`` = [{"name": str, "unit": str|None, "y": [YValue, ...]}] — each ``y`` aligned 1:1 to ``x``.
    Single-series (MVP) has one entry; multi-series (relationships, later) has several sharing ``x``.
    """
    title: str
    source: str
    url: str
    x_name: str
    x_type: str                                  # one of _X_TYPES
    x: List[XValue]
    series: List[Dict[str, Any]]
    measure: Optional[str] = None
    geo: Optional[str] = None
    retrieved: Optional[str] = None              # ISO date the data was fetched
    methodology: Optional[str] = None
    discontinuities: List[Dict[str, Any]] = field(default_factory=list)  # [{"at": XValue, "note": str}]
    source_tier: str = "unknown"                 # extraction fidelity (see _TIERS)

    def __post_init__(self):
        self.validate()

    # -- validation (fail-closed) ---------------------------------------------
    def validate(self) -> "DatasetSeries":
        for fld in ("title", "source", "url", "x_name"):
            if not (isinstance(getattr(self, fld), str) and getattr(self, fld).strip()):
                raise DatasetError(f"dataset missing required field: {fld}")
        if self.x_type not in _X_TYPES:
            raise DatasetError(f"x_type must be one of {_X_TYPES}, got {self.x_type!r}")
        if not isinstance(self.x, list) or len(self.x) < 2:
            raise DatasetError("dataset x-axis must have >= 2 points")
        if self.x_type == "categorical":
            if not all(isinstance(v, str) and v.strip() for v in self.x):
                raise DatasetError("categorical x values must be non-empty strings")
        else:  # temporal / quantitative
            if not all(_is_real_number(v) for v in self.x):
                raise DatasetError(f"{self.x_type} x values must all be finite numbers")
        if not isinstance(self.series, list) or not self.series:
            raise DatasetError("dataset must have >= 1 y-series")
        for i, s in enumerate(self.series):
            if not isinstance(s, dict) or not (isinstance(s.get("name"), str) and s["name"].strip()):
                raise DatasetError(f"series[{i}] missing a name")
            y = s.get("y")
            if not isinstance(y, list) or len(y) != len(self.x):
                raise DatasetError(f"series[{i}] '{s.get('name')}' y-length {len(y) if isinstance(y,list) else '?'} "
                                   f"!= x-length {len(self.x)}")
            if not all(v is None or _is_real_number(v) for v in y):
                raise DatasetError(f"series[{i}] '{s.get('name')}' has non-numeric y values")
            if all(v is None for v in y):
                raise DatasetError(f"series[{i}] '{s.get('name')}' is entirely empty")
        if self.source_tier not in _TIERS:
            raise DatasetError(f"source_tier must be one of {_TIERS}, got {self.source_tier!r}")
        for d in self.discontinuities:
            if not isinstance(d, dict) or "at" not in d:
                raise DatasetError("each discontinuity needs an 'at' x-value")
        return self

    def n_points(self) -> int:
        return len(self.x)

    def fingerprint(self) -> str:
        """Stable content hash → dedup identical datasets to the same id (like the chart cache)."""
        payload = json.dumps(
            {"t": self.title, "s": self.source, "u": self.url, "xn": self.x_name,
             "x": self.x, "ser": [(s["name"], s.get("y")) for s in self.series]},
            sort_keys=True, default=str)
        return hashlib.sha1(payload.encode()).hexdigest()[:10]


# ── out-of-band payload store (numbers-by-reference) ─────────────────────────
_STORE: Dict[str, "tuple[DatasetSeries, float]"] = {}   # id -> (series, expiry_ts)
_LOCK = threading.Lock()
_DEFAULT_TTL = 1800.0


def register_dataset(series: DatasetSeries, ttl: float = _DEFAULT_TTL) -> str:
    """Store the full payload; return its ``dataset_id``. Identical datasets dedup to one id."""
    series.validate()
    ds_id = f"ds_{series.fingerprint()}"
    with _LOCK:
        _prune_locked()
        _STORE[ds_id] = (series, time.time() + ttl)
    return ds_id


def get_dataset(dataset_id: str) -> Optional[DatasetSeries]:
    """Fetch a stored payload by id (the ONLY numeric source the renderer may use). None if absent/expired."""
    with _LOCK:
        entry = _STORE.get(dataset_id)
        if not entry:
            return None
        series, expiry = entry
        if time.time() > expiry:
            _STORE.pop(dataset_id, None)
            return None
        return series


def reset_datasets() -> None:
    with _LOCK:
        _STORE.clear()


def _prune_locked() -> None:
    now = time.time()
    for k in [k for k, (_s, exp) in _STORE.items() if now > exp]:
        _STORE.pop(k, None)


# ── LLM-facing digest (the only thing the model sees) ────────────────────────
def _fmt_x(v: XValue) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _sample_points(series: DatasetSeries, s: Dict[str, Any], k: int = 4) -> List[str]:
    """A few real (x, y) points (first / spread / last) so the LLM can sanity-check — NOT the full array."""
    y = s["y"]
    idxs = sorted({0, len(series.x) // 3, 2 * len(series.x) // 3, len(series.x) - 1})[:k]
    out = []
    for i in idxs:
        if y[i] is not None:
            out.append(f"({_fmt_x(series.x[i])}, {y[i]:g})")
    return out


def format_digest(series: DatasetSeries, dataset_id: str) -> str:
    """Render the compact SOURCE-block text the LLM reads (becomes the evidence item's ``content``).

    Carries provenance + shape + a handful of sample points + the ``dataset_id`` to select by — enough to
    grade/verify/select/narrate, never the raw table."""
    lines = [
        "DATASET (RAICA-fetched numeric data — a REAL, chart-ready series pulled directly from an "
        "authoritative data source; NOT web-scraped prose and NOT model-generated):",
        f"  dataset_id: {dataset_id}",
        f"  Title: {series.title}",
        f"  Source: {series.source} — {series.url}"
        + (f" (retrieved {series.retrieved})" if series.retrieved else "")
        + f"  [extraction: {series.source_tier}]",
    ]
    meta = []
    if series.measure:
        meta.append(f"measure: {series.measure}")
    if series.geo:
        meta.append(f"geography: {series.geo}")
    if meta:
        lines.append("  " + " · ".join(meta))
    xr = (f"{_fmt_x(min(series.x))} → {_fmt_x(max(series.x))}"
          if series.x_type != "categorical" else f"{len(series.x)} categories")
    lines.append(f"  X: {series.x_name} ({series.x_type}), {series.n_points()} points, {xr}")
    # For a modest temporal series (annual socioeconomic data is ≤ ~66 points) give the LLM the FULL series,
    # not 4 samples — otherwise it writes a year-by-year narrative and INVENTS the values for years it wasn't
    # shown, recalling them from training (observed: a housing answer cited Case-Shiller "220 in 2020",
    # mortgage "2.7% in 2021", starts ">2M in 2005-06" — none in the 4-sample digest; the verifier flagged 11
    # such claims). Real numbers in-context = grounded citations AND a verifier that can actually check them.
    # Numbers-by-reference is preserved: the CHART still renders from the stored payload; this just lets the
    # LLM cite the true values instead of hallucinating them.
    _full = (series.x_type != "categorical") and series.n_points() <= 80
    _any_index = False
    for s in series.series:
        unit = f" [{s['unit']}]" if s.get("unit") else ""
        if s.get("unit") and "index" in str(s["unit"]).lower():
            _any_index = True
        if _full:
            pts = [f"({_fmt_x(x)}, {y:g})" for x, y in zip(series.x, s["y"]) if y is not None]
            lines.append(f"  Series '{s['name']}'{unit} — FULL series, {len(pts)} pts: " + ", ".join(pts))
        else:
            lines.append(f"  Series '{s['name']}'{unit}: sample of {series.n_points()} pts "
                         + ", ".join(_sample_points(series, s)))
    if series.methodology:
        lines.append(f"  Methodology: {series.methodology}")
    if series.discontinuities:
        ds = "; ".join(f"{_fmt_x(d['at'])}"
                       + (f" ({d['note']})" if d.get("note") else "") for d in series.discontinuities)
        lines.append(f"  Discontinuities (do NOT bridge — annotate/segment): {ds}")
    # Grounding: cite ONLY the values given, and never mistake an index for a price.
    _g = ("  GROUNDING — cite ONLY the values above: give a number for a year ONLY if it is listed here; do "
          "NOT state a value for any year not shown, and do NOT fill gaps from memory (that is fabrication).")
    if _any_index:
        _g += (" An INDEX series (unit contains 'index') measures RELATIVE change from a base period — it is "
               "NOT a dollar/price level: never treat it as a price, never derive a price-to-income or "
               "affordability MULTIPLE from it, and never compare an index value directly to a dollar figure.")
    lines.append(_g)
    return "\n".join(lines)
