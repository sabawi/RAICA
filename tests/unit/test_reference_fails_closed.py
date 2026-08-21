"""SI-085: a reference that cannot be honoured must RAISE, never resolve to something else.

TWO PRODUCTION FAILURES, ONE SHAPE
----------------------------------
Both were found by verifying the artifact the user receives, not the logs — every one of these
logged as a successful call.

(1) WRONG SELECTION. A chart asked `compute#5` for `d[::60]` — correctly naming the thinned DATES
    for its x-axis. That output held ONE series, and the SI-047 contract ("with one series the
    output IS the answer, the column name is ignored") handed back HOUSING STARTS instead. The
    chart rendered a y=x diagonal with an axis labelled "Date" showing 600-1800. Three charts
    across two datasets failed this way (2026-08-18), each plausible, each wrong.

    The fix cannot be a whitelist: `test_integer_counts_stay_usable` legitimately passes
    `"column": "count"`, a plain descriptive label. The discriminator is SHAPE — an
    expression-shaped name (`d[::60]`, `np.mean(y)`) is a SELECTION and must match; a plain label
    (`value`, `count`) is the habit SI-047 exists to tolerate.

(2) A PREFIX IS NOT THE SERIES. `compute` renders at most 200 values and appends
    "[TRUNCATED: showing the first 200 of 943 values]". Both parsers dropped that line and returned
    the 200 as the series. A Phillips-curve answer reported inflation statistics — mean 2.00%,
    max 10.24% "in January 1948" — computed over months 1-200 (Jan 1948 - Aug 1964) of a 943-month
    series whose true maximum is ~14.8% in March 1980, while narrating the full 1948-2026 history
    around them. 36 truncation markers in that one run.
"""
import pytest

from utils.tool_output_reference import ReferenceError_, describe_reference, extract_column

# Real shape: one entry, as compute renders a single expression.
ONE = """- [478, 512, 604, 715, 880]
computed as: houst[::60]
over n=811 data point(s); inputs: houst
dtype: float64
STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it."""

TWO = """- [1.5, 1.6, 1.7]
computed as: y10[::3]
over n=157 data point(s); inputs: y10
dtype: float64
- [0.5, 0.4, 0.3]
computed as: (y10 - y2)[::3]
over n=157 data point(s); inputs: y10, y2
dtype: float64"""

TRUNC = """- [0.5, 1.2, 2.4, 3.1]
[TRUNCATED: showing the first 200 of 943 values]
computed as: (cpi[12:] / cpi[:-12] - 1) * 100
over n=955 data point(s); inputs: cpi
dtype: float64"""


# ── (1) wrong selection ───────────────────────────────────────────────────────────────────────
def test_an_expression_shaped_name_that_matches_nothing_RAISES():
    """The exact production call: asking a single-series output for a different expression."""
    with pytest.raises(ReferenceError_) as e:
        extract_column(ONE, "d[::60]")
    assert "houst[::60]" in str(e.value), "the error must name what IS available"


def test_the_wrong_series_is_never_returned_silently():
    """The failure mode itself: plausible data for a reference that was not honoured."""
    try:
        got = extract_column(ONE, "d[::60]")
    except ReferenceError_:
        got = None
    assert got != [478, 512, 604, 715, 880], "housing starts returned for a request for dates"


def test_the_garbage_column_from_a_mis_parsed_table_RAISES():
    """The other production shape: a fragment copied out of a bogus column list."""
    with pytest.raises(ReferenceError_):
        extract_column(ONE, "- ['08/17/2026'")


def test_a_mismatched_expression_RAISES_on_a_multi_entry_output_too():
    with pytest.raises(ReferenceError_) as e:
        extract_column(TWO, "m3[::3]")
    assert "y10[::3]" in str(e.value)


# ── (2) truncation ────────────────────────────────────────────────────────────────────────────
def test_a_truncated_series_cannot_be_referenced():
    with pytest.raises(ReferenceError_) as e:
        extract_column(TRUNC, "(cpi[12:] / cpi[:-12] - 1) * 100")
    msg = str(e.value)
    assert "943" in msg, "the error must state the REAL length"
    assert "prefix" in msg.lower()


def test_the_truncation_error_says_what_to_do_instead():
    """An error the model can act on beats one it can only report."""
    with pytest.raises(ReferenceError_) as e:
        extract_column(TRUNC, "(cpi[12:] / cpi[:-12] - 1) * 100")
    assert "np.mean(" in str(e.value), "no actionable alternative offered"


def test_a_truncated_series_is_ANNOUNCED_as_unreferenceable():
    """Description and resolution must agree, or the model is invited to fail."""
    d = describe_reference("compute#3", TRUNC)
    assert "TRUNCATED" in d and "NOT referenceable" in d


# ── controls: the habits SI-047 exists to tolerate must keep working ──────────────────────────
def test_CONTROL_a_plain_label_still_resolves_a_single_series():
    """SI-047. `test_computed_series_source_ignores_the_column_name` depends on this."""
    assert extract_column(ONE, "value") == [478, 512, 604, 715, 880]


def test_CONTROL_the_descriptive_label_count_still_resolves():
    """`test_integer_counts_stay_usable` passes exactly this."""
    assert extract_column(ONE, "count") == [478, 512, 604, 715, 880]


def test_CONTROL_the_matching_expression_resolves():
    assert extract_column(ONE, "houst[::60]") == [478, 512, 604, 715, 880]
    assert extract_column(TWO, "(y10 - y2)[::3]") == [0.5, 0.4, 0.3]


def test_CONTROL_an_index_still_resolves():
    assert extract_column(TWO, "1") == [0.5, 0.4, 0.3]


def test_CONTROL_an_untruncated_series_is_unaffected():
    assert extract_column(TWO, "y10[::3]") == [1.5, 1.6, 1.7]
    assert "NOT referenceable" not in describe_reference("compute#1", TWO)
