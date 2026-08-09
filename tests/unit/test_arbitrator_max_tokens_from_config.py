"""Regression: the arbitrator's max_tokens must come from CONFIG, not a literal.

FAILURE THIS PREVENTS
---------------------
`LLMManager.call_arbitrator` built its kwargs with `'max_tokens': 1024` as a
LITERAL. Providers resolve this parameter as:

    kwargs.get('max_tokens', self.get_max_tokens())

so a literal kwarg ALWAYS outranks `llm_config.yaml`. The configured
`arbitrator.config.max_tokens` was therefore dead — raising it changed nothing.
That is the worst kind of knob: one that looks adjustable and is not, so an
operator responding to truncation by raising the YAML value would see no effect
and conclude the model was at fault.

1024 was also too small. The arbitrator must emit a COMPLETE tasks[] JSON, one
entry per executed tool; truncated, it is unparseable and the lane fails
wholesale. Measured requirement is 477 + 131n (gpt-oss-120b) and 577 + 160n
(GLM-5.2); at the observed production peak of 6 tools that is 1097 / 1419 tokens
— both over the old cap. GLM-5.2 truncated on 2/2 runs at batch 6.

Plan step 4.3, docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md.

These tests FAIL on the pre-4.3 code, where the literal wins regardless of config.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from llm_providers.manager import LLMManager


def _manager_with(config_max_tokens):
    """An LLMManager whose arbitrator provider is configured with a given cap."""
    provider = MagicMock()
    provider.get_model = MagicMock(return_value="test-model")
    provider.get_max_tokens = MagicMock(return_value=config_max_tokens)

    captured = {}

    async def _stream(prompt, model, **kwargs):
        captured.update(kwargs)
        for chunk in ('{"tasks": []}',):
            yield chunk

    provider.generate_stream = _stream

    mgr = LLMManager()
    mgr.arbitrator_provider = provider
    mgr._initialized = True
    return mgr, captured


def test_configured_max_tokens_reaches_the_request():
    """The provider's configured cap must be what gets sent."""
    mgr, captured = _manager_with(4096)

    asyncio.run(mgr.call_arbitrator("validate this", "SYSTEM PROMPT"))

    assert captured["max_tokens"] == 4096, (
        f"config said 4096 but the request carried {captured.get('max_tokens')} "
        "— a literal is still outranking llm_config.yaml"
    )


def test_a_different_configured_value_is_honoured_too():
    """Not special-cased to 4096 — whatever config says is what is sent."""
    mgr, captured = _manager_with(8192)

    asyncio.run(mgr.call_arbitrator("validate this", "SYSTEM PROMPT"))

    assert captured["max_tokens"] == 8192


def test_explicit_caller_kwarg_still_wins():
    """A caller passing max_tokens explicitly must still override config.

    `**kwargs` is spread last in call_arbitrator, so an explicit argument
    outranks config. That ordering is intentional and must not regress.
    """
    mgr, captured = _manager_with(4096)

    asyncio.run(mgr.call_arbitrator("validate", "SYSTEM", max_tokens=512))

    assert captured["max_tokens"] == 512


def test_system_prompt_is_still_forwarded():
    """Guard against a regression of SI-014 via this path."""
    mgr, captured = _manager_with(4096)

    asyncio.run(mgr.call_arbitrator("validate this", "THE SCHEMA SPEC"))

    assert captured["system_prompt"] == "THE SCHEMA SPEC"


def test_shipped_config_covers_the_observed_production_peak():
    """The value in llm_config.yaml must clear the measured requirement.

    Production peak is 6 concurrent tool results (logs/archive). Measured need at
    batch 6 is 1419 tokens on the hungrier model. A cap below that reintroduces
    the exact truncation this change fixes, so the shipped config is asserted —
    not just the plumbing.
    """
    with open("config/llm_config.yaml") as fh:
        cfg = yaml.safe_load(fh)

    cap = cfg["arbitrator"]["config"]["max_tokens"]
    need_at_peak_6 = 577 + 160 * 6      # GLM-5.2, the hungrier candidate

    assert cap >= need_at_peak_6, (
        f"arbitrator max_tokens={cap} is below the measured requirement "
        f"{need_at_peak_6} at the observed production peak of 6 tool results"
    )
    assert cap >= 4096, (
        f"arbitrator max_tokens={cap} leaves no headroom; batch size is unbounded "
        "in code (fastapi_server_complete.py:5293)"
    )
