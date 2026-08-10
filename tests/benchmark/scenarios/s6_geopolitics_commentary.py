"""
S6 — original geopolitical commentary (argument, not summary).

The prompt FORBIDS summarising other writers. The failure mode is a well-cited survey that\nnever commits to a thesis, so the metrics score ARGUMENT density against attribution density\nrather than trying to judge prose quality.
"""
import time

from lib import raica_client as RC
from lib import spectrum as SP

SCENARIO = "S6_commentary_original"

PROMPT = 'survey the current national and international important conversations and hot issue of geopolitics being debated in commentaries and current news. find an issue or a set of issues that you feel you can contribute to. Read other\'s commentaries and opinions thoroughly about it, fully understand it and dig deep into it. then write YOUR OWN commentary and opinion and publishable article. NEVER just summarize someone else\'s opinion or just synthesize other writer\'s opinions to fill the article, it has to be your own and you have argue for it. Do not just go with the flow for the sake of conformity, do not be timid from voicing controversial opinions as long as you can argue for it. You are not reporting news or facts, but you are using news and facts to support your commentary. Examine your article for originality and presentation!. readers look for insights that add dimensions and "Aha" or "I never thought of this before" -- Do not waste sentences criticizing and critiquing other commentators and opinion writes, focus on your thesis, argument, veracity, and delivery'


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
            # --- the prompt's core constraint: argue a position, do not survey ---
            _m("own_thesis_markers",       "CODE", SP.first_person_thesis(text),        "count", "higher_better", 0),
            _m("attribution_per_1k_words", "CODE", SP.hedged_summary_ratio(text),       "ratio", "lower_better", 0),

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
