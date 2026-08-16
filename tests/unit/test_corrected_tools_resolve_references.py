"""Regression (SI-050): the arbitrator's retry path must resolve data references.

FAILURE THIS PREVENTS
---------------------
Regenerated tool calls arrive in the same shape as second-round calls:

    {"expr": "np.sum(mag >= 6.0)",
     "data": {"mag": {"from": "lookup_website#1", "column": "mag"}}}

Every other execution path runs them through `_resolve_call_references()` first.
`_execute_corrected_tools` did not, so the RAW reference dict reached the tool. numpy then
converted `{"from": …, "column": …}` into an array of its KEYS —
`array(['from','column'], dtype='<U6')` — and every numeric operation died:

    UFuncTypeError: ufunc 'greater_equal' … (StrDType, _PyFloatDType)
    UFuncTypeError: ufunc 'subtract' … (dtype('<U4'), dtype('<U6'))

`<U4` and `<U6` are exactly len('from') and len('column') — that is what identified it.

Measured 2026-08-15: **58** such failures across 3 E2E runs (control: 0 in the preceding 3
runs on the same build). The user was told "no figures were actually calculated" for a
dataset that fetches in under a second.
"""
import asyncio
import inspect
import json

import pytest

import fastapi_server_complete as srv

TABLE = "time,mag,place\n2026-01-01,5.5,A\n2026-01-02,6.1,B\n2026-01-03,5.8,C\n"

PRIOR = [("lookup_website", TABLE)]

CALL = [{
    "function": {
        "name": "compute",
        "arguments": json.dumps({
            "expr": "np.mean(mag)",
            "data": {"mag": {"from": "lookup_website#1", "column": "mag"}},
        }),
    }
}]


class _RecordingToolManager:
    """Captures the arguments the tool is actually executed with."""

    def __init__(self):
        self.seen = []

    async def safe_function_call(self, name, args):
        self.seen.append((name, args))
        return "mean 5.80\ncomputed as: np.mean(mag)"


def test_retry_path_accepts_prior_results():
    """The resolver needs the prior outputs the reference ids point at.

    Asserted separately so the failure on pre-fix code is a clear message rather than a
    TypeError from an unexpected keyword.
    """
    params = inspect.signature(srv._execute_corrected_tools).parameters
    assert "prior_results" in params, (
        "_execute_corrected_tools cannot resolve references without the prior tool outputs; "
        "the raw {'from':…,'column':…} dict will reach the tool (SI-050)"
    )


def test_regenerated_call_receives_resolved_numbers_not_the_reference_dict():
    """THE bug: the tool must get [5.5, 6.1, 5.8], never {'from':…, 'column':…}."""
    tm = _RecordingToolManager()
    asyncio.run(srv._execute_corrected_tools(tm, CALL, [], prior_results=PRIOR))

    assert tm.seen, "the corrected tool was never executed"
    _, args = tm.seen[0]
    mag = (args or {}).get("data", {}).get("mag")

    assert not isinstance(mag, dict), (
        f"the RAW reference dict reached the tool ({mag!r}); numpy turns this into "
        f"array(['from','column'], dtype='<U6') and every numeric op raises UFuncTypeError"
    )
    assert mag == [5.5, 6.1, 5.8], f"expected the resolved column, got {mag!r}"


def test_numpy_really_does_produce_the_observed_dtypes():
    """Pins the mechanism, so the next reader does not have to re-derive it from a dtype.

    This is why the production error said `<U4` / `<U6` and not something about dicts.
    """
    import numpy as np
    arr = np.asarray(list({"from": "lookup_website#1", "column": "mag"}))
    assert arr.dtype.str.endswith("U6")          # len('column')
    with pytest.raises(TypeError):
        _ = arr >= 5.5
