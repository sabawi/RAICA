"""The degradation gate must key on retrieval COLLAPSING, not on a throttle count.

FAILURE THIS PREVENTS
---------------------
v1.0.0.291 declared a run unmeasurable whenever throttle crossed a single threshold (150).
It produced FOUR false INCONCLUSIVEs on runs whose metrics were healthy. The clearest was
v1.0.0.297, at 164 events:

    33 of 33 rows PASS
    citation_count samples [14, 14, 14]  against a baseline of 13   <- zero variance

The guard's stated premise was "an empty result is indistinguishable from a regression".
Nothing was empty. The premise was refuted by the run's own data.

A false INCONCLUSIVE is not harmless. It blocks a good deploy, and it teaches the reader to
discount the suite -- which is how a REAL regression eventually gets waved through.

THE TRUTH TABLE THIS PINS
-------------------------
    throttle          metrics      verdict        why
    ---------------------------------------------------------------------------------
    above CEILING     anything     INCONCLUSIVE   count alone is disqualifying
    elevated          collapsed    INCONCLUSIVE   cannot attribute cause -- honest "unknown"
    elevated          healthy      scored         noisy is not broken
    normal            collapsed    REGRESSION     no environmental excuse: this is the bug
    normal            healthy      scored         the ordinary case

The bottom-left cell is the one the old rule could not express at all.
"""
import os
import sys

BENCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "benchmark")
sys.path.insert(0, BENCH)

from lib import scoring as S  # noqa: E402
from lib import throttle as TH  # noqa: E402


def _m(name, value, scenario="S1", cls="CODE", direction="higher_better"):
    return {"scenario": scenario, "name": name, "cls": cls, "value": value,
            "unit": "count", "direction": direction, "tolerance": 2}


HEALTHY = [_m("citation_count", 14), _m("answer_chars", 50000)]
COLLAPSED = [_m("citation_count", 0), _m("answer_chars", 0)]
BASE = {S.key("S1", "citation_count"): {"value": 13},
        S.key("S1", "answer_chars"): {"value": 48000}}


def _env(events):
    ceiling, msg = TH.assess(events)
    return {"elevated": TH.is_elevated(events), "ceiling_exceeded": ceiling,
            "message": msg, "throttle_events": events}


# ───────────────────────────────────────────────── the false alarm that motivated this
def test_elevated_throttle_with_healthy_metrics_is_NOT_inconclusive():
    """FAILS PRE-FIX: 164 > 150 made this INCONCLUSIVE despite 33/33 rows PASS."""
    sc = S.score_run(HEALTHY, BASE, environment=_env(164))
    assert sc["suite"] != S.INCONCLUSIVE, (
        "a run with healthy metrics was called unmeasurable because traffic was noisy")
    assert sc["suite"] == S.PASS


def test_the_real_v297_throttle_level_scores_normally():
    """Pin the exact observed count, so a future threshold edit cannot silently undo this."""
    assert S.score_run(HEALTHY, BASE, environment=_env(164))["suite"] == S.PASS
    assert S.score_run(HEALTHY, BASE, environment=_env(226))["suite"] == S.PASS


# ───────────────────────────────────────────────── the cases that MUST still trigger
def test_catastrophic_throttle_is_inconclusive_even_if_metrics_look_fine():
    """At 2,806 events nothing is trustworthy — including numbers that look plausible."""
    sc = S.score_run(HEALTHY, BASE, environment=_env(2806))
    assert sc["suite"] == S.INCONCLUSIVE
    assert sc["environment"]["ceiling_exceeded"] is True


def test_elevated_throttle_WITH_collapse_is_inconclusive():
    """The genuine can't-tell case: heavy traffic AND the metrics fell to nothing."""
    sc = S.score_run(COLLAPSED, BASE, environment=_env(164))
    assert sc["suite"] == S.INCONCLUSIVE
    assert sc["environment"]["collapsed"] is True
    assert sc["environment"]["collapse_reasons"], "must say WHICH metrics collapsed"


def test_collapse_WITHOUT_heavy_traffic_is_a_REGRESSION_not_an_excuse():
    """THE cell the old rule could not express.

    citation_count 13 -> 0 with only 3 throttle events has no environmental explanation.
    Reporting that as INCONCLUSIVE would hand a real bug a free pass.
    """
    sc = S.score_run(COLLAPSED, BASE, environment=_env(3))
    assert sc["suite"] == S.REGRESSION, "a genuine collapse was excused as environmental"


# ───────────────────────────────────────────────── the collapse detector itself
def test_collapse_means_fell_to_zero_not_merely_worse():
    """'Worse than baseline' is an ordinary regression. Collapse is the retrieval-died shape."""
    rows = [{**_m("citation_count", 6), "baseline": 13}]
    collapsed, _ = S.retrieval_collapsed(rows)
    assert collapsed is False, "a normal drop was misread as retrieval dying"

    rows = [{**_m("citation_count", 0), "baseline": 13}]
    collapsed, reasons = S.retrieval_collapsed(rows)
    assert collapsed is True and "13 -> 0" in reasons[0]


def test_a_boolean_flipping_true_to_false_counts_as_collapse():
    """dr_completed True -> False was part of the real failed run's signature."""
    rows = [{**_m("dr_completed", False), "baseline": True}]
    collapsed, reasons = S.retrieval_collapsed(rows)
    assert collapsed is True and "True -> False" in reasons[0]


