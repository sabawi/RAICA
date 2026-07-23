"""
Data-chart builder — the render-at-gather core of the data-charting feature (design:
docs/DESIGN_data_charts.md, Increment A). Ties the pieces together for ONE requested series:

    request → adapter.extract (real data) → register_dataset (store by id) → generate_data_chart (render
    the STORED payload) → publish_chart (same-origin upload) → [[chart:...]] marker + LLM digest

The returned ``content`` (marker + digest) becomes a DATASET evidence block's text — exactly how the stock
analyzer prepends a ``[[chart:...]]`` marker to its analysis, so synthesis reproduces it unchanged.

NUMBERS-BY-REFERENCE is structural here: this function only ever receives a *request*; the numbers come
from the adapter and are rendered from the stored payload — the caller/LLM never supplies a data point.
Fail-closed throughout: any failure yields a result with the digest (if we got data) but NO chart marker,
never a wrong chart. ``fetch_json``/``publish_fn`` are injectable so the whole path is unit-tested offline.
"""
import logging
from typing import Any, Callable, Dict, Optional

from datasources.base import DatasetRequest
from datasources.registry import get_adapter
from utils.dataset_block import DatasetError, DatasetSeries, format_digest, register_dataset
from utils.data_chart_generator import generate_data_chart

logger = logging.getLogger(__name__)


def _marker(url: str, caption: str, align: str = "center") -> str:
    cap = (caption or "chart").replace('"', "'").strip()
    return f'[[chart:{url}|align={align}|caption="{cap}"]]'


