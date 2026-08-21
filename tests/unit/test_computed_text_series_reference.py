"""SI-088 — a computed DATE series must be referenceable, and must be DESCRIBED.

THE FAILURE THIS PREVENTS
-------------------------
`_values_from_compute_block` built a series only if EVERY value parsed as a number. A date
series renders as `['2025-09-02', '2025-09-05', …]` (numpy dtype `<U10`) and parses as no
number at all, so the whole entry was DROPPED — silently, inside `computed_entries`, before
`extract_column`'s `numeric=False` flag could be consulted.

Production 2026-08-21, "fetch DGS10 from FRED and plot the yield over the last year", 4 runs
out of 4: no chart, `plot_data` never invoked. ONE defect, TWO symptoms:

  1. the date axis could not be referenced -> `d[-252:][::3]` raised;
  2. the surviving entries collapsed 2 -> 1, which fails the `len(_entries) > 1` gate in
     `describe_reference`, so the model was shown a bare "text" dump with NO series index
     and NO reference syntax. It called its own output "garbled — the column headers and row
     structure are malformed" and re-issued `compute` until the gather-gate rounds ran out.

Note this is NOT reachable by plotting the raw CSV instead: 16,862 rows exceeds
`plot_data._MAX_POINTS` (5000), so the dates MUST be thinned through `compute` — exactly
where they stopped being referenceable. The defect itself is size-independent (see the
3-point test below).

THE RULE, reused from the tabular path in the same module: THE CONTENT DECIDES THE TYPE.
"if most cells do not parse as numbers, the column is text" — return it as text and let the
consuming tool interpret it (plot_data understands date strings).
"""
import pytest

from utils.tool_output_reference import (
    ReferenceError_, computed_entries, describe_reference, extract_column)


def _two_series(dates, values):
    d = ", ".join(f"'{x}'" for x in dates)
    v = ", ".join(str(x) for x in values)
    return (f"- [{d}]\n"
            f"computed as: d[-252:][::3]\n"
            f"over n=16862 data point(s); inputs: d, y\n"
            f"dtype: <U10\n"
            f"- [{v}]\n"
            f"computed as: y[-252:][::3]\n"
            f"over n=16862 data point(s); inputs: d, y\n"
            f"dtype: float64")


REAL = _two_series(["2025-09-02", "2025-09-05", "2025-09-10", "2025-09-15"],
                   [4.28, 4.1, 4.04, 4.05])


# ------------------------------------------------- symptom 1: referenceable

def test_both_series_survive_parsing():
    """FAILS pre-SI-088: returned 1 entry for an output plainly holding 2."""
    entries = computed_entries(REAL)
    assert len(entries) == 2
    assert [e["expr"] for e in entries] == ["d[-252:][::3]", "y[-252:][::3]"]


def test_the_date_series_resolves_to_real_dates():
    """FAILS pre-SI-088 with ReferenceError_ — the x-axis of every time-series chart."""
    assert extract_column(REAL, "d[-252:][::3]") == [
        "2025-09-02", "2025-09-05", "2025-09-10", "2025-09-15"]


def test_the_numeric_series_is_unchanged():
    """Control: the series that always worked must still come back as numbers."""
    assert extract_column(REAL, "y[-252:][::3]") == [4.28, 4.1, 4.04, 4.05]


def test_quotes_are_stripped_they_are_numpy_presentation():
    assert all(not v.startswith("'") for v in extract_column(REAL, "d[-252:][::3]"))


def test_the_defect_is_size_independent():
    """A 3-point date series fails identically pre-fix — size is not the cause. The 16,862
    rows only closed the workaround (raw CSV > plot_data's 5000-point limit)."""
    tiny = _two_series(["2025-09-02", "2025-09-05", "2025-09-10"], [4.28, 4.1, 4.04])
    assert len(computed_entries(tiny)) == 2
    assert extract_column(tiny, "d[-252:][::3]")[0] == "2025-09-02"


# ------------------------------------------------- symptom 2: described

