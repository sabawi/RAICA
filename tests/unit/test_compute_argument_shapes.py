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


# ═══════════════════════════════════════════════════════════════════════════════════════
# SI-069 — the shapes that survived the SI-067 fix and still cost 30 rejected calls
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# Measured on production 2026-08-17, AFTER v1.0.0.303 shipped:
#     {'expr': 'np.percentile(mags, 90)',
#      'mags': '{"from": "lookup_website#1", "column": "mag"}'}
#               ^ the series at TOP LEVEL, named after itself — `data` absent entirely
# reported to the user as "the data object was not properly formed".

def test_a_series_passed_as_a_top_level_argument_is_adopted_as_data():
    """FAILS PRE-FIX: `data` was absent, so the call died on "non-empty object"."""
    out = _run(expr="np.mean(mags)", mags=MAGS)
    assert out["success"] is True, out.get("error")
    assert "6.15" in out["result"]


def test_several_stray_series_are_all_adopted():
    out = _run(expr="np.corrcoef(a, b)[0][1]", a=[1.0, 2.0, 3.0, 4.0], b=[2.0, 4.0, 6.0, 8.0])
    assert out["success"] is True, out.get("error")
    assert "1" in out["result"]


def test_an_explicit_data_always_wins_over_strays():
    """The adoption only FILLS A GAP — it must never override what the model stated."""
    out = _run(expr="np.mean(mag)", data={"mag": [10.0, 20.0]}, mag=[1.0, 1.0])
    assert out["success"] is True, out.get("error")
    assert "15" in out["result"], out["result"][:80]


def test_non_series_top_level_arguments_are_not_adopted():
    """A stray that is not a numeric series is left alone — no meaning is inferred."""
    out = _run(expr="np.mean(mags)", mags=MAGS, note="a passing remark", limit=5)
    assert out["success"] is True, out.get("error")
    assert "note" not in out["result"], "a prose argument was treated as data"


def test_len_is_rewritten_to_np_size():
    """FAILS PRE-FIX: rejected with "only `np.<function>(...)` calls are permitted".

    The evaluator already NAMES this equivalence in _BUILTIN_TO_NUMPY; it just reported it as
    an error instead of applying it, costing a round-trip every time the model wrote the
    natural spelling.
    """
    out = _run(expr="len(mag)", data={"mag": MAGS})
    assert out["success"] is True, out.get("error")
    assert "np.size(mag)" in out["result"], "the rewritten expression is not disclosed"
    assert "8" in out["result"]


def test_the_real_production_expression_now_computes():
    """The exact expression from the live log, with len() and a stray series."""
    out = _run(expr="np.sum(mags >= 7.0) / len(mags)", mags=MAGS)
    assert out["success"] is True, out.get("error")
    assert "np.size(mags)" in out["result"]


def test_rewriting_is_syntactic_and_cannot_touch_unrelated_names():
    from user_tools.compute_tool import _rewrite_builtin_calls as R
    assert R("np.mean(length)") == "np.mean(length)", "a name CONTAINING 'len' was rewritten"
    assert R("np.mean(mag)") == "np.mean(mag)"
    assert R("len(x)") == "np.size(x)"
    assert R(["len(a)", "np.mean(b)"]) == ["np.size(a)", "np.mean(b)"]


def test_an_unparseable_expression_is_left_for_the_evaluator_to_report():
    """The rewriter must never mask a syntax error with its own failure."""
    from user_tools.compute_tool import _rewrite_builtin_calls as R
    assert R("np.mean(") == "np.mean("


# ═══════════════════════════════════════════════════════════════════════════════════════
# SI-072 — `expr` as a JSON STRING containing a list: a SILENT WRONG ANSWER
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# Production 2026-08-18, Treasury yield-curve prompt. The model sent:
#     'expr': '["np.size(y3mo)", "np.mean(y3mo)", "np.std(y3mo, ddof=1)", ...]'
# a JSON STRING, not a list. That string is a VALID Python list-literal of strings, so the
# evaluator "computed" it and returned THE EXPRESSION TEXTS as the result — with success=True.
# The answer reported: "the tool output listed the expressions np.mean(y3mo), np.std(...) but
# did not return their computed values", and every per-tenor statistic had to be omitted.
#
# Worse than a rejection: a rejection is visible, this looked like success.

def test_expr_as_a_json_string_list_is_decoded_and_evaluated():
    """FAILS PRE-FIX: returned the expression TEXTS as the result, success=True."""
    out = _run(expr=json.dumps(["np.size(mag)", "np.mean(mag)"]), data={"mag": MAGS})
    assert out["success"] is True, out.get("error")
    assert "np.size(mag)" in out["result"]
    assert "6.15" in out["result"], "the mean was not actually computed"
    assert "'np.size(mag)'" not in out["result"], "expression text returned as a value"


def test_the_expression_texts_are_never_returned_as_the_value():
    """The precise production symptom, pinned."""
    out = _run(expr=json.dumps(["np.mean(mag)"]), data={"mag": MAGS})
    assert "dtype: <U" not in out.get("result", ""), \
        "result dtype is a STRING array — the expressions were evaluated as data"


def test_a_genuine_numeric_list_literal_still_evaluates_as_data():
    """CONTROL: the decode must fire ONLY for a list of expression strings.

    `[1, 2, 3]` is a legitimate expression and must keep working.
    """
    out = _run(expr="[1, 2, 3]", data={"mag": MAGS})
    assert out["success"] is True
    assert "1" in out["result"] and "3" in out["result"]


def test_a_plain_single_expression_is_unaffected():
    """CONTROL: the common case must not be disturbed."""
    out = _run(expr="np.mean(mag)", data={"mag": MAGS})
    assert out["success"] is True and "6.15" in out["result"]
