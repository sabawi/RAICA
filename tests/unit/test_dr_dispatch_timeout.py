"""One hung source must not freeze a Deep Research round — and a slow one must not be cut off.

FAILURE THIS PREVENTS (SI-064)
------------------------------
`_dispatch_round` awaits `asyncio.gather(...)` with no timeout, and the only log line in that
region came AFTER the await. So a single source that never returned froze the whole round in
total silence.

Measured on production 2026-08-17: a DR round went quiet for 41 minutes.
  * RAICA log      — last line `Web search completed`, then nothing
  * Ollama journal — last request 14:56:01, then nothing (so NOT an LLM hang)
  * `sar`          — ~98% idle CPU, ~0.03% iowait (blocked, not spinning)
  * system journal — no OOM, no network failure, no service restart
The client waited out its 1800s timeout and received 0 bytes.

`loop.wall_clock_seconds` (240s) existed and should have covered this, but it is evaluated at
the TOP of the round loop. A hung round never returns to the check, so a budget that can only
be tested BETWEEN iterations cannot bound the work inside one.

THE DESIGN CONSTRAINT
---------------------
The bound is PER TASK, deliberately not per round and not per request:
  * a stuck SOURCE is dropped, and the round keeps every other result;
  * a genuinely LENGTHY request is untouched — it may run as many rounds as its own budget
    allows, each taking as long as its sources legitimately need.
Bounding the gather itself, or charging it against the wall clock, WOULD preempt long
legitimate research. These tests pin both halves: the hang is cut, the slow work is not.
"""
import asyncio
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from research.engine import DeepResearchEngine  # noqa: E402


def _engine(timeout_s):
    """A ResearchEngine with only what these tests touch — no network, no LLM."""
    eng = DeepResearchEngine.__new__(DeepResearchEngine)
    eng._cfg = {"loop": {"dispatch_timeout_seconds": timeout_s}}
    return eng


# ───────────────────────────────────────── the hang is cut
def test_a_hung_source_is_abandoned_instead_of_freezing_the_round():
    """FAILS PRE-FIX: _safe_dispatch awaited _dispatch with no bound and never returned."""
    eng = _engine(0.3)

    async def _hang(source, query):
        await asyncio.sleep(3600)            # the production signature: never returns

    eng._dispatch = _hang
    t0 = time.monotonic()
    out = asyncio.run(asyncio.wait_for(eng._safe_dispatch("search_web", "q"), timeout=10))
    elapsed = time.monotonic() - t0

    assert elapsed < 5, f"the hung source was not abandoned (took {elapsed:.1f}s)"
    assert "timed out" in out.lower(), out


def test_the_timeout_is_reported_as_a_timeout_not_a_generic_failure():
    """A hung source and a source that answered badly need different diagnoses."""
    eng = _engine(0.3)

    async def _hang(source, query):
        await asyncio.sleep(3600)

    eng._dispatch = _hang
    # Outer bound so PRE-FIX code FAILS rather than HANGING: without a timeout of its own,
    # _safe_dispatch would sit here for an hour and the suite would never finish. A test that
    # hangs is not a failing test — it is an unusable one.
    out = asyncio.run(asyncio.wait_for(
        eng._safe_dispatch("published_papers_search", "q"), timeout=10))
    assert "published_papers_search" in out
    assert "timed out" in out.lower()
    assert "returned no usable result" not in out, "misreported as a generic failure"


def test_a_round_survives_one_hung_source_and_keeps_the_others():
    """THE point: the round completes with real evidence instead of freezing."""
    eng = _engine(0.3)

    async def _mixed(source, query):
        if source == "stuck":
            await asyncio.sleep(3600)
        return f"real content from {source}"

    eng._dispatch = _mixed

    async def _round():
        # Coroutines must be CREATED inside the running loop — building them outside and
        # handing them to asyncio.run() attaches them to a different loop and raises.
        return await asyncio.gather(
            eng._safe_dispatch("search_web", "a"),
            eng._safe_dispatch("stuck", "b"),
            eng._safe_dispatch("wikipedia_query", "c"),
        )

    results = asyncio.run(asyncio.wait_for(_round(), timeout=10))
    assert "real content from search_web" in results[0]
    assert "timed out" in results[1].lower()
    assert "real content from wikipedia_query" in results[2]


