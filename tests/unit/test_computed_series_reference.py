"""A computed series must ANNOUNCE that it is referenceable, or its chart is lost.

FAILURE THIS PREVENTS (SI-075)
------------------------------
`extract_column` has resolved `compute` results since SI-047, via a purpose-built
`computed_series()` helper. But `describe_reference` classified those same results as prose:

    === compute#1 === text, 180 characters
    - [74, 62, 17, 32, 11]
    computed as: np.histogram(mag, bins=5)[0]
    ...

The capability existed; its signpost did not. The model was never told those values could be
referenced, so to chart a histogram it had ALREADY COMPUTED CORRECTLY it re-sent the raw
16,859-point source column instead. Measured 2026-08-18 on the DGS10 prompt: ten plot_data
attempts, ten rejections ("x has 16859 points, over the 5000 limit" / "x must be a list"), and
zero charts across four runs — for a chart that needed 50 points.

THE INVARIANT: description and resolution must agree about what is referenceable. Both now go
through `computed_series()`, so they cannot drift apart.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from utils.tool_output_reference import (  # noqa: E402
    ReferenceError_, computed_series, describe_reference, extract_column)

SERIES = ("- [74, 62, 17, 32, 11]\n"
          "computed as: np.histogram(mag, bins=5)[0]\n"
          "over n=225 data point(s); inputs: mag\ndtype: int64")
SCALAR = ("5.8828\ncomputed as: np.mean(mag)\n"
          "over n=225 data point(s); inputs: mag\ndtype: float64")
PROSE = "As of today here are the website lookup results: ordinary prose, no computed values."
TABLE = "Date,Value\n2026-01-01,1.5\n2026-01-02,2.5"


def test_a_computed_series_is_described_as_referenceable():
    """FAILS PRE-FIX: described as "text, N characters" with no hint it could be referenced."""
    d = describe_reference("compute#1", SERIES)
    assert "computed series" in d, d[:120]
    assert "text," not in d, "still described as prose"


def test_the_description_shows_the_exact_reference_syntax():
    """The model must not have to guess the column name for a series that has none."""
    d = describe_reference("compute#2", SERIES)
    assert '{"from": "compute#2", "column": "value"}' in d


def test_the_description_states_the_value_count_and_expression():
    """Length decides whether it fits plot_data's 5,000-point limit; the expression is provenance."""
    d = describe_reference("compute#1", SERIES)
    assert "5 value(s)" in d
    assert "np.histogram(mag, bins=5)[0]" in d


def test_description_and_resolution_agree():
    """THE invariant. If describe says referenceable, extract must deliver — same helper, both."""
    d = describe_reference("compute#1", SERIES)
    assert "computed series" in d
    assert extract_column(SERIES, "value") == [74.0, 62.0, 17.0, 32.0, 11.0]


def test_a_scalar_result_is_also_referenceable():
    """A single computed figure is a 1-value series, not prose."""
    assert "computed series, 1 value(s)" in describe_reference("compute#1", SCALAR)
    assert extract_column(SCALAR, "value") == [5.8828]


def test_it_tells_the_model_NOT_to_resend_the_source_column():
    """The exact production mistake: re-sending the raw column the series was derived from."""
    d = describe_reference("compute#1", SERIES)
    assert "do not re-send the source column" in d


# ─────────────────────────────────────────── controls: nothing else may be reclassified
def test_prose_is_still_described_as_text():
    d = describe_reference("lookup_website#1", PROSE)
    assert "text," in d and "computed series" not in d


def test_prose_still_fails_to_resolve():
    """The control must stay unresolvable — otherwise the branch is too eager."""
    try:
        extract_column(PROSE, "value")
        raise AssertionError("prose resolved as a series")
    except ReferenceError_:
        pass


def test_a_real_table_is_still_described_as_a_table():
    d = describe_reference("lookup_website#1", TABLE)
    assert "table," in d and "computed series" not in d
    assert "'Date'" in d and "'Value'" in d


def test_computed_series_helper_is_the_single_source_of_truth():
    """Both paths must key off the same helper so they cannot disagree."""
    assert computed_series(SERIES) == [74.0, 62.0, 17.0, 32.0, 11.0]
    assert computed_series(PROSE) is None
    assert computed_series(TABLE) is None
