"""Regression: a response truncated by max_tokens must be REPORTED, not silent.

FAILURE THIS PREVENTS
---------------------
When a model hits the `max_tokens` output cap, the vendor still returns HTTP 200
with well-formed JSON. The ONLY signal that the body is incomplete is
`finish_reason == "length"` — and RAICA read that field nowhere. `finish_reason`
appeared in the codebase exclusively where RAICA WRITES it for its own clients.

Consequence: a truncated reply was indistinguishable from a model that produced
bad output. Measured instance (2026-08-09): the arbitrator lane is capped at
max_tokens=1024 (manager.py:317, hardcoded). At >=4 tool results GLM-5.2's
tasks[] JSON exceeds that and is cut mid-object, so json.loads() fails and the
lane fails wholesale — while the log blamed the model for "not returning JSON".
At batch 6 it failed 100% of runs.

This is the systemic guard from
docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md 4.2: it converts every future
cap-too-low mistake from silent corruption into a stated fact, in ONE place
rather than at each call site.

Deliberately a WARNING, not an exception — truncated output is often partially
usable, and raising would turn a degraded response into an outage. The caller
decides; this only makes the decision possible.

These tests FAIL on the pre-4.2 code (no warning is emitted, and generate_tools
returns no `truncated` key) and pass after.
"""
import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_providers.openai import OpenAIProvider

TOOLS = [{
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Do math",
        "parameters": {"type": "object",
                       "properties": {"expr": {"type": "string"}},
                       "required": ["expr"]},
    },
}]


def _provider():
    return OpenAIProvider({
        "api_key": "test-key",
        "base_url": "https://vendor.example/v1",
        "model": "test-model",
        "max_tokens": 1024,
        "retry_attempts": 1,
    })


def _stream_provider(chunks):
    """Provider whose streaming HTTP layer replays raw SSE lines."""
    provider = _provider()
    response = MagicMock()
    response.status = 200
    response.content = _aiter([c.encode() for c in chunks])
    response.text = AsyncMock(return_value="")

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    provider._get_session = AsyncMock(return_value=session)
    return provider


def _aiter(items):
    class _A:
        def __aiter__(self):
            self._it = iter(items)
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration
    return _A()


def _tools_provider(message, finish_reason):
    provider = _provider()
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1024},
    })
    response.text = AsyncMock(return_value="")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    provider._get_session = AsyncMock(return_value=session)
    return provider


async def _drain(provider):
    return "".join([c async for c in
                    provider.generate_stream("hi", "test-model")])


def test_stream_truncation_is_warned(caplog):
    """finish_reason=length on a stream must produce a TRUNCATED warning."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"{\\"tasks\\": ["}}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
        'data: [DONE]\n',
    ]
    provider = _stream_provider(chunks)
    with caplog.at_level(logging.WARNING):
        text = asyncio.run(_drain(provider))

    assert text == '{"tasks": ['          # the partial body is still yielded
    assert any("TRUNCATED by max_tokens" in r.message for r in caplog.records), \
        "truncation was NOT reported — this is the silent-corruption bug"


def test_stream_complete_response_is_not_warned(caplog):
    """finish_reason=stop must NOT warn — no false positives."""
    chunks = [
        'data: {"choices":[{"delta":{"content":"done"}}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        'data: [DONE]\n',
    ]
    provider = _stream_provider(chunks)
    with caplog.at_level(logging.WARNING):
        text = asyncio.run(_drain(provider))

    assert text == "done"
    assert not any("TRUNCATED" in r.message for r in caplog.records)


def test_tools_truncation_is_warned_and_surfaced(caplog):
    """generate_tools must warn AND return truncated=True."""
    provider = _tools_provider(
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "calculator",
                                      "arguments": '{"expr": "1+'}}]},
        "length")
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            provider.generate_tools("2?", "test-model", TOOLS))

    assert result["truncated"] is True, \
        "callers cannot detect truncation from the return value"
    assert any("TRUNCATED by max_tokens" in r.message for r in caplog.records)


def test_tools_complete_response_reports_not_truncated(caplog):
    """A normal tool call reports truncated=False and emits no warning."""
    provider = _tools_provider(
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "calculator",
                                      "arguments": '{"expr": "19*23"}'}}]},
        "stop")
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            provider.generate_tools("19*23?", "test-model", TOOLS))

    assert result["truncated"] is False
    assert [t["function"]["name"] for t in result["tool_calls"]] == ["calculator"]
    assert not any("TRUNCATED" in r.message for r in caplog.records)


def test_warning_names_the_cap_so_it_is_actionable(caplog):
    """The warning must state the cap — otherwise it says 'something broke'."""
    provider = _tools_provider(
        {"role": "assistant", "content": "x", "tool_calls": None}, "length")
    with caplog.at_level(logging.WARNING):
        asyncio.run(provider.generate_tools("hi", "test-model", TOOLS,
                                            max_tokens=1024))

    msg = " ".join(r.message for r in caplog.records)
    assert "1024" in msg, "warning does not name the cap that was hit"
    assert "test-model" in msg, "warning does not name the model"