# ───────────────────────────────────────── the slow work is NOT cut
def test_a_slow_but_legitimate_source_is_NOT_preempted():
    """THE constraint. Measured round durations were 15-46s; the default allows 300s.

    A source finishing well inside the budget must return its real content untouched.
    """
    eng = _engine(2.0)

    async def _slow(source, query):
        await asyncio.sleep(0.4)             # slow, but far inside the budget
        return "hard-won research content"

    eng._dispatch = _slow
    out = asyncio.run(eng._safe_dispatch("search_web", "q"))
    assert out == "hard-won research content", "legitimate slow work was preempted"


def test_the_default_budget_clears_the_slowest_measured_round_by_a_wide_margin():
    """Derived, not chosen: slowest observed round 46s (48 parallel sources -> 45s)."""
    eng = DeepResearchEngine.__new__(DeepResearchEngine)
    eng._cfg = {}
    assert eng._dispatch_timeout / 46.0 >= 3, "less than 3x the slowest measured round"
    assert eng._dispatch_timeout >= 120, "too tight for a realistic ~60-90s worst case"


def test_the_per_source_budget_stays_INSIDE_the_loop_budget():
    """The two limits must not contradict each other.

    A per-source budget larger than `wall_clock_seconds` would let ONE stuck source outlive
    the entire gather phase it belongs to. An earlier draft of this fix shipped 300s against
    a 240s loop budget — caught by asking what the two numbers mean together.
    """
    import yaml
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "llm_config.yaml")))
    loop = cfg["deep_research"]["engine"]["loop"]
    assert loop["dispatch_timeout_seconds"] < loop["wall_clock_seconds"], (
        f"per-source {loop['dispatch_timeout_seconds']}s exceeds loop budget "
        f"{loop['wall_clock_seconds']}s")


def test_the_budget_is_configurable():
    """Operators must be able to widen it without editing code."""
    assert _engine(900)._dispatch_timeout == 900


def test_the_bound_is_per_task_not_per_round():
    """Bounding the ROUND would preempt a long legitimate request — the thing to avoid.

    Three sources each taking most of the per-task budget must ALL succeed, because they run
    concurrently and each is judged on its own.
    """
    eng = _engine(1.5)

    async def _slowish(source, query):
        await asyncio.sleep(0.5)
        return f"content from {source}"

    eng._dispatch = _slowish

    async def _round():
        return await asyncio.gather(*[eng._safe_dispatch(f"src{i}", "q") for i in range(3)])

    results = asyncio.run(_round())
    assert all("content from" in r for r in results), \
        "a per-ROUND bound leaked in and preempted concurrent legitimate work"


# ───────────────────────────────────────── the region is no longer silent
def test_the_round_announces_itself_BEFORE_awaiting():
    """FAILS PRE-FIX: the only log line came after the gather, so a frozen round said nothing."""
    src = open(os.path.join(ROOT, "research", "engine.py")).read()
    i = src.index("outputs = await asyncio.gather(")
    before = src[max(0, i - 700):i]
    assert "Round %d: dispatching" in before, \
        "nothing is logged before the await — a hung round is invisible again"


def test_wall_clock_is_still_only_a_between_rounds_check():
    """Documents WHY the per-task bound is needed, so nobody 'simplifies' it away.

    wall_clock_seconds cannot interrupt a hung round; it is evaluated at the top of the loop.
    """
    src = open(os.path.join(ROOT, "research", "engine.py")).read()
    i = src.index("if time.monotonic() - start > self._wall_clock:")
    j = src.index("outputs = await asyncio.gather(")
    assert i > j, "layout changed — re-verify that wall_clock still cannot bound a round"
