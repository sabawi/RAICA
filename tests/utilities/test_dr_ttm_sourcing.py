"""
Deterministic unit tests for the v1.0.0.159 TTM-first sourcing fix in the DR stock-analysis
pipeline (the root cause of the MU P/E 125.49 / DCF $2.37 bug — stale fiscal-year annual data
mixed with the live price).

Proves WITHOUT hitting the network (mocked financials + ticker_info):
  1. Ratios: P/E prefers yfinance trailingPE (TTM) over the stale annual-figure P/E; forward_pe
     is passed through; a staleness note fires when the live-price-vs-annual P/E diverges >20%
     from TTM (the MU case: annual 125.5 vs TTM 21.2 → note emitted).
  2. DCF (updated v1.0.0.167): current FCF prefers the auditable TTM sum of the 4 most-recent quarters
     (OCF+CapEx) from the QUARTERLY cash-flow statement over both the stale annual statement AND
     yfinance's info.freeCashflow (which systematically understates); fcf_source is tagged and a
     directional fcf_note fires when falling back to the annual statement.
  3. Projections: revenue / net income / FCF "current" base prefers TTM (totalRevenue /
     netIncomeToCommon / freeCashflow) and tags current_source.

The end-to-end proof (live server, MU P/E 125 → ~21) is the multi-stock DR re-run; these tests
guard the data-selection logic that makes it deterministic.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from utils.financial_ratio_calculator import FinancialRatioCalculator
from utils.dcf_calculator import DCFCalculator
from utils.projection_engine import ProjectionEngine


def _annual_df(rows: dict, periods=3):
    """Build a yfinance-style statement DataFrame: index=line items, cols=periods (recent first)."""
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")][:periods]
    return pd.DataFrame(rows, index=cols).T


def _quarterly_df(rows: dict, n=4):
    """Build a yfinance-style QUARTERLY statement: index=line items, cols=n most-recent quarters."""
    cols = [pd.Timestamp("2026-03-31") - pd.Timedelta(days=91 * i) for i in range(n)]
    return pd.DataFrame(rows, index=cols).T


# --- Shared mock: the MU case (annual NI $8.54B vs TTM NI $50.47B) ---
INCOME = _annual_df({
    "Net Income":      [8.54e9, 6.0e9, 4.5e9],
    "Total Revenue":   [37.38e9, 30.0e9, 25.0e9],
    "Operating Income": [9.81e9, 7.0e9, 5.0e9],
})
BALANCE = _annual_df({
    "Stockholders Equity":       [54.16e9, 48.0e9, 42.0e9],
    "Cash And Cash Equivalents":  [9.64e9, 8.0e9, 7.0e9],
    "Total Debt":                 [15.0e9, 12.0e9, 10.0e9],
})
CASHFLOW = _annual_df({
    "Operating Cash Flow":  [17.52e9, 14.0e9, 11.0e9],
    "Capital Expenditure":  [-15.86e9, -12.0e9, -9.0e9],
})
# v1.0.0.167 — QUARTERLY cash flow: the 4 recent quarters sum to a TTM FCF (~$7.64B) far above the
# stale annual FCF ($1.66B) — MU's recent quarters are much stronger than its last full fiscal year.
# This is the auditable TTM base the DCF now prefers (over the unreliable info.freeCashflow field).
QUARTERLY_CASHFLOW = _quarterly_df({
    "Operating Cash Flow":  [13.0e9, 12.5e9, 13.0e9, 12.93e9],    # ΣOCF ≈ 51.43e9 (matches info TTM OCF)
    "Capital Expenditure":  [-11.0e9, -11.0e9, -11.0e9, -10.79e9],  # ΣCapEx ≈ -43.79e9
})

# Live market data + yfinance info TTM fields (MU, 2026-07-08)
MARKET = {"current_price": 948.80, "market_cap": 1.071568191488e12, "shares_outstanding": None}
TICKER_INFO = {
    "trailingEps": 44.69, "trailingPE": 21.230701, "forwardPE": 6.3406157,
    "netIncomeToCommon": 50468999168, "freeCashflow": 7639499776,
    "operatingCashflow": 51432001536, "totalRevenue": 90273996800,
    "ebitda": 30.0e9, "sharesOutstanding": 1129393151, "marketCap": 1.071568191488e12,
}


# ---------------------------------------------------------------------------
# 1. Ratios — TTM P/E preferred, forward P/E, staleness note
# ---------------------------------------------------------------------------
def test_ratios_ttm_pe_preferred():
    rc = FinancialRatioCalculator()
    v = rc.calculate_valuation_ratios(INCOME, BALANCE, CASHFLOW, MARKET, TICKER_INFO)
    assert v["pe_ratio"] == 21.230701 or abs(v["pe_ratio"] - 21.23) < 0.01, v
    assert v.get("pe_source") == "TTM (trailingPE)", v
    assert "pe_note" in v, ("staleness note must fire (annual 125.5 vs TTM 21.2 → >20% divergence)", v)
    assert "125.5" in v["pe_note"] and "491" in v["pe_note"], v["pe_note"]
    assert v.get("forward_pe") == 6.3406157, v
    print("PASS test_ratios_ttm_pe_preferred")


def test_ratios_eps_ttm():
    rc = FinancialRatioCalculator()
    v = rc.calculate_valuation_ratios(INCOME, BALANCE, CASHFLOW, MARKET, TICKER_INFO)
    assert abs(v["eps"] - 44.69) < 0.01, v  # TTM trailingEps, NOT 8.54B/1.129B=7.56
    assert "TTM" in v.get("eps_source", ""), v
    print("PASS test_ratios_eps_ttm")


def test_ratios_ps_ttm_revenue():
    rc = FinancialRatioCalculator()
    v = rc.calculate_valuation_ratios(INCOME, BALANCE, CASHFLOW, MARKET, TICKER_INFO)
    # P/S = market_cap / TTM revenue = 1.0715e12 / 9.027e10 ≈ 11.87 (NOT / 37.38e9 = 28.67)
    assert abs(v["ps_ratio"] - 11.87) < 0.1, v
    print("PASS test_ratios_ps_ttm_revenue")


def test_ratios_fallback_when_no_ttm():
    """When ticker_info has no TTM fields, the annual statement is used (no regression)."""
    rc = FinancialRatioCalculator()
    # No ticker_info at all
    v = rc.calculate_valuation_ratios(INCOME, BALANCE, CASHFLOW, MARKET, {})
    # Annual P/E = 948.80 / (8.54e9 / (1.0715e12/948.80))
    shares = MARKET["market_cap"] / MARKET["current_price"]
    eps_annual = 8.54e9 / shares
    pe_annual = MARKET["current_price"] / eps_annual
    assert abs(v["pe_ratio"] - pe_annual) < 0.5, (v, pe_annual)
    assert "TTM" not in v.get("pe_source", ""), v  # fell back to computed/annual
    assert "forward_pe" not in v, v
    print("PASS test_ratios_fallback_when_no_ttm")


# ---------------------------------------------------------------------------
# 2. DCF — TTM FCF preferred + source tag + stale note on fallback
# ---------------------------------------------------------------------------
def test_dcf_ttm_fcf_preferred():
    # v1.0.0.167 — current FCF is the auditable TTM sum from the QUARTERLY cash-flow statement,
    # NOT yfinance's info.freeCashflow (which systematically understates). Quarterly-TTM here (~$7.64B)
    # correctly beats the stale annual FCF ($1.66B).
    dcf = DCFCalculator()
    financials = {
        "cash_flow": {"annual": CASHFLOW, "quarterly": QUARTERLY_CASHFLOW},
        "balance_sheet": {"annual": BALANCE},
        "income_statement": {"annual": INCOME},
        "ticker_info": TICKER_INFO,
    }
    res = dcf.calculate_intrinsic_value("MU", financials, MARKET)
    calc = res.get("calculations", {})
    assert abs(calc["current_fcf"] - 7.64e9) < 5e7, calc  # quarterly-TTM (ΣOCF+ΣCapEx), NOT annual 1.66e9
    assert calc.get("fcf_source") == "TTM (4-quarter sum, cash-flow statement)", calc
    assert "fcf_note" not in res.get("assumptions", {}), "no directional note when quarterly-TTM available"
    print("PASS test_dcf_ttm_fcf_preferred")


def test_dcf_stale_note_on_annual_fallback():
    # v1.0.0.167 — with NO quarterly cash flow, fall back to the annual statement and flag the
    # intrinsic value as directional (a note fires). info.freeCashflow is only a last resort.
    dcf = DCFCalculator()
    financials = {
        "cash_flow": {"annual": CASHFLOW},  # no quarterly
        "balance_sheet": {"annual": BALANCE},
        "income_statement": {"annual": INCOME},
        "ticker_info": TICKER_INFO,
    }
    res = dcf.calculate_intrinsic_value("MU", financials, MARKET)
    calc = res.get("calculations", {})
    assert "annual" in calc.get("fcf_source", ""), calc
    assert abs(calc["current_fcf"] - 1.66e9) < 5e7, calc  # annual OCF-CapEx = 17.52 - 15.86
    assert "fcf_note" in res.get("assumptions", {}), "directional note must fire on annual fallback"
    print("PASS test_dcf_stale_note_on_annual_fallback")


# ---------------------------------------------------------------------------
# 3. Projections — TTM base + current_source tag
# ---------------------------------------------------------------------------
def test_proj_revenue_ttm():
    pe = ProjectionEngine()
    r = pe.generate_revenue_projections(INCOME, TICKER_INFO)
    assert abs(r["current"] - 90273996800) < 1, r  # TTM totalRevenue, NOT 37.38e9
    assert "TTM" in r.get("current_source", ""), r
    print("PASS test_proj_revenue_ttm")


def test_proj_earnings_ttm():
    pe = ProjectionEngine()
    r = pe.generate_earnings_projections(INCOME, TICKER_INFO)
    assert abs(r["current"] - 50468999168) < 1, r  # TTM netIncomeToCommon, NOT 8.54e9
    assert "TTM" in r.get("current_source", ""), r
    print("PASS test_proj_earnings_ttm")


def test_proj_fcf_ttm():
    pe = ProjectionEngine()
    r = pe.generate_fcf_projections(CASHFLOW, TICKER_INFO)
    assert abs(r["current"] - 7639499776) < 1, r  # TTM freeCashflow, NOT 1.66e9
    assert "TTM" in r.get("current_source", ""), r
    print("PASS test_proj_fcf_ttm")


def test_proj_fallback_to_annual_when_no_info():
    pe = ProjectionEngine()
    r = pe.generate_revenue_projections(INCOME, {})
    assert abs(r["current"] - 37.38e9) < 1, r  # annual, no regression
    assert "stale" in r.get("current_source", ""), r
    print("PASS test_proj_fallback_to_annual_when_no_info")


if __name__ == "__main__":
    test_ratios_ttm_pe_preferred()
    test_ratios_eps_ttm()
    test_ratios_ps_ttm_revenue()
    test_ratios_fallback_when_no_ttm()
    test_dcf_ttm_fcf_preferred()
    test_dcf_stale_note_on_annual_fallback()
    test_proj_revenue_ttm()
    test_proj_earnings_ttm()
    test_proj_fcf_ttm()
    test_proj_fallback_to_annual_when_no_info()
    print("\n✅ All TTM-sourcing tests passed")