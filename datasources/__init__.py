"""
Curated authoritative data-source adapters for the data-charting feature (design: docs/DESIGN_data_charts.md).

Each adapter turns a normalized ``DatasetRequest`` into a validated ``DatasetSeries`` (real numeric data,
numbers-by-reference). Deterministic "yfinance-for-stats" clients — NOT generic web scraping. The adapter
never interprets free-text user intent; it advertises its vocabulary via ``catalog()`` and serves an
already-normalized request (topic→catalog matching is the LLM's job in the plan/enumerate step).
"""
from datasources.base import DataSourceAdapter, DatasetRequest  # noqa: F401
