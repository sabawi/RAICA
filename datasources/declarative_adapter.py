"""
DeclarativeAdapter — ONE generic adapter driven by a source's config entry (design: docs/DESIGN_data_charts.md).

Replaces per-site adapter classes: a source is defined in sources.yaml (endpoint, auth, shape, field maps,
measures, metadata); this engine builds the URL, fetches, unwraps via the named response `shape`, applies the
declarative field maps, derives rates where configured, and returns a validated ``DatasetSeries``. Adding a
"normal" JSON source is now pure config. Trust machinery is unchanged: fail-closed validation +
numbers-by-reference (payload stored by id; only a request comes in).

``fetch_json`` is injectable so every source is unit-tested offline against a cached response.
"""
import datetime as _dt
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from datasources.base import DataSourceAdapter, DatasetRequest
from datasources.shapes import get_shape
from utils.dataset_block import DatasetError, DatasetSeries

logger = logging.getLogger(__name__)


def _pick(rec: Dict[str, Any], fields) -> Optional[float]:
    """First present, numeric-coercible field value among ``fields`` (a str or list of aliases)."""
    for k in ([fields] if isinstance(fields, str) else (fields or [])):
        v = rec.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


class DeclarativeAdapter(DataSourceAdapter):
    def __init__(self, name: str, cfg: Dict[str, Any]):
        if not isinstance(cfg, dict) or not cfg.get("measures"):
            raise DatasetError(f"source {name!r}: config missing 'measures'")
        self.name = name
        self.cfg = cfg
        self.source_tier = cfg.get("tier", "unknown")

    # -- advertisement --------------------------------------------------------
    def catalog(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source_tier": self.source_tier,
            "geo": [self.cfg.get("geo_label") or self.cfg.get("geo_default", "national")],
            "coverage_years": self.cfg.get("coverage", ""),
            "measures": {code: m.get("label", code) for code, m in self.cfg["measures"].items()},
            "value_kinds": self._value_kinds(),
            "note": self.cfg.get("note", ""),
        }

    def _value_kinds(self) -> List[str]:
        return list(self.cfg.get("value_kinds") or ["value"])

    # -- extraction -----------------------------------------------------------
    def extract(self, request: DatasetRequest,
                fetch_json: Optional[Callable[["DatasetRequest"], Any]] = None) -> DatasetSeries:
        if request.measure not in self.cfg["measures"]:
            raise DatasetError(f"{self.name}: unknown measure {request.measure!r} "
                               f"(known: {sorted(self.cfg['measures'])})")
        raw = (fetch_json or self._http_get)(request)
        records = get_shape(self.cfg.get("shape", "flat_json"))(raw, self.cfg)
        return self._build(records, request)

    # -- URL / params / auth (declarative) ------------------------------------
    def _fmt(self, request: DatasetRequest) -> Dict[str, Any]:
        geo = request.geo if request.geo and request.geo != "national" else self.cfg.get("geo_default", "")
        return {
            "measure_path": self.cfg["measures"][request.measure].get("path", request.measure),
            "geo_path": geo or self.cfg.get("geo_default", ""),
            "from_year": request.from_year if request.from_year is not None else "",
            "to_year": request.to_year if request.to_year is not None else "",
        }

    def _endpoint(self, request: DatasetRequest) -> str:
        return self.cfg["endpoint"].format(**self._fmt(request))

    def _build_params(self, request: DatasetRequest) -> Dict[str, Any]:
        """Query params from cfg.params, substituted + cleaned. Drops empty OR malformed PARTIAL ranges
        (e.g. '1970:' when to_year is absent, ':2024' when from is) — _build still filters by from/to, so
        dropping the param and fetching the full series is safe and correct."""
        fmt = self._fmt(request)
        params: Dict[str, Any] = {}
        for key, tmpl in (self.cfg.get("params") or {}).items():
            val = str(tmpl).format(**fmt).strip()
            if (not val) or ("{" in val) or val == ":" or val.startswith(":") or val.endswith(":"):
                continue
            params[key] = val
        return params

    def _http_get(self, request: DatasetRequest) -> Any:
        """Generic live fetch. Not exercised by offline tests (they inject fetch_json)."""
        import requests
        params = self._build_params(request)
        auth = self.cfg.get("auth") or {"type": "none"}
        if auth.get("type") == "query_key":
            key = next((os.environ.get(e) for e in auth.get("env", []) if os.environ.get(e)), None)
            if not key:
                raise DatasetError(f"{self.name}: no API key (set one of {auth.get('env')})")
            params[auth.get("param", "api_key")] = key
        resp = requests.get(self._endpoint(request), params=params, timeout=25)
        resp.raise_for_status()
        return resp.json()

    # -- parse → DatasetSeries ------------------------------------------------
    def _value_kind(self, request: DatasetRequest) -> str:
        vks = self._value_kinds()
        return request.value_kind if request.value_kind in vks else vks[0]

    def _extract_value(self, rec: Dict[str, Any], vk: str) -> Optional[float]:
        v = self.cfg["value"]
        if vk == "count" and v.get("count_field"):
            return _pick(rec, v["count_field"])
        direct = _pick(rec, v.get("field", []))
        if direct is not None:
            return direct
        if vk == "rate" and v.get("count_field") and v.get("population_field"):
            c = _pick(rec, v["count_field"])
            p = _pick(rec, v["population_field"])
            if c is not None and p:
                return round(c / p * float(v.get("rate_per", 100000)), 1)
        return None

    def _unit(self, vk: str, measure: Dict[str, Any]) -> Optional[str]:
        v = self.cfg["value"]
        if vk == "rate" and v.get("unit_rate"):
            return v["unit_rate"]
        if vk == "count" and v.get("unit_count"):
            return v["unit_count"]
        return measure.get("unit") or v.get("unit")

    def _build(self, records: List[Dict[str, Any]], request: DatasetRequest) -> DatasetSeries:
        cfg, xcfg = self.cfg, self.cfg["x"]
        measure = cfg["measures"][request.measure]
        vk = self._value_kind(request)
        rows: Dict[int, Optional[float]] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            xv = _pick(rec, xcfg["field"])
            if xv is None:
                continue
            xi = int(xv)
            if request.from_year and xi < request.from_year:
                continue
            if request.to_year and xi > request.to_year:
                continue
            rows[xi] = self._extract_value(rec, vk)     # last write wins per year
        ordered = sorted(rows.items())
        if len(ordered) < 2:
            raise DatasetError(f"{self.name}: fewer than 2 usable points for {request.measure}")

        years = [y for y, _v in ordered]
        yvals = [v for _y, v in ordered]
        label = measure.get("label", request.measure)
        disc = [{"at": d["at"], "note": d.get("note")}
                for d in cfg.get("discontinuities", [])
                if (not d.get("requires_span")) or (years[0] <= d["at"] - 1 and years[-1] >= d["at"])]
        geo_disp = cfg.get("geo_label") or (request.geo if request.geo and request.geo != "national"
                                            else cfg.get("geo_default", ""))
        title = cfg.get("title_template", "{label}, {x_min}–{x_max}").format(
            label=label, value_kind=vk, geo=geo_disp, x_min=years[0], x_max=years[-1])
        sname = f"{label} {vk}" if vk in ("rate", "count") else label

        return DatasetSeries(
            title=title, source=cfg["source_name"], url=cfg["home_url"],
            x_name=xcfg.get("name", "x"), x_type=xcfg.get("type", "temporal"), x=years,
            series=[{"name": sname, "unit": self._unit(vk, measure), "y": yvals}],
            measure=request.measure, geo=geo_disp or None,
            retrieved=_dt.date.today().isoformat(),
            methodology=cfg.get("methodology"), discontinuities=disc, source_tier=self.source_tier,
        )
