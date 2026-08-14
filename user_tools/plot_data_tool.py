"""`plot_data` — chart data the model has ALREADY retrieved (SI-028 P2a).

WHY THIS EXISTS
---------------
The charting pipeline `series → PNG → upload → [[chart:…]] marker → rendered by NewX` has been in
production for months, and every stage of it is source-agnostic. Only the INTAKE was welded to the
dataset catalog: `search_datasets` / `compare_datasets` can chart World Bank or FRED, and nothing
could chart a CSV the model had just downloaded.

The cost of that gap was not a missing picture. Asked to chart a fetched Treasury CSV, the model
FABRICATED the marker in three runs out of three — `[[chart:6a2e2a6b-1e0e-…]]`, a UUID where a real
marker carries a published image URL. It had an explicit instruction to produce a marker, no tool
that could mint one, and so it invented one. NewX's citation guard treats marker presence as proof
that a reply is tool-sourced, so an invented marker can carry an ungrounded answer past it
(SI-038).

WHAT THIS IS
------------
A THIN wrapper over the existing primitives — `DatasetSeries` → `generate_data_chart` →
`publish_chart` → `_marker`. Deliberately NOT `analytical_visualizer`, which generates and EXECUTES
chart code: that is real RCE surface for no benefit here, and the design doc rejects it explicitly.
No code generation, no sandbox, no eval. The model supplies data points and provenance; RAICA
draws.

PROVENANCE IS MANDATORY, NOT DECORATIVE
---------------------------------------
`DatasetSeries` validates fail-closed and requires `title, source, url, x_name, x_type, x, series`.
A chart therefore cannot exist without a source and a URL, and `source_tier` records honestly how
the numbers were obtained (`bulk_file` for a downloaded CSV, `html_table` for a scraped one). That
is what keeps this from becoming a way to render numbers of unknown origin.
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List

try:
    from .base_user_tool import BaseUserTool
except ImportError:
    from base_user_tool import BaseUserTool

try:
    from utils.dataset_block import DatasetError, DatasetSeries, format_digest
    from utils.data_chart_generator import generate_data_chart
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker
except ImportError:  # loaded outside the server process
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.dataset_block import DatasetError, DatasetSeries, format_digest
    from utils.data_chart_generator import generate_data_chart
    from utils.chart_publisher import publish_chart
    from datasources.data_chart_builder import _marker

logger = logging.getLogger(__name__)

_X_TYPES = ("temporal", "quantitative", "categorical")
_KINDS = ("auto", "line", "bar", "scatter")
_TIERS = ("structured_api", "bulk_file", "html_table", "unknown")
# A chart is a picture of a claim, so the points must come from somewhere real. These bounds keep a
# single call from becoming a denial of service without constraining any plausible chart.
_MAX_POINTS = 5000
_MAX_SERIES = 8


class PlotDataTool(BaseUserTool):
    """Render a chart from data the caller already has."""

    @property
    def name(self) -> str:
        return "plot_data"

    @property
    def description(self) -> str:
        return (
            "Draw a real chart from data you have ALREADY retrieved with another tool — for example "
            "a CSV, JSON or table fetched with lookup_website. Use this whenever the user asks for a "
            "chart, plot or graph of data that did not come from search_datasets/compare_datasets. "
            "Supply the x values, one or more named y series aligned to them, and where the data "
            "came from; RAICA renders the image and returns a [[chart:...]] marker to place in your "
            "answer. You cannot draw a chart any other way: never write a marker yourself. If you "
            "have no data to pass, do not call this — say a chart could not be produced."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string",
                          "description": "Chart title, e.g. \"US Treasury daily yields, 2025-2026\"."},
                "source": {"type": "string",
                           "description": "Who published the underlying data, e.g. "
                                          "\"U.S. Department of the Treasury\"."},
                "url": {"type": "string",
                        "description": "URL the data was actually retrieved from. Required — a chart "
                                       "without a source is not publishable."},
                "x_name": {"type": "string", "description": "Label for the x axis, e.g. \"Date\"."},
                "x_type": {"type": "string", "enum": list(_X_TYPES),
                           "description": "temporal for dates, quantitative for numbers, "
                                          "categorical for names/labels."},
                "x": {"type": ["array", "object"],
                      "description": "Shared x values, at least 2, in order — dates as strings "
                                     "(YYYY-MM-DD), numbers for quantitative, labels for "
                                     "categorical. For data another tool already fetched, pass a "
                                     "reference instead of the values: "
                                     "{\"from\": \"lookup_website#1\", \"column\": \"Date\"}. "
                                     "PREFER THE REFERENCE — a real table does not fit here."},
                "series": {"type": "array",
                           "description": "One entry per line/bar group: "
                                          "{\"name\": \"10 Yr\", \"unit\": \"%\", \"y\": [4.57, ...]}. "
                                          "`y` may instead be a reference to already-fetched data: "
                                          "{\"from\": \"lookup_website#1\", \"column\": \"10 Yr\"} — "
                                          "prefer this. Each y must align 1:1 with x.",
                           "items": {"type": "object"}},
                "kind": {"type": "string", "enum": list(_KINDS),
                         "description": "Chart type; 'auto' picks from the data shape."},
                "source_tier": {"type": "string", "enum": list(_TIERS),
                                "description": "How the data was obtained: bulk_file for a downloaded "
                                               "CSV/data file, html_table for a scraped table, "
                                               "structured_api for a JSON API."},
                "caption": {"type": "string", "description": "Optional caption shown under the chart."},
            },
            "required": ["title", "source", "url", "x_name", "x_type", "x", "series"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        try:
            payload = self._coerce(kwargs)
        except ValueError as e:
            return {"success": False, "error": f"plot_data: {e}"}

        try:
            series = DatasetSeries(
                title=payload["title"], source=payload["source"], url=payload["url"],
                x_name=payload["x_name"], x_type=payload["x_type"],
                x=payload["x"], series=payload["series"],
                retrieved=date.today().isoformat(),
                source_tier=payload["source_tier"])
        except DatasetError as e:
            # Fail-closed provenance is the point, so report WHY rather than drawing something
            # unattributable.
            return {"success": False, "error": f"plot_data: {e}"}

        png = generate_data_chart(series, kind=payload["kind"])
        if not png:
            return {"success": False,
                    "error": "plot_data: the chart could not be rendered from this data. Describe "
                             "the numbers in prose or a table instead — do NOT write a chart marker."}

        url = publish_chart(png, filename_hint=(payload["title"][:40] or "chart"))
        if not url:
            # No URL means no marker. Saying so is mandatory: the alternative is the model inventing
            # one, which is the failure this tool exists to remove (SI-038).
            logger.warning("📊 plot_data: chart rendered but publishing failed — no marker returned")
            return {"success": False,
                    "error": "plot_data: the chart was drawn but could not be published, so there is "
                             "no marker to show. Tell the user a chart could not be produced this "
                             "time and describe the data instead. Do NOT write a marker yourself."}

        marker = _marker(url, payload["caption"] or payload["title"])
        logger.info(f"📊 plot_data: {len(payload['series'])} series x {len(payload['x'])} points "
                    f"→ {url}")
        try:
            digest = format_digest(series)
        except Exception:  # noqa: BLE001 — a digest is a nicety; the chart is the deliverable
            digest = ""
        return {"success": True, "result": f"{marker}\n\n{digest}".strip()}

    @staticmethod
    def _to_decimal_year(value):
        """Convert a date to the DECIMAL YEAR the chart machinery actually plots.

        `DatasetSeries` requires temporal x values to be finite NUMBERS, and the generator draws
        them on a plain numeric axis with no date formatting — because every existing caller is the
        dataset catalog, which plots annual means and passes years like 2015. Handing it ISO strings
        fails validation outright ("temporal x values must all be finite numbers").

        Dates therefore become fractional years: 2025-07-02 -> 2025.5. Every daily point is still
        plotted, so daily resolution is preserved; only the tick LABELS read 2025.0 / 2025.5 rather
        than calendar dates. Doing it here keeps the shared renderer untouched, so no existing
        catalog chart changes behaviour. Teaching the renderer real date ticks is a separate change
        with its own regression risk.
        """
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m", "%Y"):
            try:
                d = date(*(__import__("time").strptime(text, fmt)[:3]))
            except (ValueError, TypeError):
                continue
            start = date(d.year, 1, 1).toordinal()
            length = date(d.year + 1, 1, 1).toordinal() - start
            return d.year + (d.toordinal() - start) / length
        try:
            return float(text)
        except ValueError:
            raise ValueError(
                f"temporal x value {value!r} is neither a number nor a recognised date "
                f"(YYYY-MM-DD, MM/DD/YYYY, YYYY)") from None

    # ------------------------------------------------------------------ input handling
    @staticmethod
    def _coerce(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise the model's arguments, rejecting what cannot be drawn honestly.

        Tool arguments arrive as JSON of varying shape across providers, so lists may be strings and
        numbers may be strings. Coercion happens here, once, rather than being discovered by
        matplotlib halfway through rendering.
        """
        def _as_list(value, field):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{field} is not valid JSON: {e}") from e
            if not isinstance(value, list):
                raise ValueError(f"{field} must be a list")
            return value

        x = _as_list(kwargs.get("x"), "x")
        if len(x) < 2:
            raise ValueError("x needs at least 2 points to make a chart")
        if len(x) > _MAX_POINTS:
            raise ValueError(f"x has {len(x)} points, over the {_MAX_POINTS} limit")

        raw_series = _as_list(kwargs.get("series"), "series")
        if not raw_series:
            raise ValueError("series must contain at least one {name, y} entry")
        if len(raw_series) > _MAX_SERIES:
            raise ValueError(f"{len(raw_series)} series requested, over the {_MAX_SERIES} limit")

        cleaned: List[Dict[str, Any]] = []
        for i, entry in enumerate(raw_series):
            if isinstance(entry, str):
                try:
                    entry = json.loads(entry)
                except json.JSONDecodeError as e:
                    raise ValueError(f"series[{i}] is not valid JSON: {e}") from e
            if not isinstance(entry, dict):
                raise ValueError(f"series[{i}] must be an object with name and y")
            y = _as_list(entry.get("y"), f"series[{i}].y")
            if len(y) != len(x):
                # The single most damaging silent error here: a y list shorter than x silently
                # shifts every point against the wrong x, producing a plausible and wrong picture.
                raise ValueError(
                    f"series[{i}] ('{entry.get('name', '?')}') has {len(y)} y values but x has "
                    f"{len(x)} — they must align 1:1, same order")
            out_y = []
            for v in y:
                if v is None or (isinstance(v, str) and not v.strip()):
                    out_y.append(None)                    # a genuine gap, drawn as a gap
                    continue
                try:
                    out_y.append(float(v))
                except (TypeError, ValueError):
                    raise ValueError(
                        f"series[{i}] ('{entry.get('name', '?')}') contains a non-numeric value: "
                        f"{v!r}") from None
            cleaned.append({"name": str(entry.get("name") or f"series {i + 1}"),
                            "unit": entry.get("unit"), "y": out_y})

        x_type = str(kwargs.get("x_type") or "").strip().lower()
        if x_type not in _X_TYPES:
            raise ValueError(f"x_type must be one of {_X_TYPES}, got {x_type!r}")
        if x_type == "categorical":
            x = [str(v) for v in x]
        elif x_type == "quantitative":
            try:
                x = [float(v) for v in x]
            except (TypeError, ValueError):
                raise ValueError("quantitative x values must all be numbers") from None
        else:
            x = [PlotDataTool._to_decimal_year(v) for v in x]

        # Order the points along a numeric axis. Source files are often newest-first, and joining
        # two of them (2025 then 2026, each descending) would draw a line that runs backwards and
        # then jumps — a picture of nothing. Sorting is safe here: on a temporal/quantitative axis
        # the sequence carries no information beyond the x values themselves. Categorical order IS
        # meaningful, so it is left alone.
        if x_type in ("temporal", "quantitative") and len(x) > 1:
            order = sorted(range(len(x)), key=lambda i: x[i])
            if order != list(range(len(x))):
                x = [x[i] for i in order]
                cleaned = [{**s, "y": [s["y"][i] for i in order]} for s in cleaned]

        kind = str(kwargs.get("kind") or "auto").strip().lower()
        if kind not in _KINDS:
            kind = "auto"
        tier = str(kwargs.get("source_tier") or "unknown").strip().lower()
        if tier not in _TIERS:
            tier = "unknown"

        return {"title": str(kwargs.get("title") or "").strip(),
                "source": str(kwargs.get("source") or "").strip(),
                "url": str(kwargs.get("url") or "").strip(),
                "x_name": str(kwargs.get("x_name") or "").strip(),
                "x_type": x_type, "x": x, "series": cleaned, "kind": kind,
                "source_tier": tier, "caption": str(kwargs.get("caption") or "").strip()}
