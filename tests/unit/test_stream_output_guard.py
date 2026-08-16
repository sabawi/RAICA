"""Regression (SI-052): a degenerate output run must be STOPPED, not merely survived.

FAILURE THIS PREVENTS
---------------------
One synthesis run streamed **2,924,215 characters that were 99.8% whitespace** — 2,152 runs
of 200+ consecutive spaces, longest 2,862 — around 6,393 characters of real content. With no
chart marker available the model hand-drew an ASCII chart and the padding ran away.

**Nothing in RAICA stopped it.** The run ended only because the vendor's ceiling fired:

    ✂️ TRUNCATED by max_tokens: deepseek-ai/DeepSeek-V4-Pro-0813 in generate_stream
       hit the 32768-token output cap (finish_reason=length)

So a *higher* cap would simply have produced a *larger* runaway, and a different trigger
would reproduce it. Detecting the cause (the missing marker) was not enough; the class needs
a damper of its own.

THRESHOLDS ARE DERIVED, NOT CHOSEN
----------------------------------
Measured over every captured answer:

    legitimate : up to 72,147 chars, longest whitespace run  18
    runaway    :    2,924,215 chars, longest whitespace run  2,862

400 sits 22x above the largest real run and 7x below the runaway. A guard that fires on real
output would be worse than no guard, so both limits sit far from the legitimate side.
"""
import asyncio
import json
import logging

from llm_providers.openai import OpenAIProvider


def _sse(chunks):
    """Raw SSE lines for a stream of content chunks."""
    out = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n" for c in chunks]
    out.append("data: [DONE]\n")
    return out


def _provider(chunks, **cfg):
    from unittest.mock import AsyncMock, MagicMock
    p = OpenAIProvider({"api_key": "k", "base_url": "https://v.example/v1",
                        "model": "m", "retry_attempts": 1, **cfg})

    class _A:
        def __aiter__(self):
            self._it = iter([c.encode() for c in _sse(chunks)])
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    resp = MagicMock()
    resp.status = 200
    resp.content = _A()
    resp.text = AsyncMock(return_value="")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    p._get_session = AsyncMock(return_value=session)
    return p


def _drain(p):
    async def go():
        return "".join([c async for c in p.generate_stream("hi", "m")])
    return asyncio.run(go())


def test_whitespace_runaway_is_stopped():
    """THE bug: unbounded blank padding, exactly as observed (runs of 200+, longest 2,862)."""
    text = _drain(_provider(["Here is the chart:\n"] + [" " * 250] * 40))
    assert len(text) < 20_000, f"the runaway was not stopped — emitted {len(text):,} chars"
    assert "unbounded blank padding" in text, "the reader is not told why output stopped"


def test_a_real_answer_is_untouched():
    """The guard must not fire on legitimate output — the largest real whitespace run was 18."""
    body = ["## Analysis\n\n", "| Statistic | Value |\n", "|---|---|\n",
            "| Mean | 5.88 |\n", "\n" + " " * 18 + "\n", "Conclusion follows.\n"]
    text = _drain(_provider(body))
    assert text == "".join(body), "the guard altered a legitimate answer"


def test_the_observed_legitimate_and_runaway_values_land_on_opposite_sides():
    """Pin the discrimination against the two numbers actually measured."""
    p = OpenAIProvider({"api_key": "k", "base_url": "u", "model": "m"})
    _, ws_limit = p._stream_guard()
    assert 18 < ws_limit < 2862, (
        f"ws_run_limit {ws_limit} does not separate the largest legitimate run (18) from "
        f"the runaway (2,862)"
    )


def test_oversized_answer_is_stopped():
    """A backstop independent of whitespace: content can run away without padding."""
    p = _provider(["x" * 5000] * 200, stream_max_chars=50_000)
    text = _drain(p)
    assert len(text) < 120_000, f"size cap did not fire — emitted {len(text):,}"
    assert "exceeded the size limit" in text


def test_the_stop_is_logged_loudly(caplog):
    """A silent truncation is its own defect — the operator must see why."""
    with caplog.at_level(logging.WARNING):
        _drain(_provider(["ok\n"] + [" " * 300] * 20))
    assert any("DEGENERATE OUTPUT" in r.message for r in caplog.records), \
        "the runaway was stopped without telling anyone"


def test_limits_are_overridable_per_deployment():
    """Config may tune them, but the code default must be protective on its own."""
    p = OpenAIProvider({"api_key": "k", "base_url": "u", "model": "m",
                        "stream_max_chars": 123, "stream_ws_run_limit": 7})
    assert p._stream_guard() == (123, 7)
    bare = OpenAIProvider({"api_key": "k", "base_url": "u", "model": "m"})
    max_chars, ws = bare._stream_guard()
    assert max_chars > 0 and ws > 0, "a missing config key disabled the guard"
