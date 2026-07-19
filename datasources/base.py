"""
Data-source adapter contract (design: docs/DESIGN_data_charts.md).

An adapter is a thin, deterministic client over ONE authoritative data source. It:
  * ``catalog()`` — advertises what it offers (measures / geographies / coverage / tier) so the plan step
    can MATCH a chart-spec to it. The adapter never classifies free-text user intent (LLM-policy gate) —
    matching is the LLM's job; the adapter receives an already-normalized ``DatasetRequest``.
  * ``extract(request)`` — fetches the real series and parses it into a validated ``DatasetSeries``
    (raises on any failure → fail-closed, so a bad extraction never reaches the renderer).

``fetch_json`` is injectable so adapters are unit-tested fully offline against a cached response.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from utils.dataset_block import DatasetSeries


@dataclass
class DatasetRequest:
    """A normalized ask for one series. ``measure``/``geo`` use the adapter's OWN catalog vocabulary
    (the LLM selects them from ``catalog()`` — the adapter does not guess them from free text)."""
    measure: str                                  # catalog code, e.g. "violent-crime"
    geo: str = "national"
    from_year: Optional[int] = None
    to_year: Optional[int] = None
    value_kind: str = "rate"                       # "rate" (per 100k) | "count"
    extra: Dict[str, Any] = field(default_factory=dict)


class DataSourceAdapter(ABC):
    name: str = "base"
    source_tier: str = "unknown"                   # extraction fidelity (see dataset_block._TIERS)

    @abstractmethod
    def catalog(self) -> Dict[str, Any]:
        """Machine-readable advertisement of this source's measures/geos/coverage (for LLM matching)."""

    @abstractmethod
    def extract(self, request: DatasetRequest,
                fetch_json: Optional[Callable[["DatasetRequest"], Any]] = None) -> DatasetSeries:
        """Fetch + parse into a validated DatasetSeries. ``fetch_json`` overrides the live HTTP call
        (used by tests). Raises on any failure (fail-closed)."""
