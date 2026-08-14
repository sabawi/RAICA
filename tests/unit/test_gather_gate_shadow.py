"""Non-DR GATHER GATE, Phase 0 (shadow) — docs/RAICA_NONDR_GATHER_GATE.md.

THE FLAW. The non-DR path terminates gathering on a COUNT, not a CONDITION
(`max_extra_rounds > 0`). Production, on "the average 10-year yield in 2025, and nothing else":

    03:33:20  selection : ['search_datasets']                  (catalog metadata)
    03:33:23  SECOND ROUND: ['search_web','search_datasets']   <- budget spent here
    03:33:33  selection : ['lookup_website']                   <- the CSV finally arrives
              (no further selection — the counter was exhausted)

No selector ever saw the CSV, so `compute` was UNREACHABLE — not rejected, not overlooked. The
answer quoted 4.24% from a web article against a true 4.2932%.

Deep Research has had the right shape since it was written: `_assess` (research/engine.py:709)
returns sufficient/needs_more and the loop stops on an evaluated condition. This is that shape for
the path that never had it. Phase 0 logs the verdict and acts on nothing.
"""
import asyncio
import sys
from pathlib import Path

import pytest

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


CSV = ("[CSV file: 250 lines retrieved (complete)]\n"
       "Date,10 Yr\n12/31/2025,4.18\n12/30/2025,4.14\n12/29/2025,4.16\n")


def _stub_model(payload):
    """Replace llm_manager.generate_stream with one returning `payload`."""
    async def gen(prompt, **kwargs):
        gen.prompt = prompt
        gen.kwargs = kwargs
        yield payload
    gen.prompt = None
    return gen


