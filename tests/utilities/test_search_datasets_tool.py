"""
Offline tests for the search_datasets user tool (increment 3b-i). No network, no NewX upload: the FBI
adapter's HTTP is monkeypatched to a fixture and the publisher is stubbed. Verifies the tool's contract
({success, result|error}), the self-disable gate, param validation, and fail-closed extraction.
Run:  venv/bin/python -m pytest tests/utilities/test_search_datasets_tool.py -q
"""
import asyncio
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "user_tools"))   # tools do `from base_user_tool import ...`

import datasources.data_chart_builder as builder
import user_tools.search_datasets_tool as sdt
from datasources.fbi_cde import FbiCdeAdapter
from user_tools.search_datasets_tool import SearchDatasetsTool


def _fixture():
    return {"results": [
        {"data_year": 2018, "count": 1240000, "population": 326000000, "rate": 380.4},
        {"data_year": 2019, "count": 1245000, "population": 328000000, "rate": 379.6},
        {"data_year": 2020, "count": 1315000, "population": 331000000, "rate": 397.3},
        {"data_year": 2021, "count": 1280000, "population": 332000000, "rate": 385.5},
        {"data_year": 2022, "count": 1250000, "population": 333000000, "rate": 375.4},
    ]}


def _run(coro):
    return asyncio.run(coro)


def _enable(monkeypatch, fixture=True, publish=True):
    monkeypatch.setattr(sdt, "_feature_enabled", lambda: True)
    if fixture:
        monkeypatch.setattr(FbiCdeAdapter, "_http_get", lambda self, req: _fixture())
    if publish:
        monkeypatch.setattr(builder, "_default_publish",
                            lambda: (lambda png, hint: f"/static/images/media/{hint}.jpg"))


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(sdt, "_feature_enabled", lambda: False)
    r = _run(SearchDatasetsTool().execute(source="fbi_cde", measure="violent-crime"))
    assert r["success"] is False and "disabled" in r["error"]


def test_enabled_returns_marker_and_digest(monkeypatch):
    _enable(monkeypatch)
    r = _run(SearchDatasetsTool().execute(source="fbi_cde", measure="violent-crime", value_kind="rate"))
    assert r["success"] is True
    out = r["result"]
    assert out.startswith("[[chart:/static/images/media/datachart_")     # render-at-gather marker first
    assert 'align=center' in out and "U.S. violent crime rate" in out
    assert "SRS→NIBRS" in out and "dataset_id" in out                     # digest follows


def test_data_without_publish_still_succeeds(monkeypatch):
    _enable(monkeypatch, publish=False)
    monkeypatch.setattr(builder, "_default_publish", lambda: None)        # charts off → data-only
    r = _run(SearchDatasetsTool().execute(source="fbi_cde", measure="violent-crime"))
    assert r["success"] is True and "[[chart:" not in r["result"] and "dataset_id" in r["result"]


def test_missing_params(monkeypatch):
    monkeypatch.setattr(sdt, "_feature_enabled", lambda: True)
    r = _run(SearchDatasetsTool().execute(source="fbi_cde"))
    assert r["success"] is False and "requires" in r["error"]


def test_extract_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(sdt, "_feature_enabled", lambda: True)
    monkeypatch.setattr(FbiCdeAdapter, "_http_get", lambda self, req: {"results": []})
    r = _run(SearchDatasetsTool().execute(source="fbi_cde", measure="violent-crime"))
    assert r["success"] is False and r["error"]


def test_tool_metadata_shape():
    t = SearchDatasetsTool()
    assert t.name == "search_datasets"
    assert t.parameters["required"] == ["source", "measure"]
    assert "fbi_cde" in t.description                                    # advertises available sources
