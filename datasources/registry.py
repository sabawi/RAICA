"""
Registry of data-source adapters, loaded DECLARATIVELY from sources.yaml (design: docs/DESIGN_data_charts.md).

Every source becomes a config-driven ``DeclarativeAdapter`` — no per-site Python. ``all_catalogs()`` is what
the plan/enumerate step shows the LLM to match a chart-spec to a source+measure (LLM chooses; the registry
just advertises). Load failures for one source never take down the rest (fail-safe).
"""
import logging
import os
from typing import Any, Dict, List, Optional

import yaml

from datasources.base import DataSourceAdapter
from datasources.declarative_adapter import DeclarativeAdapter

logger = logging.getLogger(__name__)

_SOURCES_YAML = os.path.join(os.path.dirname(__file__), "sources.yaml")
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


def load_sources(path: str = _SOURCES_YAML) -> None:
    """(Re)build the registry from a declarative YAML. Each bad source is skipped, not fatal."""
    _ADAPTERS.clear()
    try:
        with open(path) as fh:
            doc = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.error("datasources: could not load %s: %s", path, e)
        return
    for name, cfg in (doc.get("sources") or {}).items():
        try:
            register_adapter(DeclarativeAdapter(name, cfg))
        except Exception as e:  # noqa: BLE001 — one bad source must not break the rest
            logger.warning("datasources: skipping source %s: %s", name, e)


load_sources()
