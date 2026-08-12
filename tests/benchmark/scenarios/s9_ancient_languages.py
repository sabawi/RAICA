"""
S9 — a WELL-STUDIED humanities question, graded against an A+ bar.

Origin: a production @Ask answer on the linguistic landscape of the ancient Near East that
the user graded 8.5-9.0/10 (B+/A-) and asked to lift to A+. Two critiques were given:
"use of wikipedia and secondary sources while there are accessible academic and peer
reviewed sources available" and "some sources are mentioned but not cited".

DIAGNOSIS, AND A CORRECTION TO AN EARLIER ONE
---------------------------------------------
The first diagnosis was that the scholarship had never been READ — inferred from a control
test showing Brill returns HTTP 200 with 208 chars of body and De Gruyter 202/220, against
Wikipedia's 10,164. That test used URLs constructed by hand, and the conclusion was drawn
WITHOUT checking the audit for the actual production run. That audit refutes it:

    retrieval-audit: real=23 thin=1 error=0 over_captured=0 absent=0 / 24 cited

24 cited matches the answer's reference count exactly, and 23 came back with a body. The
sources WERE fetched. Recorded here because the refuted version was briefly reported as
confirmed, and an explanation that merely FITS is not a cause that has been VERIFIED.

What is actually wrong is retrieval DEPTH. That run pulled 217,207 chars over 98 unique
sources — about 2,216 each, roughly one abstract. And `retrieval_audit.min_body_chars` is
200, so a single paragraph grades as `real`: the reassuring provenance line sits happily
above an answer that never engaged its sources. An abstract tells you what a work is ABOUT
and often not what it ARGUES, which is exactly the observed prose — "Radner directly
addresses this phenomenon" — and why named works carry no claim.

Two further defects need no retrieval at all and are pure reasoning failures, both proven
from the answer's OWN dates:
  * SCOPE — the TL;DR names the "Neo-Babylonian empire" as dominating 1000-700 BC while the
    answer dates it 626-539 BC, beginning 74 years AFTER the window closes.
  * UNIFORM SPAN — Aramaic becomes a lingua franca in the 8th c., the final third of a
    300-year window, and the answer never says the picture changes across it.

METRICS
-------
All metrics come from lib/generic_quality.py and are TOPIC-AGNOSTIC: the window is parsed
from the prompt, and source classes are structural (scholarly publisher, encyclopedia,
official body) rather than subject vocabulary. The first cut of this scenario hardcoded a
700-1000 BC window, a list of ancient Near East inscriptions, and a speech-vs-writing word
list — baselining on those would have tuned RAICA for one question about one century.

Two quantities are reported as DIAGNOSTIC with no direction, deliberately: scholarly
disagreement and sub-period count. Scoring either higher-is-better would reward
manufacturing controversy on settled questions, and inventing phases in a span that does
not actually vary.
"""
import os
import re
import time

from lib import generic_quality as GQ
from lib import raica_client as RC
from lib import spectrum as SP

SCENARIO = "S9_ancient_languages"

PROMPT = ('How did people in the Middle East around 700 to 1000 BC communicate? What languages '
          'were common for everyday transactions and social interactions with Aramaic, Syriac, '
          'Arabic, Hebrew, and Greek and possibly many others in circulation')

# The window is DERIVED FROM THE PROMPT, never hardcoded — the same scenario shape then
# works for "1990 to 2020" or for a question that sets no temporal bound at all.
SPAN = GQ.declared_span(PROMPT)


def run(base, repeats=1):
    runs = []
    for _ in range(repeats):
        t0 = time.time()
        r = RC.post_v1(PROMPT, base=base, deep_research=True, timeout=1800)
        log = RC.log_window_since(t0)
        text = r["text"] or ""
        trunc, _total = SP.truncation_counts(log)
        a = SP.audit_numbers(text)
        SP.retain(SCENARIO, text, log, tag=os.environ.get("BENCH_ARM"))

        mix = GQ.citation_mix(text)
        _m = lambda n, c, v, u, d, t: SP.m(SCENARIO, n, c, v, u, d, t)

        runs.append([
            # --- sourcing SUBSTANCE (topic-agnostic; see lib/generic_quality.py) ---
            _m("unanchored_citation_ratio", "CODE", GQ.unanchored_citation_ratio(text), "ratio", "lower_better",  0),
            _m("retrieval_depth_chars",     "CODE", GQ.retrieval_depth(text),           "chars", "higher_better", 0),
            _m("citation_reuse",            "CODE", GQ.citation_reuse(text),            "ratio", "lower_better",  0),
            _m("academic_share",            "CODE", mix["academic"],                    "ratio", "higher_better", 0),
            _m("encyclopedic_share",        "CODE", mix["encyclopedic"],                "ratio", "lower_better",  0),
            _m("unique_cited_urls",         "CODE", mix["unique"],                      "count", "higher_better", 0),

            # --- the falsifiable scope error: the answer's OWN dates exclude the entity ---
            _m("scope_violations",          "CODE", len(GQ.span_violations(text, SPAN)), "count", "lower_better", 0),

            # --- DIAGNOSTIC, no direction: scoring these would reward manufacturing
            #     controversy, or inventing phases in a span that does not vary ---
            _m("span_subdivisions_diag",    "DIAG", GQ.span_subdivisions(text, SPAN),   "count", "report", 0),
            _m("debate_markers_diag",       "DIAG", GQ.debate_markers(text),            "count", "report", 0),

            # --- the standing D1-D7 bar, same as every other spectrum scenario ---
            _m("claims_checked",           "CODE", a.get("claims_checked", 0),  "count", "higher_better", 0),
            _m("claims_unsupported_ratio", "CODE", a.get("claims_unsupported_ratio", 0.0), "ratio", "lower_better", 0),
            _m("unique_sources",           "CODE", a.get("unique_sources", 0),  "count", "higher_better", 0),
            _m("evidence_items",           "CODE", a.get("evidence_items", 0),  "count", "higher_better", 0),
            _m("low_cred_sources",         "CODE", a.get("low_cred_sources", 0), "count", "lower_better",  0),
            _m("sources_truncated",        "CODE", trunc,                       "count", "lower_better",  0),
            _m("answer_chars",             "CODE", len(text),                   "chars", "higher_better", 0),
            _m("dr_latency_s",             "PERF", r["latency_s"],              "seconds", "lower_better", 300),
        ])
    return runs
