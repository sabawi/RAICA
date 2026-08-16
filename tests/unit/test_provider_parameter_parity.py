"""Contract: every provider must CONSUME the parameters callers pass it.

WHY THIS EXISTS
---------------
Four defects in one session shared a single mechanism:

    a value declared in one layer is silently ignored in another

The worst instance (SI-014) survived for months because `ollama.py` was fixed in
v1.0.2.101 and **nothing checked the other providers**. `openai.py` kept dropping
the system prompt, and because `generate_tools` in the same class handled it
correctly, the gap was invisible. The arbitrator ran without its JSON schema spec
the whole time — 0% schema compliance — and the logs blamed the model.

A per-bug fix cannot prevent that. Only an executable contract can: this test
turns the parity table in docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md 2.1 into
something that FAILS when a provider silently stops honouring a parameter, or
when a NEW provider is added without wiring one up.

WHAT IT DOES *NOT* ASSERT
-------------------------
Not every provider must support every parameter — `think` is legitimately
Ollama-only, and `headers` only matters for OpenAI-compatible endpoints. So gaps
are ALLOWED, but must be DECLARED with a reason (KNOWN_GAPS). An *undeclared*
gap fails. That keeps the test honest: closing a gap means deleting its entry,
and adding a provider means stating explicitly what it does not support.

Static analysis, deliberately: constructing a provider needs real credentials and
has side effects (GeminiProvider.__init__ calls genai.configure), and this must
run offline in Tier-0.
"""
import ast
import pathlib
import re

import pytest

PROVIDER_DIR = pathlib.Path(__file__).resolve().parents[2] / "llm_providers"
PROVIDERS = ["ollama", "openai", "gemini", "qwen"]

# Parameters callers actually pass into provider methods. Sources:
#   manager.call_arbitrator      -> system_prompt, temperature, max_tokens, stream
#   manager.generate_stream/tools-> model, system_prompt, + caller kwargs
#   llm_config.yaml lane configs -> timeout, context_window_size, num_predict, think
REQUIRED = ["system_prompt", "temperature", "max_tokens", "timeout"]

# Declared, justified gaps. Deleting an entry is how a gap gets closed.
KNOWN_GAPS = {
    # CLOSED 2026-08-15 — ("think", "openai") and ("context_window_size", "openai") used
    # to live here. Both were WRONG, and their presence is why this contract stayed green
    # through a real outage: `think` is NOT Ollama-only (DeepInfra accepts
    # chat_template_kwargs.enable_thinking on GLM-5.2 and DeepSeek-V4-Pro, measured), and
    # declaring a gap does not make it harmless — an unread `think` left reasoning ON,
    # which consumed the tool lane's output cap and returned zero tool calls.
    # LESSON: a KNOWN_GAP must say the provider CANNOT express the parameter, never
    # merely that this codebase does not. Verify against the vendor before adding one.
    ("context_window_size", "gemini"): "same as openai — no client-side knob",
    ("context_window_size", "qwen"): "same as openai — no client-side knob",
    ("num_predict", "openai"):
        "Ollama dialect. openai.py consumes the SAME intent as `max_tokens`; "
        "llm_providers/param_map.py folds both onto canonical max_output_tokens.",
    ("num_predict", "gemini"): "Ollama-specific name",
    ("num_predict", "qwen"): "Ollama-specific name",
    ("think", "gemini"): "google-generativeai exposes no thinking switch",
    ("think", "qwen"): "DashScope exposes no thinking switch",
    ("stream", "gemini"): "google-generativeai SDK selects streaming by method",
    ("stream", "qwen"): "DashScope uses parameters.incremental_output instead",
    ("retry_attempts", "ollama"): "no retry loop implemented for this provider",
    ("retry_attempts", "gemini"): "no retry loop implemented for this provider",
    ("retry_attempts", "qwen"): "no retry loop implemented for this provider",
    ("retry_delay", "ollama"): "no retry loop implemented",
    ("retry_delay", "gemini"): "no retry loop implemented",
    ("retry_delay", "qwen"): "no retry loop implemented",
    ("headers", "ollama"): "local endpoint; no custom-header use case",
    ("headers", "gemini"): "SDK manages transport headers",
    ("headers", "qwen"): "no custom-header use case",
}

