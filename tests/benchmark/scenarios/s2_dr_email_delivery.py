"""
S2 — Deep Research + delivery (FILE-ONLY locally). Locks in: DR completes, produces a real document with a
TOPIC title (not a section heading), rendered to BOTH a valid PDF and a self-contained styled HTML (the one
shared template + @media screen). No email on the benchmark run (file-only; email path has its own test).
"""
import os
import re
import time

from lib import raica_client as RC

SCENARIO = "S2_dr_delivery"

# MAX_REPEATS — this scenario caps its own repetition instead of the runner matching it by
# NAME. The runner used to do `if mod.SCENARIO in ("S2_dr_delivery", "S4_multi_ticker_dr")`,
# and this module is named "S4_multi_ticker_8" — so the guard matched nothing and the
# slowest scenario silently ran 3x instead of 1x on every Tier-1 run (~45 min instead of
# ~15, and triple the outbound search volume). A name list in another file cannot be kept
# in sync by hope; the scenario owning its own cap makes that class of drift impossible.
MAX_REPEATS = 1
PROMPT = ("Deep research the history of jazz music in America, organized into chronological sections. "
          "Save the result as a PDF file and an HTML file.")


def _m(name, cls, value, unit, direction, tol):
    return {"scenario": SCENARIO, "name": name, "cls": cls, "value": value,
            "unit": unit, "direction": direction, "tolerance": tol}


def _pdf_valid(path):
    try:
        if not path or not os.path.exists(path) or os.path.getsize(path) < 5000:
            return False
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF")
    except Exception:
        return False


def _html_self_contained(path):
    try:
        if not path or not os.path.exists(path):
            return False
        html = open(path, encoding="utf-8", errors="replace").read()
        return ("<style" in html.lower()) and ("@media screen" in html) and ("<h" in html.lower())
    except Exception:
        return False


def _title_is_section(path):
    """True if the document title looks like an enumerated SECTION ('1. …', 'Part 2 …') — the bug we fixed."""
    try:
        html = open(path, encoding="utf-8", errors="replace").read() if path and os.path.exists(path) else ""
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = (m.group(1).strip() if m else "")
        return bool(re.match(r"^(\d+\s*[\.\):]|part\s+\d+|section\s+\d+|chapter\s+\d+)", title, re.IGNORECASE))
    except Exception:
        return True   # can't read -> conservative


def run(base, repeats=1):   # DR is ~5 min; default 1 run (expensive). Median of 1 == the run.
    runs = []
    for _ in range(repeats):
        t0 = time.time()
        r = RC.post_v1(PROMPT, base=base, deep_research=True, timeout=700)
        log = RC.log_window_since(t0)
        files = RC.created_delivery_files(log)
        phases = RC.dr_phase_timings(log)   # Tier-2 per-stage
        pdfs = [f for f in files if f.lower().endswith(".pdf")]
        htmls = [f for f in files if f.lower().endswith(".html")]
        html0 = htmls[0] if htmls else None
        runs.append([
            _m("dr_completed",          "CODE", bool(r["text"]) and len(r["text"]) > 500, "bool", "must_equal", 0),
            _m("attachment_count",      "CODE", len(files),                               "count", "must_equal", 0),
            _m("pdf_valid",             "CODE", _pdf_valid(pdfs[0]) if pdfs else False,   "bool", "must_equal", 0),
            _m("html_self_contained",   "CODE", _html_self_contained(html0),              "bool", "must_equal", 0),
            _m("doc_title_is_section",  "CODE", _title_is_section(html0),                 "bool", "must_equal", 0),
            _m("dr_synthesize_s",       "PERF", phases.get("synthesize"),                 "seconds", "lower_better", 40),
            _m("dr_verify_s",           "PERF", phases.get("verify"),                     "seconds", "lower_better", 40),
            _m("dr_latency_s",          "PERF", r["latency_s"],                           "seconds", "lower_better", 120),
        ])
    return runs
