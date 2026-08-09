"""Regression: DR's JSON-returning control calls must read their OUTPUT cap from config.

FAILURE THIS PREVENTS
---------------------
Four Deep Research calls carried HARDCODED `max_tokens` literals. Each has its reply
parsed by `extract_json_object()`, and each sits inside a `try/except` that degrades to
a benign-looking fallback. So a cap set too low produces SILENT quality loss, never an
error:

  research/pipeline.py  decompose (2000) -> fallback `actions: []`, i.e. the user's
                        requested email/PDF is never sent, with no error anywhere
  research/engine.py    planner   (1200) -> plan unparseable; all 3 retries fail alike
  research/engine.py    assess     (900) -> `status: sufficient` with EMPTY gaps, so
                        later gather rounds lose their targeted follow-ups
  research/synthesis.py verify   (12000) -> claim extraction under-samples a long answer,
                        so late claims go unverified while grounding reports coverage

CONFIRMED IN PRODUCTION (2026-08-09): the 900 cap truncated on DeepSeek-V3.1 AND twice
on DeepSeek-V4-Flash — model-independent — and the 12000 verification cap truncated on
the largest run. Found by the v1.0.0.237 truncation detector; before it, all of this was
invisible. Tracked as SI-015; plan step 4.7.

These tests FAIL on the pre-4.7 code, where the literals ignore config entirely.
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _cfg():
    return yaml.safe_load((ROOT / "config" / "llm_config.yaml").read_text())


def _engine_cfg():
    return _cfg()["deep_research"]["engine"]


# --------------------------------------------------------------- no hardcoded literals
@pytest.mark.parametrize("path,pattern,what", [
    ("research/engine.py", r"max_tokens=1200", "DR planner"),
    ("research/engine.py", r"max_tokens=900", "gap assessment"),
    ("research/pipeline.py", r"max_tokens=2000", "request decompose"),
])
def test_literal_cap_is_gone(path, pattern, what):
    """The hardcoded literal must no longer appear on the call."""
    src = (ROOT / path).read_text()
    assert not re.search(pattern, src), (
        f"{path} still hardcodes the {what} cap ({pattern}). A literal here silently "
        f"outranks llm_config.yaml — the knob looks adjustable and is not."
    )


@pytest.mark.parametrize("path,pattern,what", [
    ("research/engine.py", r"max_tokens=self\._planner_max_tokens", "DR planner"),
    ("research/engine.py", r"max_tokens=self\._assess_max_tokens", "gap assessment"),
    ("research/pipeline.py", r"max_tokens=_decompose_cap", "request decompose"),
])
def test_call_reads_the_config_value(path, pattern, what):
    """...and the call must actually pass the config-derived value."""
    src = (ROOT / path).read_text()
    assert re.search(pattern, src), f"{path}: {what} does not use its config-driven cap"


# ------------------------------------------------------------------- config is present
@pytest.mark.parametrize("keypath,minimum", [
    (("decompose_max_tokens",), 4000),
    (("planner", "max_tokens"), 4000),
    (("loop", "assess_max_tokens"), 4000),
    (("verification", "max_tokens"), 32000),
])
def test_config_key_present_and_adequate(keypath, minimum):
    """Each cap must be set in config and at least the sized-for value.

    Asserts the SHIPPED value, not just that the plumbing works — a plumbing-only test
    passes with max_tokens: 100, which is exactly the bug.
    """
    node = _engine_cfg()
    for k in keypath:
        assert isinstance(node, dict) and k in node, (
            f"deep_research.engine.{'.'.join(keypath)} is MISSING. The verification cap "
            f"in particular defaulted to 12000 in code precisely because its key was "
            f"absent — and that default truncated in production."
        )
        node = node[k]
    assert int(node) >= minimum, (
        f"deep_research.engine.{'.'.join(keypath)} = {node}, below the sized-for "
        f"{minimum}. These sit above the OBSERVED failure point on purpose; billing is "
        f"on actual completion_tokens, so a generous cap costs nothing."
    )


def test_caps_exceed_the_observed_production_failure_points():
    """The whole point: every new cap must clear the value that actually truncated."""
    e = _engine_cfg()
    assert e["loop"]["assess_max_tokens"] > 900, "gap assessment truncated at 900"
    assert e["verification"]["max_tokens"] > 12000, "verification truncated at 12000"


# ----------------------------------------------------- the duplicate-key trap (YAML)
def test_no_duplicate_yaml_keys_under_engine():
    """A duplicate mapping key is SILENTLY discarded by YAML — last one wins.

    Adding `planner:`/`loop:` blocks as NEW siblings (rather than extending the existing
    ones) parsed cleanly and left the new caps as None. Nothing errored. This asserts the
    keys we depend on are singly defined so that failure cannot recur unnoticed.
    """
    src = (ROOT / "config" / "llm_config.yaml").read_text()
    for key in ("planner:", "loop:", "verification:"):
        # count only 4-space-indented occurrences (engine-level blocks)
        n = len(re.findall(rf"^    {re.escape(key)}\s*$", src, re.M))
        assert n <= 1, (
            f"'{key}' appears {n} times at engine level in llm_config.yaml. YAML keeps "
            f"only the LAST — earlier definitions are silently discarded."
        )
