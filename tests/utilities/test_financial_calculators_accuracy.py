"""
Deterministic unit tests for the v1.0.0.160 financial-data quality fixes in the RAICA stock-analysis
pipeline. These guard the root-cause fixes for the bugs found in the 5-stock @Ask audit
(META/AMZN/GOOGL/ORCL/MU):

  1. P/B prefers yfinance ``priceToBook`` (TTM) over stale annual equity; fallback emits a note.
  2. Dividend yield is computed authoritatively as ``dividendRate / current_price`` — the MU "6.00%"
     mis-formatting (yfinance dividendYield mis-populated as 0.06) is gone.
  3. DCF negative-intrinsic guard: when net debt > enterprise value, ``negative_equity`` is flagged and
     NO >100% "downside" is emitted (the ORCL "137% downside" bug).
  4. Projection SOURCE blocks render the raw historical CAGR + capped projected rate and are labeled
     "Historical-CAGR Extrapolation — not analyst consensus".
  5. ROIC uses NOPAT (operating income × (1−tax)), not net income (the META 20.08% vs 31.38% bug).
  6. ``calculate_all_ratios`` consumes the QUARTERLY balance sheet (most-recent) instead of stale annual.
  7. Interest coverage uses TTM (4-quarter sum) and emits a note when the denominator is negligible
     (the GOOGL 175x bug).

All tests are offline (mocked DataFrames + ticker_info dicts) — no network.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from utils.financial_ratio_calculator import FinancialRatioCalculator
from utils.dcf_calculator import DCFCalculator
from utils.projection_engine import ProjectionEngine
from user_tools.comprehensive_stock_analyzer import ComprehensiveStockAnalyzerTool


def _annual_df(rows: dict, periods=3):
    """yfinance-style annual statement: index=line items, cols=periods (recent first)."""
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")][:periods]
    return pd.DataFrame(rows, index=cols).T


def _qdf(rows: dict, n=4):
    """yfinance-style QUARTERLY statement: cols = most-recent n quarters (recent first)."""
    base = pd.Timestamp("2025-12-31")
    cols = [base - pd.Timedelta(days=91 * i) for i in range(n)]
    return pd.DataFrame(rows, index=cols).T


# ---------------------------------------------------------------------------
# 1. P/B — priceToBook preferred; fallback uses balance-sheet equity + note
# ---------------------------------------------------------------------------
def test_pb_prefers_priceToBook():
    rc = FinancialRatioCalculator()
    inc = _annual_df({"Net Income": [10e9], "Total Revenue": [50e9]})
    bal = _annual_df({"Stockholders Equity": [100e9], "Total Debt": [10e9],
                      "Cash And Cash Equivalents": [5e9]})
    cf = _annual_df({"Operating Cash Flow": [15e9], "Capital Expenditure": [-5e9]})
    market = {"current_price": 100.0, "market_cap": 1e11, "shares_outstanding": 1e9}
    info = {"priceToBook": 10.9, "sharesOutstanding": 1e9, "trailingPE": 20, "trailingEps": 5,
            "marketCap": 1e11}
    v = rc.calculate_valuation_ratios(inc, bal, cf, market, info)
    assert abs(v["pb_ratio"] - 10.9) < 0.01, v
    assert v.get("pb_source") == "TTM (info.priceToBook)", v
    assert "pb_note" not in v, v
    print("PASS test_pb_prefers_priceToBook")


def test_pb_fallback_equity_with_note():
    rc = FinancialRatioCalculator()
    inc = _annual_df({"Net Income": [10e9], "Total Revenue": [50e9]})
    bal = _annual_df({"Stockholders Equity": [54.16e9], "Total Debt": [15e9],
                      "Cash And Cash Equivalents": [9.64e9]})
    cf = _annual_df({"Operating Cash Flow": [17.52e9], "Capital Expenditure": [-15.86e9]})
    market = {"current_price": 948.80, "market_cap": 1.071568191488e12, "shares_outstanding": None}
    info = {"sharesOutstanding": 1129393151, "marketCap": 1.071568191488e12}  # no priceToBook
    v = rc.calculate_valuation_ratios(inc, bal, cf, market, info)
    # bvps = 54.16e9 / 1.129e9 ≈ 47.97 → P/B = 948.80 / 47.97 ≈ 19.78
    assert abs(v["pb_ratio"] - 19.78) < 0.5, v
    assert "pb_note" in v, v
    print("PASS test_pb_fallback_equity_with_note")


# ---------------------------------------------------------------------------
# 2. Dividend yield — authoritative dividendRate / price (MU "6.00%" → "0.06%")
# ---------------------------------------------------------------------------
def test_dividend_yield_authoritative_from_rate():
    ana = ComprehensiveStockAnalyzerTool()
    # MU: dividendRate 0.56, price 948.80 → 0.000590 → "0.06%". The authoritative rate/price path must
    # win regardless of dividendYield. (Under yfinance 0.2.65, dividendYield 0.06 also = 0.06% — a
    # percentage number — but this test pins the rate/price computation, not the fallback.)
    out = ana._format_dividend_yield({"dividendRate": 0.56, "currentPrice": 948.80,
                                      "dividendYield": 0.06})
    assert "0.06%" in out, out
    assert "6.00%" not in out, out             # the old heuristic's wrong output
    assert "dividendRate / price" in out, out
    print("PASS test_dividend_yield_authoritative_from_rate")


def test_dividend_yield_fallback_yfinance_percent_number():
    ana = ComprehensiveStockAnalyzerTool()
    # No dividendRate → fall back to yfinance's dividendYield. Verified empirically against the PINNED
    # yfinance 0.2.65: dividendYield is a PERCENTAGE NUMBER (MU 0.06 → 0.06%, VZ 6.67 → 6.67%), NOT a
    # 0..1 fraction. The fallback must render it DIRECTLY as a percent, never apply :.2% (which ×100
    # and printed "6.00%"/"667.00%"). See v1.0.0.162.
    out = ana._format_dividend_yield({"dividendYield": 0.06})    # MU-style 0.06% yield
    assert "0.06%" in out, out
    assert "6.00%" not in out, out                               # the ×100 bug's wrong output
    out2 = ana._format_dividend_yield({"dividendYield": 6.67})   # VZ-style 6.67% yield
    assert "6.67%" in out2, out2
    assert "667" not in out2, out2                               # the ×100 bug would print 667.00%
    print("PASS test_dividend_yield_fallback_yfinance_percent_number")


def test_dividend_yield_high_yield_sanity_note():
    ana = ComprehensiveStockAnalyzerTool()
    # 10/50 = 20% → unusual; sanity note must fire (not a silent cap)
    out = ana._format_dividend_yield({"dividendRate": 10.0, "currentPrice": 50.0})
    assert "20.00%" in out, out
    assert "verify" in out.lower(), out
    print("PASS test_dividend_yield_high_yield_sanity_note")


# ---------------------------------------------------------------------------
# 3. DCF — negative-intrinsic guard (no >100% "downside")
# ---------------------------------------------------------------------------
def test_dcf_negative_equity_guard():
    dcf = DCFCalculator()
    # Construct a name where net debt > enterprise value (high debt, low FCF) → negative equity value.
    inc = _annual_df({"Operating Income": [12e9, 11e9, 10e9], "Net Income": [8e9, 7e9, 6e9],
                      "Pretax Income": [10e9, 9e9, 8e9], "Tax Provision": [2e9, 1.8e9, 1.6e9],
                      "Interest Expense": [2e9, 1.9e9, 1.8e9], "Total Revenue": [40e9, 38e9, 36e9]})
    bal = _annual_df({"Total Debt": [80e9, 75e9, 70e9], "Cash And Cash Equivalents": [10e9, 9e9, 8e9],
                      "Stockholders Equity": [5e9, 4e9, 3e9], "Total Assets": [60e9, 58e9, 56e9]})
    cf = _annual_df({"Operating Cash Flow": [10e9, 9e9, 8e9], "Capital Expenditure": [-8e9, -7e9, -6e9]})
    info = {"freeCashflow": 2e9, "sharesOutstanding": 2.8e9, "marketCap": 1e11, "beta": 1.0}
    market = {"current_price": 350.0, "market_cap": 1e11, "sharesOutstanding": 2.8e9, "beta": 1.0}
    financials = {"cash_flow": {"annual": cf}, "balance_sheet": {"annual": bal},
                  "income_statement": {"annual": inc}, "ticker_info": info}
    res = dcf.calculate_intrinsic_value("TEST", financials, market)
    assert res.get("negative_equity") is True, res
    assert res.get("intrinsic_value") is None, res
    assert res.get("upside_downside") is None, res      # no misleading >100% downside value
    formatted = dcf.format_dcf_for_llm(res, "TEST")
    assert "N/M" in formatted, formatted
    assert "DOWNSIDE" not in formatted, formatted        # no >100% downside
    assert "RAICA MODEL ESTIMATE" in formatted, formatted  # labeled as model estimate
    print("PASS test_dcf_negative_equity_guard")


def test_dcf_marketable_securities_netted():
    """Cash + short/long-term investments are all netted against debt (META net-cash fix)."""
    dcf = DCFCalculator()
    inc = _annual_df({"Operating Income": [120e9], "Net Income": [140e9], "Pretax Income": [160e9],
                      "Tax Provision": [32e9], "Interest Expense": [1e9], "Total Revenue": [160e9]})
    bal = _annual_df({"Total Debt": [30e9], "Cash And Cash Equivalents": [20e9],
                      "Short Term Investments": [40e9], "Long Term Investments": [30e9],
                      "Stockholders Equity": [200e9], "Total Assets": [320e9]})
    cf = _annual_df({"Operating Cash Flow": [120e9], "Capital Expenditure": [-40e9]})
    info = {"freeCashflow": 80e9, "sharesOutstanding": 2.5e9, "marketCap": 1.3e12, "beta": 1.1}
    market = {"current_price": 520.0, "market_cap": 1.3e12, "sharesOutstanding": 2.5e9, "beta": 1.1}
    financials = {"cash_flow": {"annual": cf}, "balance_sheet": {"annual": bal},
                  "income_statement": {"annual": inc}, "ticker_info": info}
    res = dcf.calculate_intrinsic_value("TEST", financials, market)
    calc = res.get("calculations", {})
    # cash_and_securities = 20 + 40 + 30 = 90e9; net_debt = 30 - 90 = -60e9 (net cash)
    assert abs(calc.get("cash_and_securities", 0) - 90e9) < 1e6, calc
    assert abs(calc.get("net_debt", 0) - (-60e9)) < 1e6, calc
    print("PASS test_dcf_marketable_securities_netted")


# ---------------------------------------------------------------------------
# 4. Projections — historical CAGR rendered + "not analyst consensus" label
# ---------------------------------------------------------------------------
def test_projection_renders_historical_cagr_and_label():
    pe = ProjectionEngine()
    inc = _annual_df({"Total Revenue": [37.38e9, 30e9, 25e9], "Net Income": [8.54e9, 6e9, 4.5e9]})
    cf = _annual_df({"Operating Cash Flow": [17.52e9, 14e9, 11e9], "Capital Expenditure": [-15.86e9, -12e9, -9e9]})
    info = {"totalRevenue": 90.27e9, "netIncomeToCommon": 50.47e9, "freeCashflow": 7.64e9}
    projections = pe.generate_projections("MU", {"income_statement": {"annual": inc},
                                                 "cash_flow": {"annual": cf}, "ticker_info": info})
    formatted = pe.format_projections_for_llm(projections, "MU")
    assert "Historical CAGR" in formatted, formatted
    assert "NOT analyst consensus" in formatted, formatted
    assert "Historical-CAGR Extrapolation" in formatted, formatted  # relabeled title
    print("PASS test_projection_renders_historical_cagr_and_label")


# ---------------------------------------------------------------------------
# 5. ROIC uses NOPAT (operating income × (1−tax)), not net income
# ---------------------------------------------------------------------------
def test_roic_uses_nopat_not_net_income():
    rc = FinancialRatioCalculator()
    # NOPAT = 15e9 × (1 − 0.2) = 12e9; invested capital = 50 + 50 = 100e9 → ROIC = 12.0%
    # (net-income-based ROIC would be 10/100 = 10.0% — the old understated value)
    inc = _annual_df({"Net Income": [10e9], "Operating Income": [15e9], "Pretax Income": [12.5e9],
                      "Tax Provision": [2.5e9], "Total Revenue": [50e9], "Gross Profit": [30e9]})
    bal = _annual_df({"Stockholders Equity": [50e9], "Total Debt": [50e9], "Total Assets": [100e9]})
    qinc = _qdf({"Operating Income": [15e9]}, 1)  # TTM operating income = 15e9
    info = {"netIncomeToCommon": 10e9}
    r = rc.calculate_profitability_ratios(inc, bal, info, qinc)
    assert "roic" in r, r
    assert abs(r["roic"] - 12.0) < 0.1, r           # NOPAT-based, not 10.0
    assert "NOPAT" in r.get("roic_basis", ""), r
    print("PASS test_roic_uses_nopat_not_net_income")


# ---------------------------------------------------------------------------
# 6. calculate_all_ratios consumes the QUARTERLY balance sheet
# ---------------------------------------------------------------------------
def test_calculate_all_ratios_uses_quarterly_balance():
    rc = FinancialRatioCalculator()
    annual_bal = _annual_df({"Stockholders Equity": [100e9, 90e9, 80e9], "Total Assets": [200e9, 190e9, 180e9],
                             "Total Debt": [10e9, 9e9, 8e9], "Cash And Cash Equivalents": [5e9, 4e9, 3e9],
                             "Current Assets": [60e9, 55e9, 50e9], "Current Liabilities": [30e9, 28e9, 26e9],
                             "Inventory": [5e9, 4e9, 3e9], "Accounts Receivable": [10e9, 9e9, 8e9]})
    q_bal = _qdf({"Stockholders Equity": [50e9, 48e9], "Total Assets": [120e9, 115e9],
                  "Total Debt": [12e9, 11e9], "Cash And Cash Equivalents": [6e9, 5e9],
                  "Current Assets": [70e9, 65e9], "Current Liabilities": [35e9, 33e9],
                  "Inventory": [6e9, 5e9], "Accounts Receivable": [12e9, 11e9]}, 2)
    financials = {"income_statement": {"annual": _annual_df({"Total Revenue": [50e9], "Net Income": [10e9],
                                                            "Operating Income": [12e9], "Gross Profit": [30e9]})},
                  "balance_sheet": {"annual": annual_bal, "quarterly": q_bal},
                  "cash_flow": {"annual": _annual_df({"Operating Cash Flow": [15e9], "Capital Expenditure": [-5e9]})},
                  "ticker_info": {"sharesOutstanding": 1e9, "trailingPE": 20, "trailingEps": 5,
                                  "marketCap": 1e11, "netIncomeToCommon": 10e9}}
    market = {"current_price": 100.0, "market_cap": 1e11, "shares_outstanding": 1e9}
    ratios = rc.calculate_all_ratios(financials, market)
    pb = ratios["valuation"].get("pb_ratio")
    # Quarterly equity 50e9 / 1e9 shares = 50 bvps → P/B = 100/50 = 2.0
    # (annual equity 100e9 would give P/B = 1.0 — proves quarterly is used)
    assert pb is not None and abs(pb - 2.0) < 0.05, ratios["valuation"]
    print("PASS test_calculate_all_ratios_uses_quarterly_balance")


# ---------------------------------------------------------------------------
# 7. Interest coverage — TTM 4-quarter sum + negligible-denominator note
# ---------------------------------------------------------------------------
def test_interest_coverage_ttm_and_note():
    rc = FinancialRatioCalculator()
    # GOOGL-like: negligible interest expense → very high coverage → note emitted
    qinc = _qdf({"Operating Income": [40e9, 38e9, 36e9, 34e9],
                 "Interest Expense": [0.1e9, 0.1e9, 0.1e9, 0.1e9]}, 4)
    inc = _annual_df({"Operating Income": [150e9], "Interest Expense": [0.4e9], "Total Revenue": [300e9],
                      "Net Income": [100e9], "Pretax Income": [120e9], "Tax Provision": [20e9]})
    bal = _annual_df({"Total Assets": [400e9], "Stockholders Equity": [300e9], "Total Debt": [10e9]})
    r = rc.calculate_leverage_ratios(inc, bal, qinc)
    # TTM op income = 40+38+36+34 = 148e9; TTM interest = 0.4e9; coverage = 370x
    assert abs(r["interest_coverage"] - 370.0) < 5, r
    assert "interest_coverage_note" in r, r
    print("PASS test_interest_coverage_ttm_and_note")


# ---------------------------------------------------------------------------
# 8. Revenue base-case growth is CAPPED (v1.0.0.163) — no absurd doubling for hyper-growth names
# ---------------------------------------------------------------------------
def test_revenue_base_growth_capped():
    pe = ProjectionEngine()
    # 100% historical revenue CAGR (NVDA-like): [200, 100] → CAGR 1.0 (clamped). Pre-v1.0.0.163 the
    # base case used the RAW 100% → revenue DOUBLED every year (the absurd ~$2T 3-year path). It must
    # now be capped at 20%, stay below the 25% best case, and still surface the raw CAGR separately.
    inc = _annual_df({"Total Revenue": [200e9, 100e9]}, periods=2)
    proj = pe.generate_revenue_projections(inc, {"totalRevenue": 250e9})
    assert proj, proj
    assert proj["historical_growth"] == 1.0, proj                     # raw CAGR preserved (clamp)
    assert proj["base_case"]["growth_rate"] <= 0.20 + 1e-9, proj      # base capped at 20%
    assert proj["best_case"]["growth_rate"] >= proj["base_case"]["growth_rate"], proj  # best ≥ base
    year1 = proj["base_case"]["projections"][0]
    assert year1 < 2 * 250e9, proj                                    # NOT doubling
    assert abs(year1 - 250e9 * 1.20) < 1e6, proj                      # exactly +20% off the TTM base
    print("PASS test_revenue_base_growth_capped")


# ---------------------------------------------------------------------------
# 9. yfinance field-scale rendering (v1.0.0.164): revenueGrowth fraction + debtToEquity percent-number
# ---------------------------------------------------------------------------
def test_revenue_growth_and_debt_to_equity_scale():
    ana = ComprehensiveStockAnalyzerTool()
    # yfinance revenueGrowth is a FRACTION (NVDA 0.852 = 85.2%, QCOM -0.035 = -3.5%). Must render via
    # _format_percentage (×100), NOT _format_change (which printed "+0.85%" — 100× too small).
    assert ana._format_percentage(0.852) == "85.20%", ana._format_percentage(0.852)
    assert ana._format_percentage(-0.035) == "-3.50%", ana._format_percentage(-0.035)
    # yfinance debtToEquity is a PERCENTAGE NUMBER (AMAT 30.399 = 0.30x, NVDA 6.555 = 0.07x); render as ratio.
    assert ana._format_debt_to_equity(30.399) == "0.30x", ana._format_debt_to_equity(30.399)
    assert ana._format_debt_to_equity(6.555) == "0.07x", ana._format_debt_to_equity(6.555)
    assert ana._format_debt_to_equity("N/A") == "N/A"
    assert ana._format_debt_to_equity(None) == "N/A"
    print("PASS test_revenue_growth_and_debt_to_equity_scale")


# ---------------------------------------------------------------------------
# 10. ddgs search backends exclude the dead/redundant mullvad_* proxies (v1.0.0.165)
# ---------------------------------------------------------------------------
def test_ddgs_backends_exclude_mullvad():
    from user_tools.comprehensive_stock_analyzer import ddgs_working_backends
    bk = ddgs_working_backends()
    assert "mullvad" not in bk, bk            # dead proxies (leta.mullvad.net DNS-fails) never included
    if bk != "auto":                          # introspection worked → explicit engine list, not fallback
        assert "google" in bk and "brave" in bk, bk
    print("PASS test_ddgs_backends_exclude_mullvad")


# ---------------------------------------------------------------------------
# 11. Analyst-consensus block (v1.0.0.166): fraction→percent scaling + no-data guards
# ---------------------------------------------------------------------------
def test_analyst_estimates_scale_and_guards():
    from utils.analyst_estimates import AnalystEstimates
    ae = AnalystEstimates()
    # yfinance growth fields are FRACTIONS → ×100 (same gotcha class as dividendYield/revenueGrowth)
    assert abs(ae._pct(0.4225) - 42.25) < 1e-9, ae._pct(0.4225)
    assert abs(ae._pct(-0.035) - (-3.5)) < 1e-9, ae._pct(-0.035)
    assert ae._pct(None) is None
    assert ae._num(float("nan")) is None
    # no-data guards → empty string, never a half-rendered SOURCE block
    assert ae.format_for_llm({}, "X") == ""
    assert ae.format_for_llm({"symbol": "X"}, "X") == ""
    # populated dict → labeled block, correct scaling, distinct-from-projections labeling
    d = {"symbol": "T", "current_price": 100.0, "target_mean": 150.0, "target_low": 120.0,
         "target_high": 180.0, "target_median": 148.0, "num_analysts": 30, "recommendation_mean": 1.8,
         "recommendation_key": "buy", "upside_to_mean_pct": 50.0, "fwd_eps_avg": 5.0,
         "fwd_eps_growth_pct": 25.0, "fwd_eps_n": 20,
         "rec_dist": {"strongBuy": 10, "buy": 15, "hold": 5, "sell": 0, "strongSell": 0}}
    blk = ae.format_for_llm(d, "T")
    assert "ANALYST CONSENSUS" in blk and "NOT web-scraped" in blk, blk
    assert "mean $150.00" in blk and "+50.0%" in blk, blk
    assert "+25.0% YoY" in blk, blk                       # growth as percent, not fraction
    assert "10 Strong Buy, 15 Buy" in blk, blk
    print("PASS test_analyst_estimates_scale_and_guards")


# ---------------------------------------------------------------------------
# 12. DCF v1.0.0.167: Blume-adjusted beta + quarterly-TTM FCF base + WACC sensitivity band
# ---------------------------------------------------------------------------
def test_dcf_blume_beta_ttm_fcf_and_sensitivity():
    dcf = DCFCalculator()
    # (2a) Blume-adjusted CAPM regresses high beta toward 1.0 → lower cost of equity than raw CAPM
    raw = 0.04 + 2.47 * 0.07                       # raw-beta cost of equity = 21.29%
    blume = dcf.calculate_cost_of_equity({"beta": 2.47})
    assert abs(blume - (0.04 + (0.67 * 2.47 + 0.33) * 0.07)) < 1e-9, blume
    assert blume < raw, (blume, raw)               # Blume LOWERS it (17.9% < 21.3%)
    assert abs(dcf.calculate_cost_of_equity({}) - 0.11) < 1e-9   # no beta → market β 1.0 → 11%
    # (2c) TTM FCF from quarterly = sum of the 4 most-recent quarters of (OCF + CapEx); CapEx negative
    q = _qdf({"Operating Cash Flow": [30e9, 28e9, 26e9, 24e9],
              "Capital Expenditure": [-3e9, -2e9, -2e9, -1e9]}, 4)
    assert abs(dcf._ttm_fcf_from_quarterly(q) - 100e9) < 1e6, dcf._ttm_fcf_from_quarterly(q)  # 108-8
    assert dcf._ttm_fcf_from_quarterly(None) is None
    # (2b) sensitivity: a LOWER WACC yields a HIGHER intrinsic value (bull > bear)
    proj = [10e9, 11e9, 12e9, 13e9, 14e9]
    bull = dcf._intrinsic_at_wacc(proj, 0.10, 0.025, 20e9, 50e6)
    bear = dcf._intrinsic_at_wacc(proj, 0.15, 0.025, 20e9, 50e6)
    assert bull and bear and bull > bear, (bull, bear)
    print("PASS test_dcf_blume_beta_ttm_fcf_and_sensitivity")


if __name__ == "__main__":
    test_pb_prefers_priceToBook()
    test_pb_fallback_equity_with_note()
    test_dividend_yield_authoritative_from_rate()
    test_dividend_yield_fallback_yfinance_percent_number()
    test_dividend_yield_high_yield_sanity_note()
    test_dcf_negative_equity_guard()
    test_dcf_marketable_securities_netted()
    test_projection_renders_historical_cagr_and_label()
    test_roic_uses_nopat_not_net_income()
    test_calculate_all_ratios_uses_quarterly_balance()
    test_interest_coverage_ttm_and_note()
    test_revenue_base_growth_capped()
    test_revenue_growth_and_debt_to_equity_scale()
    test_ddgs_backends_exclude_mullvad()
    test_analyst_estimates_scale_and_guards()
    test_dcf_blume_beta_ttm_fcf_and_sensitivity()
    print("\n✅ All financial-calculator accuracy tests passed")