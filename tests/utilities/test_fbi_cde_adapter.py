"""
Offline unit tests for the FBI CDE adapter (increment 2). No network — a fixture stands in for the live
API via the injectable ``fetch_json``. Validates parse logic, rate derivation, year filtering,
fail-closed behavior, the SRS→NIBRS discontinuity, and the adapter→DatasetSeries→chart handoff.

NOTE: the CDE wire shape is ASSUMED (see fbi_cde.py header); these tests prove the PARSE, not the real
shape. Reconcile on the first live fetch (needs an api.data.gov key).
Run:  venv/bin/python -m pytest tests/utilities/test_fbi_cde_adapter.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datasources.base import DatasetRequest
from datasources.fbi_cde import FbiCdeAdapter
from utils.dataset_block import DatasetError, register_dataset, format_digest
from utils.data_chart_generator import generate_data_chart


def _fixture_with_rate():
    # crosses the 2021 SRS→NIBRS break; 'rate' provided directly
    return {"offense": "violent-crime", "results": [
        {"data_year": 2016, "count": 1250000, "population": 323000000, "rate": 387.0},
        {"data_year": 2017, "count": 1245000, "population": 325000000, "rate": 383.1},
        {"data_year": 2018, "count": 1240000, "population": 326000000, "rate": 380.4},
        {"data_year": 2019, "count": 1245000, "population": 328000000, "rate": 379.6},
        {"data_year": 2020, "count": 1315000, "population": 331000000, "rate": 397.3},
        {"data_year": 2021, "count": 1280000, "population": 332000000, "rate": 385.5},
        {"data_year": 2022, "count": 1250000, "population": 333000000, "rate": 375.4},
        {"data_year": 2023, "count": 1215000, "population": 334000000, "rate": 363.8},
    ]}


def _fixture_count_only():
    # no 'rate' field -> adapter derives rate = count/pop*100000
    return {"results": [
        {"year": 2018, "count": 1240000, "population": 326000000},
        {"year": 2019, "count": 1245000, "population": 328000000},
        {"year": 2020, "count": 1315000, "population": 331000000},
    ]}


def test_extract_rate_series_with_discontinuity():
    ad = FbiCdeAdapter()
    s = ad.extract(DatasetRequest(measure="violent-crime", value_kind="rate"),
                   fetch_json=lambda req: _fixture_with_rate())
    assert s.x == list(range(2016, 2024))
    assert s.series[0]["y"][0] == 387.0 and s.series[0]["unit"] == "per 100,000"
    assert s.source_tier == "structured_api" and "Crime Data Explorer" in s.source
    assert s.x_type == "temporal" and s.measure == "violent-crime" and s.geo == "US-national"
    # SRS→NIBRS break carried as metadata (span crosses 2021)
    assert any(d["at"] == 2021 for d in s.discontinuities)
    assert "NIBRS" in s.methodology


def test_rate_derived_from_count_and_population():
    ad = FbiCdeAdapter()
    s = ad.extract(DatasetRequest(measure="violent-crime", value_kind="rate"),
                   fetch_json=lambda req: _fixture_count_only())
    # 1240000 / 326000000 * 100000 = 380.4 (rounded 1dp)
    assert s.series[0]["y"][0] == pytest.approx(380.4, abs=0.1)


def test_count_value_kind():
    ad = FbiCdeAdapter()
    s = ad.extract(DatasetRequest(measure="violent-crime", value_kind="count"),
                   fetch_json=lambda req: _fixture_with_rate())
    assert s.series[0]["y"][0] == 1250000.0 and s.series[0]["unit"] == "offenses"


def test_year_filtering_and_no_discontinuity_pre_2021():
    ad = FbiCdeAdapter()
    s = ad.extract(DatasetRequest(measure="violent-crime", from_year=2016, to_year=2020),
                   fetch_json=lambda req: _fixture_with_rate())
    assert s.x == [2016, 2017, 2018, 2019, 2020]
    assert s.discontinuities == []          # span never crosses 2021 → no SRS/NIBRS break


def test_unknown_offense_and_bad_geo_fail_closed():
    ad = FbiCdeAdapter()
    with pytest.raises(DatasetError):
        ad.extract(DatasetRequest(measure="jaywalking"), fetch_json=lambda req: _fixture_with_rate())
    with pytest.raises(DatasetError):
        ad.extract(DatasetRequest(measure="violent-crime", geo="Texas"),
                   fetch_json=lambda req: _fixture_with_rate())


def test_empty_and_garbage_response_fail_closed():
    ad = FbiCdeAdapter()
    with pytest.raises(DatasetError):
        ad.extract(DatasetRequest(measure="violent-crime"), fetch_json=lambda req: {"results": []})
    with pytest.raises(DatasetError):
        ad.extract(DatasetRequest(measure="violent-crime"), fetch_json=lambda req: {"nope": 1})


def test_catalog_advertises_vocabulary():
    cat = FbiCdeAdapter().catalog()
    assert cat["name"] == "fbi_cde" and cat["source_tier"] == "structured_api"
    assert "violent-crime" in cat["measures"] and "rate" in cat["value_kinds"]


def test_end_to_end_adapter_to_chart():
    """The load-bearing handoff: adapter → DatasetSeries → store/digest → renderer produces a PNG."""
    ad = FbiCdeAdapter()
    s = ad.extract(DatasetRequest(measure="violent-crime", value_kind="rate"),
                   fetch_json=lambda req: _fixture_with_rate())
    ds_id = register_dataset(s)
    digest = format_digest(s, ds_id)
    assert ds_id in digest and "SRS→NIBRS" in digest
    png = generate_data_chart(s, kind="auto")
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 2000
