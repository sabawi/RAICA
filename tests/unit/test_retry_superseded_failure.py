"""The retry engine must not re-run a failed call whose work a later call in the same request already completed.

NewX post 9088 (2026-10-25): run_python_analysis failed its self-check; the gather loop ran it again and it succeeded;
then `intelligent_retry_with_circuit_breakers` re-ran the FAILED call twice more. Two extra programs, two duplicate
charts, and an answer that presented the duplicate as a deliberate second experiment ("two time steps were tested").

Whether the work is the same is the MODEL's decision (`_failure_already_done`); these tests stub that decision and
pin the wiring around it. Offline: no model is called.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _srv():
    import fastapi_server_complete as srv
    return srv


def _run(error_analysis, tools_called, results, decision, monkeypatch):
    srv = _srv()
    # The breaker is process-global and counts retries per task; a fresh one keeps tests independent.
    monkeypatch.setattr(srv, "circuit_breaker_manager", srv.CircuitBreakerManager())
    asked = []

    async def fake(user_prompt, failed_name, failed_result, later):
        asked.append((failed_name, [n for n, _ in later]))
        return decision
    monkeypatch.setattr(srv, "_failure_already_done", fake)
    out = asyncio.run(srv.intelligent_retry_with_circuit_breakers(
        error_analysis, {}, tools_called, results, "solve the wave equation and plot it", tool_manager=None))
    return out, asked


FAIL = {"1": {"error_pattern": "command_failed", "feedback": "exit status 1", "retry_strategy": "fix"}}


def test_a_failure_redone_successfully_is_not_retried(monkeypatch):
    """Post 9088: the later run succeeded; the failed one must not be regenerated."""
    out, asked = _run(FAIL, ["run_python_analysis", "run_python_analysis"], ["error: exit 1", "[[chart:x]] ok"],
                      "the later call completed the simulation", monkeypatch)
    assert asked == [("run_python_analysis", ["run_python_analysis"])]
    assert out["reason"] == "NO_RETRY_NEEDED"


def test_a_failure_the_model_says_is_different_work_is_still_retried(monkeypatch):
    """Two different searches by one tool are not the same work: the retry must still run."""
    out, _ = _run(FAIL, ["search_web", "search_web"], ["error: timeout", "results for another query"], None,
                  monkeypatch)
    assert out["reason"] == "MISSING_TOOL_MANAGER"      # i.e. it went on to regenerate


def test_no_later_success_means_no_question(monkeypatch):
    """The model is asked only when the same tool later succeeded; otherwise nothing changes."""
    out, asked = _run(FAIL, ["run_python_analysis", "search_web"], ["error: exit 1", "results"], "x", monkeypatch)
    assert asked == [] and out["reason"] == "MISSING_TOOL_MANAGER"


def test_a_later_call_that_also_failed_does_not_count(monkeypatch):
    """A later call of the same tool that ALSO failed has done nothing."""
    both = {**FAIL, "2": {"error_pattern": "command_failed", "feedback": "exit 1", "retry_strategy": "fix"}}
    out, asked = _run(both, ["run_python_analysis", "run_python_analysis"], ["error: 1", "error: 2"], "x",
                      monkeypatch)
    assert asked == []


def test_the_check_failing_keeps_the_retry(monkeypatch):
    """If the model call itself fails, the retry runs exactly as before."""
    srv = _srv()

    async def boom(*a, **k):
        raise RuntimeError("model down")

    async def gen(*a, **k):
        raise RuntimeError("model down")
        yield  # pragma: no cover
    monkeypatch.setattr(srv.llm_manager, "generate_stream", gen)
    r = asyncio.run(srv._failure_already_done("q", "run_python_analysis", "err", [("run_python_analysis", "ok")]))
    assert r is None
