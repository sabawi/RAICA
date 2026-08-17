"""The benchmark must retain enough to answer 'is this delta bigger than the noise?'

FAILURE THIS PREVENTS
---------------------
An A/B is only meaningful if a between-arm delta can be compared against the within-arm
spread. Two things made that impossible after the fact:

  1. `median_runs` computed the per-repeat values and then discarded them, keeping only the
     median. A saved scorecard held one number per metric and nothing about how much it
     moved between repeats.
  2. `scorecard.json` is overwritten by the next run, so keeping an arm depended on
     remembering to `cp` it by hand.

Measured 2026-08-16: a GLM-vs-Flash comparison reported `unique_sources` +46.3% on one pair
of runs and ~0% at n=4. Deciding which of those was signal required the per-repeat numbers,
and they no longer existed -- the raw runs had been overwritten. The A/B could not even be
re-analysed, only re-run, at ~40 minutes per arm.

This is the repo's own standing rule (docs/RESPONSE_QUALITY_BASELINE.md: RETAIN artifacts)
being enforced by a test instead of by memory.
"""
import os
import sys

BENCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmark")
sys.path.insert(0, BENCH)

from lib import scoring as S  # noqa: E402


def _runs(values, scenario="S1", name="citation_count"):
    """N runs of one metric — the shape median_runs consumes."""
    return [[{"scenario": scenario, "name": name, "cls": "CODE", "value": v,
              "unit": "count", "direction": "higher_better", "tolerance": 2}]
            for v in values]


def test_per_repeat_samples_survive_the_median():
    """FAILS PRE-FIX: only the median was kept, so the spread was unrecoverable."""
    out = S.median_runs(_runs([10, 14, 18]))
    assert len(out) == 1
    metric = out[0]
    assert metric["value"] == 14, "median itself must be unchanged"
    assert metric.get("samples") == [10, 14, 18], "per-repeat values were discarded"
    assert metric.get("n") == 3


def test_the_spread_is_recoverable_so_a_delta_can_be_judged():
    """THE point of retaining them: a +46% delta against a spread this wide is noise."""
    arm = S.median_runs(_runs([108, 158, 112]))[0]
    lo, hi = min(arm["samples"]), max(arm["samples"])
    assert hi - lo == 50, "cannot compute within-arm spread from a saved run"


def test_a_single_run_still_records_its_sample():
    """n=1 must be visibly n=1, not silently indistinguishable from a converged n=5."""
    metric = S.median_runs(_runs([7]))[0]
    assert metric["samples"] == [7]
    assert metric["n"] == 1


def test_boolean_metrics_keep_their_samples_too():
    """Majority-vote metrics hide disagreement worst: 2-of-3 True reads as plain True."""
    metric = S.median_runs(_runs([True, True, False], name="dr_completed"))[0]
    assert metric["value"] is True
    assert metric["samples"] == [True, True, False], "a 2/3 flake is invisible without these"
    assert metric["n"] == 3


def test_metrics_with_no_value_do_not_fabricate_samples():
    """A metric that never produced a value must not look like it did."""
    metric = S.median_runs(_runs([None, None]))[0]
    assert metric["value"] is None
    assert metric["samples"] == []
    assert metric["n"] == 0


def test_the_runner_archives_every_run():
    """FAILS PRE-FIX: scorecard.json was the only output and the next run overwrote it."""
    src = open(os.path.join(BENCH, "run_benchmark.py")).read()
    assert '"runs"' in src, "no per-run archive directory"
    i_score = src.index('"scorecard.json"')
    i_arch = src.index('"runs"', i_score)
    assert i_arch > i_score, "archive must be written alongside the scorecard"
    assert "--label" in src, "no way to tag an A/B arm"
