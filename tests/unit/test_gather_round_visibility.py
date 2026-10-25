"""Gather loop: every round's output is SEEN, and the selector is TOLD what the gate found missing.

Production-shaped failure, 2026-10-25 — "@Ask plot the monthly changes in Brent oil prices … since the US/Israel
made their first attack on Iran this year", 3 runs through the real NewX path, 0 charts:

  * the preview budget was filled in order, so round 1's long search results used all of it and a page fetched
    in round 2 was omitted from what the gate and the selector saw (`shown 3 of 6`);
  * the gate said "no chart; use plot_data / run_python_analysis" in every round, but the selector was never
    given that verdict and chose another search in every round;
  * the gate read "this year" as the previous year in 3/3 runs, although the selector, reading the same output,
    resolved it correctly.

Failures each test prevents are named in its docstring. No model is called: every LLM is a stand-in.
"""
import ast
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _srv():
    import fastapi_server_complete as srv
    return srv


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def tools(*names):
    return [{"function": {"name": n, "description": "", "parameters": {}}} for n in names]


def _prose(tag, n):
    """A long prose output whose first and last words carry a tag, so head+tail truncation keeps both."""
    return f"{tag}-START " + ("lorem ipsum dolor sit amet " * (n // 27 + 1))[:n] + f" {tag}-END"


EARLY = [("search_web", _prose("EARLY1", 29000)), ("search_web", _prose("EARLY2", 20000)),
         ("search_web", _prose("EARLY3", 12000))]


class TestEveryOutputIsSeen:

    def test_a_later_round_output_is_shown_when_early_outputs_are_long(self):
        """The Brent failure: a page fetched in a later round was omitted because earlier search results had
        already used the whole preview budget, so the gate kept asking for data that was in hand."""
        late = [("lookup_website", "Brent monthly: Jan 2026 78.1, Feb 2026 81.4, Mar 2026 96.0 LATE-FACT"),
                ("search_web", _prose("LATE2", 15000))]
        out = _srv()._describe_round_results(EARLY + late)
        assert "further tool output omitted" not in out
        for ref in ("search_web#1", "search_web#2", "search_web#3", "search_web#4", "lookup_website#1"):
            assert f"=== {ref} ===" in out, ref
        assert "LATE-FACT" in out and "LATE2-START" in out and "LATE2-END" in out

    def test_short_outputs_keep_their_full_text(self):
        """Sharing the budget must not shave a short result (a computed value, a chart marker) to fit."""
        marker = "[[chart:/static/images/media/abc.png|caption=\"x\"]] values 1, 2, 3"
        out = _srv()._describe_round_results(EARLY + [("plot_data", marker)])
        assert marker in out

    def test_the_total_stays_within_the_budget(self):
        """Fair share must still bound the prompt — the reason the budget exists (a 43,013-char prompt made
        the selector echo the data back as arguments and produce no parseable call)."""
        from utils.tool_output_reference import _TOTAL_PREVIEW_CHARS, REFERENCE_HELP
        out = _srv()._describe_round_results(EARLY * 3)
        body = out[len("AVAILABLE TOOL OUTPUT\n"):-len(REFERENCE_HELP)]
        assert len(body) <= _TOTAL_PREVIEW_CHARS

    def test_output_within_the_budget_is_unchanged(self):
        """When everything fits, nothing is shortened — the common case must behave exactly as before."""
        from utils.tool_output_reference import describe_reference
        res = [("search_web", _prose("A", 3000)), ("lookup_website", _prose("B", 2000))]
        out = _srv()._describe_round_results(res)
        assert describe_reference("search_web#1", res[0][1]) in out
        assert describe_reference("lookup_website#1", res[1][1]) in out


class TestSelectorHearsTheGate:

    @staticmethod
    def _gen():
        async def fake(**kwargs):
            fake.seen = kwargs
            return {"tool_calls": []}
        fake.seen = None
        return fake

    def test_the_gate_verdict_reaches_the_selector(self):
        """The Brent failure: the gate named the missing chart and the tools to make it in every round; the
        selector never saw that and searched again in every round."""
        gen = self._gen()
        verdict = {"status": "needs_more", "missing": "no chart of monthly prices has been produced",
                   "next_tools": ["plot_data", "run_python_analysis"]}
        run(_srv()._second_round_tool_calls("plot it", [("search_web", "Jan 78.1, Feb 81.4")],
                                            tools("plot_data", "run_python_analysis", "search_web"),
                                            set(), "m", gen, gate_verdict=verdict))
        prompt = gen.seen["prompt"]
        assert "no chart of monthly prices has been produced" in prompt
        assert "plot_data, run_python_analysis" in prompt
        # advice, not an order: the gate misread the request's date in 3/3 runs
        assert "the suggestion is advice" in prompt

    def test_without_a_verdict_the_prompt_has_no_gate_section(self):
        """The plain second round (no gate) must not carry an empty or invented gate finding."""
        gen = self._gen()
        run(_srv()._second_round_tool_calls("q", [("search_web", "x")], tools("compute"), set(), "m", gen))
        assert "COMPLETENESS CHECK" not in gen.seen["prompt"]

    def test_figures_in_text_may_be_passed_as_values(self):
        """The selector was told 'never retype the rows' with no exception, while figures found only in prose
        cannot be referenced — a directive that forbade the one way to chart them."""
        gen = self._gen()
        run(_srv()._second_round_tool_calls("q", [("search_web", "x")], tools("plot_data"), set(), "m", gen))
        prompt = gen.seen["prompt"]
        assert "Figures that appear only in text cannot be referenced" in prompt

    def test_the_gather_loop_passes_the_verdict(self):
        """Reachability: the parameter is worthless unless the loop's call actually supplies it."""
        tree = ast.parse((ROOT / "fastapi_server_complete.py").read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "_second_round_tool_calls"]
        # BOTH callers: the gate loop's selector, and the final second round that runs after the gate stops at
        # its ceiling (in the Brent runs that last round, too, searched again without hearing the gate).
        assert len(calls) >= 2
        assert all(any(k.arg == "gate_verdict" for k in c.keywords) for c in calls)


class TestGateKnowsToday:

    def test_the_gate_prompt_states_today(self):
        """The gate read "this year" as the previous year in 3/3 runs; the date must be stated to it as a fact."""
        srv = _srv()

        async def gen(prompt, **kwargs):
            gen.prompt = prompt
            yield '{"status":"sufficient","missing":"","next_tools":[]}'
        original = srv.llm_manager.generate_stream
        try:
            srv.llm_manager.generate_stream = gen
            run(srv._gather_gate_assess("since this year", [("search_web", "text")], tools("search_web"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        assert f"TODAY: {datetime.now().strftime('%A, %B %d, %Y')}" in gen.prompt
