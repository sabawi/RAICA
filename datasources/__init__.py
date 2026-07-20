"""
Curated authoritative data-source adapters for the data-charting feature (design: docs/DESIGN_data_charts.md).

Each adapter turns a normalized ``DatasetRequest`` into a validated ``DatasetSeries`` (real numeric data,
numbers-by-reference). Deterministic "yfinance-for-stats" clients — NOT generic web scraping. The adapter
never interprets free-text user intent; it advertises its vocabulary via ``catalog()`` and serves an
already-normalized request (topic→catalog matching is the LLM's job in the plan/enumerate step).
"""
import os

from datasources.base import DataSourceAdapter, DatasetRequest  # noqa: F401


def data_charts_cfg():
    """The deep_research.data_charts config subtree (single config file). {} on any error (fail safe)."""
    try:
        from utils.config_loader import config_loader
        return (config_loader.load_config() or {}).get("deep_research", {}).get("data_charts", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def data_charts_enabled():
    """SINGLE source of truth for the data-charts feature flag — used by BOTH the planner (research/engine.py)
    and the search_datasets tool, so they can never disagree (NO-INCONSISTENCY). RAICA_DATA_CHARTS_ENABLED
    env override wins (mirrors RAICA_CHARTS_ENABLED); else deep_research.data_charts.enabled."""
    _env = os.getenv("RAICA_DATA_CHARTS_ENABLED")
    if _env is not None:
        return _env.strip().lower() == "true"
    return bool(data_charts_cfg().get("enabled", False))
