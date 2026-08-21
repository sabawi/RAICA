"""Production replay — REAL `compute#` column references, harvested from the server logs.

WHAT THIS PREVENTS
------------------
SI-085 made `extract_column` strict, SI-087 then widened it to accept the label RAICA
printed. Both decisions turn on `_EXPRESSION_CHARS` and on the ORDER of the branches in
`extract_column`. A future edit to either — adding a character, moving the habit fallback,
reordering the label match — can silently change which references resolve, and unit tests
built from invented names would not notice.

So this corpus is not invented. Every name below was extracted from
`logs/server_complete.log` and `logs/archive/*.log` by matching the real reference payload
`{"from": "compute#N", "column": "..."}`: 3946 references in total, 55 distinct
`compute#` column names, which is the complete population for those logs (3946 of 3946
`"column"` occurrences matched, none in reverse field order).

The invariant is not "these exact values" but: EVERY real reference must land on a defined
outcome — resolve, or raise ReferenceError_ so the model can retry. Nothing may crash, and
the plain habit names must keep resolving.
"""
import pytest

from utils.tool_output_reference import ReferenceError_, extract_column

# --- harvested from production logs; see module docstring -------------------

PRODUCTION_PLAIN = ['0', 'bin_centres', 'centres', 'counts', 'd', 'd2', 'daily_change', 'diff', 'value', 'y', 'zero_line']

PRODUCTION_EXPRESSIONS = ['d[::1]', 'd[::10]', 'd[::20]', 'd[::4]', 'd[::40]', 'dates[::20]', 'd_dates[::20]', 'dt[::20]', 'np.diff(y)', 'np.histogram(chg[~np.isnan(chg)], bins=60)[0]', '(np.histogram(chg[~np.isnan(chg)], bins=60)[1][:-1] + np.histogram(chg[~np.isnan(chg)], bins=60)[1][1:]) / 2', 'np.histogram(daily_changes, bins=50)[0]', '(np.histogram(daily_changes, bins=50)[1][:-1] + np.histogram(daily_changes, bins=50)[1][1:]) / 2', 'np.histogram(d[~np.isnan(d)], bins=60)[0]', '(np.histogram(d[~np.isnan(d)], bins=60)[1][:-1] + np.histogram(d[~np.isnan(d)], bins=60)[1][1:]) / 2', '(np.histogram(mag, bins=np.arange(5.5, np.max(mag) + 0.11, 0.1))[1][:-1] + np.histogram(mag, bins=np.arange(5.5, np.max(mag) + 0.11, 0.1))[1][1:]) / 2', 'np.histogram(mag, bins=np.arange(np.floor(np.min(mag)*10)/10, np.ceil(np.max(mag)*10)/10 + 0.1, 0.1))[1]', 'np.histogram(np.diff(yf)[~np.isnan(np.diff(yf))], bins=50)[0]', '(np.histogram(np.diff(yf)[~np.isnan(np.diff(yf))], bins=50)[1][:-1] + np.histogram(np.diff(yf)[~np.isnan(np.diff(yf))], bins=50)[1][1:]) / 2', 'np.histogram(np.diff(y)[np.isfinite(np.diff(y))], bins=80)[0]', '(np.histogram(np.diff(y)[np.isfinite(np.diff(y))], bins=80)[1][:-1] + np.histogram(np.diff(y)[np.isfinite(np.diff(y))], bins=80)[1][1:]) / 2', 'np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=50)[0]', '(np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=50)[1][:-1] + np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=50)[1][1:]) / 2', 'np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=60)[0]', '(np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=60)[1][:-1] + np.histogram(np.diff(y)[~np.isnan(np.diff(y))], bins=60)[1][1:]) / 2', 'np.histogram(np.diff(y[~np.isnan(y)]), bins=50)[0]', '(np.histogram(np.diff(y[~np.isnan(y)]), bins=50)[1][:-1] + np.histogram(np.diff(y[~np.isnan(y)]), bins=50)[1][1:]) / 2', 'np.histogram(yv[~np.isnan(yv)], bins=60)[0]', '(np.histogram(yv[~np.isnan(yv)], bins=60)[1][:-1] + np.histogram(yv[~np.isnan(yv)], bins=60)[1][1:]) / 2', 'np.log10(np.cumsum(np.histogram(mag, bins=np.arange(5.5, np.max(mag) + 0.11, 0.1))[0][::-1])[::-1])', 'np.mean(yv) - np.sum((xv - np.mean(xv)) * (yv - np.mean(yv))) / np.sum((xv - np.mean(xv))**2) * np.mean(xv)', 'np.nanstd(np.diff(yf), ddof=1)', 'np.size(y)', 'np.sum((xv - np.mean(xv)) * (yv - np.mean(yv))) / np.sum((xv - np.mean(xv))**2)', 'y[::10]', 'y10 - y2', 'y[::20]', 'y[::4]', 'y[::40]', 'yf[::20]']