def test_the_model_is_shown_a_series_index_and_the_reference_syntax():
    """FAILS pre-SI-088: entries collapsed 2->1, the `len(_entries) > 1` gate failed, and the
    model got a bare 'text' dump with nothing telling it what it could reference."""
    desc = describe_reference("compute#1", REAL)
    assert "2 computed series" in desc
    assert "`d[-252:][::3]`" in desc
    assert "REFERENCE ONE BY ITS EXPRESSION" in desc
    assert '"from": "compute#1"' in desc


def test_describing_a_text_series_does_not_crash():
    """`f"{x:g}"` raises ValueError on a str — the preview must tolerate a text series."""
    assert "2025-09-02" in describe_reference("compute#1", REAL)


# ------------------------------------------------- the rule stays honest

def test_a_mostly_numeric_series_with_junk_is_still_refused():
    """The rescue is for a series that is PLAINLY text. A mixed column is not silently
    reinterpreted as text — that would hand back numbers as strings."""
    mixed = ("- [1.0, 2.0, 3.0, N/A]\n"
             "computed as: y[:4]\n"
             "over n=4 data point(s); inputs: y\n"
             "dtype: float64")
    with pytest.raises(ReferenceError_):
        extract_column(mixed, "y[:4]")


def test_an_all_numeric_series_is_never_turned_into_text():
    plain = ("- [1.0, 2.0, 3.0]\n"
             "computed as: y[:3]\n"
             "over n=3 data point(s); inputs: y\n"
             "dtype: float64")
    assert extract_column(plain, "y[:3]") == [1.0, 2.0, 3.0]


def test_nan_gaps_do_not_make_a_numeric_series_text():
    """A gap must stay a gap in a NUMERIC series, not flip the whole column to strings."""
    gappy = ("- [4.28, nan, 4.04]\n"
             "computed as: y[:3]\n"
             "over n=3 data point(s); inputs: y\n"
             "dtype: float64")
    out = extract_column(gappy, "y[:3]")
    assert out[0] == 4.28 and out[2] == 4.04
    assert out[1] != out[1]          # nan


# ------------------------- the habit must survive dates becoming visible

@pytest.mark.parametrize("plain", ["value", "count", "diff", "d", "counts",
                                   "bin_centres", "daily_change"])
def test_a_plain_label_still_names_the_one_numeric_series(plain):
    """REGRESSION GUARD for the SI-088 fix itself.

    Making dates referenceable turned a dates+values output from ONE entry into TWO, which
    silently withdrew the SI-047 habit for every plain label that used to resolve — 13 of
    them in the production corpus (`value`, `diff`, `count`, …), measured by differential
    replay. A plain label means "the number I computed" and a date is not a value, so with
    exactly one NUMERIC series a plain label must still name it.
    """
    assert extract_column(REAL, plain) == [4.28, 4.1, 4.04, 4.05]


def test_the_habit_is_withdrawn_when_two_NUMERIC_series_are_present():
    """The habit is only safe while it is unambiguous. Two numeric series must raise and name
    them, not silently pick one."""
    two_numeric = ("- [1.0, 2.0]\ncomputed as: y\nover n=2 data point(s); inputs: y\n"
                   "dtype: float64\n"
                   "- [3.0, 4.0]\ncomputed as: np.diff(y)\nover n=2 data point(s); inputs: y\n"
                   "dtype: float64")
    with pytest.raises(ReferenceError_):
        extract_column(two_numeric, "value")


def test_index_zero_is_the_FIRST_series_and_agrees_with_the_description():
    """Resolution must agree with what the model is told is addressable.

    `describe_reference` lists `[0] d[…]` then `[1] y[…]`, so index 0 must be the DATES. Before
    SI-088 the date entry was invisible, so index 0 landed on the yields — and no index was
    ever shown for such an output, so nothing depended on that numbering.
    """
    desc = describe_reference("compute#1", REAL)
    assert desc.index("`d[-252:][::3]`") < desc.index("`y[-252:][::3]`")
    assert extract_column(REAL, "0")[0] == "2025-09-02"
    assert extract_column(REAL, "1") == [4.28, 4.1, 4.04, 4.05]
