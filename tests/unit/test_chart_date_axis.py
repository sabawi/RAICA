"""SI-091 / SI-090 — a date axis must read as dates, and a window must be a window.

SI-091 — THE FAILURE THIS PREVENTS
----------------------------------
`plot_data_tool._to_decimal_year` turns 2025-07-02 into 2025.5, because `DatasetSeries`
requires temporal x values to be finite NUMBERS. Positioning was always right — every daily
point is plotted — but nothing converted the number back for the TICK LABEL. A chart of daily
Treasury yields therefore carried an x-axis reading

    2025.8   2026.0   2026.2   2026.4   2026.6

beneath an axis labelled "Date". Correct data that reads as wrong. Found on 2026-08-21 by
INSPECTING two published charts; every log line had reported success, and no test caught it,
because nothing in the pipeline looks at the picture.

THE CATALOG MUST NOT CHANGE. Its callers plot annual means and pass WHOLE years
(`range(2016, 2025)`), for which "2016" is already the right label. So the reformatting is
gated on the values NOT all being whole numbers — which can only be true of values derived
from real dates. Content decides the type, the same rule the reference layer uses.

SI-090 — a slice counts OBSERVATIONS, not calendar days. The model computed `d[-365:]` on a
business-daily series (~252 rows/yr), producing ~17 months of data under a title claiming one
year. That is a model-reasoning error, so the fix is POLICY LANGUAGE in the tool the model
reads — not a hardcoded rule — and this file guards that the directive is still there.
"""
import json

import pytest

from utils.data_chart_generator import (_apply_temporal_ticks, _decimal_year_to_date,
                                        generate_data_chart)
from utils.dataset_block import DatasetSeries
from user_tools.plot_data_tool import PlotDataTool


def _fig_ax():
    from matplotlib.figure import Figure
    fig = Figure()
    return fig, fig.subplots(1, 1)


# --------------------------------------------------------------- SI-091

@pytest.mark.parametrize("iso", ["2025-09-02", "2026-08-17", "2025-01-01",
                                 "2025-12-31", "2024-02-29"])
def test_decimal_year_round_trips_exactly(iso):
    """The label must name the day that was plotted — including across a leap year."""
    assert _decimal_year_to_date(PlotDataTool._to_decimal_year(iso)).isoformat() == iso


def test_date_derived_values_get_date_ticks():
    """FAILS pre-SI-091: there was no formatter at all, so ticks printed as 2025.8."""
    _, ax = _fig_ax()
    xs = [PlotDataTool._to_decimal_year(d) for d in
          ("2025-09-02", "2025-12-01", "2026-03-01", "2026-08-17")]
    assert _apply_temporal_ticks(ax, xs) is True
    label = ax.xaxis.get_major_formatter()(xs[0], 0)
    assert "2025" in label and "." not in label      # a date, not a decimal year
    assert any(c.isalpha() for c in label)           # month name present


def test_whole_years_are_left_alone_the_catalog_must_not_change():
    """CONTROL. The dataset catalog passes `range(2016, 2025)`; 2016 is already correct."""
    _, ax = _fig_ax()
    assert _apply_temporal_ticks(ax, list(range(2016, 2025))) is False


def test_a_single_point_is_not_reformatted():
    _, ax = _fig_ax()
    assert _apply_temporal_ticks(ax, [PlotDataTool._to_decimal_year("2025-09-02")]) is False


