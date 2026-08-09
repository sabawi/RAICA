"""Regression: a present-but-null `tool_calls` must not crash the tool lane.

FAILURE THIS PREVENTS
---------------------
`OpenAIProvider.generate_tools` used `message.get('tool_calls', [])`. A dict
default fires only when the KEY IS ABSENT. OpenAI omits the key when the model
calls no tool, so the bug never surfaced there — but other OpenAI-compatible
vendors return the key PRESENT and NULL:

    "message": {"role": "assistant", "content": "Hi!", "tool_calls": null}

`.get('tool_calls', [])` then returns None, and the formatting loop did
`for tool_call in None` -> TypeError: 'NoneType' object is not iterable.

Impact: the crash fired on every CORRECT ABSTENTION — i.e. exactly when the
model rightly decided no tool was needed (a greeting, a pure-knowledge
question, an explicit "do not search"). Discovered 2026-08-09 while evaluating
DeepInfra for the tool_calling lane, where 2 of 16 tool-selection cases died
this way. `content` had the identical flaw and is covered here too.

These tests FAIL on the pre-fix code and pass after it.
"""
import asyncio
import json
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


def _provider_returning(message_body):
    """An OpenAIProvider whose HTTP layer replays `message_body` verbatim."""
    provider = OpenAIProvider({
        "api_key": "test-key",
        "base_url": "https://vendor.example/v1",
        "model": "test-model",
        "retry_attempts": 1,
    })

    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={
        "choices": [{"message": message_body}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })
    response.text = AsyncMock(return_value="")

    post_ctx = MagicMock()
    post_ctx.__aenter__ = AsyncMock(return_value=response)
    post_ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=post_ctx)
    provider._get_session = AsyncMock(return_value=session)
    return provider


def test_null_tool_calls_does_not_raise():
    """Vendor sends tool_calls:null (correct abstention) -> empty list, no crash."""
    provider = _provider_returning(
        {"role": "assistant", "content": "Hello!", "tool_calls": None})

    result = asyncio.run(provider.generate_tools("hi", "test-model", TOOLS))

    assert result["tool_calls"] == []
    assert result["content"] == "Hello!"


def test_null_content_does_not_become_none():
    """Vendor sends content:null alongside a tool call -> '' not None.

    Downstream code concatenates and length-checks this value; None propagates
    as a TypeError far from the origin.
    """
    provider = _provider_returning({
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "calculator",
                                     "arguments": '{"expr": "1+1"}'}}],
    })

    result = asyncio.run(provider.generate_tools("2?", "test-model", TOOLS))

    assert result["content"] == ""
    assert isinstance(result["content"], str)
    assert [t["function"]["name"] for t in result["tool_calls"]] == ["calculator"]


def test_absent_tool_calls_key_still_works():
    """OpenAI's own shape (key omitted) must keep working — no regression."""
    provider = _provider_returning({"role": "assistant", "content": "Hello!"})

    result = asyncio.run(provider.generate_tools("hi", "test-model", TOOLS))

    assert result["tool_calls"] == []
    assert result["content"] == "Hello!"


def test_real_tool_calls_still_normalised():
    """A populated tool_calls list is still converted to the internal shape."""
    provider = _provider_returning({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_abc", "type": "function",
                        "function": {"name": "calculator",
                                     "arguments": '{"expr": "19*23"}'}}],
    })

    result = asyncio.run(provider.generate_tools("19*23?", "test-model", TOOLS))

    assert len(result["tool_calls"]) == 1
    call = result["tool_calls"][0]
    assert call["id"] == "call_abc"
    assert call["type"] == "function"
    assert call["function"]["name"] == "calculator"
    assert json.loads(call["function"]["arguments"])["expr"] == "19*23"
