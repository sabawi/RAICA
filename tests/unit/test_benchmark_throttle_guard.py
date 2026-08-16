"""Regression (SI-055): a rate-limited benchmark run must not report a CODE regression.

FAILURE THIS PREVENTS
---------------------
Tier-1 runs S1 x3, S3 x3 and S4 x3 over 8 tickers across several search engines. That volume
trips the engines' own rate limiters; the scenarios then return empty, and the harness scored
the emptiness as CODE regressions:

    S1 citation_count      0    (base 13)   REGRESSION  CODE
    S2 dr_completed        False (base True) REGRESSION CODE
    S4 answer_chars        0                 INFO

Measured the same night, on the SAME build:

    23:00-23:30      0 throttle events   6 E2E runs, all correct
    00:00-00:30  1,015 throttle events   benchmark
    00:30-01:00    976 throttle events   benchmark

**The benchmark was failing itself.** That is a measurement-integrity defect in both
directions: a false CODE-REGRESSION blocks a good deploy, and a suite people learn to
distrust is how a REAL regression eventually gets waved through. It also meant no valid
baseline could be captured at all.

The fix is not to excuse failures. It is to report that the run COULD NOT MEASURE:
INCONCLUSIVE, never PASS and never REGRESSION, with the evidence attached, and a refusal to
write such a run into baseline.json.

These tests use synthetic metrics and the archived logs — no LLM calls, no cost.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tests", "benchmark"))

from lib import scoring as S      # noqa: E402
from lib import throttle as TH    # noqa: E402


def _metric(name, value, baseline_value, cls="CODE", direction="higher_better"):
    return {"scenario": "S1_news_citation", "name": name, "cls": cls, "value": value,
            "unit": "n", "direction": direction, "tolerance": 0}


# The exact shape of the failed run: a CODE metric that collapsed to zero.
COLLAPSED = [_metric("citation_count", 0, 13)]
BASELINE = {"S1_news_citation.citation_count": {"value": 13}}


def test_healthy_run_still_reports_a_real_regression():
    """The guard must not become a blanket excuse — with no throttling this MUST fail."""
    env = {"degraded": False, "message": "3 rate-limit response(s)", "throttle_events": 3}
    sc = S.score_run(COLLAPSED, BASELINE, environment=env)
    assert sc["suite"] == S.REGRESSION, "a genuine regression was suppressed"


def test_throttled_run_is_inconclusive_not_a_regression():
    """THE bug: identical metrics, but retrieval was rate-limited into the ground."""
    env = {"degraded": True, "message": "2806 rate-limit responses", "throttle_events": 2806}
    sc = S.score_run(COLLAPSED, BASELINE, environment=env)
    assert sc["suite"] == S.INCONCLUSIVE, (
        f"a run that could not measure reported {sc['suite']!r} — PASS would hide a real "
        f"regression, REGRESSION would block a good deploy"
    )


def test_throttled_run_keeps_the_raw_observations():
    """The per-metric verdicts are evidence and must survive; only the CONCLUSION changes."""
    env = {"degraded": True, "message": "x", "throttle_events": 999}
    sc = S.score_run(COLLAPSED, BASELINE, environment=env)
    row = sc["rows"][0]
    assert row["verdict"] == S.REGRESSION, "the raw observation was rewritten, not just the suite"
    assert row.get("unreliable") is True, "the row is not flagged as unreliable"


def test_render_states_why_and_forbids_baselining():
    """A reader must be told the run cannot be used as a baseline."""
    env = {"degraded": True, "message": "2806 rate-limit responses observed", "throttle_events": 2806}
    text = S.render(S.score_run(COLLAPSED, BASELINE, environment=env))
    assert "INCONCLUSIVE" in text
    assert "2806" in text, "the evidence is not shown to the reader"
    assert "MUST NOT be used as a baseline" in text


# ─────────────────────────────────────────────── the detector itself, on REAL archived logs
def test_detector_separates_the_failed_run_from_healthy_ones():
    """Threshold is derived from measured data, so pin that it actually discriminates."""
    import glob
    counts = {os.path.basename(f): TH.count_since(f, 0)
              for f in glob.glob(os.path.join(ROOT, "logs", "archive", "server_complete_*.log"))}
    if not counts:
        pytest.skip("no archived server logs on this machine")
    worst = max(counts.values())
    # The failed Tier-1 window recorded ~2,800; healthy runs recorded double digits at most.
    if worst > 1000:
        assert TH.assess(worst)[0] is True, "the catastrophic run was not flagged"
    healthy = [c for c in counts.values() if c <= 20]
    for c in healthy:
        assert TH.assess(c)[0] is False, f"a healthy run ({c} events) was flagged as degraded"


def test_threshold_sits_above_heavy_but_usable_runs():
    """Over-triggering would call healthy runs inconclusive — its own way of killing trust."""
    assert TH.assess(99)[0] is False, "a heavy-but-usable run would be called inconclusive"
    assert TH.assess(2806)[0] is True, "the run that measured nothing would be trusted"
