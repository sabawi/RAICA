"""
Unit tests for the data-charting contract + renderer (increment 1, fully offline — no network, no LLM,
no pipeline wiring). Design: docs/DESIGN_data_charts.md.

Covers: DatasetSeries validation (fail-closed), the numbers-by-reference payload store (register/get/
dedup/reset), the LLM digest, general rendering (line/bar/scatter), and — the load-bearing one —
discontinuity SEGMENTATION (never silently bridged).
Run:  venv/bin/python -m pytest tests/utilities/test_data_charts.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utils.dataset_block import (DatasetSeries, DatasetError, register_dataset, get_dataset,
                                 reset_datasets, format_digest)
from utils.data_chart_generator import generate_data_chart, _segments


# ── fixtures ─────────────────────────────────────────────────────────────────
def _crime_series(disc=True):
    """US-crime-like temporal series spanning the FBI SRS→NIBRS 2021 break."""
    years = list(range(2016, 2025))
    rate = [386.6, 382.9, 380.6, 379.4, 398.5, 387.0, 377.0, 363.8, 364.4]
    return DatasetSeries(
        title="US violent crime rate (per 100k)", source="FBI UCR/CDE",
        url="https://cde.ucr.cjis.gov/", x_name="year", x_type="temporal",
        x=years, series=[{"name": "rate", "unit": "per 100k", "y": rate}],
        measure="violent_crime_rate", geo="US-national", retrieved="2026-07-19",
        methodology="SRS 2016–2020; NIBRS 2021–", source_tier="structured_api",
        discontinuities=([{"at": 2021, "note": "SRS→NIBRS"}] if disc else []))


def _png_ok(b):
    return bool(b) and b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) > 2000


# ── contract / validation (fail-closed) ──────────────────────────────────────
def test_valid_single_series_constructs():
    s = _crime_series()
    assert s.n_points() == 9 and s.source_tier == "structured_api"


def test_valid_multi_series_shared_x():
    s = DatasetSeries(title="t", source="src", url="http://x", x_name="year", x_type="temporal",
                      x=[2000, 2001, 2002],
                      series=[{"name": "a", "y": [1.0, 2.0, 3.0]}, {"name": "b", "y": [3.0, 2.0, 1.0]}])
    assert len(s.series) == 2


@pytest.mark.parametrize("kw", [
    {"title": ""},                                       # missing title
    {"x_type": "banana"},                                # bad x_type
    {"x": [2020]},                                       # < 2 points
    {"series": [{"name": "r", "y": [1.0]}]},             # y length != x length
    {"series": [{"name": "r", "y": [1.0, None, "x"]}]},  # non-numeric y
    {"series": [{"name": "r", "y": [None, None, None]}]},# entirely empty
    {"source_tier": "made_up"},                          # bad tier
])
def test_validation_fails_closed(kw):
    base = dict(title="t", source="s", url="http://x", x_name="year", x_type="temporal",
                x=[2000, 2001, 2002], series=[{"name": "r", "y": [1.0, 2.0, 3.0]}])
    base.update(kw)
    with pytest.raises(DatasetError):
        DatasetSeries(**base)


def test_categorical_requires_string_labels():
    with pytest.raises(DatasetError):
        DatasetSeries(title="t", source="s", url="http://x", x_name="state", x_type="categorical",
                      x=[1, 2, 3], series=[{"name": "r", "y": [1.0, 2.0, 3.0]}])


# ── payload store (numbers-by-reference) ─────────────────────────────────────
def test_store_roundtrip_and_dedup():
    reset_datasets()
    a = register_dataset(_crime_series())
    b = register_dataset(_crime_series())            # identical content → same id (dedup)
    assert a == b and a.startswith("ds_")
    got = get_dataset(a)
    assert got is not None and got.title.startswith("US violent")
    reset_datasets()
    assert get_dataset(a) is None                    # gone after reset


def test_store_ttl_expiry():
    reset_datasets()
    ds_id = register_dataset(_crime_series(), ttl=-1)  # already expired
    assert get_dataset(ds_id) is None


# ── digest (what the LLM sees) ───────────────────────────────────────────────
def test_digest_has_id_meta_sample_and_discontinuity():
    s = _crime_series()
    ds_id = register_dataset(s)
    d = format_digest(s, ds_id)
    assert ds_id in d
    assert "FBI UCR/CDE" in d and "year" in d and "structured_api" in d
    assert "sample" in d and "2021" in d              # sample points + discontinuity surfaced
    assert "do NOT bridge" in d


# ── renderer ─────────────────────────────────────────────────────────────────
def test_line_bar_scatter_render_valid_png():
    assert _png_ok(generate_data_chart(_crime_series(), kind="line"))
    assert _png_ok(generate_data_chart(_crime_series(), kind="scatter"))
    cats = DatasetSeries(title="Violent crime by region", source="FBI", url="http://x",
                         x_name="region", x_type="categorical",
                         x=["NE", "MW", "S", "W"], series=[{"name": "rate", "y": [300.0, 350.0, 450.0, 420.0]}])
    assert _png_ok(generate_data_chart(cats, kind="bar"))


def test_auto_kind_and_multiseries():
    assert _png_ok(generate_data_chart(_crime_series(), kind="auto"))            # temporal → line
    s = DatasetSeries(title="two", source="s", url="http://x", x_name="year", x_type="temporal",
                      x=[2000, 2001, 2002, 2003],
                      series=[{"name": "a", "y": [1.0, 2.0, 3.0, 4.0]}, {"name": "b", "y": [4, 3, 2, 1]}])
    assert _png_ok(generate_data_chart(s, kind="auto"))


def test_bad_kind_returns_none_not_wrong_chart():
    assert generate_data_chart(_crime_series(), kind="pie") is None


# ── the load-bearing behaviour: SEGMENT at discontinuities, never bridge ──────
def test_segments_break_at_discontinuity():
    x = [2018, 2019, 2020, 2021, 2022]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    segs = _segments(x, y, cuts=[2021])               # SRS↔NIBRS: break 2020↔2021
    assert [s[0] for s in segs] == [[2018, 2019, 2020], [2021, 2022]]


def test_segments_break_at_none_gap():
    x = [1, 2, 3, 4]
    y = [1.0, None, 3.0, 4.0]
    segs = _segments(x, y, cuts=[])
    assert [s[0] for s in segs] == [[1], [3, 4]]


def test_no_discontinuity_is_single_run():
    x = [1, 2, 3, 4]
    segs = _segments(x, [1.0, 2.0, 3.0, 4.0], cuts=[])
    assert len(segs) == 1 and segs[0][0] == x
