"""
S7 — 50-year economic simulation with charts and tables.

The prompt explicitly demands charts AND tables. This is the non-finance path to the same\nSI-025 class of failure: a rendered artifact produced upstream but discarded before synthesis\nwould show up here as chart_markers_in_answer = 0.
"""
import time

from lib import raica_client as RC
from lib import spectrum as SP

SCENARIO = "S7_simulation_charts"

PROMPT = "Do a theoretical simulation to gage the impact of immigration reduction to the USA on the country's economy and world standing. Take into account all aspects of economic impacts: Export, imports, farming, innovation, tech, military, social composition, and employment rates. Highlight sectors and industries that will be most affected and the overall impact on GDP and the value of the US dollar. Project the impact to up to 50 years in the future (or two generations). Show best and worst sceneries, then speculate on what you see as the most likely scenario from the impact of the reduction. Use real and verified data and build a rock solid analysis with charts and table to support your arguments"


def run(base, repeats=1):
    runs = []
    for _ in range(repeats):
        t0 = time.time()
        r = RC.post_v1(PROMPT, base=base, deep_research=True, timeout=1800)
        log = RC.log_window_since(t0)
        text = r["text"] or ""
        trunc, total = SP.truncation_counts(log)
        a = SP.audit_numbers(text)
        SP.retain(SCENARIO, text, log, tag=__import__("os").environ.get("BENCH_ARM"))
        _m = lambda n, c, v, u, d, t: SP.m(SCENARIO, n, c, v, u, d, t)
        runs.append([
            # --- artifacts the prompt explicitly demands ---
            _m("chart_markers_in_answer",  "CODE", SP.chart_markers(text),              "count", "higher_better", 0),
            _m("has_tables",               "CODE", SP.has_tables(text, 2),              "bool", "must_equal", 0),

            # --- grounding: the same bar the finance scenarios are held to ---
            _m("claims_checked",           "CODE", a.get("claims_checked", 0),          "count", "higher_better", 0),
            _m("claims_unsupported_ratio", "CODE", a.get("claims_unsupported_ratio", 0.0), "ratio", "lower_better", 0),
            _m("unique_sources",           "CODE", a.get("unique_sources", 0),          "count", "higher_better", 0),
            _m("evidence_items",           "CODE", a.get("evidence_items", 0),          "count", "higher_better", 0),
            _m("low_cred_sources",         "CODE", a.get("low_cred_sources", 0),        "count", "lower_better", 0),
            _m("sources_truncated",        "CODE", trunc,                               "count", "lower_better", 0),
            _m("answer_chars",             "CODE", len(text),                           "chars", "higher_better", 0),
            _m("dr_latency_s",             "PERF", r["latency_s"],                      "seconds", "lower_better", 300),
        ])
    return runs
