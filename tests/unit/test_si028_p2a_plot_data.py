"""SI-028 P2a — charting data the model already fetched, so it stops inventing charts.

WHY THIS TOOL EXISTS. The pipeline `series → PNG → upload → [[chart:…]] → rendered by NewX` has
been in production for months and every stage is source-agnostic. Only the INTAKE was welded to the
dataset catalog, so `search_datasets` could chart FRED and nothing could chart a CSV the model had
just downloaded.

The cost was not a missing picture. Asked to chart a fetched Treasury CSV, the model FABRICATED the
marker in 3 runs out of 3:

    run 1  [[chart:eyJuYW1lIjoiVVMgVHJlYXN1cnkgRGFpbHkgWWll...   (base64 of a chart JSON)
    run 2  [[chart:6a2e2a6b-1e0e-4e0e-8e0e-6e0e-6e0e-6e0e-6e0e]] (UUID-shaped)
    run 3  [[chart:ea2e5e6e-5e5e-4e5e-8e5e-5e5e5e5e5e5e]]        (UUID-shaped)

A real marker carries a PUBLISHED IMAGE URL (`data_chart_builder._marker`), so none of those is a
chart. NewX's citation guard treats marker presence as proof a reply is tool-sourced and accepts it
in place of a source URL — so an invented marker can carry an ungrounded answer past it (SI-038).
The model had an explicit instruction to emit a marker and no tool that could mint one.

The upload step is stubbed here (it needs a running NewX); it is the one part of the chain already
exercised in production every time search_datasets draws a chart.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from user_tools.plot_data_tool import PlotDataTool  # noqa: E402

X = [f"2025-01-{i:02d}" for i in range(1, 11)]
Y10 = [4.57, 4.61, 4.63, 4.69, 4.68, 4.67, 4.77, 4.79, 4.79, 4.65]
Y30 = [4.79, 4.83, 4.85, 4.92, 4.91, 4.90, 4.98, 4.98, 4.97, 4.86]
BASE = dict(title="US Treasury yields", source="U.S. Treasury",
            url="https://home.treasury.gov/x.csv", x_name="Date", x_type="temporal",
            x=X, source_tier="bulk_file",
            series=[{"name": "10 Yr", "unit": "%", "y": Y10},
                    {"name": "30 Yr", "unit": "%", "y": Y30}])


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def call(**over):
    """Run the tool with the upload stubbed to a fixed URL."""
    import user_tools.plot_data_tool as mod
    original = mod.publish_chart
    try:
        mod.publish_chart = lambda png, filename_hint="chart", **k: "https://newx.test/media/abc123.png"
        return run(PlotDataTool().execute(**{**BASE, **over}))
    finally:
        mod.publish_chart = original


class TestProducesARealMarker:

    def test_returns_a_marker_pointing_at_a_published_url(self):
        """The whole point: a REAL marker, in the format the renderer and the guard expect —
        a published image URL, not base64 and not a UUID."""
        r = call()
        assert r["success"] is True
        assert "[[chart:https://newx.test/media/abc123.png" in r["result"]
        assert "align=" in r["result"] and "caption=" in r["result"]

    def test_dates_survive_as_a_plotted_series(self):
        """DatasetSeries requires temporal x to be finite NUMBERS and the renderer draws a plain
        numeric axis — passing ISO strings fails validation outright. Daily dates therefore become
        decimal years, which keeps every point."""
        assert PlotDataTool._to_decimal_year("2025-01-01") == 2025.0
        assert 2025.49 < PlotDataTool._to_decimal_year("2025-07-02") < 2025.51
        assert PlotDataTool._to_decimal_year("08/13/2026") > 2026.6
        assert PlotDataTool._to_decimal_year(2015) == 2015.0

    def test_categorical_and_quantitative_axes_work(self):
        r = call(x_type="categorical", x=["a", "b", "c"],
                 series=[{"name": "n", "y": [1, 2, 3]}])
        assert r["success"] is True
        r = call(x_type="quantitative", x=[1, 2, 3], series=[{"name": "n", "y": [4, 5, 6]}])
        assert r["success"] is True


class TestFailuresNeverInviteFABRICATION:
    """Every failure path must tell the model NOT to write a marker itself — that is the behaviour
    whose absence produced three fabricated charts."""

    def test_publish_failure_says_do_not_write_a_marker(self):
        import user_tools.plot_data_tool as mod
        original = mod.publish_chart
        try:
            mod.publish_chart = lambda *a, **k: None          # NewX unreachable / charts disabled
            r = run(PlotDataTool().execute(**BASE))
        finally:
            mod.publish_chart = original
        assert r["success"] is False
        assert "[[chart:" not in str(r)
        assert "do not write a marker" in r["error"].lower()

    def test_render_failure_says_do_not_write_a_marker(self):
        import user_tools.plot_data_tool as mod
        original = mod.generate_data_chart
        try:
            mod.generate_data_chart = lambda *a, **k: None
            r = run(PlotDataTool().execute(**BASE))
        finally:
            mod.generate_data_chart = original
        assert r["success"] is False
        assert "do NOT write a chart marker" in r["error"]


class TestProvenanceIsMandatory:

    def test_a_chart_cannot_exist_without_a_source_url(self):
        """DatasetSeries validates fail-closed. This is what stops the tool becoming a way to
        render numbers of unknown origin."""
        r = call(url="")
        assert r["success"] is False and "url" in r["error"]

    def test_source_tier_records_how_the_data_was_obtained(self):
        """`bulk_file` is precisely the fidelity tier for a downloaded CSV; an unknown value must
        degrade to 'unknown' rather than claim a higher grade."""
        assert PlotDataTool._coerce({**BASE, "source_tier": "made_up"})["source_tier"] == "unknown"
        assert PlotDataTool._coerce({**BASE, "source_tier": "bulk_file"})["source_tier"] == "bulk_file"


class TestSilentlyWrongPicturesAreRejected:

    def test_misaligned_series_is_refused_not_drawn(self):
        """THE dangerous input. A y list shorter than x shifts every point against the wrong x and
        produces a plausible, wrong picture — worse than no chart, because it looks right."""
        r = call(series=[{"name": "10 Yr", "y": Y10[:5]}])
        assert r["success"] is False
        assert "align 1:1" in r["error"]

    def test_non_numeric_values_are_refused(self):
        r = call(series=[{"name": "a", "y": ["n/a"] * 10}])
        assert r["success"] is False and "non-numeric" in r["error"]

    def test_gaps_are_preserved_not_zero_filled(self):
        """A missing observation must stay missing. Zero-filling would draw a plunge to zero that
        never happened."""
        y = list(Y10)
        y[3] = None
        out = PlotDataTool._coerce({**BASE, "series": [{"name": "a", "y": y}]})
        assert out["series"][0]["y"][3] is None

    def test_a_single_point_is_not_a_chart(self):
        r = call(x=["2025-01-01"], series=[{"name": "a", "y": [1]}])
        assert r["success"] is False and "at least 2 points" in r["error"]

    def test_absurd_sizes_are_bounded(self):
        r = call(x=list(range(6000)), x_type="quantitative",
                 series=[{"name": "a", "y": list(range(6000))}])
        assert r["success"] is False and "limit" in r["error"]


class TestReachability:
    def test_the_tool_is_discoverable_under_its_advertised_name(self):
        """A tool the loader never registers is inert however correct it is — the SI-036 lesson."""
        assert PlotDataTool().name == "plot_data"
        required = PlotDataTool().parameters["required"]
        for field in ("title", "source", "url", "x", "series"):
            assert field in required
