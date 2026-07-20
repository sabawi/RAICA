"""
Registry of data-source adapters, loaded DECLARATIVELY from the SINGLE config file
(``config/llm_config.yaml`` → ``deep_research.data_charts.sources.catalog``; design: docs/DESIGN_data_charts.md).

Every source becomes a config-driven ``DeclarativeAdapter`` — no per-site Python. Per RAICA's config
directive (config/llm_config.yaml is the single source of truth), the catalog lives IN llm_config.yaml, read
via ``config_loader`` — not a separate file. ``all_catalogs()`` is what the plan/enumerate step shows the LLM
to match a chart-spec to a source+measure (LLM chooses; the registry just advertises). One bad source is
skipped, not fatal.
"""
import logging
from typing import Any, Dict, List, Optional

from datasources.base import DataSourceAdapter
from datasources.declarative_adapter import DeclarativeAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: Dict[str, DataSourceAdapter] = {}


def register_adapter(adapter: DataSourceAdapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> Optional[DataSourceAdapter]:
    return _ADAPTERS.get(name)


def adapter_names() -> List[str]:
    return sorted(_ADAPTERS)


def all_catalogs() -> List[Dict[str, Any]]:
    """Machine-readable advertisement of every source (for LLM topic→source matching)."""
    return [a.catalog() for a in _ADAPTERS.values()]


def _load_catalog() -> Dict[str, Any]:
    from utils.config_loader import config_loader
    cfg = config_loader.load_config() or {}
    return (cfg.get("deep_research", {}).get("data_charts", {})
            .get("sources", {}).get("catalog", {}) or {})


def load_sources() -> None:
    """(Re)build the registry from deep_research.data_charts.sources.catalog. Each bad source is skipped."""
    _ADAPTERS.clear()
    try:
        catalog = _load_catalog()
    except Exception as e:  # noqa: BLE001 — config trouble → empty registry (feature just can't chart)
        logger.error("datasources: could not load catalog from llm_config.yaml: %s", e)
        return
    for name, scfg in catalog.items():
        try:
            register_adapter(DeclarativeAdapter(name, scfg))
        except Exception as e:  # noqa: BLE001 — one bad source must not break the rest
            logger.warning("datasources: skipping source %s: %s", name, e)


load_sources()