@pytest.mark.parametrize("span_days,expect_alpha", [(30, True), (400, True), (1600, False)])
def test_the_format_follows_the_span(span_days, expect_alpha):
    """A multi-year chart wants years; a one-year chart wants months. `%Y` has no letters."""
    from datetime import date, timedelta
    _, ax = _fig_ax()
    d0 = date(2022, 1, 3)
    xs = [PlotDataTool._to_decimal_year((d0 + timedelta(days=i)).isoformat())
          for i in range(0, span_days, max(1, span_days // 10))]
    assert _apply_temporal_ticks(ax, xs) is True
    assert any(c.isalpha() for c in ax.xaxis.get_major_formatter()(xs[0], 0)) is expect_alpha


def _series(x, name="DGS10", unit="%"):
    return DatasetSeries(title="t", source="FRED", url="https://fred.stlouisfed.org/",
                         x_name="Date", x_type="temporal", x=x,
                         series=[{"name": name, "unit": unit,
                                  "y": [1.0 + i * 0.1 for i in range(len(x))]}],
                         retrieved="2026-08-21", source_tier="bulk_file")


def test_a_real_chart_still_renders_with_date_ticks():
    xs = [PlotDataTool._to_decimal_year(d) for d in
          ("2025-09-02", "2025-12-01", "2026-03-01", "2026-08-17")]
    assert generate_data_chart(_series(xs), kind="line")


def test_a_catalog_chart_still_renders():
    assert generate_data_chart(_series(list(range(2016, 2025))), kind="line")


# --------------------------------------------------------------- SI-090

def test_compute_tells_the_model_a_slice_counts_observations():
    """POLICY GUARD. `[-365:]` on a business-daily series is ~17 months, not a year, and the
    chart then contradicts its own title. The rule is stated in language to the model — no
    keyword list, no hardcoded frequency — so this asserts the directive still reaches it."""
    from user_tools.compute_tool import ComputeTool
    schema = json.dumps(ComputeTool().parameters, default=str)
    assert "A SLICE COUNTS OBSERVATIONS, NOT CALENDAR DAYS" in schema
    assert "select it from the date column" in schema


def test_the_directive_states_the_REAL_returned_element_cap():
    """A DIRECTIVE MUST NOT ASK FOR WHAT A CODE GATE REFUSES.

    The first version of this directive said a trading year is "roughly 252 trading rows".
    The model duly switched from `[-365:]` to `[-252:]` — and `compute` renders at most
    `_MAX_RETURNED_ELEMENTS` (200) values, so a 252-row result came back TRUNCATED, which the
    SI-085 guard correctly refuses to reference. Measured: `d[-252:]` 36x, four
    "shows only the first 200 of 252 values" refusals, and charts fell from 2/3 to 0/3.

    The directive now states the cap and tells the model to thin. Asserting it against the
    CONSTANT, not a literal, is the point: if the cap ever changes, the text follows it.
    """
    from user_tools.compute_tool import ComputeTool, _MAX_RETURNED_ELEMENTS
    schema = json.dumps(ComputeTool().parameters, default=str)
    assert f"at most {_MAX_RETURNED_ELEMENTS} values" in schema
    assert "thin a long window" in schema
    assert "252 " not in schema, "do not anchor the model on a row count that exceeds the cap"


@pytest.mark.asyncio
async def test_a_thinned_window_is_actually_referenceable():
    """The shape the directive now recommends must survive the round trip: compute it, then
    reference it — the exact step that failed when the series exceeded the cap."""
    from user_tools.compute_tool import ComputeTool, _MAX_RETURNED_ELEMENTS
    from utils.tool_output_reference import extract_column
    n = _MAX_RETURNED_ELEMENTS + 52          # a full trading year: over the cap
    d = [f"2025-{1 + i % 12:02d}-{1 + i % 28:02d}" for i in range(n)]
    y = [4.0 + (i % 17) * 0.01 for i in range(n)]
    r = await ComputeTool().execute(expr='y[::2]', data={"d": d, "y": y}, label="")
    assert r["success"]
    vals = extract_column(r["result"], "y[::2]")       # must NOT raise
    assert len(vals) == (n + 1) // 2 <= _MAX_RETURNED_ELEMENTS


@pytest.mark.asyncio
async def test_an_over_cap_series_is_still_refused_the_guard_must_not_be_weakened():
    """SI-085 must keep refusing a truncated series — the fix is to thin, not to relax."""
    from user_tools.compute_tool import ComputeTool, _MAX_RETURNED_ELEMENTS
    from utils.tool_output_reference import ReferenceError_, extract_column
    n = _MAX_RETURNED_ELEMENTS + 52
    y = [4.0 + (i % 17) * 0.01 for i in range(n)]
    r = await ComputeTool().execute(expr='y[:]', data={"y": y}, label="")
    assert r["success"]
    with pytest.raises(ReferenceError_):
        extract_column(r["result"], "y[:]")


@pytest.mark.asyncio
async def test_a_calendar_window_is_actually_expressible():
    """The directive must not tell the model to do something the CODE refuses — the prompt-vs-
    code contradiction that has bitten twice. A date mask must really evaluate."""
    from user_tools.compute_tool import ComputeTool
    r = await ComputeTool().execute(
        expr='y[np.array(d) >= "2025-08-21"]',
        data={"d": ["2025-06-01", "2025-08-20", "2025-08-21", "2026-01-15"],
              "y": [4.0, 4.1, 4.2, 4.3]}, label="")
    assert r["success"] and "4.2" in r["result"] and "4.0" not in r["result"]


# ------------------------- SI-091 generalisation: every sampling frequency
#
# The first version of this fix was tested ONLY on business-daily data, and looked correct.
# Asked whether it generalised to weekly and monthly data, it did not: with `%Y` the locator
# placed ticks at evenly-spaced DECIMAL positions that do not align to 1 January, so two ticks
# could fall inside one calendar year. Measured before the locator was matched to the format:
#     span 3.2y  -> ['2020', '2021', '2021', '2022', '2023']        duplicate
#     span 4.1y  -> ['2020', '2020', '2021', '2022', '2023', ...]   duplicate
#     quarterly  -> ['2020', '2021', '2023', '2024', '2026']        2022 and 2025 skipped
# An axis that repeats or skips a year is worse than one reading 2025.8, because it looks
# authoritative. These cases exist so a future change to the format thresholds has to face
# every frequency, not just the one that was in front of us.

from datetime import date, timedelta            # noqa: E402


def _months(start, n):
    out, d = [], start
    for _ in range(n):
        out.append(d.isoformat())
        d = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return out


def _quarters(start, n):
    out, d = [], start
    for _ in range(n):
        out.append(d.isoformat())
        m = d.month + 3
        d = date(d.year + (m > 12), (m - 1) % 12 + 1, 1)
    return out


def _rendered_ticks(isos):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    xs = [PlotDataTool._to_decimal_year(s) for s in isos]
    fig, ax = _fig_ax()
    ax.plot(xs, list(range(len(xs))))
    applied = _apply_temporal_ticks(ax, xs)
    FigureCanvasAgg(fig)
    fig.canvas.draw()
    return applied, [t.get_text() for t in ax.get_xticklabels() if t.get_text()]


FREQUENCIES = {
    "monthly/10yr":  _months(date(2016, 1, 1), 120),
    "monthly/5yr":   _months(date(2021, 1, 1), 60),
    "monthly/18mo":  _months(date(2021, 1, 1), 18),
    "monthly/12mo":  _months(date(2025, 1, 1), 12),
    "quarterly/6yr": _quarters(date(2020, 1, 1), 24),
    "quarterly/2yr": _quarters(date(2024, 1, 1), 8),
    "weekly/3yr":    [(date(2023, 1, 2) + timedelta(weeks=i)).isoformat() for i in range(156)],
    "weekly/1yr":    [(date(2025, 1, 3) + timedelta(weeks=i)).isoformat() for i in range(52)],
    "weekly/8wk":    [(date(2025, 1, 3) + timedelta(weeks=i)).isoformat() for i in range(8)],
    "daily/1yr":     [(date(2025, 9, 2) + timedelta(days=i)).isoformat() for i in range(0, 365, 3)],
    "daily/30d":     [(date(2025, 9, 2) + timedelta(days=i)).isoformat() for i in range(30)],
    "daily/5d":      [(date(2025, 9, 2) + timedelta(days=i)).isoformat() for i in range(5)],
    # The spans that ACTUALLY produced duplicates before the locator matched the format.
    # Without these the suite passes on the broken code — the first version of this file did.
    "daily/3.2yr":   [(date(2020, 3, 15) + timedelta(days=i)).isoformat() for i in range(0, 1180, 29)],
    "daily/4.1yr":   [(date(2020, 3, 15) + timedelta(days=i)).isoformat() for i in range(0, 1500, 37)],
    "daily/3.6yr":   [(date(2020, 3, 15) + timedelta(days=i)).isoformat() for i in range(0, 1300, 32)],
}


@pytest.mark.parametrize("name", sorted(FREQUENCIES))
def test_no_frequency_produces_a_repeated_tick_label(name):
    """An axis that says 2021 twice, or skips 2022, reads as missing data."""
    applied, labels = _rendered_ticks(FREQUENCIES[name])
    assert applied is True
    assert len(labels) == len(set(labels)), f"{name}: repeated labels {labels}"


@pytest.mark.parametrize("name", sorted(FREQUENCIES))
def test_no_frequency_leaves_a_decimal_year_on_the_axis(name):
    """The whole point: no tick may read '2025.8'."""
    _, labels = _rendered_ticks(FREQUENCIES[name])
    assert not any("." in lab for lab in labels), f"{name}: decimal year in {labels}"


@pytest.mark.parametrize("name", sorted(FREQUENCIES))
def test_year_labels_land_on_year_boundaries(name):
    """With `%Y` the ticks must be whole years, EVENLY spaced — not arbitrary positions that
    happen to round to a year. Pre-fix the quarterly/6yr axis read
    ['2020', '2021', '2023', '2024', '2026'], skipping 2022 and 2025, which reads as missing
    data. Applied to every frequency so a threshold change cannot quietly reintroduce it."""
    _, labels = _rendered_ticks(FREQUENCIES[name])
    if not all(lab.isdigit() for lab in labels):
        pytest.skip("not a %Y axis")
    years = [int(x) for x in labels]
    assert years == sorted(years)
    steps = {b - a for a, b in zip(years, years[1:])}
    assert len(steps) == 1, f"{name}: uneven year spacing {years}"


def test_annual_data_given_as_dates_is_left_alone():
    """Every value is exactly YYYY.0, so it is indistinguishable from the catalog's whole years
    — and '2016' is already the right label."""
    applied, _ = _rendered_ticks([f"{y}-01-01" for y in range(2016, 2025)])
    assert applied is False
