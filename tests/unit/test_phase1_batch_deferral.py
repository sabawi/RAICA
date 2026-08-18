"""SI-080: the FIRST tool batch must defer a call that reads its own batch's output.

THE DEFECT THIS PREVENTS
------------------------
`_split_calls_awaiting_batch_output` was written for SI-044 and wired into exactly ONE place —
the gather-gate loop — which is disabled in production. The batch that actually runs for every
request had no deferral, and the defect it fixes is most likely THERE: round 1 selects every tool
before any tool has run, so a consumer scheduled beside its producer is the normal case.

Measured 2026-08-18 on the DGS10 regression testcase, the model's own call:

    'x':      '{"from": "compute#5", "column": "d2"}'
    'series': '[{"name": "...", "y": {"from": "compute#5", "column": "y"}}]'

Correct syntax, correct id, correct column — and `compute#5` did not exist yet, because those
computes were in the SAME batch, executed in parallel. `plot_data` received `x` unresolved and
rejected it with "x must be a list" 8-11 times per run, in every arm of every experiment that day.
Five separate fixes aimed at getting plot_data SELECTED all missed this, because it was already
being selected correctly.
"""
import inspect
import json

import fastapi_server_complete as srv


def _call(name, args):
    return {"id": f"c_{name}", "function": {"name": name, "arguments": json.dumps(args)}}


CHART = _call("plot_data", {"title": "t", "source": "s", "url": "u", "x_name": "Date",
                            "x_type": "temporal",
                            "x": {"from": "compute#5", "column": "d2"},
                            "series": [{"name": "y", "y": {"from": "compute#5", "column": "y"}}]})
COMPUTES = [_call("compute", {"data": {"y": {"from": "lookup_website#1", "column": "DGS10"}},
                              "expr": f"np.mean(y)+{i}"}) for i in range(6)]


def test_consumer_is_deferred_when_its_producer_shares_the_batch():
    """The exact production shape: plot_data reading compute#5 from its own batch."""
    ready, deferred = srv._split_calls_awaiting_batch_output(COMPUTES + [CHART], [])
    names = [(c["function"]["name"]) for c in deferred]
    assert names == ["plot_data"], f"expected plot_data held back, got {names}"
    assert len(ready) == 6


def test_producers_still_run_in_the_first_pass():
    """Deferral must not delay the tools that have everything they need."""
    ready, _ = srv._split_calls_awaiting_batch_output(COMPUTES + [CHART], [])
    assert all(c["function"]["name"] == "compute" for c in ready)


def test_a_reference_to_a_tool_outside_the_batch_is_not_deferred():
    """CONTROL — that reference is genuinely unknown; the existing path reports it."""
    lone = _call("compute", {"data": {"y": {"from": "nosuchtool#1", "column": "c"}}, "expr": "np.mean(y)"})
    ready, deferred = srv._split_calls_awaiting_batch_output([lone], [])
    assert deferred == [] and len(ready) == 1


def test_a_batch_with_no_references_is_untouched():
    """CONTROL — the common case must not acquire an extra round."""
    plain = [_call("search_web", {"query": "x"}), _call("lookup_website", {"url": "u"})]
    ready, deferred = srv._split_calls_awaiting_batch_output(plain, [])
    assert deferred == [] and len(ready) == 2


def test_an_already_available_reference_is_not_deferred():
    """CONTROL — if the producer already ran, the consumer must go in the first pass."""
    prior = [("lookup_website", "date,DGS10\n1962-01-02,4.06\n1962-01-03,4.03\n")]
    consumer = _call("compute", {"data": {"y": {"from": "lookup_website#1", "column": "DGS10"}},
                                 "expr": "np.mean(y)"})
    ready, deferred = srv._split_calls_awaiting_batch_output([consumer], prior)
    assert deferred == [] and len(ready) == 1


def test_phase1_actually_wires_the_deferral():
    """The helper existed and was correct for a year of nothing, because ONE path called it.

    Asserts the production batch now (a) splits, (b) executes only the ready calls, and
    (c) resolves the deferred ones against the results before running them.
    """
    src = inspect.getsource(srv)
    seg = src[src.index("phase1_tasks = [execute_single_tool(call)") - 3000:]
    seg = seg[:seg.index("PHASE 1 COMPLETE")]
    assert "_split_calls_awaiting_batch_output(" in seg, "phase 1 still runs an unsplit batch"
    assert "for call in _p1_ready" in seg, "phase 1 still executes the full batch"
    assert "_resolve_call_references(_p1_deferred" in seg, "deferred calls run without resolution"


def test_deferral_runs_after_the_first_gather_not_before():
    """Ordering. Resolving before the producers have run would defeat the whole point."""
    src = inspect.getsource(srv)
    i_split = src.index("_split_calls_awaiting_batch_output(\n                                            phase1_tools")
    seg = src[i_split:]
    i_gather = seg.index("phase1_results = await asyncio.gather(*phase1_tasks")
    i_resolve = seg.index("_resolve_call_references(_p1_deferred")
    assert i_gather < i_resolve, "deferred calls resolved before their producers ran"
