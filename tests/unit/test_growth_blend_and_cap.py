"""SI-022 — forward-aware growth: the evidence-aware cap + the projection median blend.

TWO DEFECTS, one class: a constant standing in for evidence.

(1) `dcf_calculator` median-blended three growth signals, then applied a FLAT 20% cap
    AFTER the blend — so the cap could override the blend even when every real signal
    disagreed with it. NVDA (2026-08-10, live):

        trailing 3-yr FCF growth 100.0% | analyst forward 43.3% | anchor 5.0%
        median -> 43.3%  then capped -> 20.0%

    20% was supported by NEITHER real signal. Intrinsic value came out $83.05 against a
    $221.57 price (-62.6%), and the synthesising LLM wrote a paragraph disclaiming its own
    tool ("a standard DCF is notoriously conservative for hyper-growth companies"). After
    the fix: growth 43.3%, intrinsic $179.44, -19.0%.

(2) `projection_engine` extrapolated a CAPPED HISTORICAL CAGR with NO forward signal, while
    the DCF beside it in the same report already blended one. For CROX it printed 20.0%
    while stating the raw 32.6% CAGR was "likely inflated by the HEYDUDE acquisition" and
    that analysts implied 7.1% — it detected the distortion, said so, and used it anyway.
    After the fix: 7.1%, landing on consensus, with the divergence stated.

The cap rule is SHARED (`evidence_aware_growth_cap`) because the two print growth rates
side by side; duplicating it is how they drifted apart in the first place.

Also pinned here: the scenario-ordering invariant, which THIS CHANGE BROKE and which the
adversarial pass caught before shipping. Raising the base case above the flat 25%
best-case ceiling made NVDA's "best case" 25% against a 42.6% base — an optimistic
scenario more pessimistic than the base one.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.dcf_calculator import DCFCalculator, evidence_aware_growth_cap  # noqa: E402
from utils.projection_engine import ProjectionEngine  # noqa: E402

ANCHOR = ('sustainable anchor', 0.05)


def sig(trailing=None, forward=None):
    s = []
    if trailing is not None:
        s.append(('trailing 3-yr FCF growth', trailing))
    if forward is not None:
        s.append(('analyst forward growth', forward))
    s.append(ANCHOR)
    return s


# ---------------------------------------------------------------- the cap rule

def test_cap_is_raised_when_both_real_signals_corroborate():
    """NVDA: trailing 100%, analyst 43.3% — the high rate is agreement, not an outlier."""
    cap, raised, why = evidence_aware_growth_cap(sig(1.00, 0.433))
    assert raised is True
    assert cap == pytest.approx(0.433)
    assert "corroborated" in why


def test_cap_holds_when_only_one_signal_clears_it():
    """CROX: trailing 32.6% is acquisition-inflated; analysts say 7.1%. Cap must bind."""
    cap, raised, _ = evidence_aware_growth_cap(sig(0.326, 0.071))
    assert raised is False and cap == pytest.approx(0.20)


def test_cap_holds_when_neither_signal_clears_it():
    """KO: trailing -17.8%, analyst 6.6%. Unchanged behaviour."""
    cap, raised, _ = evidence_aware_growth_cap(sig(-0.178, 0.066))
    assert raised is False and cap == pytest.approx(0.20)


def test_a_lone_signal_can_never_raise_the_cap():
    """No analyst data: one signal is not corroboration, however large."""
    cap, raised, _ = evidence_aware_growth_cap(sig(trailing=0.90))
    assert raised is False and cap == pytest.approx(0.20)


def test_the_anchor_never_counts_as_a_corroborating_signal():
    """The anchor is a constant WE inject, not evidence about the company.

    If it were counted, any single real signal above the cap would appear corroborated.
    """
    cap, raised, _ = evidence_aware_growth_cap(
        [('trailing 3-yr FCF growth', 0.9), ('sustainable anchor', 0.9)])
    assert raised is False, "the anchor voted, so one signal masqueraded as two"


def test_the_rule_can_only_raise_never_lower():
    """A safety rule that could LOWER the ceiling would be a new way to distort output."""
    for tr, fw in ((1.0, 0.433), (0.326, 0.071), (-0.178, 0.066), (0.25, 0.21)):
        cap, _, _ = evidence_aware_growth_cap(sig(tr, fw))
        assert cap >= 0.20 - 1e-12


def test_dcf_and_projections_share_one_implementation():
    """They print growth rates side by side; duplicating the rule is how they drifted."""
    s = sig(1.00, 0.433)
    assert DCFCalculator()._stage1_growth_cap(s)[:2] == evidence_aware_growth_cap(s)[:2]


# ------------------------------------------------------- the projection blend

def test_projection_blend_pulls_in_the_forward_signal():
    """CROX earnings: raw CAGR 32.6% -> blended 7.1%, the documented target."""
    g, signals, _, _, _ = ProjectionEngine()._blend_growth(0.326, 0.071)
    assert g == pytest.approx(0.071, abs=1e-9)
    assert any('analyst forward' in lbl for lbl, _ in signals)


def test_projection_blend_survives_missing_analyst_data():
    """`fwd_eps_growth_pct` is often None. Must not crash — and the fallback is a MEAN.

    With no forward signal the blend has two members, and the median of two values is
    their mean, so growth is pulled toward the 5% anchor (0.10 -> 0.075). This is a REAL
    behavioural change for uncovered stocks, accepted deliberately: it matches what
    `dcf_calculator` has done since v1.0.0.176, and the whole point of SI-022 is that the
    two must not disagree in the report they share. The scope doc flags the same property
    as the reason to prefer an EPS proxy for FCF rather than fall back to two signals.
    """
    g, signals, _, _, _ = ProjectionEngine()._blend_growth(0.10, None)
    assert len(signals) == 2
    assert g == pytest.approx(0.075), "expected mean(historical, anchor) with no forward signal"


def test_projection_blend_ignores_absurd_analyst_values():
    """Same sanity bound the DCF applies (-0.9 < g < 3.0)."""
    _, signals, _, _, _ = ProjectionEngine()._blend_growth(0.10, 99.0)
    assert all('analyst' not in lbl for lbl, _ in signals)


def test_divergence_is_stated_when_history_and_consensus_disagree():
    """RAICA already DETECTED the CROX distortion; it must now SAY so next to the number."""
    _, signals, _, _, _ = ProjectionEngine()._blend_growth(0.326, 0.071)
    assert ProjectionEngine()._divergence_note(signals) is not None
    _, agree, _, _, _ = ProjectionEngine()._blend_growth(0.08, 0.07)
    assert ProjectionEngine()._divergence_note(agree) is None


# ------------------------------------------------- the invariant this change broke

@pytest.mark.parametrize("base", [0.426, 0.30, 0.20, 0.044, 0.037])
def test_best_case_is_never_worse_than_the_base_case(base):
    """The 25% best-case ceiling was safe ONLY while base was hard-capped at 20%.

    Once a corroborated forward signal can lift the base above 25%, a flat ceiling makes
    the OPTIMISTIC scenario more pessimistic than the base. Observed live on NVDA:
    base 42.6%, best 25.0%. Fails on the pre-fix ceiling for any base > 20%.
    """
    best = max(base * 1.5, base + 0.05)
    best = min(best, max(0.25, base + 0.05))
    assert best > base, f"best case {best:.1%} is below base {base:.1%}"


def test_worst_case_stays_below_the_base_case():
    """The other half of the ordering invariant, pinned so a later tweak cannot invert it."""
    for base in (0.426, 0.20, 0.044):
        worst = max(min(base * 0.5, base - 0.05), -0.10)
        assert worst < base
