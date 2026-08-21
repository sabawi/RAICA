"""SI-087 — a compute result must resolve by the LABEL RAICA ITSELF PRINTED.

THE FAILURE THIS PREVENTS
-------------------------
`compute_tool._format` (user_tools/compute_tool.py:419) renders a single result as

    10-Year Treasury: [4.3, 4.35, 4.28, 4.41]
    computed as: y10

so the output announces its own human-readable name. SI-085 then hardened
`extract_column` so that an EXPRESSION-SHAPED name matching nothing raises instead of
silently returning a different series — the fix for a chart that asked `compute#5` for
`d[::60]` (dates) and was handed HOUSING STARTS, rendering a y=x diagonal labelled "Date".

But `_EXPRESSION_CHARS` contains `-`, `.` and `(`, which are ordinary ENGLISH punctuation.
So `"10-Year Treasury"` and `"CPI (index)"` were classified expression-shaped, matched no
expression, and RAISED — meaning the server rejected a reference to the very name it had
just printed one line above the values. Real Treasury and CPI labels are exactly this shape.

Found by the mandatory adversarial audit of v1.0.0.312 (attack #3), before release.

THE INVARIANTS, all of which must hold together:
  1. a reference to the printed label RESOLVES                        (SI-087, the fix)
  2. an expression-shaped name naming nothing still RAISES            (SI-085 preserved)
  3. a TRUNCATED series still RAISES even when the label matches      (SI-085 preserved)
  4. a plain label on a single series still resolves                  (SI-047 habit kept)
  5. non-compute outputs (table/JSON/prose) are untouched entirely

Tests 1 and 2-of-the-multi-series case FAIL on pre-SI-087 code.
"""
import pytest

from utils.tool_output_reference import ReferenceError_, computed_entries, extract_column


def _single(expr, label="", vals="[4.3, 4.35, 4.28, 4.41]"):
    """One computed series, exactly as compute_tool._format renders it."""
    head = f"{label}: " if label else ""
    return (f"{head}{vals}\n"
            f"computed as: {expr}\n"
            f"over n=4 data point(s); inputs: y\n"
            f"dtype: float64\n"
            f"STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it.")


def _multi(exprs, labels=None):
    out = []
    for i, e in enumerate(exprs):
        lab = f"{labels[i]}: " if labels else ""
        out.append(f"- {lab}[{i}.1, {i}.2, {i}.3]\n"
                   f"computed as: {e}\n"
                   f"over n=3 data point(s); inputs: y\n"
                   f"dtype: float64")
    return "\n".join(out)


def _truncated(expr, label=""):
    head = f"{label}: " if label else ""
    return (f"{head}[1.0, 2.0, 3.0]\n"
            f"[TRUNCATED: showing the first 3 of 900 values]\n"
            f"computed as: {expr}\n"
            f"over n=900 data point(s); inputs: y\n"
            f"dtype: float64")


# ---------------------------------------------------------------- 1. the fix

@pytest.mark.parametrize("label", [
    "10-Year Treasury",     # hyphen  -> was expression-shaped
    "CPI (index)",          # parens  -> was expression-shaped
    "Real GDP (chained)",
    "y/y change",           # slash
    "Unemployment rate",    # plain, must keep working
])
def test_reference_by_the_printed_label_resolves(label):
    """FAILS pre-SI-087 for every punctuated label: raised on the name it had printed."""
    text = _single("y10", label=label)
    assert extract_column(text, label) == [4.3, 4.35, 4.28, 4.41]


def test_label_match_is_case_insensitive_like_the_expression_match():
    text = _single("y10", label="10-Year Treasury")
    assert extract_column(text, "10-YEAR TREASURY") == [4.3, 4.35, 4.28, 4.41]


def test_label_resolves_among_several_series():
    """FAILS pre-SI-087: with >1 entry there was no habit fallback at all, so a labelled
    reference could never resolve — it went straight to the raise."""
    text = _multi(["y", "d[::20]", "np.diff(y)"],
                  ["10-Year Treasury", "Dates", "Daily change"])
    assert extract_column(text, "Daily change") == [2.1, 2.2, 2.3]
    assert extract_column(text, "10-Year Treasury") == [0.1, 0.2, 0.3]


def test_the_label_is_carried_on_every_entry():
    entries = computed_entries(_single("y10", label="10-Year Treasury"))
    assert entries[0]["label"] == "10-Year Treasury"
    assert entries[0]["expr"] == "y10"


def test_an_unlabelled_output_carries_an_empty_label_not_a_stray_prefix():
    """A bare `[1, 2, 3]` must not have its own values mistaken for a label."""
    entries = computed_entries(_single("y10"))
    assert entries[0]["label"] == ""


# ------------------------------------------------- 2 & 3. SI-085 must survive

def test_expression_shaped_name_matching_nothing_still_raises():
    """The original SI-085 defect: `d[::60]` must never resolve to a different series."""
    with pytest.raises(ReferenceError_):
        extract_column(_single("houst[::60]", label="Housing starts"), "d[::60]")


def test_truncated_series_still_raises_even_when_the_label_matches():
    """A prefix is not the series — the label match must not smuggle one through."""
    with pytest.raises(ReferenceError_) as exc:
        extract_column(_truncated("y", label="10-Year Treasury"), "10-Year Treasury")
    assert "first 3" in str(exc.value)


def test_a_wrong_label_still_raises():
    with pytest.raises(ReferenceError_):
        extract_column(_single("y10", label="10-Year Treasury"), "30-Year Treasury")


# ------------------------------------------------- 4. the SI-047 habit is kept

@pytest.mark.parametrize("plain", ["value", "count", "y", "diff", "counts", "centres"])
def test_plain_label_on_a_single_series_still_resolves(plain):
    assert extract_column(_single("y10"), plain) == [4.3, 4.35, 4.28, 4.41]


# ------------------------------------- 5. non-compute outputs are not touched

TABLE = "Date,10 Yr,30 Yr\n2026-01-01,4.18,4.84\n2026-01-02,4.14,4.81\n2026-01-03,4.16,4.83\n"
RECORDS = '[{"rate": 4.1, "place": "a"}, {"rate": 4.3, "place": "b"}]'


def test_tabular_reference_is_unaffected():
    """Every punctuated Treasury label in production is a TABULAR reference — the
    strict compute branch must never see them."""
    assert extract_column(TABLE, "10 Yr") == [4.18, 4.14, 4.16]
    assert extract_column(TABLE, "30 Yr") == [4.84, 4.81, 4.83]


def test_json_records_reference_is_unaffected():
    assert extract_column(RECORDS, "rate") == [4.1, 4.3]


def test_prose_still_raises():
    with pytest.raises(ReferenceError_):
        extract_column("There is no computed series in this sentence.", "value")
