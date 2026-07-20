"""
Offline test for the planner wiring of data-charting (increment 3b-ii). No LLM, no network — just checks
that the flag gates BOTH the allowed-source list and the planner prompt: with the feature OFF the prompt is
unchanged and search_datasets is absent; with it ON, search_datasets is offered and the source catalog is
injected. (The planner's actual routing decision needs a live LLM run — not tested here.)
Run:  venv/bin/python -m pytest tests/utilities/test_planner_data_charts.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import research.engine as engine
from research.engine import ResearchPlanner, DeepResearchEngine

_ENGINE_CFG = {"sources": {"allowed": ["search_web", "comprehensive_stock_analyzer"]},
               "planner": {"per_source_queries": True}}


def _planner():
    return ResearchPlanner(lambda *a, **k: None, _ENGINE_CFG)


def test_off_by_default_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(engine, "_data_charts_enabled", lambda: False)
    p = _planner()
    assert "search_datasets" not in p._allowed_sources
    system, _ = p._build_prompt("chart US population since 1970")
    assert "search_datasets" not in system and "DATA SOURCES CATALOG" not in system


def test_enabled_adds_source_and_catalog(monkeypatch):
    monkeypatch.setattr(engine, "_data_charts_enabled", lambda: True)
    # real registry catalogs, restricted to the two configured sources
    monkeypatch.setattr(engine, "_data_source_catalogs",
                        lambda: [{"name": "world_bank", "source_tier": "structured_api", "geo": ["USA"],
                                  "coverage_years": "1960–", "measures": {"population": "population",
                                                                          "gdp": "GDP"}},
                                 {"name": "fbi_cde", "source_tier": "structured_api", "geo": ["US-national"],
                                  "coverage_years": "1979–", "measures": {"violent-crime": "violent crime"}}])
    p = _planner()
    assert "search_datasets" in p._allowed_sources
    system, _ = p._build_prompt("chart US population since 1970")
    assert "search_datasets" in system
    assert "world_bank" in system and "population" in system          # catalog injected
    assert "fbi_cde" in system and "violent-crime" in system
    assert "NEVER invents numbers" in system                          # the numbers-by-reference framing


def test_engine_dispatch_allowset_gated(monkeypatch):
    monkeypatch.setattr(engine, "_data_charts_enabled", lambda: False)
    eng = DeepResearchEngine(lambda *a, **k: None, lambda *a, **k: "", _ENGINE_CFG)
    assert "search_datasets" not in eng._allowed_sources
    monkeypatch.setattr(engine, "_data_charts_enabled", lambda: True)
    assert "search_datasets" in eng._allowed_sources


def test_requires_per_source_queries(monkeypatch):
    monkeypatch.setattr(engine, "_data_charts_enabled", lambda: True)
    p = ResearchPlanner(lambda *a, **k: None,
                        {"sources": {"allowed": ["search_web"]}, "planner": {"per_source_queries": False}})
    # without the queries map the tool can't get its JSON arg → don't offer it
    assert "search_datasets" not in p._allowed_sources
