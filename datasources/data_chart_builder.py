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
from utils.dataset_block import DatasetError, format_digest, register_dataset
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


def _default_publish() -> Optional[Callable[[bytes, str], Optional[str]]]:
    """chart_publisher.publish_chart, but only when the charts feature is enabled (else None → no upload)."""
    try:
        from utils.chart_publisher import charts_enabled, publish_chart
        return publish_chart if charts_enabled() else None
    except Exception:  # noqa: BLE001 — publisher unavailable → degrade to data-only
        return None
