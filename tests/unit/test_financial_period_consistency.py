"""Regression: a financial snapshot must not mix reporting PERIODS or FCF DEFINITIONS.

FAILURES THESE PREVENT
----------------------
Both were found by a user reviewing a real CROX analysis (2026-08-09) and calling the
report internally inconsistent. He was right, and both faults were ours.

**Bug 1 — period mixing.** `calculate_profitability_ratios` took margins from the ANNUAL
income statement while net income, EPS, ROE/ROA and P/E came from TTM, then printed them
as one snapshot with nothing saying so. For CROX that is not a rounding difference — it
flips the sign:

    net_margin from annual 2025 net income  -$81M  =  -2.01%   <- what was reported
    net_margin from TTM     net income +$593M      = +14.63%   <- consistent with the
                                                                  EPS $11.27 and ROE 42%
                                                                  printed beside it

The reviewer's objection — "a -2.01% net margin cannot coexist with a positive TTM EPS
and a 42% ROE" — was exactly right. They could, because they were different periods.

The old code justified this with "no TTM gross/operating field exists in yfinance info".
That premise is FALSE: `grossMargins` / `operatingMargins` / `profitMargins` are all TTM
and all present.

**Bug 2 — FCF definition mixing.** The projection engine used `info['freeCashflow']` as
the TTM base while the statements are OCF+capex. Different formulas, printed side by side
as a trend:

    annual 2025 (OCF 710.4 - capex 51.2)   = $659.2M
    info.freeCashflow                      = $533.9M   -> apparent DECLINE
    4-quarter (OCF 762.6 - capex 58.0)     = $704.6M   -> actually RISING

`info.freeCashflow` implied $228.7M of capex against the $58.0M actually reported. The
analysis described "robust FCF with a 9.7% CAGR" beside a falling number — the reviewer
flagged the contradiction, and the number was the thing that was wrong.

CROX is the fixture because it is the case that exposes this class: a company whose
ANNUAL and TTM net income have OPPOSITE SIGNS. Figures are the real ones from
2026-08-09.
"""
import sys
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.financial_ratio_calculator import FinancialRatioCalculator  # noqa: E402
from utils.projection_engine import ProjectionEngine  # noqa: E402

# --- Real CROX figures, 2026-08-09 -------------------------------------------------
CROX_ANNUAL_INCOME = pd.DataFrame(
    {pd.Timestamp("2025-12-31"): {
        "Total Revenue": 4_041_000_000.0,
        "Gross Profit": 2_357_000_000.0,
        "Operating Income": 888_000_000.0,
        "Net Income": -81_000_000.0,          # ← NEGATIVE on the annual statement
    }}
)
CROX_INFO = {
    "grossMargins": 0.5747,
    "operatingMargins": 0.24221,
    "profitMargins": 0.14635,                 # ← POSITIVE on TTM
    "netIncomeToCommon": 593_424_000,
    "totalRevenue": 4_054_865_920,
    "trailingEps": 11.27,
    "freeCashflow": 533_888_736,              # vendor definition
    "operatingCashflow": 762_600_000,
}
CROX_ANNUAL_CF = pd.DataFrame(
    {pd.Timestamp("2025-12-31"): {
        "Operating Cash Flow": 710_430_000.0,
        "Capital Expenditure": -51_230_000.0,
    }}
)
# 4 quarters summing to OCF 762.6M / capex -58.0M
CROX_QUARTERLY_CF = pd.DataFrame({
    pd.Timestamp("2026-06-30"): {"Operating Cash Flow": 210_000_000.0, "Capital Expenditure": -15_000_000.0},
    pd.Timestamp("2026-03-31"): {"Operating Cash Flow": 180_000_000.0, "Capital Expenditure": -14_000_000.0},
    pd.Timestamp("2025-12-31"): {"Operating Cash Flow": 192_600_000.0, "Capital Expenditure": -14_000_000.0},
    pd.Timestamp("2025-09-30"): {"Operating Cash Flow": 180_000_000.0, "Capital Expenditure": -15_000_000.0},
})
CROX_BALANCE = pd.DataFrame(
    {pd.Timestamp("2025-12-31"): {
        "Total Assets": 4_170_000_000.0,
        "Stockholders Equity": 1_290_000_000.0,
    }}
)


# ============================ Bug 1 — period consistency ============================
def test_net_margin_uses_ttm_not_the_annual_statement():
    """The headline failure: an annual-derived net margin with the wrong SIGN."""
    ratios = FinancialRatioCalculator().calculate_profitability_ratios(
        CROX_ANNUAL_INCOME, CROX_BALANCE, CROX_INFO)

    assert ratios["net_margin"] == pytest.approx(14.635, abs=0.1), (
        f"net_margin is {ratios.get('net_margin')}, expected ~14.64% (TTM). "
        f"-2.01% means it came from the ANNUAL statement while EPS/ROE beside it are TTM."
    )
    assert ratios["net_margin"] > 0, (
        "net margin is NEGATIVE while TTM EPS is +$11.27 — the exact contradiction a "
        "reviewer caught in the CROX report"
    )


