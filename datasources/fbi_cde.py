"""
FBI Crime Data Explorer (CDE) adapter — the MVP data source for the data-charting feature.

Serves national yearly crime estimates (counts + rates) for the standard UCR offenses, with the
SRS→NIBRS 2021 methodology break carried as METADATA (a documented property of FBI crime data — so the
renderer segments/annotates it rather than guessing). Deterministic structured-API source
(``source_tier="structured_api"``).

⚠️ WIRE SHAPE IS ASSUMED — CONFIRM ON FIRST LIVE FETCH. The exact CDE endpoint path and JSON field names
are modeled here from the public API's documented shape but have NOT been validated against a live call
(needs a free api.data.gov key). ``_parse`` is deliberately tolerant of common field aliases; the offline
tests validate the PARSE LOGIC + DatasetSeries construction, NOT that the shape matches production. When a
key is available, run one live fetch and reconcile ``_endpoint`` / field names here.

Env key: ``FBI_CDE_API_KEY`` or ``DATA_GOV_API_KEY`` (one api.data.gov key works across data.gov APIs).
"""
import datetime as _dt
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from datasources.base import DataSourceAdapter, DatasetRequest
from utils.dataset_block import DatasetError, DatasetSeries

logger = logging.getLogger(__name__)


class FbiCdeAdapter(DataSourceAdapter):
    name = "fbi_cde"
    source_tier = "structured_api"
    BASE = "https://api.usa.gov/crime/fbi/cde"
    HOME = "https://cde.ucr.cjis.gov/"
    NIBRS_BREAK_YEAR = 2021

    # Catalog vocabulary: our code -> (human label, CDE offense path). This is the API's OWN offense
    # vocabulary (a data-schema map advertised to the LLM), NOT an interpretation of user language.
    OFFENSES: Dict[str, "tuple[str, str]"] = {
        "violent-crime": ("violent crime", "violent-crime"),
        "homicide": ("homicide", "homicide"),
        "rape": ("rape", "rape"),
        "robbery": ("robbery", "robbery"),
        "aggravated-assault": ("aggravated assault", "aggravated-assault"),
        "property-crime": ("property crime", "property-crime"),
        "burglary": ("burglary", "burglary"),
        "larceny": ("larceny-theft", "larceny"),
        "motor-vehicle-theft": ("motor vehicle theft", "motor-vehicle-theft"),
        "arson": ("arson", "arson"),
    }

    # -- advertisement (for LLM matching in the plan/enumerate step) ----------
    def catalog(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source_tier": self.source_tier,
            "geo": ["US-national"],
            "coverage_years": "~1979–present (SRS through 2020; NIBRS 2021+)",
            "measures": {code: label for code, (label, _p) in self.OFFENSES.items()},
            "value_kinds": ["rate", "count"],  # rate = per 100,000 population
            "note": ("FBI national crime estimates. Methodology break at 2021 (SRS→NIBRS) is emitted as a "
                     "discontinuity so it is segmented, never bridged."),
        }

    # -- extraction -----------------------------------------------------------
    def extract(self, request: DatasetRequest,
                fetch_json: Optional[Callable[["DatasetRequest"], Any]] = None) -> DatasetSeries:
        if request.measure not in self.OFFENSES:
            raise DatasetError(f"fbi_cde: unknown offense {request.measure!r} "
                               f"(known: {sorted(self.OFFENSES)})")
        if request.geo not in ("national", "US-national"):
            raise DatasetError(f"fbi_cde: only national geo supported at MVP, got {request.geo!r}")
        if request.value_kind not in ("rate", "count"):
            raise DatasetError(f"fbi_cde: value_kind must be 'rate' or 'count', got {request.value_kind!r}")
        raw = (fetch_json or self._http_get)(request)
        return self._parse(raw, request)

    def _endpoint(self, request: DatasetRequest) -> str:
        return f"{self.BASE}/estimate/national/{self.OFFENSES[request.measure][1]}"

    def _http_get(self, request: DatasetRequest) -> Any:
        """Live fetch (deferred — needs an api.data.gov key). Not exercised by the offline tests."""
        import requests
        key = os.environ.get("FBI_CDE_API_KEY") or os.environ.get("DATA_GOV_API_KEY")
        if not key:
            raise DatasetError("fbi_cde: no API key (set DATA_GOV_API_KEY or FBI_CDE_API_KEY)")
        params = {"API_KEY": key}
        if request.from_year:
            params["from"] = request.from_year
        if request.to_year:
            params["to"] = request.to_year
        resp = requests.get(self._endpoint(request), params=params, timeout=25)
        resp.raise_for_status()
        return resp.json()

    # -- parsing (tolerant of common field aliases) ---------------------------
    @staticmethod
    def _records(raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            for k in ("results", "data", "offenses", "estimates"):
                if isinstance(raw.get(k), list):
                    return raw[k]
        raise DatasetError("fbi_cde: unrecognized response shape (no results list)")

    @staticmethod
    def _pick(rec: Dict[str, Any], *keys) -> Optional[float]:
        for k in keys:
            if rec.get(k) is not None:
                try:
                    return float(rec[k])
                except (TypeError, ValueError):
                    return None
        return None

    def _parse(self, raw: Any, request: DatasetRequest) -> DatasetSeries:
        recs = self._records(raw)
        rows = []  # (year:int, value:float|None)
        for rec in recs:
            yr = self._pick(rec, "data_year", "year", "yr")
            if yr is None:
                continue
            yr = int(yr)
            if request.from_year and yr < request.from_year:
                continue
            if request.to_year and yr > request.to_year:
                continue
            count = self._pick(rec, "count", "value", "actual", "estimate")
            pop = self._pick(rec, "population", "pop")
            if request.value_kind == "count":
                val = count
            else:  # rate per 100k — prefer a provided rate, else derive from count/population
                val = self._pick(rec, "rate", "rate_per_100000")
                if val is None and count is not None and pop:
                    val = round(count / pop * 100000, 1)
            rows.append((yr, val))

        rows = sorted({y: v for y, v in rows}.items())  # dedup by year, ascending
        if len(rows) < 2:
            raise DatasetError("fbi_cde: fewer than 2 usable yearly points after parse")

        years = [y for y, _v in rows]
        yvals = [v for _y, v in rows]
        label = self.OFFENSES[request.measure][0]
        unit = "per 100,000" if request.value_kind == "rate" else "offenses"
        # SRS→NIBRS break only if the span actually crosses it.
        disc = ([{"at": self.NIBRS_BREAK_YEAR, "note": "SRS→NIBRS"}]
                if years[0] <= self.NIBRS_BREAK_YEAR - 1 and years[-1] >= self.NIBRS_BREAK_YEAR else [])
        method = ("FBI UCR estimates: Summary Reporting System (SRS) through 2020, "
                  "National Incident-Based Reporting System (NIBRS) 2021–present.")

        return DatasetSeries(
            title=f"U.S. {label} {request.value_kind}, {years[0]}–{years[-1]}",
            source="FBI UCR / Crime Data Explorer",
            url=self.HOME,
            x_name="year", x_type="temporal", x=years,
            series=[{"name": f"{label} {request.value_kind}", "unit": unit, "y": yvals}],
            measure=request.measure, geo="US-national",
            retrieved=_dt.date.today().isoformat(),
            methodology=method, discontinuities=disc, source_tier=self.source_tier,
        )
