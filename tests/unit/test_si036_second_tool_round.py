"""SI-036 — a tool whose arguments depend on another tool's OUTPUT was unreachable.

FOUND ON PRODUCTION 2026-08-14 by the user's own Treasury request, run twice. `compute` was
loaded, whitelisted and offered — `Available tools: [... 'compute']` — and never called:

    tool calls: ['lookup_website', 'lookup_website']

The second run had the `DERIVED FIGURES MUST BE CALCULATED` directive verifiably present in the
merged prompt. Same result. The directive did not change tool selection, because the cause is not
a prompt problem:

    About to call LLM Manager for tool calling
    tool calls: ['lookup_website', 'lookup_website']   <- chosen ONCE, before any data exists
    LLM Manager tool calling response received  ->  synthesis  ->  POST-LLM

The non-DR path calls generate_tools exactly once (fastapi_server_complete.py:9834) with
`user_message = messages[-1]['content']` (:9953) — the prompt alone. `compute` is inherently a
SECOND-round tool: what to calculate is unknowable until the CSV has been fetched. So it could
never be selected for fetch-then-calculate, whatever the prompt said.

(The pre-existing "Phase 1 / Phase 2" split is a second EXECUTION group from the SAME single
selection — delivery tools deferred — not a second selection.)

CONSEQUENCE the user saw: the minimum spread was ESTIMATED — "narrowed to around 20-22 basis
points" — for a number sitting in a CSV already fetched, against an explicit instruction not to
fill gaps with estimates. An earlier run was self-refuting: minimum +0.52 quoted beside a start
value of +0.23.

These tests cover the guarantees the round must hold, and fail on the pre-fix code (the helpers
do not exist there).
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _srv():
    import fastapi_server_complete as srv
    return srv


def call(name, args):
    return {"function": {"name": name, "arguments": args}}


def tools(*names):
    return [{"function": {"name": n, "description": "", "parameters": {}}} for n in names]


def run(coro):
    """Fresh event loop per call.

    asyncio.get_event_loop() raises "no current event loop" once any earlier test in the suite has
    closed the global one — so these passed alone and failed in the full run, which is the worst
    way for a test to be wrong.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------------------------------------------------- dedup identity

class TestToolCallKey:
    def test_same_call_as_json_string_and_dict_is_one_key(self):
        """Providers return arguments as either a JSON string or a dict. If those hash
        differently the SAME fetch runs twice — the round re-downloads what it already has."""
        k1 = _srv()._tool_call_key(call("lookup_website", '{"url": "http://x/y.csv"}'))
        k2 = _srv()._tool_call_key(call("lookup_website", {"url": "http://x/y.csv"}))
        assert k1 == k2

    def test_key_is_order_insensitive(self):
        """Argument order is not semantic; two orderings are the same call."""
        a = _srv()._tool_call_key(call("compute", {"expr": "np.min(x)", "label": "m"}))
        b = _srv()._tool_call_key(call("compute", {"label": "m", "expr": "np.min(x)"}))
        assert a == b

    def test_different_arguments_are_different_keys(self):
        """Dedup must not collapse two genuinely different calls to the same tool — fetching
        2025 and 2026 are separate calls, and the user's request needs BOTH."""
        a = _srv()._tool_call_key(call("lookup_website", {"url": "http://x/2025.csv"}))
        b = _srv()._tool_call_key(call("lookup_website", {"url": "http://x/2026.csv"}))
        assert a != b

    def test_malformed_arguments_do_not_raise(self):
        """Selection runs outside the per-tool try/except; raising here would abort the request."""
        assert _srv()._tool_call_key(call("x", "not json")) is not None
        assert _srv()._tool_call_key({}) is not None


# --------------------------------------------------------------------- what the selector sees

class TestResultSummary:
    def test_truncation_is_disclosed_in_band(self):
        """A selector that cannot see it was truncated will compute a 'maximum' over the half of
        the series it was shown — the silent-wrong-number failure this feature exists to remove."""
        out = _srv()._summarise_round_results(
            [("lookup_website", "x" * 5000)], max_per_tool=100, max_total=10000)
        assert "TRUNCATED" in out
        assert "5000" in out                      # states the true size
        assert "do NOT compute an extremum" in out

    def test_total_budget_stops_the_summary(self):
        out = _srv()._summarise_round_results(
            [("a", "x" * 900), ("b", "y" * 900), ("c", "z" * 900)],
            max_per_tool=1000, max_total=1000)
        assert "budget reached" in out
        assert "z" * 900 not in out

    def test_untruncated_output_is_passed_whole(self):
        """The selector must be able to re-emit real values as arguments; needless truncation
        would force it to estimate, which is the bug."""
        out = _srv()._summarise_round_results(
            [("lookup_website", "4.64,3.97\n4.55,3.95")], max_per_tool=20000, max_total=40000)
        assert "4.64,3.97" in out and "TRUNCATED" not in out

    def test_non_string_and_malformed_results_survive(self):
        out = _srv()._summarise_round_results(
            [("a", {"k": 1}), "not-a-tuple", ("b", None)], max_per_tool=500, max_total=5000)
        assert "OUTPUT OF a" in out and "OUTPUT OF b" in out


