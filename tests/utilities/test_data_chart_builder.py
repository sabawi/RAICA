"""
Offline tests for the render-at-gather builder (increment 3a). No network, no NewX upload — the FBI
adapter reads a fixture via ``fetch_json`` and the publisher is a stub. Verifies the full chain
extract→store→render→publish→[[chart:]] marker, the numbers-by-reference store, and every fail-closed path.
Run:  venv/bin/python -m pytest tests/utilities/test_data_chart_builder.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from datasources.base import DatasetRequest
from datasources.data_chart_builder import build_data_chart
from datasources.registry import get_adapter, all_catalogs, adapter_names
from utils.dataset_block import get_dataset, reset_datasets


def _fixture():
    return {"results": [
        {"data_year": 2018, "count": 1240000, "population": 326000000, "rate": 380.4},
        {"data_year": 2019, "count": 1245000, "population": 328000000, "rate": 379.6},
        {"data_year": 2020, "count": 1315000, "population": 331000000, "rate": 397.3},
        {"data_year": 2021, "count": 1280000, "population": 332000000, "rate": 385.5},
        {"data_year": 2022, "count": 1250000, "population": 333000000, "rate": 375.4},
    ]}


def _pub_stub():
    cap = {}
    def publish(png, hint):
        cap["png"] = png; cap["hint"] = hint
        return f"/static/images/media/{hint}.jpg"
    return publish, cap


def _req():
    return DatasetRequest(measure="violent-crime", value_kind="rate")


# ── happy path ───────────────────────────────────────────────────────────────
def test_full_chain_produces_marker_and_stored_data():
    reset_datasets()
    publish, cap = _pub_stub()
    r = build_data_chart("fbi_cde", _req(), fetch_json=lambda q: _fixture(), publish_fn=publish)
    assert r["ok"] and r["error"] is None
    ds_id = r["dataset_id"]
    # marker: correct form, references the published url + a real caption
    assert r["marker"].startswith(f"[[chart:/static/images/media/datachart_{ds_id}.jpg|align=center|caption=")
    assert "U.S. violent crime rate" in r["marker"]
    assert r["chart_url"].endswith(f"datachart_{ds_id}.jpg")
    # content = marker THEN digest (render-at-gather), digest carries the discontinuity
    assert r["content"].startswith(r["marker"]) and "SRS→NIBRS" in r["content"]
    # numbers-by-reference: the published PNG rendered from the STORED payload, reachable by id
    assert cap["png"][:8] == b"\x89PNG\r\n\x1a\n" and cap["hint"] == f"datachart_{ds_id}"
    stored = get_dataset(ds_id)
    assert stored is not None and stored.series[0]["y"][0] == 380.4   # real number lives in the store


def test_unknown_source_fails_closed():
    r = build_data_chart("bogus_src", _req(), fetch_json=lambda q: _fixture(), publish_fn=_pub_stub()[0])
    assert not r["ok"] and r["marker"] is None and "unknown data source" in r["error"]


def test_extract_failure_fails_closed_no_marker():
    r = build_data_chart("fbi_cde", _req(), fetch_json=lambda q: {"results": []}, publish_fn=_pub_stub()[0])
    assert not r["ok"] and r["marker"] is None and r["error"]


def test_publish_disabled_gives_data_without_marker():
    reset_datasets()
    r = build_data_chart("fbi_cde", _req(), fetch_json=lambda q: _fixture(), publish_fn=None)
    # charts off (publish_fn None simulates disabled) → still valid data evidence, just no chart
    assert r["ok"] and r["marker"] is None
    assert r["dataset_id"] and r["content"] == r["digest"] and "year" in r["digest"]


def test_publish_returns_none_no_marker_but_data_ok():
    r = build_data_chart("fbi_cde", _req(), fetch_json=lambda q: _fixture(), publish_fn=lambda p, h: None)
    assert r["ok"] and r["marker"] is None and r["content"] == r["digest"]


# ── registry ─────────────────────────────────────────────────────────────────
def test_registry_has_fbi_cde():
    assert "fbi_cde" in adapter_names()
    assert get_adapter("fbi_cde") is not None
    cats = all_catalogs()
    assert any(c["name"] == "fbi_cde" and "violent-crime" in c["measures"] for c in cats)
