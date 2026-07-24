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
        # Series resolved at runtime by dynamic discovery (e.g. FRED search), keyed by resolved id →
        # a synthesized measure spec {path,label,unit,coverage}. Idempotent cache; safe to share.
        self._discovered: Dict[str, Dict[str, Any]] = {}

    # -- advertisement --------------------------------------------------------
    def catalog(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source_tier": self.source_tier,
            "geo": self.cfg.get("geo_hint") or [self.cfg.get("geo_label") or self.cfg.get("geo_default", "national")],
            "coverage_years": self.cfg.get("coverage", ""),
            "measures": {code: m.get("label", code) for code, m in self.cfg["measures"].items()},
            "value_kinds": self._value_kinds(),
            "note": self.cfg.get("note", ""),
        }

    def _value_kinds(self) -> List[str]:
        return list(self.cfg.get("value_kinds") or ["value"])

    # -- extraction -----------------------------------------------------------
    @staticmethod
    def _norm(s: str) -> str:
        """Lowercase and strip everything but alphanumerics — for tolerant identifier matching. NFKC-normalize
        first so unicode presentation forms fold to ASCII (e.g. subscript '₂' → '2'), letting the LLM's plain
        'CO2 emissions per capita' match a catalog label written with the subscript 'CO₂'."""
        import unicodedata
        s = unicodedata.normalize("NFKC", s or "")
        return "".join(ch for ch in s.lower() if ch.isalnum())

    def _resolve_measure(self, measure: str) -> Optional[str]:
        """Map the caller's measure string to a catalog CODE. The LLM sometimes passes the human LABEL
        ('CO2 emissions per capita') or a lightly-varied code instead of the exact key ('co2-per-capita').
        Resolve by matching, in order: exact key → normalized key → normalized label → substring on either.
        This is deterministic DATA resolution against the catalog (like the geo resolver), not intent
        classification. Returns the catalog key, or None if nothing matches (caller fails closed)."""
        measures = self.cfg["measures"]
        if measure in measures:
            return measure
        nm = self._norm(measure)
        if not nm:
            return None
        # normalized exact match on key or label
        for key, spec in measures.items():
            if self._norm(key) == nm or self._norm(spec.get("label", "")) == nm:
                return key
        # substring either direction (e.g. 'co2 per capita' ⊂ label, or label ⊂ a longer phrase)
        for key, spec in measures.items():
            nk, nl = self._norm(key), self._norm(spec.get("label", ""))
            if nk and (nk in nm or nm in nk):
                return key
            if nl and (nl in nm or nm in nl):
                return key
        return None

    def _spec(self, measure_key: str) -> Dict[str, Any]:
        """The measure spec for a key — a catalog entry OR a runtime-discovered series. One accessor so
        _fmt/_build resolve both transparently."""
        return self.cfg["measures"].get(measure_key) or self._discovered.get(measure_key) or {}

    def _discover_measure(self, request: DatasetRequest) -> Optional[str]:
        """DYNAMIC DISCOVERY fallback (when a source declares `discovery`): the caller's `measure` is a plain
        DESCRIPTION (or a provider series id) rather than a catalog code, and we resolve it to a real series
        via the provider's own search — so the catalog need not hand-list every series. Numbers-by-reference
        holds: the LLM supplies only a search intent; the tool finds the id and fetches the data. Populates
        self._discovered with the resolved spec and returns its id (or None → caller fails closed)."""
        disc = self.cfg.get("discovery") or {}
        dtype = disc.get("type")
        try:
            if dtype == "fred_search":
                auth = self.cfg.get("auth") or {}
                key = next((os.environ.get(e) for e in auth.get("env", []) if os.environ.get(e)), None)
                if not key:
                    return None
                from datasources.discovery import fred_search
                spec = fred_search(request.measure, request.from_year, request.to_year, key, disc)
            elif dtype == "wb_search":            # World Bank is keyless
                from datasources.discovery import wb_search
                spec = wb_search(request.measure, request.from_year, request.to_year, disc)
            else:
                return None
        except Exception as e:  # noqa: BLE001 — discovery must never break the run
            logger.warning("🔎 %s discovery error for %r: %s", dtype, request.measure, e)
            return None
        if not spec:
            return None
        sid = spec["path"]
        self._discovered[sid] = spec
        logger.info("🔎 %s discovery: %r → %s (%s; coverage %s)",
                    dtype, request.measure, sid, spec.get("label"), spec.get("coverage"))
        return sid

    def extract(self, request: DatasetRequest,
                fetch_json: Optional[Callable[["DatasetRequest"], Any]] = None) -> DatasetSeries:
        resolved = self._resolve_measure(request.measure)
        if resolved is None:
            resolved = self._discover_measure(request)      # dynamic discovery (e.g. FRED search)
        if resolved is None:
            raise DatasetError(f"{self.name}: unknown measure {request.measure!r} "
                               f"(known: {sorted(self.cfg['measures'])}; discovery found nothing)")
        if resolved != request.measure:
            logger.info("🔎 data_chart measure resolved %r → %r", request.measure, resolved)
            request.measure = resolved
        raw = (fetch_json or self._http_get)(request)
        records = get_shape(self.cfg.get("shape", "flat_json"))(raw, self.cfg)
        return self._build(records, request)

    # -- URL / params / auth (declarative) ------------------------------------
    def _resolve_geo(self, geo: str) -> str:
        """Normalize a geography to the source's expected code. For geo_resolver=iso3 (World Bank), map a
        country NAME or code to an ISO-3166 alpha-3 code — so 'Egypt', 'egypt' and 'EGY' all work. The LLM
        won't reliably emit codes, so the adapter resolves it (a data lookup, not intent classification).
        Fail-open: an unrecognized value passes through (fails closed downstream if the API rejects it)."""
        g = (geo or "").strip()
        if self.cfg.get("geo_resolver") != "iso3" or not g:
            return g
        if g.upper() in ("WLD", "WORLD", "ALL"):
            return "WLD"
        try:
            import pycountry
            c = (pycountry.countries.get(alpha_3=g.upper()) or pycountry.countries.get(alpha_2=g.upper()))
            if c is None:
                c = pycountry.countries.lookup(g)      # name lookup: 'Egypt', 'United States', …
            return c.alpha_3
        except Exception:  # noqa: BLE001 — unresolved → as-given
            return g

    def _fmt(self, request: DatasetRequest) -> Dict[str, Any]:
        geo_in = request.geo if request.geo and request.geo != "national" else self.cfg.get("geo_default", "")
        geo = self._resolve_geo(geo_in) or self.cfg.get("geo_default", "")
        # Some sources (FBI CDE) 400 on an out-of-coverage start year instead of clamping. When the source
        # declares `min_year`, clamp from_year to it (and default it there if absent), and default a missing
        # to_year to the current year, so a "last 50 years" ask maps to the available window rather than erroring.
        min_year = self.cfg.get("min_year")
        if min_year is not None:
            import datetime as _dt
            fy = request.from_year if request.from_year is not None else int(min_year)
            from_year_out: Any = max(int(fy), int(min_year))
            to_year_out: Any = request.to_year if request.to_year is not None else _dt.date.today().year
        else:
            from_year_out = request.from_year if request.from_year is not None else ""
            to_year_out = request.to_year if request.to_year is not None else ""
        return {
            "measure_path": self._spec(request.measure).get("path", request.measure),
            "geo_path": geo,
            "from_year": from_year_out,
            "to_year": to_year_out,
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
        _secret_param = None
        if auth.get("type") == "query_key":
            key = next((os.environ.get(e) for e in auth.get("env", []) if os.environ.get(e)), None)
            if not key:
                raise DatasetError(f"{self.name}: no API key (set one of {auth.get('env')})")
            _secret_param = auth.get("param", "api_key")
            params[_secret_param] = key
        from datasources import data_charts_cfg
        _fcfg = data_charts_cfg()
        # Fetch tuning is PER-SOURCE-overridable (source cfg wins over the global default), because latency
        # patterns differ: World Bank via Cloudflare is BIMODAL (~0.2s or a 30-40s burst) → a SHORT per-attempt
        # timeout + retries on a FRESH connection re-rolls for a fast edge. But FBI CDE's big multi-decade fetch
        # is SLOW-BUT-COMPLETES (~20s when busy; verified a 40yr fetch that succeeded at 20.5s) — a short 10s
        # timeout wrongly abandons it, so crime silently drops from a combined chart. FBI therefore sets a
        # LONGER fetch_timeout_seconds in its config. Each attempt still uses a fresh Connection: close session.
        def _fcfgval(key, default):
            v = self.cfg.get(key)          # per-source override
            return v if v is not None else _fcfg.get(key, default)
        timeout = float(_fcfgval("fetch_timeout_seconds", 10))
        attempts = max(1, int(_fcfgval("fetch_retries", 4)) + 1)
        backoff = float(_fcfgval("fetch_retry_backoff_seconds", 0.5))
        last_err = None
        import time as _t
        _url = self._endpoint(request)
        # NEVER log the auth key: redact the secret query param before logging the params dict.
        _log_params = dict(params)
        if _secret_param and _secret_param in _log_params:
            _log_params[_secret_param] = "***REDACTED***"
        logger.info("🔎 data_chart fetch START %s params=%s timeout=%ss attempts=%d", _url, _log_params, timeout, attempts)
        # requests puts query params (incl. the auth key) into the exception's URL — redact it from any
        # error text before logging OR raising, so the key never reaches a log or an upstream error message.
        _secret_val = params.get(_secret_param) if _secret_param else None

        def _scrub(msg: str) -> str:
            return msg.replace(_secret_val, "***REDACTED***") if _secret_val else msg

        for _i in range(attempts):
            _t0 = _t.time()
            sess = requests.Session()
            try:
                # fresh connection each attempt (no keep-alive reuse) → a new try can land on a healthy edge
                resp = sess.get(_url, params=params, timeout=timeout, headers={"Connection": "close"})
                logger.info("🔎 data_chart fetch OK on attempt %d in %.1fs (%d bytes, HTTP %s)",
                            _i + 1, _t.time() - _t0, len(resp.content), resp.status_code)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                logger.warning("🔎 data_chart fetch attempt %d/%d FAILED in %.1fs: %s",
                               _i + 1, attempts, _t.time() - _t0, _scrub(str(e)))
                last_err = e
                if _i + 1 < attempts and backoff > 0:
                    _t.sleep(backoff)
            finally:
                sess.close()
        # re-raise with a scrubbed message (never leak the key up the stack / into build_data_chart's log)
        raise DatasetError(f"{self.name}: fetch failed: {_scrub(str(last_err))}")

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
        measure = self._spec(request.measure)
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
