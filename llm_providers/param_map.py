"""Canonical LLM parameter vocabulary and per-provider wire translation.

WHY THIS EXISTS
---------------
2026-08-15: the tool-calling lane moved from Ollama to DeepInfra. A provider switch is a
TRANSPORT change and was supposed to preserve the model and its limits. It preserved
neither, and nothing said so:

  * `think: false` (`llm_config.yaml:106,1000`) is read only by `ollama.py`. On the
    OpenAI-compatible transport no code consumed it, so GLM-5.2 reasoned freely and its
    reasoning tokens were billed against `max_tokens`.
  * callers pass `max_tokens=4096`; `ollama.py` reads only `num_predict`, so on Ollama
    that value was dropped and the lane silently ran at the 16384 default.

Net effect of the "seamless" switch: a 16,384-token budget with reasoning OFF became a
4,096-token budget with reasoning ON. The tool model then hit `finish_reason=length`
before emitting a single tool call — twice in one request — and the user's answer was
synthesised with zero tools, no data and no chart.

This is the mechanism named once in docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md §0:

    a value declared in one layer is silently ignored or overridden in another

Per-parameter fixes cannot prevent the next instance, because the parameter NAMES and
their wire shapes genuinely differ per provider and no single place said how they map.
docs/.../PARITY §2.1 recorded `think`/`num_predict` as "provider-specific" gaps and the
parity contract test declared them acceptable — which is exactly why the test stayed
green while the lane was broken. A DECLARED gap is not automatically a HARMLESS gap.

WHAT THIS IS
------------
One lookup table: canonical parameter -> per-provider wire location + transform, or an
explicit `Unsupported` with a reason. Providers translate through this table instead of
each reaching into `kwargs` with its own spelling and its own default.

THE RULE THAT MATTERS: an unsupported parameter is LOUD, never silent. If a caller or a
lane config asks for something the transport cannot express, that is reported once per
(provider, parameter) rather than dropped. Silence is what cost the incident above.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Tuple, Union

logger = logging.getLogger(__name__)

__all__ = ["CANONICAL", "ALIASES", "PROVIDER_PARAMS", "Wire", "Unsupported",
           "normalize", "apply_to_payload", "supports"]


# --------------------------------------------------------------------------- vocabulary
# The names RAICA speaks internally. Callers and llm_config.yaml may use any alias below;
# everything is normalised to these before a provider sees it.
CANONICAL: Tuple[str, ...] = ("max_output_tokens", "context_window_size", "reasoning_enabled")

# Legacy / provider-flavoured spellings that callers and config still use. `num_predict`
# and `max_tokens` are the SAME intent expressed in two vendors' dialects — the incident
# happened because they were treated as different parameters.
ALIASES: Dict[str, str] = {
    "max_tokens": "max_output_tokens",
    "max_output_tokens": "max_output_tokens",
    "num_predict": "max_output_tokens",
    "context_window_size": "context_window_size",
    "num_ctx": "context_window_size",
    "think": "reasoning_enabled",
    "reasoning_enabled": "reasoning_enabled",
}


@dataclass(frozen=True)
class Wire:
    """Where a canonical parameter lands in a provider's request payload."""
    path: Tuple[str, ...]
    transform: Callable[[Any], Any] = field(default=lambda v: v)
    note: str = ""


@dataclass(frozen=True)
class Unsupported:
    """The transport genuinely cannot express this parameter. Stated, not implied."""
    reason: str


Spec = Union[Wire, Unsupported]


# --------------------------------------------------------------------------- the table
# Keyed by provider TYPE (llm_config.yaml `type:`), not by vendor: `openai` covers every
# OpenAI-compatible endpoint (DeepInfra, OpenRouter, Ollama's own /v1 proxy, OpenAI).
PROVIDER_PARAMS: Dict[str, Dict[str, Spec]] = {
    "ollama": {
        "max_output_tokens": Wire(("options", "num_predict"),
                                  note="Ollama's name for the output cap"),
        "context_window_size": Wire(("options", "num_ctx"),
                                    note="client-side context knob; genuinely settable here"),
        "reasoning_enabled": Wire(("think",), bool,
                                  note="native top-level thinking switch"),
    },
    "openai": {
        "max_output_tokens": Wire(("max_tokens",)),
        "context_window_size": Unsupported(
            "OpenAI-compatible APIs expose no client-side context knob; the vendor's "
            "model context governs. Setting it in a lane config has no effect."),
        # MEASURED 2026-08-15 against DeepInfra: `chat_template_kwargs.enable_thinking`
        # is accepted by BOTH zai-org/GLM-5.2 and deepseek-ai/DeepSeek-V4-Pro-0813 and
        # suppresses `reasoning_content` (GLM: 224 chars -> 0). Chosen over
        # `reasoning_effort: none` — which also worked here — because `reasoning_effort`
        # is rejected by several OpenAI-compatible vendors for models that lack it,
        # whereas an unknown chat_template_kwargs key is ignored by the template.
        "reasoning_enabled": Wire(("chat_template_kwargs", "enable_thinking"), bool,
                                  note="vLLM/DeepInfra chat-template switch"),
    },
    "gemini": {
        "max_output_tokens": Wire(("generation_config", "max_output_tokens")),
        "context_window_size": Unsupported("SDK has no client-side context knob"),
        "reasoning_enabled": Unsupported(
            "google-generativeai exposes no thinking switch on the models RAICA uses"),
    },
    "qwen": {
        "max_output_tokens": Wire(("parameters", "max_tokens")),
        "context_window_size": Unsupported("DashScope has no client-side context knob"),
        "reasoning_enabled": Unsupported("DashScope exposes no thinking switch"),
    },
}

# Warn once per (provider, parameter) — a config-declared but unsupported value would
# otherwise warn on every single call and get tuned out, which is its own kind of silence.
_reported: set = set()


def normalize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Fold aliases into canonical names. Unknown keys are left out entirely."""
    out: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        canon = ALIASES.get(key)
        if canon is not None and value is not None:
            out[canon] = value
    return out


def supports(provider_type: str, canonical: str) -> bool:
    spec = PROVIDER_PARAMS.get(provider_type, {}).get(canonical)
    return isinstance(spec, Wire)


def apply_to_payload(provider_type: str, payload: Dict[str, Any],
                     params: Dict[str, Any], where: str = "") -> Dict[str, Any]:
    """Write canonical params into `payload` using this provider's wire spelling.

    `params` may use any alias. Values of None are ignored (not set). A parameter the
    provider cannot express is reported once, never silently dropped.
    """
    table = PROVIDER_PARAMS.get(provider_type)
    if table is None:
        logger.warning("🔌 param_map: unknown provider type %r — parameters passed through "
                       "untranslated; add it to PROVIDER_PARAMS", provider_type)
        return payload

    for canon, value in normalize(params).items():
        spec = table.get(canon)
        if spec is None:
            continue
        if isinstance(spec, Unsupported):
            key = (provider_type, canon)
            if key not in _reported:
                _reported.add(key)
                logger.warning(
                    "🔌 param_map: %r was requested (=%r%s) but provider %r cannot express "
                    "it — %s. The value is NOT in effect.",
                    canon, value, f", {where}" if where else "", provider_type, spec.reason)
            continue
        target = payload
        for part in spec.path[:-1]:
            target = target.setdefault(part, {})
        target[spec.path[-1]] = spec.transform(value)
    return payload
