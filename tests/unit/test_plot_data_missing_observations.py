"""SI-082: a missing observation is a GAP, not a fatal error.

THE DEFECT THIS PREVENTS
------------------------
Real series have holes. FRED writes market holidays into DGS10 as ".", which becomes NaN as soon
as the column is numeric, and every chart of it was refused outright:

    plot_data: temporal x values must all be finite numbers
    plot_data: quantitative x values must all be finite numbers

The model had done nothing wrong — it computed NaN-aware statistics exactly as asked, then handed
over the series it was asked to plot. 0 charts in 18 end-to-end runs.

THE CONTRACT (specified by the user, 2026-08-18)
-----------------------------------------------
A NaN y is SKIPPED in the drawing but KEPT in the series; the line joins Y(n-1) to Y(n+1) across
it; and every surviving point keeps its OWN true x — the date/label axis is never re-indexed.

WHY SKIP RATHER THAN EMIT None
------------------------------
`_segments` (data_chart_generator.py:59) BREAKS a line at a None. That is deliberate and correct
for a declared discontinuity (SRS↔NIBRS). A public holiday is not a discontinuity, and drawing it
as one would state something false about the data.
"""
import math

import pytest

from user_tools.plot_data_tool import PlotDataTool

BASE = dict(title="10-Year Treasury Yield", source="FRED",
            url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
            x_name="Date", x_type="temporal", source_tier="bulk_file")


def coerce(**over):
    return PlotDataTool._coerce({**BASE, **over})


def test_a_nan_y_no_longer_kills_the_chart():
    """The whole SI-082 failure: one holiday made the entire series unplottable."""
    out = coerce(x=[2020.0, 2020.1, 2020.2, 2020.3],
                 series=[{"name": "DGS10", "y": [1.5, float("nan"), 1.7, 1.8]}])
    assert out["x"], "coercion still rejects a series containing a hole"


def test_the_gap_point_is_skipped_and_neighbours_join():
    """Y(n-1) -> Y(n+1): the NaN row is gone, and nothing else is."""
    out = coerce(x=[2020.0, 2020.1, 2020.2, 2020.3],
                 series=[{"name": "DGS10", "y": [1.5, float("nan"), 1.7, 1.8]}])
    assert out["series"][0]["y"] == [1.5, 1.7, 1.8]
    assert out["x"] == [2020.0, 2020.2, 2020.3]


def test_every_surviving_point_keeps_its_OWN_x():
    """The axis must never be re-indexed — a skipped holiday must not shift later dates."""
    out = coerce(x=[2020.0, 2020.1, 2020.2, 2020.3],
                 series=[{"name": "DGS10", "y": [1.5, float("nan"), 1.7, 1.8]}])
    assert out["x"] == [2020.0, 2020.2, 2020.3], "x was re-indexed rather than filtered"
    assert list(zip(out["x"], out["series"][0]["y"])) == [(2020.0, 1.5), (2020.2, 1.7), (2020.3, 1.8)]


def test_a_point_with_no_X_is_skipped_too():
    """A point with no position cannot be drawn by any series."""
    out = coerce(x=[2020.0, float("nan"), 2020.2],
                 series=[{"name": "DGS10", "y": [1.5, 1.6, 1.7]}])
    assert out["x"] == [2020.0, 2020.2]
    assert out["series"][0]["y"] == [1.5, 1.7]


def test_the_number_skipped_is_reported():
    """A skipped point is a fact about coverage; the answer must be able to state it."""
    out = coerce(x=[2020.0, 2020.1, 2020.2, 2020.3],
                 series=[{"name": "DGS10", "y": [1.5, float("nan"), float("nan"), 1.8]}])
    assert out["_skipped_points"] == 2


def test_multi_series_keeps_a_row_any_series_can_draw():
    """A hole in ONE series must not delete the other's valid point at that x."""
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "A", "y": [1.0, float("nan"), 3.0]},
                         {"name": "B", "y": [9.0, 8.0, 7.0]}])
    assert out["x"] == [2020.0, 2020.1, 2020.2], "dropped an x B could still draw"
    assert out["series"][0]["y"] == [1.0, None, 3.0], "A's hole should stay a None"
    assert out["series"][1]["y"] == [9.0, 8.0, 7.0]


