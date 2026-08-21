"""SI-081: every series in a multi-expression `compute` result must be addressable.

THE DEFECT THESE PREVENT
------------------------
Two faults, compounding, both in the reference layer:

1. `extract_column` reached its computed-series branch only when `not _looks_tabular(text)`.
   `_looks_tabular` is a comma-counting guess, and a computed array prints as
   `- [-0.03, -0.04, 0.03, ...]` — commas enough to look like CSV. So the branch was skipped for
   exactly the outputs it exists to serve, `_parse_table` read the VALUE line as a header, and the
   model was told:

       available columns: ['- [-0.03', '-0.04', '0.03', '0.01', '0.02', '0.', '']

   i.e. the data itself, offered as column names.

2. `compute` evaluates a LIST of expressions in one call (SI-067, up to 12), but `computed_series`
   splits on the FIRST "computed as:" and could only ever see the first entry. There was no way to
   address expression #3. The model tried `{"column": "d[::10]"}` (the expression) and
   `{"column": "0"}` (an index) — both reasonable, neither supported, neither announced.

Net effect: a chart of anything computed was impossible. Measured 2026-08-18: 0 real charts in 15
end-to-end runs.
"""
import pytest

from utils.tool_output_reference import (
    ReferenceError_, describe_reference, extract_column)

# The REAL shape, per compute_tool._format + _evaluate_many: batch label, bulleted entries, and
# the provenance + directive block that trails each one.
MULTI = """DGS10 yield statistics: valid count, mean, thinned series:
- 16859
computed as: np.size(y)
over n=16859 data point(s); inputs: y
dtype: int64
STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it, and give an extremum its date/label.
- 5.882
computed as: np.nanmean(y)
over n=16859 data point(s); inputs: y
dtype: float64
STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it, and give an extremum its date/label.
- [-0.03, -0.04,  0.03,  0.01,  0.02]
computed as: d[::10]
over n=16859 data point(s); inputs: d
dtype: float64
STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it, and give an extremum its date/label."""

SINGLE = """25th/75th/90th percentiles: [5.6  , 6.   , 6.4  ]
computed as: np.percentile(mag, [25, 75, 90])
over n=225 data point(s); inputs: mag
dtype: float64"""

TABLE = "date,DGS10\n1962-01-02,4.06\n1962-01-03,4.03\n1962-01-04,3.99\n"
PROSE = "The ten-year yield averaged 5.88% over the period, with notable peaks in 1981."


def test_a_computed_array_is_not_mistaken_for_a_table():
    """FAULT 1. The comma-rich value line was being read as a CSV header."""
    values = extract_column(MULTI, "d[::10]")
    assert values == [-0.03, -0.04, 0.03, 0.01, 0.02]


def test_the_model_can_reference_a_series_by_its_EXPRESSION():
    """FAULT 2, and exactly what the model actually sent on production."""
    assert extract_column(MULTI, "d[::10]") == [-0.03, -0.04, 0.03, 0.01, 0.02]
    assert extract_column(MULTI, "np.nanmean(y)") == [5.882]


def test_the_model_can_reference_a_series_by_its_INDEX():
    """The model's other real attempt, `{"column": "0"}`."""
    assert extract_column(MULTI, "0") == [16859.0]
    assert extract_column(MULTI, "2") == [-0.03, -0.04, 0.03, 0.01, 0.02]


def test_expression_lookup_is_case_insensitive():
    assert extract_column(MULTI, "NP.NANMEAN(Y)") == [5.882]


def test_an_unknown_name_names_the_REAL_expressions():
    """An error the model can act on beats a wrong series charted silently."""
    with pytest.raises(ReferenceError_) as e:
        extract_column(MULTI, "np.median(y)")
    msg = str(e.value)
    assert "np.size(y)" in msg and "d[::10]" in msg
    assert "'- [-0.03" not in msg, "still offering the data as column names"


def test_every_series_is_ANNOUNCED_with_its_reference_syntax():
    """Description and resolution must agree, or the model is told one thing and refused another."""
    d = describe_reference("compute#3", MULTI)
    assert "3 computed series" in d
    for expr in ("np.size(y)", "np.nanmean(y)", "d[::10]"):
        assert expr in d, f"{expr} not announced"
    assert '{"from": "compute#3", "column":' in d
    assert "text, " not in d, "still described as opaque prose"


def test_the_announced_name_actually_resolves():
    """The syntax the description advertises must be one extract_column accepts."""
    import re
    d = describe_reference("compute#3", MULTI)
    col = re.search(r'"column":\s*"([^"]+)"', d).group(1)
    assert extract_column(MULTI, col) is not None


# ── controls: everything that already worked must keep working ────────────────────────────────
def test_CONTROL_single_expression_result_is_unchanged():
    """SI-047/SI-075 behaviour: one series, the output IS the answer, column name irrelevant."""
    assert extract_column(SINGLE, "value") == [5.6, 6.0, 6.4]
    assert extract_column(SINGLE, "anything") == [5.6, 6.0, 6.4]
    assert "computed series" in describe_reference("compute#1", SINGLE)


def test_CONTROL_a_real_table_is_still_a_table():
    assert extract_column(TABLE, "DGS10") == [4.06, 4.03, 3.99]
    assert "table" in describe_reference("lookup_website#1", TABLE)


def test_CONTROL_prose_is_not_a_computed_series():
    with pytest.raises(ReferenceError_):
        extract_column(PROSE, "value")


def test_a_FAILED_expression_yields_no_referenceable_series():
    """Fail-closed: a figure that was never computed must never be citable.

    Scoped to the MULTI case deliberately. With exactly ONE computed series the column name is
    ignored by long-standing design (SI-047, and `test_computed_series_source_ignores_the_column
    _name` asserts it) — the output IS the answer there. An earlier draft of this test demanded
    the stricter behaviour in the single case too and was wrong about the contract, not about the
    code.
    """
    partial = """- 5.882
computed as: np.nanmean(y)
over n=10 data point(s); inputs: y
dtype: float64
- 0.42
computed as: np.nanstd(y)
over n=10 data point(s); inputs: y
dtype: float64
- `np.std(d)` -> rejected: name 'd' is not defined"""
    with pytest.raises(ReferenceError_) as e:
        extract_column(partial, "np.std(d)")
    listed = str(e.value)[str(e.value).index("["):]      # the expressions the error offers
    assert "np.std(d)" not in listed, "a rejected expression was offered as referenceable"
    assert "np.nanmean(y)" in listed and "np.nanstd(y)" in listed
    assert extract_column(partial, "np.nanmean(y)") == [5.882]
    assert extract_column(partial, "np.nanstd(y)") == [0.42]
