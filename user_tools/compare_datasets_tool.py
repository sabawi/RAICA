"""
compare_datasets — the CROSS-SOURCE synthesis tool: fetch SEVERAL real numeric series (from DIFFERENT
authoritative sources) and render them as ONE integrated comparative chart.

This is what separates RAICA from a single-API lookup: a socioeconomic / sociopolitical question rarely
lives in one dataset. "Did crime track unemployment and inequality?" needs FBI crime + FRED labour/income
data + World Bank development indicators on ONE time axis, not three disconnected charts the reader has to
mentally overlay.

Design notes (see docs/DESIGN_data_charts.md):
  * NUMBERS-BY-REFERENCE — the caller supplies only a REQUEST (source+measure). Every number comes from the
    source; the digest quotes the RAW values, so anything the LLM cites is true to the source.
  * Units — when the series carry different units (% vs per-100,000 vs US$), the CHART is indexed to a
    common base year (=100) so the trends are comparable; the digest still carries raw values and the
    methodology says so explicitly.
  * Fail-closed — a series that can't be fetched is skipped; fewer than 2 usable series → no chart at all,
    never a partial/fabricated one.
"""
import asyncio
import functools
import logging
from typing import Any, Dict

from base_user_tool import BaseUserTool
from datasources.data_chart_builder import build_combined_data_chart
from datasources.registry import all_catalogs

logger = logging.getLogger(__name__)


def _feature_enabled() -> bool:
    # SINGLE source of truth (shared with the planner + search_datasets) — env override + config.
    try:
        from datasources import data_charts_enabled
        return data_charts_enabled()
    except Exception:  # noqa: BLE001 — trouble → fail safe (disabled)
        return False


class CompareDatasetsTool(BaseUserTool):
    @property
    def name(self) -> str:
        return "compare_datasets"

    @property
    def description(self) -> str:
        names = ", ".join(sorted(c["name"] for c in all_catalogs())) or "(none)"
        return (
            "RESEARCH/GATHER source (runs DURING research, NOT a delivery/packaging action): fetch 2 or "
            "MORE real numeric series — possibly from DIFFERENT authoritative sources — and render them as "
            "ONE integrated comparative chart on a shared time axis. Use this whenever a question involves "
            "the RELATIONSHIP between indicators ('did crime track unemployment?', 'compare inequality with "
            "growth', 'crime vs poverty vs income'), or any socioeconomic/sociopolitical issue best answered "
            "by several indicators together rather than one. Prefer this over calling search_datasets "
            "repeatedly, because it puts the indicators on ONE chart so trends can actually be compared. "
            "Series with different units are automatically indexed to a common base year for comparability, "
            "and it computes the REAL pairwise correlations (Pearson r) so you can cite measured values; "
            "it NEVER invents numbers (all data comes straight from the sources). Pick each `source` and "
            f"`measure` from the advertised catalogs (available sources: {names}). For the `fred` source, "
            "`measure` may ALSO be a plain DESCRIPTION of any U.S. economic/financial/housing/labor series "
            "(e.g. 'home price index', 'homeownership rate', '30-year mortgage rate') — it is resolved by "
            "searching FRED, so you are not limited to the listed measures. "
            # SI-027 — the model was choosing this tool for short-window questions and then
            # describing 3 annual dots as a two-year 'path'. State the resolution up front so
            # it can set expectations (or pick a different framing) BEFORE it writes.
            "GRANULARITY: values are ANNUAL MEANS of each series' published frequency, so a short "
            "window returns only a few points per line (e.g. '2024-2026' is THREE points, not a "
            "daily path) and the newest year is a PARTIAL-year average whenever the current year is "
            "unfinished. Say so when you present the chart, and treat the correlations it reports as "
            "informative only when there are enough points to support them."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "series": {
                    "type": "array",
                    "description": "2..6 series to combine on one chart, each naming a source + measure "
                                   "from the advertised catalogs.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "data-source id (e.g. 'fred')"},
                            "measure": {"type": "string",
                                        "description": "measure code from that source's catalog"},
                            "geo": {"type": "string", "description": "geography (source-specific)",
                                    "default": "national"},
                            "value_kind": {"type": "string", "enum": ["rate", "count", "value"],
                                           "default": "value"},
                        },
                        "required": ["source", "measure"],
                    },
                },
                "title": {"type": "string",
                          "description": "Short chart title naming the QUESTION being compared (e.g. "
                                         "'U.S. crime, unemployment and inequality'). Keep it under ~55 "
                                         "characters — the legend already names each series."},
                "from_year": {"type": "integer", "description": "start year (optional)"},
                "to_year": {"type": "integer", "description": "end year (optional)"},
                "chart_kind": {"type": "string", "enum": ["auto", "line", "bar", "scatter"],
                               "default": "line"},
            },
            "required": ["series"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        if not _feature_enabled():
            return {"success": False, "error": "data_charts feature is disabled"}
        series = kwargs.get("series") or []
        if not isinstance(series, list) or len(series) < 2:
            return {"success": False, "error": "compare_datasets needs at least 2 series"}
        specs = []
        for s in series[:6]:
            if not isinstance(s, dict) or not s.get("source") or not s.get("measure"):
                continue
            specs.append({
                "source": str(s["source"]).strip(),
                "measure": str(s["measure"]).strip(),
                "geo": s.get("geo", "national"),
                "value_kind": s.get("value_kind", "value"),
                "from_year": kwargs.get("from_year"),
                "to_year": kwargs.get("to_year"),
            })
        if len(specs) < 2:
            return {"success": False, "error": "compare_datasets needs 2 valid {source, measure} entries"}
        try:
            res = await asyncio.get_event_loop().run_in_executor(
                None, functools.partial(build_combined_data_chart, specs,
                                        chart_kind=kwargs.get("chart_kind", "line"),
                                        title=kwargs.get("title")))
        except Exception as e:  # noqa: BLE001 — never break the gather round
            logger.warning("compare_datasets: %s", e)
            return {"success": False, "error": f"compare_datasets error: {e}"}

        if not res.get("ok"):
            return {"success": False, "error": res.get("error") or "combined dataset extraction failed"}
        out = res["content"]
        if res.get("skipped"):
            out += "\n  NOTE: some requested series were unavailable and are NOT on the chart: " \
                   + "; ".join(res["skipped"])
        return {"success": True, "result": out}
