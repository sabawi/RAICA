"""
Registry of curated data-source adapters (design: docs/DESIGN_data_charts.md).

The single place that knows which authoritative sources exist. ``all_catalogs()`` is what the plan/enumerate
step shows the LLM so it can MATCH a chart-spec to a source+measure (LLM-policy gate: the LLM chooses; the
registry just advertises). Start with FBI CDE; add FRED / World Bank / OWID / Census here later.
"""
from typing import Any, Dict, List, Optional

from datasources.base import DataSourceAdapter
from datasources.fbi_cde import FbiCdeAdapter

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


# curated set (MVP) — grows as adapters are added
register_adapter(FbiCdeAdapter())
