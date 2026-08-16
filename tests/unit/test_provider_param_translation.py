"""Regression: a provider swap must not silently change generation limits.

FAILURE THIS PREVENTS
---------------------
2026-08-15. The tool-calling lane was moved from Ollama to DeepInfra — a TRANSPORT
change intended to keep the same model and the same limits. Two parameters silently
changed meaning across that boundary:

  * `think: false` in llm_config.yaml was read ONLY by ollama.py. On the OpenAI-
    compatible transport nothing consumed it, so GLM-5.2 emitted reasoning_content
    which is billed against max_tokens.
  * callers passed `max_tokens=4096`; ollama.py reads ONLY `num_predict`, so the value
    was dropped there and the lane ran at the 16384 default.

Net: 16384 tokens with reasoning OFF became 4096 tokens with reasoning ON. The tool
model hit finish_reason=length before emitting any tool call — twice in one request —
and the user's answer was synthesised with zero tools, no data and no chart. Neither
half was visible in a log or a test: the parity contract even DECLARED both as
acceptable provider-specific gaps, which is why it stayed green.

These tests pin the translation itself, so the next transport swap cannot repeat it.
Every test below FAILS on the pre-fix code.
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_providers.openai import OpenAIProvider
from llm_providers.ollama import OllamaProvider

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


def _mock_post(provider, response_json):
    """Give a provider an HTTP layer that records the payload it was sent."""
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=response_json)
    response.text = AsyncMock(return_value="")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    provider._get_session = AsyncMock(return_value=session)
    return session


def _openai_payload(config, **kwargs):
    provider = OpenAIProvider({"api_key": "k", "base_url": "https://v.example/v1",
                               "model": "test-model", "retry_attempts": 1, **config})
    session = _mock_post(provider, {
        "choices": [{"message": {"content": "", "tool_calls": []},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })
    asyncio.run(provider.generate_tools("hi", "test-model", TOOLS, **kwargs))
    return session.post.call_args.kwargs["json"]


def _ollama_payload(config, response_json=None, **kwargs):
    provider = OllamaProvider({"base_url": "http://127.0.0.1:11434",
                               "model": "test-model", **config})
    session = _mock_post(provider, response_json or {
        "message": {"content": "", "tool_calls": []}, "done_reason": "stop"})
    result = asyncio.run(provider.generate_tools("hi", "test-model", TOOLS, **kwargs))
    return session.post.call_args.kwargs["json"], result


# ----------------------------------------------------------------- reasoning parity
def test_openai_suppresses_reasoning_by_default():
    """think defaults to False on BOTH transports, or the swap changed behaviour.

    ollama.py has always used `self.config.get('think', False)`. The OpenAI path had no
    equivalent, so moving a lane there turned reasoning ON without anyone choosing it.
    """
    payload = _openai_payload({})
    assert payload.get("chat_template_kwargs", {}).get("enable_thinking") is False, (
        "OpenAI transport did not suppress reasoning. GLM-5.2 then spends the output "
        "budget on reasoning_content and can return ZERO tool calls."
    )


def test_openai_honours_think_true_when_configured():
    """The switch must be a real switch, not a hardcoded off."""
    payload = _openai_payload({"think": True})
    assert payload["chat_template_kwargs"]["enable_thinking"] is True


def test_ollama_and_openai_agree_on_the_reasoning_default():
    """Same config in, same reasoning decision out — that is what 'seamless' means."""
    ollama_payload, _ = _ollama_payload({})
    openai_payload = _openai_payload({})
    assert ollama_payload["think"] is False
    assert openai_payload["chat_template_kwargs"]["enable_thinking"] is False


# ------------------------------------------------------------------- budget parity
def test_openai_tool_cap_comes_from_config_not_a_literal():
    """A literal max_tokens at the call site outranks config (PARITY plan 2.2)."""
    payload = _openai_payload({"max_tokens": 8192})
    assert payload["max_tokens"] == 8192, (
        f"expected the configured 8192, got {payload['max_tokens']} — the lane is "
        f"running at a cap that config cannot see"
    )


def test_ollama_honours_max_tokens_as_num_predict():
    """`max_tokens` and `num_predict` are one intent in two dialects.

    Pre-fix, ollama.py read only `num_predict`, so a caller passing max_tokens=4096 got
    the 16384 default instead — the same class of silent drop, in the other direction.
    """
    payload, _ = _ollama_payload({}, max_tokens=4096)
    assert payload["options"]["num_predict"] == 4096, (
        f"max_tokens was dropped; num_predict={payload['options']['num_predict']}"
    )


def test_ollama_explicit_num_predict_still_wins():
    """Precedence must be explicit, not accidental."""
    payload, _ = _ollama_payload({}, max_tokens=4096, num_predict=777)
    assert payload["options"]["num_predict"] == 777


# --------------------------------------------------------------- truncation parity
def test_ollama_reports_truncation(caplog):
    """Ollama had no truncation detection, so only ONE transport could report it.

    That asymmetry makes the instrumented provider look buggier than the silent one.
    """
    with caplog.at_level(logging.WARNING):
        _, result = _ollama_payload(
            {}, response_json={"message": {"content": "{partial", "tool_calls": []},
                               "done_reason": "length"})
    assert result.get("truncated") is True, "generate_tools did not surface `truncated`"
    assert any("TRUNCATED by num_predict" in r.message for r in caplog.records), \
        "an Ollama response cut off at the cap was reported as nothing at all"


def test_ollama_complete_response_is_not_warned(caplog):
    """The detector must discriminate, not fire on everything."""
    with caplog.at_level(logging.WARNING):
        _, result = _ollama_payload({})
    assert result.get("truncated") is False
    assert not any("TRUNCATED" in r.message for r in caplog.records)


# ------------------------------------------------------- the table itself is a contract
def test_unsupported_parameter_is_reported_never_silent():
    """A value the transport cannot express must be stated once, not dropped.

    context_window_size is set on OpenAI lanes in llm_config.yaml and has no effect
    there. Silence is what let the incident above run for a full session.
    """
    from llm_providers import param_map
    param_map._reported.clear()
    logger = logging.getLogger("llm_providers.param_map")
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    try:
        payload = param_map.apply_to_payload(
            "openai", {}, {"context_window_size": 32768}, where="test")
    finally:
        logger.removeHandler(handler)
        param_map._reported.clear()

    assert "context_window_size" not in payload and "num_ctx" not in payload
    assert any("cannot express" in r.getMessage() for r in records), \
        "an inexpressible parameter was dropped silently"


def test_every_provider_declares_every_canonical_parameter():
    """A new provider or a new parameter cannot be half-wired.

    This is the check the old KNOWN_GAPS list could not make: it forces a DECISION
    (wire it, or declare why not) for every cell of the matrix.
    """
    from llm_providers import param_map
    for provider, table in param_map.PROVIDER_PARAMS.items():
        missing = [p for p in param_map.CANONICAL if p not in table]
        assert not missing, (
            f"provider {provider!r} has no entry for {missing} — add a Wire or an "
            f"explicit Unsupported(reason). An absent entry is an undeclared gap."
        )
