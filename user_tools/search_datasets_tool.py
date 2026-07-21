"""
search_datasets — the deep-research SOURCE that fetches a REAL numeric dataset from a curated authoritative
source and renders an actual chart for it (design: docs/DESIGN_data_charts.md, Increment 3b).

The planner routes here (when the feature is enabled) with a normalized request naming a source + measure it
picked from the advertised catalogs. This tool executes the acquire→store→render→publish→[[chart:]] chain via
``build_data_chart`` and returns the marker+digest as its output — exactly like ``comprehensive_stock_analyzer``
prepends a chart marker to its analysis, so synthesis reproduces the marker unchanged.

Self-disabling: if ``deep_research.data_charts.enabled`` is false the tool refuses (defense in depth — the
planner also won't route here unless search_datasets is in engine.sources.allowed). NUMBERS-BY-REFERENCE:
this tool never receives data points, only a request; the numbers come from the source and render from the
stored payload.
"""
import asyncio
import functools
import logging
from typing import Any, Dict

from base_user_tool import BaseUserTool
from datasources.base import DatasetRequest
from datasources.data_chart_builder import build_data_chart
from datasources.registry import all_catalogs

logger = logging.getLogger(__name__)


def _feature_enabled() -> bool:
    # SINGLE source of truth (shared with the planner via research/engine.py) — env override + config.
    try:
        from datasources import data_charts_enabled
        return data_charts_enabled()
    except Exception:  # noqa: BLE001 — trouble → fail safe (disabled)
        return False


class SearchDatasetsTool(BaseUserTool):
    @property
    def name(self) -> str:
        return "search_datasets"

    @property
    def description(self) -> str:
        cats = all_catalogs()
        names = ", ".join(sorted(c["name"] for c in cats)) or "(none)"
        return (
            "RESEARCH/GATHER source (runs DURING research, NOT a delivery/packaging action): fetch a REAL "
            "numeric dataset from a curated authoritative data source and render an actual chart, embedding "
            "it as CONTENT in the report. Use it when the user asks to plot/chart/graph numeric data (trends "
            "over time, comparisons, relationships) — e.g. population, GDP, GDP per capita, inflation, "
            "unemployment, life expectancy, CO2 emissions, crime rates and similar official statistics. This "
            "is the RIGHT tool (not analytical_visualizer) whenever the data is a known public statistic: it "
            "FETCHES the authentic numbers so you never supply or transcribe them. Returns a chart marker + a "
            "data digest; it NEVER invents numbers (data comes straight from the source). Pick `source` and "
            f"`measure` from the advertised catalogs (available sources: {names}). Not a file/email/deliverable "
            "step — only real datasets."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string",
                           "description": "data-source id from the catalog (e.g. 'fbi_cde')"},
                "measure": {"type": "string",
                            "description": "measure code from that source's catalog (e.g. 'violent-crime')"},
                "geo": {"type": "string", "description": "geography (source-specific)", "default": "national"},
                "from_year": {"type": "integer", "description": "start year (optional)"},
                "to_year": {"type": "integer", "description": "end year (optional)"},
                "value_kind": {"type": "string", "enum": ["rate", "count"], "default": "rate"},
                "chart_kind": {"type": "string", "enum": ["auto", "line", "bar", "scatter"], "default": "auto"},
            },
            "required": ["source", "measure"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if not _feature_enabled():
            return {"success": False, "error": "data_charts feature is disabled"}
        source = (kwargs.get("source") or "").strip()
        measure = (kwargs.get("measure") or "").strip()
        if not source or not measure:
            return {"success": False, "error": "search_datasets requires 'source' and 'measure'"}
        try:
            req = DatasetRequest(
                measure=measure, geo=kwargs.get("geo", "national"),
                from_year=kwargs.get("from_year"), to_year=kwargs.get("to_year"),
                value_kind=kwargs.get("value_kind", "rate"))
            res = await asyncio.get_event_loop().run_in_executor(
                None, functools.partial(build_data_chart, source, req,
                                        chart_kind=kwargs.get("chart_kind", "auto")))
        except Exception as e:  # noqa: BLE001 — never break the gather round
            logger.warning("search_datasets: %s", e)
            return {"success": False, "error": f"search_datasets error: {e}"}

        if not res.get("ok"):
            return {"success": False, "error": res.get("error") or "dataset extraction failed"}
        return {"success": True, "result": res["content"]}
