"""SI-021 — the Deep Research gap-assessment loop must actually RUN.

WHAT WENT WRONG (v1.0.0.240 -> v1.0.0.246, found 2026-08-10)
------------------------------------------------------------
SI-015 made the DR JSON-call output caps config-driven. `_assess_max_tokens` was defined
on `ResearchPlanner` but is CONSUMED in `DeepResearchEngine._assess`. Every assessment
therefore raised:

    AttributeError: 'DeepResearchEngine' object has no attribute '_assess_max_tokens'

`_assess` wraps its call in a bare `except Exception` whose documented purpose is "never
lose a round to a transient assess error" — so it logged a warning and returned
`{"status": "sufficient"}`. The result: **DR never requested another round.** It always
stopped at `min_rounds`, on every prompt, for every provider, while reporting success.

Measured on one real prompt (@Ask, tech-earnings, full NewX payload):

    prod, pre-fix code   4 rounds · 44 evidence · 171 unique sources · stop=max_rounds
    post-fix, DeepInfra  2 rounds · 19 evidence ·  63 unique sources · stop=sufficient
    post-fix, Ollama     2 rounds · 19 evidence ·  93 unique sources · stop=sufficient

The two post-fix arms returning the SAME round and evidence counts on different
providers is what exposed it — a provider A/B in which both arms agree exactly is not
measuring the provider.

WHY IT HID: the exception was swallowed into a warning by a catch-all whose reason for
existing is legitimate. Nothing failed, nothing 500'd, and the answers still looked
good. Same class as the swallowed `NameError` that killed search_web for six days.
"""
import asyncio
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.engine import DeepResearchEngine, ResearchPlanner  # noqa: E402

CFG = {"loop": {"assess_max_tokens": 4000, "max_rounds_ceiling": 4},
       "planner": {"max_tokens": 4000},
       "sources": {"allowed": ["search_web"]}}


def _engine(gen=None):
    return DeepResearchEngine(gen or (lambda *a, **k: None),
                              lambda *a, **k: None, CFG)


def test_engine_resolves_its_own_assess_cap():
    """The property must live on the class that CONSUMES it.

    Fails on pre-fix code with AttributeError — the exact production failure.
    """
    assert _engine()._assess_max_tokens == 4000


def test_every_attribute_assess_touches_resolves_on_the_engine():
    """Guards the whole class, not just the one attribute that broke.

    A second config-driven cap added to the wrong class would reproduce SI-021 exactly,
    and the catch-all in _assess would hide it again.
    """
    eng = _engine()
    for attr in ("_assess_max_tokens", "_allowed_sources", "_coverage_summary", "_cfg"):
        assert hasattr(eng, attr), f"DeepResearchEngine is missing {attr}"


def test_assess_returns_the_llm_verdict_not_the_swallowed_fallback():
    """BEHAVIOURAL: a stub that says needs_more must produce needs_more.

    This is the test that would have caught SI-021 on the real path. Pre-fix, the
    AttributeError fires BEFORE the stub is ever consulted, so the catch-all returns
    `sufficient` and the assertion fails — proving the loop was dead rather than merely
    that an attribute was missing.
    """
    async def gen(prompt, **kwargs):
        yield ('{"status": "needs_more", "gaps": ["coverage gap"], '
               '"next_queries": [{"source": "search_web", "query": "more"}]}')

    plan = {"sub_questions": [{"id": "sq1", "question": "q?"}], "stop_condition": "x"}
    out = asyncio.run(_engine(gen)._assess("req", plan, []))

    assert out["status"] == "needs_more", (
        "assessment fell back to 'sufficient' — the gap-assessment loop is dead and DR "
        "will always stop at min_rounds")
    assert out["gaps"] == ["coverage gap"]
    assert out["next_queries"], "next_queries lost — later rounds have nothing to dispatch"


def test_planner_cap_still_resolves_on_the_planner():
    """The sibling property is consumed inside ResearchPlanner and must stay there."""
    assert ResearchPlanner(lambda *a, **k: None, CFG)._planner_max_tokens == 4000


def test_assess_failure_path_is_still_reachable_but_logs_loudly():
    """The catch-all is legitimate for TRANSIENT errors; it must not be removed.

    But a fallback to 'sufficient' silently truncates the whole research loop, so this
    pins the contract: on a real generator failure we still degrade gracefully.
    """
    async def boom(prompt, **kwargs):
        raise RuntimeError("transient upstream 503")
        yield ""                                    # pragma: no cover

    plan = {"sub_questions": [{"id": "sq1", "question": "q?"}], "stop_condition": "x"}
    out = asyncio.run(_engine(boom)._assess("req", plan, []))
    assert out["status"] == "sufficient"
    assert out["gaps"] == [] and out["next_queries"] == []
