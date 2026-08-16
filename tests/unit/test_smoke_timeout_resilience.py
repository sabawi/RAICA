"""Regression (SI-054): the smoke gate must not fail a deploy on a cold-start timeout.

FAILURE THIS PREVENTS
---------------------
`make smoke` is a MANDATORY pre-deploy gate whose stated job is "does the tool CRASH on
invocation". It classified `asyncio.TimeoutError` as a CODE defect:

    SMOKE FAILED — 1 CODE defect(s); a tool crashes on invocation:
       - get_news_summaries: RAISED TimeoutError

Re-run immediately afterwards, with no code change, it passed: 4,887 chars. Invoked directly
with the gate's exact arguments three times: **2.5s / 0.5s / 0.4s**. The first, uncached
fetch is simply the slow one against a 30s budget — not a crash.

The cost runs BOTH ways, and the second way is worse:
  * a spurious CODE-FAIL blocks a good deploy;
  * a gate people learn to dismiss as "just flaky" is a gate whose REAL failures get waved
    through — which is exactly how search_web stayed dead for six days.

So the fix is not to widen the timeout until nothing ever fails. It is to retry ONCE on a
timeout only, keep a second timeout as a genuine failure, and report the retry so a flaky
tool never looks clean.
"""
import asyncio
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SMOKE = os.path.join(ROOT, "tests", "smoke", "tool_smoke.py")


def _source():
    return open(SMOKE).read()


def test_a_timeout_is_not_reported_as_a_crash():
    """"RAISED TimeoutError" sent the reader hunting for a crash that does not exist."""
    src = _source()
    assert "TIMED OUT twice" in src, (
        "a double timeout is still reported as a generic RAISED exception; the operator "
        "cannot tell a slow fetch from a crashing tool"
    )
    assert "except asyncio.TimeoutError:" in src, "timeouts are not distinguished at all"


def test_the_gate_retries_once_on_timeout():
    """Exactly once — enough for a cold cache, not enough to hide a hang."""
    src = _source()
    assert "_invoke_resilient" in src, "no retry wrapper exists"
    assert "res, captured, retried = asyncio.run(_invoke_resilient" in src, \
        "the main loop does not use the resilient invoker"


def test_a_retry_is_disclosed_in_the_output():
    """A tool that only passes on the second attempt must not look identical to a clean pass."""
    assert "passed only on RETRY" in _source(), \
        "a retried pass is indistinguishable from a first-attempt pass"


def test_retry_logic_behaves(monkeypatch):
    """Behavioural check of the wrapper itself: one timeout recovers, two do not."""
    sys.path.insert(0, os.path.join(ROOT, "tests", "smoke"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("tool_smoke_mod", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:                                   # noqa: BLE001
        pytest.skip("tool_smoke imports the full server stack; not available here")

    calls = {"n": 0}

    async def one_timeout(name, args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError()
        return "real content", ""

    monkeypatch.setattr(mod, "_invoke", one_timeout)
    res, captured, retried = asyncio.run(mod._invoke_resilient("x", {}))
    assert res == "real content" and retried is True, "a single cold timeout was not recovered"

    async def always_timeout(name, args):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(mod, "_invoke", always_timeout)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(mod._invoke_resilient("x", {}))
