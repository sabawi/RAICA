"""
S4 — 8-ticker financial Deep Research (the query that failed for a user on 2026-08-10).

This is the EXACT prompt that returned 'No technical chart markers were provided in the\nevidence' for all 8 stocks and ZERO DCF values, while the log showed 8/8 DCFs computed and\n8/8 markers emitted. Evidence budgeting discarded them. No pre-existing scenario exercised\nmany entities at full detail, so nothing caught it — the defect scaled with entity count.
"""
import time

from lib import raica_client as RC
from lib import spectrum as SP

SCENARIO = "S4_multi_ticker_8"

# MAX_REPEATS — this scenario caps its own repetition instead of the runner matching it by
# NAME. The runner used to do `if mod.SCENARIO in ("S2_dr_delivery", "S4_multi_ticker_dr")`,
# and this module is named "S4_multi_ticker_8" — so the guard matched nothing and the
# slowest scenario silently ran 3x instead of 1x on every Tier-1 run (~45 min instead of
# ~15, and triple the outbound search volume). A name list in another file cannot be kept
# in sync by hope; the scenario owning its own cap makes that class of drift impossible.
MAX_REPEATS = 1
TICKERS = ["KO", "JPM", "BRK-B", "CROX", "RIVN", "PLUG", "FUBO", "RBRK"]

PROMPT = ("Using the research tool, pull the latest available company and financial data for "
          + ", ".join(TICKERS) +
          " (run the structured stock analyzer on each, full detail) FOR LONG (2 YEARS) AND SHORT TERMS (< 6 MONTHS). "
          "For each, analyze: (1) growth outlook — revenue/earnings/FCF trajectory and its drivers; (2) profitability & returns — margins and ROIC vs. cost of capital; (3) valuation — trailing & forward P/E, P/S, EV/EBITDA, P/B, each compared to the company's own history and to the peer group; (4) balance-sheet strength and key risks; (5) near-term catalysts over a 6-month-to-2-year horizon (AI/data-center capex cycle, product roadmaps, end-market demand, customer concentration).\n\nGround every figure in the retrieved data and cite it. Clearly label any DCF intrinsic value or multi-year projection as a model estimate / historical-CAGR extrapolation — not analyst consensus, and note where a figure is stale or unavailable rather than guessing. Include a side-by-side comparison table of the key metrics across all five.\n\nUse Technical Analysis to check the timing of the trade whether to sell or buy or take new positions. And recommend the appropriate time.\n\nThen give a Buy / Hold / Sell call for each stock for the 6-month-to-2-year horizon, with reasoning. In your conclusion, rank the five by risk-adjusted upside and select exactly one to add to my portfolio — the best expected capital gain for a reasonable level of risk (weigh valuation risk, cyclicality, volatility/beta, and balance-sheet risk) — and explain why it beats the other four. State the price and as-of date you based it on.")


def run(base, repeats=1):
    runs = []
    for _ in range(repeats):
        t0 = time.time()
        r = RC.post_v1(PROMPT, base=base, deep_research=True, timeout=1800)
        log = RC.log_window_since(t0)
        text = r["text"] or ""
        ev, placed, required = SP.synth_marker_counts(log)
        trunc, total = SP.truncation_counts(log)
        a = SP.audit_numbers(text)
        SP.retain(SCENARIO, text, log, tag=__import__("os").environ.get("BENCH_ARM"))
        _m = lambda n, c, v, u, d, t: SP.m(SCENARIO, n, c, v, u, d, t)
        runs.append(RC.unmeasured_if_no_response(r, [
            # --- the invariants that broke on 2026-08-10 ---
            _m("tickers_with_dcf",        "CODE", SP.tickers_with_dcf(text, TICKERS), "count", "higher_better", 0),
            _m("tickers_with_call",       "CODE", SP.tickers_with_call(text, TICKERS), "count", "higher_better", 0),
            _m("chart_markers_in_answer", "CODE", SP.chart_markers(text),             "count", "higher_better", 0),
            _m("markers_reaching_synthesis", "CODE", ev if ev is not None else 0,     "count", "higher_better", 0),
            _m("charts_placed_ratio",     "CODE", (placed / required) if (required or 0) > 0 else 1.0,
               "ratio", "higher_better", 0),
            _m("answer_reports_starvation", "CODE", bool(SP.STARVED.search(text)),    "bool", "must_equal", 0),
            _m("tickers_with_chart_emitted", "CODE", SP.emitted_chart_tickers(log),   "count", "higher_better", 0),
            # --- deliverables the prompt explicitly demands ---
            _m("comparison_table",        "CODE", SP.has_comparison_table(text, TICKERS), "bool", "must_equal", 0),
            _m("states_as_of_date",       "CODE", SP.states_as_of_date(text),         "bool", "must_equal", 0),
            # --- grounding quality ---
            _m("claims_checked",          "CODE", a.get("claims_checked", 0),         "count", "higher_better", 0),
            _m("claims_unsupported_ratio","CODE", a.get("claims_unsupported_ratio", 0.0), "ratio", "lower_better", 0),
            _m("unique_sources",          "CODE", a.get("unique_sources", 0),         "count", "higher_better", 0),
            _m("evidence_items",          "CODE", a.get("evidence_items", 0),         "count", "higher_better", 0),
            _m("low_cred_sources",        "CODE", a.get("low_cred_sources", 0),       "count", "lower_better", 0),
            _m("sources_truncated",       "CODE", trunc,                              "count", "lower_better", 0),
            _m("answer_chars",            "CODE", len(text),                          "chars", "higher_better", 0),
            _m("dr_latency_s",            "PERF", r["latency_s"],                     "seconds", "lower_better", 300),
        ]))
    return runs
