#!/usr/bin/env python3
"""
DETERMINISTIC baseline regression test (Phase 3a) — no LLM required.

Pins the LEGACY keyword classifier's behavior on the labeled eval corpus: exactly which cases it gets
RIGHT and WRONG vs ground truth. This complements the Phase-0 golden (which pins raw output) by pinning
the *correctness* picture that justifies the convergence — so any future change to `_verify_task_completion`
(or its eventual retirement) is a conscious, reviewed event. Also unit-tests the eval scoring helpers.

The LLM side of the baseline is measured by the live harness tests/utilities/run_intent_eval.py
(not in CI — it makes real model calls). As of the 2026-06-05 baseline: LLM 100% delivery-decision
(32/32) vs LEGACY 71.9% (23/32); legacy fails the 9 cases asserted below.

RUN: venv/bin/python3 -m pytest tests/integration/test_intent_eval_baseline.py -v
"""
import os
import sys
import asyncio

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in (_ROOT, os.path.join(_ROOT, "tests", "data"), os.path.join(_ROOT, "tests", "utilities")):
    if p not in sys.path:
        sys.path.insert(0, p)

from intent_eval_corpus import CASES                         # noqa: E402
from intent_eval_scoring import delivery_kinds, kind_of, score, DELIVERY_KINDS  # noqa: E402

# The 9 cases the LEGACY classifier gets WRONG on the delivery decision (recorded 2026-06-05 baseline).
# This set IS the legacy baseline. A change here means the keyword classifier's behavior moved.
LEGACY_DELIVERY_FAILURES = {
    "plain_poem", "plain_haiku", "plain_draft_tweet",          # plain answers misread as file/publish
    "edge_negation", "edge_howto_email", "edge_howto_publish",  # negation / "how-to" misread as actions
    "edge_printable",                                          # format synonym missed (false negative)
    "mt_thanks", "mt_distractor",                              # multi-turn false positives
    "mt_newx_info_only",                                       # false-positive on the system preamble's "create/generate" keywords
}


# ── scoring helper unit tests (pure, fast) ──────────────────────────────────────────────────────
def test_kind_of_mapping():
    assert kind_of("sandboxed_executor") == "file"
    assert kind_of("secure_email_sender") == "email"
    assert kind_of("social_media_substack_test") == "publish"   # _test suffix + social_media prefix
    assert kind_of("analytical_visualizer") == "image"
    assert kind_of("raica_research_agent") == "raica_research_agent"  # not a delivery kind


def test_delivery_kinds_filters_non_delivery():
    assert delivery_kinds(["sandboxed_executor", "secure_email_sender", "raica_research_agent"]) == {"file", "email"}
    assert delivery_kinds([]) == set()


def test_score():
    assert score(True, {"email"}, True, {"email"}) == {"needs_ok": True, "full_ok": True}
    assert score(True, {"file", "email"}, True, {"email"}) == {"needs_ok": True, "full_ok": False}
    assert score(False, set(), True, {"email"}) == {"needs_ok": False, "full_ok": False}


# ── legacy baseline pin-down (deterministic) ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def legacy_results():
    import fastapi_server_complete as F

    async def run():
        out = {}
        for case in CASES:
            res = await F._verify_task_completion(case["prompt"], [], "", None)
            needs = not res.get("complete", True)
            kinds = delivery_kinds(res.get("missing_tools"))
            out[case["id"]] = {"needs": needs, "kinds": kinds, "case": case}
        return out
    return asyncio.run(run())


def test_legacy_delivery_failures_match_recorded_baseline(legacy_results):
    """The set of cases legacy gets WRONG on the delivery decision must equal the recorded baseline."""
    actual = set()
    for cid, r in legacy_results.items():
        truth = bool(r["case"]["truth_delivery"])
        if bool(r["needs"]) != truth:
            actual.add(cid)
    assert actual == LEGACY_DELIVERY_FAILURES, (
        f"LEGACY BASELINE MOVED:\n  newly_failing = {actual - LEGACY_DELIVERY_FAILURES}\n"
        f"  newly_passing = {LEGACY_DELIVERY_FAILURES - actual}")


def test_legacy_delivery_accuracy_is_baseline(legacy_results):
    n = len(legacy_results)
    correct = sum(1 for r in legacy_results.values()
                  if bool(r["needs"]) == bool(r["case"]["truth_delivery"]))
    # Recorded baseline: 24/34. Guards against silent regression of the legacy path.
    assert (n, correct) == (34, 24), f"legacy delivery-accuracy changed: {correct}/{n} (was 24/34)"


def test_corpus_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in CASES:
        assert isinstance(c["truth_delivery"], bool)
        assert set(c["truth_kinds"]) <= DELIVERY_KINDS, f"{c['id']}: unknown truth kind"
        # ground truth must be self-consistent: kinds present iff delivery needed
        assert bool(c["truth_kinds"]) == c["truth_delivery"], f"{c['id']}: kinds/delivery mismatch"
