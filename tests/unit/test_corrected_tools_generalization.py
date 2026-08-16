"""SI-050 GENERALIZATION: the retry path must handle every reference shape, not one CSV.

WHY THIS FILE EXISTS SEPARATELY
-------------------------------
`test_corrected_tools_resolve_references.py` proves the SI-050 defect is gone for the case that
exposed it: a wrapped CSV, one float column, `compute`. Three E2E runs of the same USGS prompt
measure stochastic variance — they do NOT establish that the fix generalises. A fix verified on
one data shape is exactly the "band-aid for a specific case" the project directive forbids.

The resolution SEMANTICS are already covered against `resolve_references`/`extract_column`
(tests/unit/test_tool_output_reference.py, test_computed_series_reference.py). What was never
covered is that the ARBITRATOR RETRY PATH inherits them — it was the one path that bypassed the
resolver entirely, so "the resolver handles it" said nothing about this path.

So: the same variety those suites feed the resolver, driven end-to-end through
`_execute_corrected_tools`. If the retry path is ever special-cased again, these fail.
"""
import asyncio
import json

import pytest

import fastapi_server_complete as srv

# A tool result as lookup_website ACTUALLY returns it — RAICA's wrapper around the file,
# not a bare CSV. Parsing from line 0 would make the preamble the header.
WRAPPED_CSV = """
As of [Current Date and Time: Saturday, August 15, 2026 08:26:39 PM] here are the website lookup results:
───────────────────────────────────────────────────────
[CSV file: 4 lines retrieved (complete)]
Date,Close,Volume,Note
2026-01-01,101.5,1200,ok
2026-01-02,103.25,1350,ok
2026-01-03,99.0,,ok
───────────────────────────────────────────────────────
Source: example.test
"""

JSON_RECORDS = '[{"date":"2026-01-01","close":101.5},{"date":"2026-01-02","close":103.25}]'


def _compute_out(body, expr="np.mean(mag)", n=225, dtype="float64"):
    """The exact shape compute_tool._format emits."""
    return (f"{body}\ncomputed as: {expr}\n"
            f"over n={n} data point(s); inputs: mag\ndtype: {dtype}\n"
            f"STATE THE EXPRESSION AND n ALONGSIDE THIS VALUE when you use it.")


class _Recorder:
    def __init__(self):
        self.seen = []

    async def safe_function_call(self, name, args):
        self.seen.append((name, args))
        return "ok"


def _run(tool_name, arguments, prior):
    """Drive one regenerated call through the REAL retry path; return the args the tool saw."""
    tm = _Recorder()
    call = [{"function": {"name": tool_name, "arguments": json.dumps(arguments)}}]
    asyncio.run(srv._execute_corrected_tools(tm, call, [], prior_results=prior))
    assert tm.seen, "the corrected tool was never executed"
    return tm.seen[0][1]


def _no_raw_reference(args):
    """No argument anywhere may still be a {'from':…,'column':…} dict (the SI-050 signature)."""
    def walk(v):
        if isinstance(v, dict):
            assert not ("from" in v and "column" in v), f"raw reference survived: {v!r}"
            for iv in v.values():
                walk(iv)
        elif isinstance(v, list):
            for iv in v:
                walk(iv)
    walk(args)


# --------------------------------------------------------------------------- data formats
def test_wrapped_csv_float_column():
    """The shape that exposed the bug — kept here so the matrix is complete."""
    args = _run("compute", {"expr": "np.mean(Close)",
                            "data": {"Close": {"from": "lookup_website#1", "column": "Close"}}},
                [("lookup_website", WRAPPED_CSV)])
    _no_raw_reference(args)
    assert args["data"]["Close"] == [101.5, 103.25, 99.0]


def test_json_records_source():
    """A tool returning JSON records, not a CSV — same reference form, different parser."""
    args = _run("compute", {"expr": "np.mean(close)",
                            "data": {"close": {"from": "lookup_website#1", "column": "close"}}},
                [("lookup_website", JSON_RECORDS)])
    _no_raw_reference(args)
    assert args["data"]["close"] == [101.5, 103.25]


def test_computed_series_source_ignores_the_column_name():
    """A reference to a COMPUTE output: the result IS the series, there are no columns.

    The contract (SI-047) is that the model supplies a `column` out of habit and it is IGNORED
    here — `_is_reference` requires both keys, so the column is what makes the reference visible
    at all. See SI-053 for the column-less form, which is NOT recognised.
    """
    args = _run("plot_data", {"series": {"from": "compute#1", "column": "value"}},
                [("compute", _compute_out("percentiles: [5.6  , 6.   , 6.4  , 6.68 , 7.476]"))])
    _no_raw_reference(args)
    assert args["series"] == [5.6, 6.0, 6.4, 6.68, 7.476]