def build_data_chart(
    source: str,
    request: DatasetRequest,
    *,
    chart_kind: str = "auto",
    align: str = "center",
    fetch_json: Optional[Callable[["DatasetRequest"], Any]] = None,
    publish_fn: Optional[Callable[[bytes, str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """Acquire → render → publish one data chart. Returns:
        {ok, dataset_id, digest, marker, chart_url, content, error}
    ``publish_fn(png_bytes, hint)->url|None`` defaults to chart_publisher.publish_chart (only when the
    charts feature is enabled); pass a stub in tests. A None publish result yields the digest WITHOUT a
    marker (data still usable as evidence)."""
    result: Dict[str, Any] = {"ok": False, "dataset_id": None, "digest": "", "marker": None,
                              "chart_url": None, "content": "", "error": None}

    adapter = get_adapter(source)
    if adapter is None:
        result["error"] = f"unknown data source {source!r}"
        return result

    # 1) acquire the REAL series (fail-closed on any extraction/validation error)
    try:
        series = adapter.extract(request, fetch_json=fetch_json)
    except DatasetError as e:
        result["error"] = f"extract failed: {e}"
        return result
    except Exception as e:  # noqa: BLE001 — a source blowing up must never break the run
        logger.warning("build_data_chart: %s extract error: %s", source, e)
        result["error"] = f"extract error: {e}"
        return result

    # 2) store by id + build the LLM digest (this much always succeeds once we have valid data)
    dataset_id = register_dataset(series)
    digest = format_digest(series, dataset_id)
    result.update(ok=True, dataset_id=dataset_id, digest=digest, content=digest)

    # 3) render from the STORED payload + publish → marker (best-effort; absence ≠ failure of the data)
    publish = publish_fn if publish_fn is not None else _default_publish()
    if publish is None:
        return result                     # charts disabled → data-only evidence, no marker
    try:
        png = generate_data_chart(series, kind=chart_kind)
        if not png:
            return result                 # renderer failed → no chart, never a wrong one
        url = publish(png, f"datachart_{dataset_id}")
        if not url:
            return result
        marker = _marker(url, series.title, align)
        result.update(marker=marker, chart_url=url, content=f"{marker}\n\n{digest}")
    except Exception as e:  # noqa: BLE001
        logger.warning("build_data_chart: render/publish failed: %s", e)
    return result


def build_combined_data_chart(
    specs,
    *,
    chart_kind: str = "auto",
    align: str = "center",
    title: Optional[str] = None,
    publish_fn: Optional[Callable[[bytes, str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """Fetch SEVERAL real series — across DIFFERENT sources — and merge them into ONE integrated chart.

    This is the cross-source synthesis RAICA is for: e.g. FBI violent-crime rate + FRED unemployment +
    FRED income-Gini + World Bank GDP-per-capita on a single time axis, so a socioeconomic question can be
    answered with one comparative visual instead of N disconnected charts.

    ``specs`` = [{source, measure, geo?, value_kind?, from_year?, to_year?}, ...] (2..N).

    Alignment: the x axis is the UNION of every series' years (``None`` where a series has no data), so each
    source keeps its full span (FRED from 1947, FBI from 1985, …) instead of being truncated to an overlap.

    Units + honesty: the returned DatasetSeries always carries the RAW values, so the digest the LLM reads
    (and therefore every number it cites) stays true to the source — NUMBERS-BY-REFERENCE is preserved. Only
    when the series have DIFFERENT units is a normalized COPY rendered (each series indexed to 100 at a
    common base year), because plotting a % against a $-billions level on one axis is unreadable. The chart
    title, y-label and methodology all state the indexing explicitly.

    Fail-closed: specs that fail to fetch are skipped; fewer than 2 usable series → no chart.
    """
    result: Dict[str, Any] = {"ok": False, "dataset_id": None, "digest": "", "marker": None,
                              "chart_url": None, "content": "", "error": None, "skipped": []}
    if not specs or len(specs) < 2:
        result["error"] = "combined chart needs at least 2 series"
        return result

    fetched = []          # (spec, DatasetSeries)
    for spec in specs:
        src = (spec.get("source") or "").strip()
        try:
            req = DatasetRequest(
                measure=(spec.get("measure") or "").strip(),
                geo=spec.get("geo", "national"),
                from_year=spec.get("from_year"), to_year=spec.get("to_year"),
                value_kind=spec.get("value_kind", "rate"))
            fetched.append((spec, get_adapter(src).extract(req)))
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the comparison
            logger.warning("build_combined_data_chart: %s/%s skipped: %s", src, spec.get("measure"), e)
            result["skipped"].append(f"{src}/{spec.get('measure')}: {e}")
    if len(fetched) < 2:
        result["error"] = f"fewer than 2 usable series ({'; '.join(result['skipped']) or 'no data'})"
        return result

    # union x (years), sorted
    xs = sorted({x for _s, ser in fetched for x in ser.x})
    combined_series, units, sources, tiers, discs = [], [], [], [], []
    for spec, ser in fetched:
        s0 = ser.series[0]
        by_x = dict(zip(ser.x, s0["y"]))
        name = s0.get("name") or ser.measure or "series"
        geo = (ser.geo or "").strip()
        if geo and geo.lower() not in name.lower():
            name = f"{name} ({geo})"
        combined_series.append({"name": name, "unit": s0.get("unit"),
                                "y": [by_x.get(x) for x in xs]})
        units.append(s0.get("unit"))
        sources.append(ser.source)
        tiers.append(ser.source_tier)
        discs.extend(ser.discontinuities or [])

    same_unit = len({u for u in units}) == 1
    src_label = " · ".join(dict.fromkeys(sources))
    span = f"{xs[0]}–{xs[-1]}"
    if title:
        base_title = f"{title.strip()}, {span}" if span not in title else title.strip()
    else:
        # Concise auto-title: the LEGEND already names every series, so listing them all here just
        # overflows the plot (observed: a 4-series title rendered truncated at both edges). Join names
        # only while they stay short; otherwise fall back to a count.
        us_only = all((s.geo or "").lower() in ("us-national", "united states", "usa", "")
                      for _sp, s in fetched)
        short = [n.split(" (")[0] for n in dict.fromkeys(s["name"] for s in combined_series)]
        joined = ", ".join(short)
        if len(joined) > 58:
            joined = f"{len(combined_series)} indicators"
        base_title = ("U.S. " if us_only else "") + f"{joined}, {span}"

    meth = f"Combined from {len(combined_series)} sources ({src_label}); x = union of available years."
    raw = DatasetSeries(
        title=base_title, source=src_label, url=fetched[0][1].url,
        x_name=fetched[0][1].x_name, x_type=fetched[0][1].x_type, x=xs,
        series=combined_series, measure=None,
        geo=", ".join(dict.fromkeys((s.geo or "") for _sp, s in fetched if s.geo)) or None,
        retrieved=fetched[0][1].retrieved,
        methodology=meth + ("" if same_unit else
                            " Units differ, so the CHART is indexed (each series = 100 at its base year); "
                            "the values quoted in this dataset block are the RAW source values."),
        discontinuities=discs,
        source_tier=("structured_api" if all(t == "structured_api" for t in tiers) else "unknown"))

    dataset_id = register_dataset(raw)
    digest = format_digest(raw, dataset_id)
    result.update(ok=True, dataset_id=dataset_id, digest=digest, content=digest)

    # render: raw when units match, else an indexed COPY (raw stays the cited truth)
    to_render = raw
    if not same_unit:
        base_year, idx_series = None, []
        firsts = [next((x for x, v in zip(xs, s["y"]) if v not in (None, 0)), None) for s in combined_series]
        if all(f is not None for f in firsts):
            base_year = max(firsts)
        for s in combined_series:
            by_x = dict(zip(xs, s["y"]))
            b = by_x.get(base_year) if base_year is not None else None
            if b in (None, 0):                       # no common base → index on the series' own first point
                b = next((v for v in s["y"] if v not in (None, 0)), None)
            idx_series.append({"name": s["name"], "unit": None,
                               "y": [(None if (v is None or not b) else round(v / b * 100.0, 2)) for v in s["y"]]})
        try:
            to_render = DatasetSeries(
                title=f"{base_title} (indexed, {base_year}=100)" if base_year else f"{base_title} (indexed)",
                source=src_label, url=raw.url, x_name=raw.x_name, x_type=raw.x_type, x=xs,
                series=[{**s, "unit": f"index ({base_year}=100)" if base_year else "index"} for s in idx_series],
                measure=None, geo=raw.geo, retrieved=raw.retrieved,
                methodology=raw.methodology, discontinuities=discs, source_tier=raw.source_tier)
        except DatasetError as e:
            logger.warning("build_combined_data_chart: indexing failed (%s); rendering raw", e)
            to_render = raw

    publish = publish_fn if publish_fn is not None else _default_publish()
    if publish is None:
        return result
    try:
        png = generate_data_chart(to_render, kind=chart_kind)
        if not png:
            return result
        url = publish(png, f"datachart_{dataset_id}")
        if not url:
            return result
        marker = _marker(url, to_render.title, align)
        result.update(marker=marker, chart_url=url, content=f"{marker}\n\n{digest}")
    except Exception as e:  # noqa: BLE001
        logger.warning("build_combined_data_chart: render/publish failed: %s", e)
    return result


def _default_publish() -> Optional[Callable[[bytes, str], Optional[str]]]:
    """chart_publisher.publish_chart, but only when the charts feature is enabled (else None → no upload)."""
    try:
        from utils.chart_publisher import charts_enabled, publish_chart
        return publish_chart if charts_enabled() else None
    except Exception:  # noqa: BLE001 — publisher unavailable → degrade to data-only
        return None