def test_every_margin_declares_its_period():
    """A period that is not stated cannot be reconciled by the reader or the LLM."""
    ratios = FinancialRatioCalculator().calculate_profitability_ratios(
        CROX_ANNUAL_INCOME, CROX_BALANCE, CROX_INFO)
    for key in ("gross_margin", "operating_margin", "net_margin"):
        assert f"{key}_period" in ratios, f"{key} carries no period label"
        assert ratios[f"{key}_period"] == "TTM"


def test_margins_are_consistent_with_the_returns_printed_beside_them():
    """net margin and ROE must derive from the SAME net income."""
    ratios = FinancialRatioCalculator().calculate_profitability_ratios(
        CROX_ANNUAL_INCOME, CROX_BALANCE, CROX_INFO)
    implied_ni = ratios["net_margin"] / 100 * CROX_INFO["totalRevenue"]
    assert implied_ni == pytest.approx(CROX_INFO["netIncomeToCommon"], rel=0.02), (
        f"net_margin implies net income ${implied_ni/1e6:.0f}M but ROE/EPS use "
        f"${CROX_INFO['netIncomeToCommon']/1e6:.0f}M — different periods in one snapshot"
    )


def test_formatted_output_shows_the_period():
    calc = FinancialRatioCalculator()
    text = calc._format_profitability_ratios(
        calc.calculate_profitability_ratios(CROX_ANNUAL_INCOME, CROX_BALANCE, CROX_INFO))
    assert "[TTM]" in text, "the rendered report does not state the margin period"


def test_annual_fallback_when_ttm_margin_missing():
    """No TTM field -> annual, and the label must SAY annual. No silent substitution."""
    ratios = FinancialRatioCalculator().calculate_profitability_ratios(
        CROX_ANNUAL_INCOME, CROX_BALANCE,
        {k: v for k, v in CROX_INFO.items() if k != "profitMargins"})
    assert ratios["net_margin"] == pytest.approx(-2.005, abs=0.05)
    assert "annual" in ratios["net_margin_period"]


def test_bank_sentinel_zero_margin_is_not_treated_as_a_real_zero():
    """yfinance reports grossMargins 0.0 for banks (JPM). That is 'not meaningful'.

    Taking it literally would print a 0.00% gross margin as though measured.
    """
    ratios = FinancialRatioCalculator().calculate_profitability_ratios(
        CROX_ANNUAL_INCOME, CROX_BALANCE, dict(CROX_INFO, grossMargins=0.0))
    assert ratios["gross_margin"] == pytest.approx(58.33, abs=0.1)
    assert "annual" in ratios["gross_margin_period"]


# ============================ Bug 2 — FCF definition ============================
def test_ttm_fcf_uses_the_same_formula_as_the_annual_figure():
    """OCF+capex on both sides, or the comparison is not a comparison."""
    proj = ProjectionEngine().generate_fcf_projections(
        CROX_ANNUAL_CF, CROX_INFO, CROX_QUARTERLY_CF)

    assert proj["current"] == pytest.approx(704_600_000, rel=0.01), (
        f"TTM FCF is ${proj.get('current', 0)/1e6:.1f}M; expected ~$704.6M "
        f"(4-quarter OCF+capex). $533.9M means info.freeCashflow was used, which uses a "
        f"DIFFERENT capex definition and manufactures a decline."
    )
    assert "same formula as annual" in proj["current_source"]


def test_ttm_fcf_does_not_invent_a_decline():
    """The reported trend must match reality: CROX FCF is RISING."""
    proj = ProjectionEngine().generate_fcf_projections(
        CROX_ANNUAL_CF, CROX_INFO, CROX_QUARTERLY_CF)
    annual_fcf = 710_430_000 - 51_230_000        # $659.2M
    assert proj["current"] > annual_fcf, (
        f"TTM FCF ${proj['current']/1e6:.1f}M <= annual ${annual_fcf/1e6:.1f}M — this is "
        f"the phantom decline that made the analysis contradict itself"
    )


def test_falls_back_to_vendor_fcf_but_labels_the_definition():
    """Fewer than 4 quarters -> vendor field, with the mismatch STATED not hidden."""
    proj = ProjectionEngine().generate_fcf_projections(
        CROX_ANNUAL_CF, CROX_INFO, CROX_QUARTERLY_CF.iloc[:, :2])
    assert proj["current"] == pytest.approx(533_888_736, rel=0.01)
    assert "NOT comparable" in proj["current_source"], (
        "fell back to the vendor definition without warning that it is not comparable "
        "to the annual figures printed beside it"
    )


def test_partial_quarters_never_produce_an_understated_ttm():
    """A 2-quarter sum would understate TTM and reintroduce the bug."""
    assert ProjectionEngine()._ttm_fcf_from_quarters(CROX_QUARTERLY_CF.iloc[:, :3]) is None
    assert ProjectionEngine()._ttm_fcf_from_quarters(None) is None
