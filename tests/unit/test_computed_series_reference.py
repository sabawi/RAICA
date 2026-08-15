"""SI-047 — a COMPUTED series must be chartable, not just a fetched column.

THE DEFECT. `extract_column` resolved every reference through `_parse_table`, which requires a
header and at least two rows. A `compute` result is not a table — it is a labelled scalar or array
followed by its provenance:

    25th/75th/90th percentiles: [5.6  , 6.   , 6.4  ]
    computed as: np.percentile(mag, [25, 75, 90])
    over n=225 data point(s); inputs: mag
    dtype: float64

So `{"from": "compute#9", ...}` could NEVER resolve, and anything the model calculated — a
histogram, a fitted curve, a transformed axis — was unchartable by construction. On production
every plot_data call for a distribution curve failed with "referenced output does not contain a
table with a header and rows".

It only became fatal once the SI-046 directive started pushing the model to plot computed things.
Before that, charts referenced a raw fetched column, which IS a table and resolved fine — which is
why the defect sat unnoticed behind a working feature.
"""
import pytest

# `computed_series` is imported INSIDE the one test that needs it. At module level it would make
# this whole file error at collection against pre-fix code, where the function does not exist —
# and an ERROR proves nothing. Imported lazily, the behavioural tests below fail on their own
# assertions instead, which is what discriminates.
from utils.tool_output_reference import ReferenceError_, extract_column


def _compute(body, expr="np.mean(mag)", n=225, dtype="float64"):
    """The exact shape compute_tool._format emits."""
    return (f"{body}\ncomputed as: {expr}\n"
            f"over n={n} data point(s); inputs: mag\ndtype: {dtype}\n"
            f"STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it.")


CSV = "Date,Close\n2026-01-01,101.5\n2026-01-02,103.25\n2026-01-03,99.0\n"
JSON = '[{"date":"2026-01-01","close":101.5},{"date":"2026-01-02","close":103.25}]'


class TestComputedSeriesResolves:

    def test_an_array_result_resolves_without_a_column(self):
        """A compute result has no columns — the output IS the series. Pre-fix this raised
        'a reference needs a column naming which values to take'."""
        text = _compute("25th, 75th, 90th, 95th, 99th percentiles: [5.6  , 6.   , 6.4  , 6.68 , 7.476]")
        assert extract_column(text, None) == [5.6, 6.0, 6.4, 6.68, 7.476]

    def test_integer_histogram_counts_resolve(self):
        """The exact series a distribution chart needs."""
        text = _compute("counts (15 bins): [74, 62, 17, 32, 11, 8, 5, 6, 0, 2, 1, 2, 2, 2, 1]",
                        expr="np.histogram(mag, bins=15)[0]", dtype="int64")
        assert extract_column(text, None)[:4] == [74.0, 62.0, 17.0, 32.0]

    def test_a_scalar_result_resolves_as_a_one_value_series(self):
        assert extract_column(_compute("mean magnitude: 5.88"), None) == [5.88]

    def test_an_unlabelled_array_resolves(self):
        assert extract_column(_compute("[1.5, 2.5, 3.5]"), None) == [1.5, 2.5, 3.5]

    def test_a_truncation_note_is_not_mistaken_for_data(self):
        """compute appends '[TRUNCATED: showing the first N of M values]' — square brackets that
        are prose, not values. Parsing them would poison the series with garbage."""
        text = ("curve: [0.1, 0.2, 0.3]\n[TRUNCATED: showing the first 3 of 900 values]\n"
                "computed as: np.linspace(0,1,900)\nover n=900 data point(s); inputs: x\ndtype: float64")
        assert extract_column(text, None) == [0.1, 0.2, 0.3]

    def test_a_column_name_is_ignored_rather_than_rejected(self):
        """The model often passes a column out of habit. Erroring on it would fail a reference
        that is otherwise perfectly resolvable."""
        text = _compute("counts: [74, 62, 17]", expr="np.histogram(mag, bins=3)[0]")
        assert extract_column(text, "count") == [74.0, 62.0, 17.0]


class TestExistingPathsUnchanged:
    """Widening the resolver must not weaken it: a table is still a table, and a missing or wrong
    column must still fail loudly rather than silently charting the wrong numbers."""

    def test_a_csv_column_still_resolves(self):
        assert extract_column(CSV, "Close") == [101.5, 103.25, 99.0]

    def test_json_records_still_resolve(self):
        assert extract_column(JSON, "close") == [101.5, 103.25]

    def test_a_table_without_a_column_still_errors(self):
        with pytest.raises(ReferenceError_, match="needs a 'column'"):
            extract_column(CSV, None)

    def test_a_wrong_column_name_still_errors_and_lists_the_real_ones(self):
        with pytest.raises(ReferenceError_, match="available columns"):
            extract_column(CSV, "Nope")

    def test_non_compute_prose_is_not_treated_as_a_series(self):
        from utils.tool_output_reference import computed_series
        assert computed_series("just some prose with no marker at all") is None
        assert computed_series("") is None