def test_integer_counts_stay_usable():
    """Histogram counts — the exact series a distribution chart consumes."""
    args = _run("plot_data", {"series": {"from": "compute#1", "column": "count"}},
                [("compute", _compute_out("counts: [74, 62, 17, 32, 11]", dtype="int64"))])
    _no_raw_reference(args)
    assert [int(v) for v in args["series"]] == [74, 62, 17, 32, 11]


def test_a_column_less_reference_is_not_silently_executed_as_key_names():
    """SI-053 — documents a REAL latent trap, asserted as it currently behaves.

    `{"from": "compute#1"}` (no column) is not recognised by `_is_reference`, so it passes
    through raw and numpy turns it into `array(['from'])` — the SI-050 signature again, for a
    shape the model could plausibly emit against a compute output that genuinely has no columns.
    Not changed here: making a bare `from` a reference would also capture legitimate arguments
    like `{"from": "2026-01-01", "to": "2026-06-30"}`. Needs the index-aware disambiguation
    described in SI-053, not a widened predicate.
    """
    args = _run("plot_data", {"series": {"from": "compute#1"}},
                [("compute", _compute_out("counts: [1, 2, 3]", dtype="int64"))])
    assert args["series"] == {"from": "compute#1"}, (
        "behaviour changed — if column-less references now resolve, delete this test and "
        "close SI-053; if they resolve PARTIALLY, that is worse than either state"
    )


# --------------------------------------------------------------------------- column types
def test_date_column_comes_back_as_text_not_none():
    """A temporal axis is NOT numeric. Coercing it to None made plot_data refuse the chart."""
    args = _run("plot_data", {"x": {"from": "lookup_website#1", "column": "Date"},
                              "series": {"from": "lookup_website#1", "column": "Close"}},
                [("lookup_website", WRAPPED_CSV)])
    _no_raw_reference(args)
    assert args["x"] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert args["series"] == [101.5, 103.25, 99.0]


def test_gaps_stay_gaps_in_a_numeric_column():
    """A blank cell must not silently become 0 — that would shift every statistic."""
    args = _run("compute", {"expr": "np.mean(Volume)",
                            "data": {"Volume": {"from": "lookup_website#1", "column": "Volume"}}},
                [("lookup_website", WRAPPED_CSV)])
    _no_raw_reference(args)
    assert args["data"]["Volume"][:2] == [1200.0, 1350.0]
    assert args["data"]["Volume"][2] is None


def test_column_lookup_is_case_insensitive():
    """The model routinely varies case; a case mismatch must not become a type error."""
    args = _run("compute", {"expr": "np.mean(close)",
                            "data": {"close": {"from": "lookup_website#1", "column": "close"}}},
                [("lookup_website", WRAPPED_CSV)])
    _no_raw_reference(args)
    assert args["data"]["close"] == [101.5, 103.25, 99.0]


# --------------------------------------------------------------------------- reference forms
def test_multiple_sources_concatenate():
    """Two fetches of the same tool stay distinguishable and can be combined."""
    args = _run("compute", {"expr": "np.mean(Close)",
                            "data": {"Close": {"from": ["lookup_website#1", "lookup_website#2"],
                                               "column": "Close"}}},
                [("lookup_website", WRAPPED_CSV), ("lookup_website", WRAPPED_CSV)])
    _no_raw_reference(args)
    assert len(args["data"]["Close"]) == 6


def test_non_reference_arguments_pass_through_untouched():
    """Literal arguments must survive resolution unchanged."""
    args = _run("plot_data", {"kind": "line", "title": "T", "bins": 15,
                              "series": {"from": "compute#1"}},
                [("compute", _compute_out("counts: [1, 2, 3]", dtype="int64"))])
    assert args["kind"] == "line" and args["title"] == "T" and args["bins"] == 15


# --------------------------------------------------------------------------- error paths
@pytest.mark.parametrize("arguments,prior,why", [
    ({"expr": "np.mean(x)", "data": {"x": {"from": "nope#1", "column": "Close"}}},
     [("lookup_website", WRAPPED_CSV)], "unknown reference id"),
    ({"expr": "np.mean(x)", "data": {"x": {"from": "lookup_website#1", "column": "Missing"}}},
     [("lookup_website", WRAPPED_CSV)], "column that does not exist"),
])
def test_unresolvable_reference_reports_an_error_instead_of_passing_the_dict(arguments, prior, why):
    """FAIL the call with a readable reason — never hand the tool the raw dict.

    Passing it through is what produced `UFuncTypeError … dtype('<U4')`, a message that says
    nothing about the actual problem and cost a diagnosis round to see through.
    """
    args = _run("compute", arguments, prior)
    _no_raw_reference(args)
    assert "_reference_error" in args, f"{why}: expected a reference error, got {args!r}"
