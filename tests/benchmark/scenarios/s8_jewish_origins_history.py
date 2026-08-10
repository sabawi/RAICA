"""
S8 — evidence-only historical synthesis (archaeology and dated manuscripts).

Tests grounding on a HUMANITIES topic where the STEM-only academic sources do not apply — the\ndomain that exposed the homonym/source-relevance issues (SI dr_source_relevance). The prompt\nbars religious text as evidence, so the discriminator is whether hard-evidence vocabulary is\nactually present, not whether the prose sounds scholarly.
"""
import time

from lib import raica_client as RC
from lib import spectrum as SP

SCENARIO = "S8_history_evidence"

PROMPT = 'Strictly historically speaking and based on physical archaeological and authentic manuscripts scientifically dated as far back as we can go, answer the question: Who are the Jewish people? How did they become a distinct group. DO NOT LEAN ON RELIGIOUS TEXT AND MYTHOLOGY, use deep scholarly grounded research that is based on hard evidence to construct their origins and history from the first mention to modernity.'


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
            # --- the prompt bars scripture as evidence; hard-evidence vocabulary must be present ---
            _m("hard_evidence_terms",      "CODE", len(__import__("re").findall(
                r"archaeolog|excavat|inscription|stele|papyr|manuscript|radiocarbon|epigraph|ostrac",
                text, __import__("re").I)),                                             "count", "higher_better", 0),

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
