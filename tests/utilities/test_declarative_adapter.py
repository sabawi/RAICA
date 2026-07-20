"""
Offline tests for the config-driven DeclarativeAdapter + sources.yaml (data-charts refactor). No network —
fixtures stand in for each API via the injectable ``fetch_json``. Covers BOTH a key-required flat-JSON source
(FBI CDE) and a keyless enveloped source (World Bank), proving one engine + config + shape handlers replaces
per-site classes. Parse logic is validated, not the real wire shape (reconcile on first live fetch).
Run:  venv/bin/python -m pytest tests/utilities/test_declarative_adapter.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datasources.base import DatasetRequest
from datasources.registry import get_adapter, adapter_names, all_catalogs
from utils.dataset_block import DatasetError


# ── fixtures ─────────────────────────────────────────────────────────────────
def _fbi_with_rate():
    return {"results": [
        {"data_year": 2016, "count": 1250000, "population": 323000000, "rate": 387.0},
        {"data_year": 2017, "count": 1245000, "population": 325000000, "rate": 383.1},
        {"data_year": 2019, "count": 1245000, "population": 328000000, "rate": 379.6},
        {"data_year": 2020, "count": 1315000, "population": 331000000, "rate": 397.3},
        {"data_year": 2021, "count": 1280000, "population": 332000000, "rate": 385.5},
        {"data_year": 2023, "count": 1215000, "population": 334000000, "rate": 363.8},
    ]}


def _fbi_count_only():
    return {"results": [
        {"year": 2018, "count": 1240000, "population": 326000000},
        {"year": 2019, "count": 1245000, "population": 328000000},
        {"year": 2020, "count": 1315000, "population": 331000000},
    ]}


def _wb_population():
    # World Bank v2 envelope: [metadata, [records...]] — descending by date, string years, direct value
    return [
        {"page": 1, "pages": 1, "per_page": 20000, "total": 5},
        [
            {"indicator": {"id": "SP.POP.TOTL"}, "countryiso3code": "USA", "date": "2020", "value": 331501080},
            {"indicator": {"id": "SP.POP.TOTL"}, "countryiso3code": "USA", "date": "2010", "value": 309327143},
            {"indicator": {"id": "SP.POP.TOTL"}, "countryiso3code": "USA", "date": "2000", "value": 282162411},
            {"indicator": {"id": "SP.POP.TOTL"}, "countryiso3code": "USA", "date": "1990", "value": 249623000},
            {"indicator": {"id": "SP.POP.TOTL"}, "countryiso3code": "USA", "date": "1970", "value": 209513341},
        ],
    ]


# ── registry loads both sources from config ──────────────────────────────────
def test_registry_loads_declarative_sources():
    assert "fbi_cde" in adapter_names() and "world_bank" in adapter_names()
    cats = {c["name"]: c for c in all_catalogs()}
    assert "violent-crime" in cats["fbi_cde"]["measures"]
    assert "population" in cats["world_bank"]["measures"]
    assert cats["world_bank"]["source_tier"] == "structured_api"


# ── FBI CDE (flat_json, key-required) via the generic engine ─────────────────
def test_fbi_rate_with_discontinuity():
    s = get_adapter("fbi_cde").extract(DatasetRequest(measure="violent-crime", value_kind="rate"),
                                       fetch_json=lambda r: _fbi_with_rate())
    assert s.x == [2016, 2017, 2019, 2020, 2021, 2023]
    assert s.series[0]["y"][0] == 387.0 and s.series[0]["unit"] == "per 100,000"
    assert "Crime Data Explorer" in s.source and s.source_tier == "structured_api"
    assert "U.S. violent crime rate" in s.title
    assert any(d["at"] == 2021 for d in s.discontinuities) and "NIBRS" in s.methodology


def test_fbi_rate_derived_and_count_kind():
    s = get_adapter("fbi_cde").extract(DatasetRequest(measure="violent-crime", value_kind="rate"),
                                       fetch_json=lambda r: _fbi_count_only())
    assert s.series[0]["y"][0] == pytest.approx(380.4, abs=0.1)      # 1240000/326000000*1e5
    c = get_adapter("fbi_cde").extract(DatasetRequest(measure="violent-crime", value_kind="count"),
                                       fetch_json=lambda r: _fbi_with_rate())
    assert c.series[0]["y"][0] == 1250000.0 and c.series[0]["unit"] == "offenses"


def test_fbi_year_filter_no_discontinuity_pre_2021():
    s = get_adapter("fbi_cde").extract(DatasetRequest(measure="violent-crime", from_year=2016, to_year=2020),
                                       fetch_json=lambda r: _fbi_with_rate())
    assert s.x == [2016, 2017, 2019, 2020] and s.discontinuities == []


def test_fbi_unknown_measure_and_empty_fail_closed():
    with pytest.raises(DatasetError):
        get_adapter("fbi_cde").extract(DatasetRequest(measure="jaywalking"), fetch_json=lambda r: _fbi_with_rate())
    with pytest.raises(DatasetError):
        get_adapter("fbi_cde").extract(DatasetRequest(measure="violent-crime"), fetch_json=lambda r: {"results": []})


# ── World Bank (worldbank shape, keyless) via the SAME engine ────────────────
def test_world_bank_population_series():
    s = get_adapter("world_bank").extract(DatasetRequest(measure="population", geo="USA"),
                                          fetch_json=lambda r: _wb_population())
    assert s.x == [1970, 1990, 2000, 2010, 2020]                     # sorted ascending from descending input
    assert s.series[0]["y"][-1] == 331501080 and s.series[0]["unit"] == "people"
    assert s.source == "World Bank Open Data" and s.x_type == "temporal"
    assert "population" in s.title and "USA" in s.title and s.discontinuities == []


def test_world_bank_value_kind_defaults_and_bad_envelope():
    # request.value_kind default 'rate' isn't in WB's ['value'] → engine falls back to 'value'
    s = get_adapter("world_bank").extract(DatasetRequest(measure="population", geo="USA"),
                                          fetch_json=lambda r: _wb_population())
    assert s.series[0]["y"]  # populated
    with pytest.raises(DatasetError):
        get_adapter("world_bank").extract(DatasetRequest(measure="population"),
                                          fetch_json=lambda r: [{"message": "bad"}])   # not [meta, data]