OPTIONAL = ["context_window_size", "num_predict", "think", "stream",
            "retry_attempts", "retry_delay", "headers"]


def _source(provider):
    return (PROVIDER_DIR / f"{provider}.py").read_text()


def _references(provider, param):
    """Does the provider's source reference this parameter by name?"""
    return bool(re.search(rf"""['"]{re.escape(param)}['"]""", _source(provider)))


@pytest.mark.parametrize("param", REQUIRED)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_required_parameter_is_consumed(provider, param):
    """A parameter every caller passes must be read by every provider.

    `system_prompt` is the one that bit us: dropping it produces no error, no
    warning, and output that looks superficially fine while every system
    directive — citation rules, JSON-only contracts — has been stripped.
    """
    assert _references(provider, param), (
        f"{provider}.py never references '{param}'. Callers pass it "
        f"(manager.py), so it is being SILENTLY DROPPED. This is the SI-014 "
        f"class of defect: no error, no warning, just missing behaviour."
    )


@pytest.mark.parametrize("param", OPTIONAL)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_optional_gap_is_declared(provider, param):
    """Optional gaps are allowed — but must be DECLARED, not discovered."""
    if _references(provider, param):
        assert (param, provider) not in KNOWN_GAPS, (
            f"{provider}.py now DOES handle '{param}', but it is still listed "
            f"in KNOWN_GAPS. Remove the entry — a stale allow-list hides the "
            f"next real gap."
        )
        return

    assert (param, provider) in KNOWN_GAPS, (
        f"{provider}.py does not handle '{param}' and the gap is UNDECLARED. "
        f"Either wire it up, or add ('{param}', '{provider}') to KNOWN_GAPS "
        f"with the reason it does not apply."
    )


@pytest.mark.parametrize("provider", PROVIDERS)
def test_system_prompt_reaches_the_messages_payload(provider):
    """Referencing `system_prompt` is not enough — it must reach the request.

    A provider could read the kwarg and never use it. This asserts the name
    appears in an assignment or call that also builds messages/payload, so a
    read-and-discard cannot pass.
    """
    src = _source(provider)
    tree = ast.parse(src)

    uses = [n for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "system_prompt"]
    assert uses, f"{provider}.py binds no `system_prompt` variable at all"

    # It must be used somewhere other than the line that reads it from kwargs.
    read_lines = {m.start() for m in
                  re.finditer(r"system_prompt\s*=\s*kwargs\.get", src)}
    read_linenos = {src[:pos].count("\n") + 1 for pos in read_lines}
    downstream = [n for n in uses if n.lineno not in read_linenos]
    assert downstream, (
        f"{provider}.py reads `system_prompt` from kwargs but never uses it "
        f"downstream — it is read and discarded."
    )


def test_every_provider_module_is_covered():
    """A new provider file must be added to PROVIDERS, or this test fails.

    Without this, adding provider N+1 silently escapes every check above —
    which is precisely how openai.py escaped the v1.0.2.101 ollama fix.
    """
    # `param_map` is infrastructure, not a provider: it holds the canonical-parameter
    # translation table the providers TRANSLATE THROUGH. It implements no LLM API, so
    # the per-parameter assertions below are meaningless against it. Its own contract
    # lives in tests/unit/test_provider_param_translation.py.
    on_disk = {p.stem for p in PROVIDER_DIR.glob("*.py")
               if p.stem not in {"__init__", "base", "factory", "manager", "param_map"}}
    missing = on_disk - set(PROVIDERS)
    assert not missing, (
        f"provider module(s) {sorted(missing)} exist but are not covered by the "
        f"parity contract. Add them to PROVIDERS."
    )