# --------------------------------------------------------------------- the round's guarantees

class TestSecondRound:

    @staticmethod
    def _gen(returns=None, raises=None):
        async def fake(**kwargs):
            fake.seen = kwargs
            if raises:
                raise raises
            return returns or {}
        fake.seen = None
        return fake

    def test_requests_a_computation_tool_once_data_exists(self):
        """The whole point: with the CSV in hand, `compute` becomes selectable."""
        gen = self._gen({"tool_calls": [call("compute", {"expr": "np.min(y30-y10)"})]})
        out = run(_srv()._second_round_tool_calls(
            "spreads?", [("lookup_website", "4.64,3.97")], tools("lookup_website", "compute"),
            set(), "m", gen))
        assert [c["function"]["name"] for c in out] == ["compute"]

    def test_a_tool_outside_the_offered_set_is_dropped(self):
        """SECURITY. The offered set is already whitelist-filtered upstream (:9930). If round 2
        honoured a name outside it, the round would become a bypass of a HARD gate that a bot's
        allowed_tools relies on."""
        gen = self._gen({"tool_calls": [call("secure_email_sender", {"to": "x@y.z"}),
                                        call("compute", {"expr": "np.min(a)"})]})
        out = run(_srv()._second_round_tool_calls(
            "q", [("lookup_website", "data")], tools("lookup_website", "compute"), set(), "m", gen))
        assert [c["function"]["name"] for c in out] == ["compute"]

    def test_a_call_already_run_is_not_repeated(self):
        """Round 2 sees round 1's output; without dedup it re-fetches the same URL, doubling
        latency and outbound traffic on every request."""
        prior = call("lookup_website", {"url": "http://x/2025.csv"})
        gen = self._gen({"tool_calls": [prior]})
        out = run(_srv()._second_round_tool_calls(
            "q", [("lookup_website", "data")], tools("lookup_website"),
            {_srv()._tool_call_key(prior)}, "m", gen))
        assert out == []

    def test_no_prior_output_means_no_selection_call_at_all(self):
        """Nothing to reason about — spending a tool-model call would be pure cost."""
        gen = self._gen({"tool_calls": [call("compute", {})]})
        out = run(_srv()._second_round_tool_calls("q", [], tools("compute"), set(), "m", gen))
        assert out == []
        assert gen.seen is None, "the selector must not be called with no prior output"

    def test_selector_failure_is_fail_open(self):
        """A round-2 failure must degrade to today's behaviour, never lose the answer that
        round 1 already earned."""
        gen = self._gen(raises=RuntimeError("provider 500"))
        out = run(_srv()._second_round_tool_calls(
            "q", [("lookup_website", "data")], tools("compute"), set(), "m", gen))
        assert out == []

    def test_empty_and_malformed_responses_are_handled(self):
        for resp in ({}, {"tool_calls": None}, {"tool_calls": []}, None):
            out = run(_srv()._second_round_tool_calls(
                "q", [("lookup_website", "d")], tools("compute"), set(), "m", self._gen(resp)))
            assert out == []

    def test_prior_output_actually_reaches_the_selector(self):
        """Guards against the round firing but reasoning about nothing — the failure mode where a
        feature looks live in the log and is inert in fact."""
        gen = self._gen({"tool_calls": []})
        run(_srv()._second_round_tool_calls(
            "what is the min spread?", [("lookup_website", "4.64,3.97")],
            tools("compute"), set(), "m", gen))
        prompt = gen.seen["prompt"]
        assert "4.64,3.97" in prompt
        assert "what is the min spread?" in prompt
        assert "Do NOT repeat a call that already appears above" in prompt


# --------------------------------------------------------------------- the damper

