"""Regression: the arbitrator's retry must stay inside the request whitelist and keep what it made.

FAILURE THIS PREVENTS (2026-10-24, local E2E, Ask bot, "solve the wave equation and plot it")
-----------------------------------------------------------------------------------------------
A `compute` call failed. The arbitrator's retry ("INTELLIGENT RETRY ENGINE") asked the
tool-calling model to correct it and OFFERED ALL 35 TOOLS — Ask allows 10 — so the model
"corrected" `compute` into `analytical_visualizer`, a tool Ask may not use, and it ran.
It drew a chart; `_merge_corrected_results` matched corrections to failed tools BY NAME,
found no failed `analytical_visualizer`, and discarded the chart while the loop reported
success. The answer said it had computed the curve and showed no plot.

Two defects, one gap (a retry may return a DIFFERENT tool than the one that failed):
  * permission — the retry must offer and run only the request whitelist plus the tools
    that failed (those were permitted when first dispatched; social_media_wordpress, a
    legitimate retry from outside the whitelist, must still run);
  * loss — a successful substitute must be kept as an entry of its own.

These tests FAIL on the pre-fix code.
"""
import asyncio

from fastapi_server_complete import (
    _merge_corrected_results,
    _model_allowed_tools,
    _regenerate_failed_tools_with_llm,
    _retry_permitted_tools,
)

ASK = frozenset({"search_web", "wikipedia_query", "compute", "plot_data"})
FAILED_COMPUTE = [{"tool_name": "compute", "task_index": 1}]


def _call(name):
    return {"function": {"name": name, "arguments": "{}"}}


class _FakeManager:
    """Returns fixed tool calls and records which tools it was offered. No model is called."""

    def __init__(self, names):
        self.names = names
        self.offered = None

    async def generate_tools(self, prompt, tools, system_prompt=None):
        self.offered = [t["function"]["name"] for t in tools]
        return {"tool_calls": [_call(n) for n in self.names]}


def _with_whitelist(allowed, fn):
    token = _model_allowed_tools.set(allowed)
    try:
        return fn()
    finally:
        _model_allowed_tools.reset(token)


def test_retry_permits_whitelist_plus_failed_tools_only():
    """The permitted set is the request whitelist + the failed tools — nothing else."""
    got = _with_whitelist(ASK, lambda: _retry_permitted_tools(
        [{"tool_name": "social_media_wordpress", "task_index": 0}]))
    assert "social_media_wordpress" in got          # a failed tool from outside the whitelist may retry
    assert ASK <= got
    assert "analytical_visualizer" not in got
    assert "sandboxed_executor" not in got


def test_unrestricted_client_is_unchanged():
    """No whitelist (an internal client) → no restriction, exactly as before."""
    assert _with_whitelist(None, lambda: _retry_permitted_tools(FAILED_COMPUTE)) is None


def test_retry_drops_a_substitute_the_request_never_allowed():
    """THE permission bug: the retry returned analytical_visualizer for a failed compute, and it ran."""
    mgr = _FakeManager(["analytical_visualizer", "compute"])
    permitted = _with_whitelist(ASK, lambda: _retry_permitted_tools(FAILED_COMPUTE))
    calls = asyncio.run(_regenerate_failed_tools_with_llm(
        mgr, "ctx", FAILED_COMPUTE, [], permitted=permitted))
    assert [c["function"]["name"] for c in calls] == ["compute"]


def test_retry_of_a_failed_off_whitelist_tool_still_runs():
    """The Tier-1 case the old comment protects: a failed social_media_wordpress must still retry."""
    cands = [{"tool_name": "social_media_wordpress", "task_index": 0}]
    mgr = _FakeManager(["social_media_wordpress"])
    permitted = _with_whitelist(ASK, lambda: _retry_permitted_tools(cands))
    calls = asyncio.run(_regenerate_failed_tools_with_llm(mgr, "ctx", cands, [], permitted=permitted))
    assert [c["function"]["name"] for c in calls] == ["social_media_wordpress"]


def test_merge_keeps_a_successful_substitute_and_its_chart():
    """THE loss bug: a chart made by a different tool than the failed one was thrown away."""
    original = ["Tool: wikipedia_query\nResult: wave equation\n\n",
                "Tool: compute\nResult: Tool 'compute' error: unknown output reference\n\n"]
    corrected = [{"tool_name": "plot_data",
                  "result": "[[chart:/static/images/media/abc.jpg|caption=\"u(x,t)\"]]",
                  "corrected": True}]
    merged = _merge_corrected_results(original, corrected, FAILED_COMPUTE)
    joined = "".join(merged)
    assert "[[chart:/static/images/media/abc.jpg" in joined
    assert "Tool: plot_data" in joined
    assert "unknown output reference" in joined     # the failure stays stated, not hidden


def test_merge_still_replaces_a_same_name_correction_in_place():
    """Unchanged behaviour: a corrected compute replaces the failed compute at its index."""
    original = ["Tool: wikipedia_query\nResult: x\n\n", "Tool: compute\nResult: error\n\n"]
    corrected = [{"tool_name": "compute", "result": "1.5\ncomputed as: np.sqrt(2.25)",
                  "corrected": True}]
    merged = _merge_corrected_results(original, corrected, FAILED_COMPUTE)
    assert len(merged) == 2 and "np.sqrt(2.25)" in merged[1] and "error" not in merged[1]
