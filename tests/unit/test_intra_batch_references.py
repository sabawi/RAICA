"""SI-044 — a tool may read an output produced by its OWN batch, and a verdict must be coherent.

REPRODUCED FROM PRODUCTION (v1.0.0.281, 2026-08-15 02:59). The USGS request computed everything
correctly and still rendered no chart, for two defects that were both in RAICA, not the model:

    round=1 executing ['compute' x14, 'plot_data', 'plot_data']
    second-round-args: tool=plot_data available=['lookup_website#1']
      -> Tool 'plot_data' error: unknown output reference(s) ['compute#9']

`plot_data` read `compute#9` — a compute in that same batch. References resolve ONCE before the
batch, which then runs in parallel, so the id could not exist yet. The next round had all fourteen.

Then the gate ended the loop while describing the very thing it was missing:

    round=2 verdict=sufficient
      missing='The plot_data tool failed ... A valid plot_data call is needed to produce the
               [[chart:...'   next=['plot_data']
"""
import json

import pytest

import fastapi_server_complete as srv


def _call(name, args):
    return {"function": {"name": name, "arguments": args}}


class TestIntraBatchDeferral:

    def test_a_consumer_scheduled_with_its_producer_is_DEFERRED_not_failed(self):
        """The exact prod batch shape. On pre-fix code plot_data ran immediately, could not
        resolve compute#9, and errored — so no chart was ever drawn."""
        batch = [_call("compute", {"label": f"c{i}", "expr": "np.mean(mag)",
                                   "data": {"mag": {"from": "lookup_website#1", "column": "mag"}}})
                 for i in range(1, 15)]
        batch.append(_call("plot_data", {"title": "Magnitude histogram",
                                         "y": {"from": "compute#9", "column": None}}))
        prior = [("lookup_website", "mag\n5.5\n6.1\n7.2\n")]

        ready, deferred = srv._split_calls_awaiting_batch_output(batch, prior)

        assert len(deferred) == 1, f"plot_data should wait one round, got deferred={len(deferred)}"
        assert deferred[0]["function"]["name"] == "plot_data"
        assert len(ready) == 14 and {c["function"]["name"] for c in ready} == {"compute"}

    def test_the_deferred_call_resolves_once_its_producer_has_run(self):
        """Deferral is only correct if the next round can actually run it — otherwise the chart is
        merely lost later instead of sooner. Per-tool ids are 1-based in execution order and
        asyncio.gather preserves order, so `compute#9` still means the 9th compute."""
        prior = [("lookup_website", "mag\n5.5\n")] + [("compute", f"{i}.0") for i in range(1, 15)]
        call = [_call("plot_data", {"title": "t", "y": {"from": "compute#9", "column": None}})]
        ready, deferred = srv._split_calls_awaiting_batch_output(call, prior)
        assert not deferred and len(ready) == 1, "producer has run; the call must now be runnable"

    def test_a_reference_to_a_tool_NOT_in_the_batch_still_fails_loudly(self):
        """Deferral must not become a way to swallow a genuinely bad reference: that would run a
        tool on missing data and produce a confident answer over nothing."""
        batch = [_call("plot_data", {"title": "t", "y": {"from": "nonexistent_tool#3", "column": None}})]
        ready, deferred = srv._split_calls_awaiting_batch_output(batch, [("lookup_website", "a\n1\n")])
        assert not deferred and len(ready) == 1, "unknown producer must NOT be deferred forever"

    def test_nested_references_are_seen(self):
        """compute carries its references nested inside `data`. A shallow scan misses them —
        that is why an earlier diagnostic never showed compute's references at all."""
        args = {"label": "x", "data": {"mag": {"from": "compute#3", "column": "mag"}}}
        assert srv._reference_ids_in(args) == ["compute#3"]
        assert srv._reference_ids_in({"y": {"from": ["compute#1", "compute#2"], "column": None}}) \
            == ["compute#1", "compute#2"]


class TestVerdictCoherence:

    def _verdict(self, payload):
        import asyncio

        class _Stub:
            def __call__(self, *a, **k):
                async def gen():
                    yield json.dumps(payload)
                return gen()

        original = srv.llm_manager.generate_stream
        try:
            srv.llm_manager.generate_stream = _Stub()
            return asyncio.new_event_loop().run_until_complete(
                srv._gather_gate_assess("chart it", [("lookup_website", "a,b\n1,2\n3,4\n")],
                                        [{"function": {"name": "plot_data"}}], "m"))
        finally:
            srv.llm_manager.generate_stream = original

    def test_sufficient_while_naming_a_gap_is_treated_as_needs_more(self):
        """THE PROD VERDICT, verbatim in shape. On pre-fix code this returns 'sufficient' and the
        loop stops one round before the chart would have been produced."""
        out = self._verdict({"status": "sufficient",
                             "missing": "plot_data failed; a valid call is needed for the chart",
                             "next_tools": ["plot_data"]})
        assert out["status"] == "needs_more", f"incoherent verdict accepted: {out}"

    def test_a_genuinely_clean_verdict_is_still_sufficient(self):
        """The guard must not turn every verdict into needs_more — that would loop to max_rounds
        on every request and burn the wall-clock budget."""
        out = self._verdict({"status": "sufficient", "missing": "", "next_tools": []})
        assert out["status"] == "sufficient", f"clean verdict was escalated: {out}"

    def test_a_stray_next_tool_without_a_stated_gap_stays_sufficient(self):
        """Both signals are required. next_tools alone is routinely non-empty noise; escalating on
        it would defeat the previous test in practice."""
        out = self._verdict({"status": "sufficient", "missing": "", "next_tools": ["plot_data"]})
        assert out["status"] == "sufficient", f"escalated on next_tools alone: {out}"
