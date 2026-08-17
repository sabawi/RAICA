"""`compute` must accept the call shapes tool-calling models actually emit.

FAILURE THIS PREVENTS (SI-067)
------------------------------
A USGS earthquake request ("sample size, mean, median and std-dev of the magnitudes, and plot
the distribution") produced an answer that reported NO statistics at all. The model wrote:

    "the compute tool calls ... all failed to execute due to expression errors ... I am
     therefore unable to report the mean, median, standard deviation"

28 attempts, every one rejected. Nothing was wrong with the data or the model's intent.

The live log shows what it actually sent:

    'data': '{"mag": {"from": "lookup_website#1", "column": "mag"}}'
             ^ a STRING containing JSON, not an object

That reference is CORRECT — right output id, right column. But `_prepare_data` does
`isinstance(data, dict)`, which is False for a string, so the call died at the door with
"`data` must be a non-empty object mapping names to arrays". The top-level `arguments` blob
was already json.loads'd; nested values were not, so the resolver never even saw the
reference.

Everything else was verified working: `extract_column` returns all 225 magnitudes; the
reference block shown to the model lists `lookup_website#1` and every column name; the tool
schema documents the reference form and says "PREFER THE REFERENCE". The model used the
affordance correctly and RAICA rejected it on a type check.

Two further shapes came from the same run:
  * a BARE reference where a mapping belongs: 'data': '{"from": ..., "column": "mag"}'
  * a SCRIPT instead of an expression, because four figures were wanted at once:
        'n = len(mag); mean_mag = np.mean(mag); std_mag = np.std(mag, ddof=1); ...'
    which fails ast.parse(mode="eval") AND blows the 500-character cap.
"""
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from user_tools.compute_tool import ComputeTool  # noqa: E402

try:                       # absent pre-fix; imported tolerantly so the BEHAVIOURAL tests below
    from user_tools.compute_tool import _looks_like_multiple_statements  # noqa: E402
except ImportError:        # still run and FAIL on old code, instead of erroring at collection
    _looks_like_multiple_statements = None


def _run(**kwargs):
    return asyncio.run(ComputeTool().execute(**kwargs))


MAGS = [5.5, 5.8, 6.1, 5.9, 6.5, 7.8, 5.6, 6.0]


# ───────────────────────────────────── 1. `data` as a JSON string (THE production failure)
def test_data_sent_as_a_json_string_is_accepted():
    """FAILS PRE-FIX: rejected with "`data` must be a non-empty object mapping names to arrays"."""
    out = _run(expr="np.mean(mag)", data=json.dumps({"mag": MAGS}))
    assert out["success"] is True, out.get("error")
    # Expected value COMPUTED from the fixture, not eyeballed: fmean(MAGS) == 6.15.
    # An earlier version of this test asserted a guessed "5.9" and failed on correct code.
    assert "6.15" in out["result"], out["result"][:120]


def test_a_real_dict_still_works():
    """CONTROL — the shape that always worked must keep working."""
    out = _run(expr="np.max(mag)", data={"mag": MAGS})
    assert out["success"] is True and "7.8" in out["result"]


def test_a_non_json_string_is_not_mangled():
    """The decode must be conservative: prose stays prose and still fails honestly."""
    out = _run(expr="np.mean(mag)", data="the magnitudes from the table")
    assert out["success"] is False
    assert "non-empty object" in out["error"]


# ───────────────────────────────────── 2. a bare reference where a mapping belongs
def test_a_bare_reference_gets_an_actionable_error_naming_the_right_shape():
    """FAILS PRE-FIX: produced the generic "must be a non-empty object" with no guidance.

    Deliberately an ERROR rather than a guess: inventing a series name would bind the data to
    a name `expr` does not use, and the model would then see "name not defined" instead of the
    real problem.
    """
    out = _run(expr="np.mean(mag)",
               data={"from": "lookup_website#1", "column": "mag"})
    assert out["success"] is False
    assert '"mag"' in out["error"], out["error"]
    assert "lookup_website#1" in out["error"], "the error does not echo the reference to fix"


# ───────────────────────────────────── 3. several figures in one call
def test_a_list_of_expressions_returns_every_value():
    """FAILS PRE-FIX: a list was passed straight to the evaluator and rejected."""
    out = _run(expr=["np.mean(mag)", "np.median(mag)", "np.std(mag, ddof=1)"],
               data={"mag": MAGS}, label="magnitude stats")
    assert out["success"] is True, out.get("error")
    for fragment in ("np.mean(mag)", "np.median(mag)", "np.std(mag, ddof=1)"):
        assert fragment in out["result"], f"{fragment} missing from batch result"


def test_one_bad_expression_does_not_lose_the_others():
    """All-or-nothing is the behaviour this fix exists to remove."""
    out = _run(expr=["np.mean(mag)", "np.not_a_function(mag)", "np.max(mag)"],
               data={"mag": MAGS})
    assert out["success"] is True, out.get("error")
    assert "np.mean(mag)" in out["result"] and "np.max(mag)" in out["result"]
    assert "not_a_function" in out["result"], "the failing entry is not reported"


def test_a_batch_where_everything_fails_is_reported_as_failure():
    """Success must mean a figure exists — otherwise the fail-closed notice never fires."""
    out = _run(expr=["np.nope(mag)", "np.alsonope(mag)"], data={"mag": MAGS})
    assert out["success"] is False
    assert "NO FIGURE WAS CALCULATED" in out["error"]


def test_a_partial_batch_warns_that_missing_figures_must_not_be_stated():
    out = _run(expr=["np.mean(mag)", "np.nope(mag)"], data={"mag": MAGS})
    assert out["success"] is True
    assert "forbidden" in out["result"].lower()


def test_a_script_expression_is_told_to_use_a_list():
    """FAILS PRE-FIX: surfaced as "could not parse expression: invalid syntax" with no remedy."""
    out = _run(expr="n = len(mag); mean_mag = np.mean(mag); std_mag = np.std(mag, ddof=1)",
               data={"mag": MAGS})
    assert out["success"] is False
    assert "LIST" in out["error"] or "list" in out["error"]
    assert "NO FIGURE WAS CALCULATED" in out["error"], "fail-closed notice missing"


def test_the_expression_count_is_capped():
    out = _run(expr=[f"np.mean(mag) + {i}" for i in range(40)], data={"mag": MAGS})
    assert out["success"] is False and "limit" in out["error"]


# ───────────────────────────────────── the statement detector
def test_statement_detection_is_structural_not_pattern_matching():
    """Asks Python, so it covers assignments, `;` and newlines without listing spellings."""
    assert _looks_like_multiple_statements is not None, "helper missing (pre-fix code)"
    assert _looks_like_multiple_statements("n = 1; m = 2") is True
    assert _looks_like_multiple_statements("x = np.mean(mag)") is True
    assert _looks_like_multiple_statements("np.mean(mag)") is False
    assert _looks_like_multiple_statements("np.corrcoef(a, b)[0][1]") is False


def test_a_valid_expression_is_never_misread_as_a_script():
    """A false positive here would break working calls — the expensive direction."""
    assert _looks_like_multiple_statements is not None, "helper missing (pre-fix code)"
    for good in ("np.percentile(x, 90)", "np.min(y30 - y10)", "np.std(mag, ddof=1)",
                 "np.histogram(mag, bins=15)[0]", "np.mean(np.diff(gdp))"):
        assert _looks_like_multiple_statements(good) is False, good