# Names that are DATA that leaked into the column field (the SI-081 defect). These must
# raise: they name nothing, and resolving them silently is how a wrong series gets charted.
PRODUCTION_LEAKED_DATA = ['- [-0.03', '0.954243,  0.845098,  0.845098,  0.778151,  0.69897 ,  0.60206 ,  0.30103 , ', '10 ** (np.polyfit((np.arange(5.5, 8.0, 0.1)[:-1] + np.arange(5.5, 8.0, 0.1)[1:]) / 2, np.log10(np.cumsum(np.histogram(mag, bins=np.arange(5.5, 8.0, 0.1))[0][::-1])[::-1]), 1)[0] * (np.arange(5.5, 8.0, 0.1)[:-1] + np.arange(5.5, 8.0, 0.1)[1:]) / 2 + np.polyfit((np.arange(5.5, 8.0, 0.1)[:-1] + np.arange(5.5, 8.0, 0.1)[1:]) / 2, np.log10(np.cumsum(np.histogram(mag, bins=np.arange(5.5, 8.0, 0.1))[0][::-1])[::-1]), 1)[1])']


def _single(expr, label="", vals="[4.3, 4.35, 4.28, 4.41]"):
    head = f"{label}: " if label else ""
    return (f"{head}{vals}\n"
            f"computed as: {expr}\n"
            f"over n=4 data point(s); inputs: y\n"
            f"dtype: float64")


def _multi(exprs):
    return "\n".join(
        f"- [{i}.1, {i}.2, {i}.3]\ncomputed as: {e}\n"
        f"over n=3 data point(s); inputs: y\ndtype: float64"
        for i, e in enumerate(exprs))


@pytest.mark.parametrize("col", PRODUCTION_PLAIN)
def test_real_plain_names_resolve_on_a_single_series(col):
    """SI-047 habit: with one series the output IS the answer."""
    assert extract_column(_single("y10"), col) == [4.3, 4.35, 4.28, 4.41]


@pytest.mark.parametrize("col", PRODUCTION_EXPRESSIONS)
def test_real_expression_resolves_when_it_names_the_series(col):
    assert extract_column(_single(col), col) == [4.3, 4.35, 4.28, 4.41]


@pytest.mark.parametrize("col", PRODUCTION_EXPRESSIONS)
def test_real_expression_raises_when_it_names_nothing(col):
    """The SI-085 defect: this used to hand back a DIFFERENT series."""
    with pytest.raises(ReferenceError_):
        extract_column(_single("some_other_variable"), col)


@pytest.mark.parametrize("col", PRODUCTION_LEAKED_DATA)
def test_leaked_data_as_a_column_name_raises(col):
    with pytest.raises(ReferenceError_):
        extract_column(_single("y10"), col)


@pytest.mark.parametrize("col", PRODUCTION_PLAIN + PRODUCTION_EXPRESSIONS)
def test_no_real_reference_ever_crashes(col):
    """Every reference must resolve or raise ReferenceError_ — never an unhandled type."""
    for text in (_single("y10"), _single("y10", label="10-Year Treasury"),
                 _multi(["y", "d[::20]", "np.diff(y)"]), "prose, no series here"):
        try:
            extract_column(text, col)
        except ReferenceError_:
            pass