def test_a_metric_with_no_baseline_cannot_be_judged_collapsed():
    """Without a baseline, zero is indistinguishable from a legitimately-zero measurement."""
    rows = [{**_m("unique_sources", 0), "baseline": None}]
    assert S.retrieval_collapsed(rows)[0] is False


def test_a_legitimately_zero_baseline_is_not_a_collapse():
    """low_cred_sources has baseline 0 and value 0 — that is the GOOD outcome."""
    rows = [{**_m("low_cred_sources", 0), "baseline": 0}]
    assert S.retrieval_collapsed(rows)[0] is False


def test_lower_better_metrics_are_not_collapse_candidates():
    """A latency of 0 would be suspicious, but it is not 'retrieval returned nothing'."""
    rows = [{**_m("latency_s", 0, cls="PERF", direction="lower_better"), "baseline": 20}]
    assert S.retrieval_collapsed(rows)[0] is False


def test_the_detector_uses_no_hardcoded_metric_names():
    """A name list here could not track metrics defined in the scenario files.

    A metric invented tomorrow must be covered with no edit to the detector.
    """
    rows = [{**_m("some_brand_new_metric_2099", 0), "baseline": 42}]
    assert S.retrieval_collapsed(rows)[0] is True


# ───────────────────────────────────────────────── the two levels stay ordered
def test_elevated_sits_below_the_ceiling():
    assert TH.ELEVATED_AT < TH.CEILING


def test_the_ceiling_sits_between_the_measured_good_and_bad_runs():
    """Derived, not chosen: usable at 226, nothing measurable at 2,806."""
    assert 226 < TH.CEILING < 2806
    assert TH.is_elevated(164) is True, "164 must still be REPORTED as elevated"
    assert TH.assess(164)[0] is False, "164 must not be disqualifying on its own"


# ═══════════════════════════════════════════════════════════════════════════════════════
# v1.0.0.299 — a harness that gives up early must not blame the system it was measuring
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# S2's client timed out at exactly 700.0s. The server had FINISHED: "Deep research complete:
# 4 rounds, 53 evidence items", a verified 107,956-byte %PDF-1.7 and a 72,405-byte HTML on
# disk, written ~30s after the client stopped listening. The suite reported REGRESSION on
# seven rows for a run that produced correct output.

def test_an_unmeasured_metric_is_not_a_regression():
    """FAILS PRE-FIX: verdict_for returned REGRESSION for value None while its own comment
    said 'the run couldn't measure it'."""
    assert S.verdict_for(None, 42.4, cls="PERF", direction="lower_better",
                         tolerance=40) == S.UNMEASURED


def test_a_run_with_holes_is_inconclusive_not_pass():
    """'We did not measure this' is not evidence of health."""
    rows = [_m("dr_synthesize_s", None, scenario="S2", cls="PERF", direction="lower_better")]
    base = {S.key("S2", "dr_synthesize_s"): {"value": 42.4}}
    sc = S.score_run(rows, base, environment=_env(3))
    assert sc["suite"] == S.INCONCLUSIVE
    assert "S2.dr_synthesize_s" in sc["environment"]["unmeasured"]


def test_a_real_measured_regression_still_outranks_an_unmeasured_row():
    """A hole must never MASK a genuine failure elsewhere in the run."""
    rows = [_m("dr_synthesize_s", None, scenario="S2", cls="PERF", direction="lower_better"),
            _m("citation_count", 2)]
    base = {S.key("S2", "dr_synthesize_s"): {"value": 42.4},
            S.key("S1", "citation_count"): {"value": 13}}
    assert S.score_run(rows, base, environment=_env(3))["suite"] == S.REGRESSION


def test_a_failed_request_nulls_the_metrics_but_keeps_the_latency():
    """The wait itself is a real observation — it is what makes a timeout visible."""
    sys.path.insert(0, os.path.join(BENCH, "lib"))
    from lib import raica_client as RC
    metrics = [_m("dr_completed", False, scenario="S2"),
               _m("attachment_count", 0, scenario="S2"),
               _m("dr_latency_s", 700.1, scenario="S2", cls="PERF", direction="lower_better")]
    out = RC.unmeasured_if_no_response({"ok": False}, metrics)
    by = {m["name"]: m["value"] for m in out}
    assert by["dr_completed"] is None, "a timed-out request still reported a False result"
    assert by["attachment_count"] is None
    assert by["dr_latency_s"] == 700.1, "the observed wait was discarded"


def test_a_successful_request_is_passed_through_untouched():
    """CONTROL: the guard must not null anything on a normal run."""
    from lib import raica_client as RC
    metrics = [_m("dr_completed", True, scenario="S2")]
    assert RC.unmeasured_if_no_response({"ok": True}, metrics) == metrics


def test_must_equal_metrics_count_as_collapse():
    """FAILS PRE-FIX: the detector filtered to higher_better, so dr_completed True->False
    and attachment_count 2->0 -- the very signature quoted in its own docstring -- were
    invisible to it."""
    rows = [{**_m("dr_completed", False, scenario="S2", direction="must_equal"),
             "baseline": True},
            {**_m("attachment_count", 0, scenario="S2", direction="must_equal"),
             "baseline": 2}]
    collapsed, reasons = S.retrieval_collapsed(rows)
    assert collapsed is True
    assert len(reasons) == 2, f"expected both rows flagged, got {reasons}"