class TestVerdict:

    def _assess(self, payload, results):
        srv = _srv()
        original = srv.llm_manager.generate_stream
        stub = _stub_model(payload)
        try:
            srv.llm_manager.generate_stream = stub
            out = run(srv._gather_gate_assess("average 10-year yield in 2025?", results,
                                              tools("compute", "lookup_website"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        return out, stub

    def test_needs_more_is_reported(self):
        """The verdict the failing run should have produced: data present, calculation absent."""
        out, _ = self._assess(
            '{"status":"needs_more","missing":"the average is not calculated","next_tools":["compute"]}',
            [("lookup_website", CSV, 0, False, None)])
        assert out["status"] == "needs_more"
        assert out["next_tools"] == ["compute"]
        assert "average" in out["missing"]

    def test_sufficient_is_reported(self):
        out, _ = self._assess('{"status":"sufficient","missing":"","next_tools":[]}',
                              [("lookup_website", CSV, 0, False, None)])
        assert out["status"] == "sufficient"

    def test_an_unparseable_verdict_is_UNAVAILABLE_not_a_fake_sufficient(self):
        """CONTRACT CORRECTED while writing this: I first asserted that unparseable output should
        default to "sufficient". The code returns None, and None is the better answer.

        `extract_json_object` raises JSONDecodeError on prose, so a gate that could not produce a
        verdict reports NO verdict rather than inventing an agreeable one. In shadow that logs
        UNAVAILABLE — a distinguishable signal, and the difference between "the gate judged this
        sufficient" and "the gate did not run" is exactly what SI-021 lost for seven builds. It
        still fails open: None means the request proceeds untouched."""
        out, _ = self._assess("I think it's probably fine?",
                              [("lookup_website", CSV, 0, False, None)])
        assert out is None

    def test_next_tools_outside_the_offered_set_are_dropped(self):
        """Even in shadow the verdict must not name a tool the caller is not allowed — it would
        read as a recommendation to widen a bot's whitelist."""
        out, _ = self._assess(
            '{"status":"needs_more","missing":"x","next_tools":["compute","secure_email_sender"]}',
            [("lookup_website", CSV, 0, False, None)])
        assert out["next_tools"] == ["compute"]

    def test_no_prior_output_means_no_model_call(self):
        out, stub = self._assess('{"status":"sufficient"}', [])
        assert out is None
        assert stub.prompt is None, "the gate must not spend a call with nothing to judge"

    def test_a_model_failure_returns_none_not_an_exception(self):
        srv = _srv()
        original = srv.llm_manager.generate_stream

        async def boom(prompt, **kwargs):
            raise RuntimeError("provider 500")
            yield ""  # pragma: no cover
        try:
            srv.llm_manager.generate_stream = boom
            out = run(srv._gather_gate_assess("q", [("lookup_website", CSV, 0, False, None)],
                                              tools("compute"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        assert out is None


class TestWhatTheGateSees:

    def test_it_receives_a_schema_preview_not_the_file(self):
        """579 chars for a 20,730-char CSV. 'Do I have what I need?' is answerable from what EXISTS;
        sending contents is what made the selector truncate at 4,096 tokens."""
        srv = _srv()
        original = srv.llm_manager.generate_stream
        stub = _stub_model('{"status":"sufficient"}')
        big = CSV + "\n".join(f"01/{i:02d}/2025,4.{i:02d}" for i in range(1, 250))
        try:
            srv.llm_manager.generate_stream = stub
            run(srv._gather_gate_assess("q", [("lookup_website", big, 0, False, None)],
                                        tools("compute"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        assert len(stub.prompt) < len(big)
        assert "'10 Yr'" in stub.prompt and "data rows" in stub.prompt

    def test_the_derived_figure_rule_is_stated(self):
        """The whole point: data in hand does NOT mean a derived figure is in hand."""
        srv = _srv()
        original = srv.llm_manager.generate_stream
        stub = _stub_model('{"status":"sufficient"}')
        try:
            srv.llm_manager.generate_stream = stub
            run(srv._gather_gate_assess("q", [("lookup_website", CSV, 0, False, None)],
                                        tools("compute"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        assert "has to be calculated" in stub.prompt


class TestPhase0IsInert:

    def test_config_ships_disabled_and_in_shadow(self):
        """Phase 0 must not be able to change behaviour. Enforcement is a later, separate decision
        taken on shadow numbers."""
        import yaml
        gg = yaml.safe_load((ROOT / "config/llm_config.yaml").read_text())["tool_calling"]["gather_gate"]
        assert gg["enabled"] is False
        assert gg["shadow"] is True
        assert gg["max_gather_rounds"] >= 1 and gg["wall_clock_seconds"] > 0

    def test_config_is_fail_closed(self):
        srv = _srv()
        original = srv.config_loader.load_config
        try:
            srv.config_loader.load_config = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
            assert srv._gather_gate_config()["enabled"] is False
        finally:
            srv.config_loader.load_config = original


class TestTheGateActuallySeesTheRequest:
    """FOUND IN THE FIRST SHADOW RUN. The gate returned:

        verdict=needs_more missing='No user prompt was provided; the request is empty…'

    `user_message` is CONSTRUCTED (fastapi_server_complete.py:10135-10164): a directive preamble
    first, with the real request appended LAST as "User Prompt: …". Truncating from the FRONT kept
    the preamble and cut the question — with NewX's ~7,000-char system prompt merged in, the gate
    judged a request it had never seen.

    It would have produced a plausible-looking verdict on every run, and the whole point of Phase 0
    is that the shadow numbers are trustworthy."""

    def test_the_question_survives_truncation(self):
        srv = _srv()
        original = srv.llm_manager.generate_stream
        stub = _stub_model('{"status":"sufficient"}')
        constructed = ("Examine the intent of the user's prompt and apply the system directives. "
                       + "DIRECTIVE FILLER. " * 400
                       + "\n\nUser Prompt: what was the average 10-year yield in 2025?")
        assert len(constructed) > 4000
        try:
            srv.llm_manager.generate_stream = stub
            run(srv._gather_gate_assess(constructed, [("lookup_website", CSV, 0, False, None)],
                                        tools("compute"), "m"))
        finally:
            srv.llm_manager.generate_stream = original
        assert "average 10-year yield in 2025" in stub.prompt, \
            "the actual question was truncated away — every verdict would be about nothing"