class TestRoundCap:
    def test_config_is_fail_closed(self):
        """An unreadable config must DISABLE the round, not enable it with defaults."""
        srv = _srv()
        original = srv.config_loader.load_config
        try:
            srv.config_loader.load_config = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
            assert srv._second_round_config()['enabled'] is False
        finally:
            srv.config_loader.load_config = original

    def test_capped_at_exactly_one_extra_round(self):
        """THE DAMPER, and the invariant that outlives any on/off decision.

        A round that can itself request more tools is a control loop, and an undamped control loop
        oscillates rather than converging. Exactly one extra round is permitted: the tools it asks
        for run, and cannot trigger another selection.

        (The feature shipped OFF and was switched ON by the operator on 2026-08-14, once truncation
        was fixed and reading a complete table by eye was still producing a wrong maximum. The cap
        is asserted here; the enabled flag deliberately is not, because that one is an operational
        choice and this test must not have to change every time it is made.)
        """
        import yaml
        cfg = yaml.safe_load(open(Path(__file__).resolve().parents[2] / "config/llm_config.yaml"))
        sr = cfg["tool_calling"]["second_round"]
        assert sr["max_extra_rounds"] == 1
        assert isinstance(sr["enabled"], bool)

    def test_selector_budget_fits_a_real_data_file(self):
        """SI-037's lesson, applied one layer in. A budget of 20,000 would re-truncate the very
        Treasury CSV (20,730 chars) the truncation fix just repaired, so the selector would again
        be reasoning over half a table — the same silent-wrong-extremum bug, moved rather than
        removed."""
        import yaml
        cfg = yaml.safe_load(open(Path(__file__).resolve().parents[2] / "config/llm_config.yaml"))
        sr = cfg["tool_calling"]["second_round"]
        assert sr["max_chars_per_tool"] >= 50000
        assert sr["max_chars_total"] >= 2 * sr["max_chars_per_tool"] - 1


class TestUnresolvableReferenceFailsTheCall:
    """FOUND ON PRODUCTION 2026-08-14. An unresolvable reference used to leave the ORIGINAL
    arguments in place, so the tool received raw {"from":…,"column":…} dicts and reported

        data['mag'] is not numeric: float() argument must be … not 'dict'

    — a type error that hid the real problem (an unknown output id) and cost a whole diagnosis
    round to see through. The call must fail with the reference's own message instead."""

    def test_unresolved_reference_replaces_the_arguments(self):
        srv = _srv()
        calls = [call("compute", {"expr": "np.min(y)",
                                  "data": {"y": {"from": "nope#7", "column": "mag"}}})]
        out = srv._resolve_call_references(calls, [("lookup_website", "a,b\n1,2\n3,4", 0, False, None)])
        args = out[0]["function"]["arguments"]
        assert "_reference_error" in args
        assert "nope#7" in args["_reference_error"]
        assert "data" not in args, "unresolved reference dicts must NOT reach the tool"

    def test_a_resolvable_reference_is_untouched_by_this_path(self):
        srv = _srv()
        calls = [call("compute", {"expr": "np.min(b)",
                                  "data": {"b": {"from": "lookup_website#1", "column": "b"}}})]
        out = srv._resolve_call_references(calls, [("lookup_website", "a,b\n1,2\n3,4", 0, False, None)])
        args = out[0]["function"]["arguments"]
        assert "_reference_error" not in args
        assert args["data"]["b"] == [2.0, 4.0]


class TestUncomputedClaimAudit:
    """SHADOW measurement for the fail-closed notice. Two prompt-only fixes in this line of work
    already failed under measurement, so the directive is instrumented rather than trusted."""

    def test_flags_a_claim_with_no_successful_compute(self):
        a = _srv().audit_uncomputed_claim(
            "The average was 4.30%, computed as the arithmetic mean over 251 observations.",
            "Tool: compute\nExpression rejected: comprehension …\nNO FIGURE WAS CALCULATED. …")
        assert a["unsupported"] is True

    def test_does_not_flag_a_genuinely_computed_figure(self):
        a = _srv().audit_uncomputed_claim(
            "The minimum was 0.18, computed as np.min(y30 - y10) over n=404 data points.",
            "Tool: compute\ncomputed as: np.min(y30 - y10)\nover n=404 data point(s)")
        assert a["unsupported"] is False and a["compute_succeeded"] is True

    def test_does_not_flag_an_honest_omission(self):
        """compute failed and the answer made no claim — the behaviour the notice is meant to
        produce."""
        a = _srv().audit_uncomputed_claim(
            "The calculation could not be completed, so I cannot give the average.",
            "Tool: compute\nNO FIGURE WAS CALCULATED. …")
        assert a["unsupported"] is False and a["compute_failed"] is True

    def test_no_compute_involved_is_never_flagged(self):
        a = _srv().audit_uncomputed_claim("Barcelona is in Spain.", "Tool: search_web\n…")
        assert a["unsupported"] is False