def test_infinity_is_treated_as_a_hole_not_a_value():
    """inf is not plottable and must not be smuggled through as a number."""
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "DGS10", "y": [1.5, float("inf"), 1.7]}])
    assert out["series"][0]["y"] == [1.5, 1.7]


def test_quantitative_axis_gets_the_same_treatment():
    """The daily-change histogram is quantitative and hit the identical wall."""
    out = PlotDataTool._coerce({**BASE, "x_type": "quantitative", "x_name": "Daily change",
                                "x": [-0.1, float("nan"), 0.1, 0.2],
                                "series": [{"name": "freq", "y": [3.0, 4.0, 5.0, 6.0]}]})
    assert out["x"] == [-0.1, 0.1, 0.2]


# ── controls ──────────────────────────────────────────────────────────────────────────────────
def test_CONTROL_a_clean_series_is_untouched():
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "DGS10", "y": [1.5, 1.6, 1.7]}])
    assert out["x"] == [2020.0, 2020.1, 2020.2]
    assert out["series"][0]["y"] == [1.5, 1.6, 1.7]
    assert out["_skipped_points"] == 0


def test_CONTROL_an_explicit_None_gap_still_reaches_the_renderer_as_a_gap():
    """A caller-declared gap in a MULTI-series chart keeps its break semantics."""
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "A", "y": [1.0, None, 3.0]},
                         {"name": "B", "y": [9.0, 8.0, 7.0]}])
    assert out["series"][0]["y"] == [1.0, None, 3.0]


def test_CONTROL_an_all_holes_series_still_fails_loudly():
    """Fail-closed: nothing plottable must not silently produce an empty chart."""
    with pytest.raises(ValueError) as e:
        coerce(x=[2020.0, 2020.1, 2020.2],
               series=[{"name": "DGS10", "y": [float("nan")] * 3}])
    assert "fewer than 2" in str(e.value)


def test_CONTROL_a_non_numeric_string_is_still_an_error():
    """Coercion must not start swallowing genuine junk as a 'gap'."""
    with pytest.raises(ValueError):
        coerce(x=[2020.0, 2020.1], series=[{"name": "DGS10", "y": [1.5, "banana"]}])


def test_a_CALLER_DECLARED_null_keeps_its_break_even_in_one_series():
    """The distinction this fix turns on, and it is not cosmetic.

    A NaN found in the numbers is a non-trading day: skip it and join the neighbours. An explicit
    null passed BY THE CALLER is a statement that the data is absent there, and `_segments` breaks
    the line at it on purpose — `test_gaps_are_preserved_not_zero_filled` (SI-028) has guarded that
    since the tool was built. Collapsing the two would silently convert a declared gap into a
    bridged line, which asserts continuity that was never claimed.

    Both are `None` by the time the drop decision is made, so the origin is carried explicitly
    rather than re-derived — re-deriving it would be a guess.
    """
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "DGS10", "y": [1.5, None, 1.7]}])
    assert out["x"] == [2020.0, 2020.1, 2020.2], "a declared gap was dropped"
    assert out["series"][0]["y"] == [1.5, None, 1.7]
    assert out["_skipped_points"] == 0

    # ...while a NaN at the SAME position is skipped and the neighbours join.
    out2 = coerce(x=[2020.0, 2020.1, 2020.2],
                  series=[{"name": "DGS10", "y": [1.5, float("nan"), 1.7]}])
    assert out2["x"] == [2020.0, 2020.2]
    assert out2["_skipped_points"] == 1


def test_the_internal_gap_mask_never_reaches_the_dataset():
    """`DatasetSeries` validates series dicts; an unexpected key is a fail-closed error waiting."""
    out = coerce(x=[2020.0, 2020.1, 2020.2],
                 series=[{"name": "DGS10", "y": [1.5, float("nan"), 1.7]}])
    assert all("_declared_gap" not in s for s in out["series"])
