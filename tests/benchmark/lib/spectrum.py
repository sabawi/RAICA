"""Shared measurement helpers for the full-spectrum DR scenarios (S4-S8).

Every metric here is read off the ANSWER the user receives or off structured log markers —
never off the model's own prose about what it did. The 2026-08-10 failure is the reason:
the tools had computed 8 DCFs and emitted 8 chart markers, the log proved it, and the
answer still said "No technical chart markers were provided in the evidence" because the
pipeline had discarded them before synthesis. Measuring the log alone would have scored
that run as a PASS.
"""
import re

# The phrase the synthesis model emits when the pipeline has starved it of its own tool
# output. Its presence is the user-visible signature of the SI-025 class of failure.
STARVED = re.compile(r"no (?:technical )?chart markers?[^.]{0,60}provided", re.I)


def chart_markers(text):
    return len(re.findall(r"\[\[chart:", text))


def tickers_with_dcf(text, tickers):
    """Tickers whose DCF intrinsic value reached the READER.

    Deliberately not counted from the log: a DCF the tool computed but that never appears
    in the answer is worth exactly nothing, and that is precisely what broke.
    """
    n = 0
    for t in tickers:
        if re.search(rf"{re.escape(t)}[\s\S]{{0,4000}}?intrinsic value"
                     rf"|intrinsic value[\s\S]{{0,400}}?{re.escape(t)}", text, re.I):
            n += 1
    return n


def tickers_with_call(text, tickers):
    """Tickers given an explicit Buy/Hold/Sell call — the deliverable the user asked for."""
    n = 0
    for t in tickers:
        if re.search(rf"{re.escape(t)}[\s\S]{{0,2500}}?\b(BUY|HOLD|SELL|ACCUMULATE|AVOID)\b",
                     text, re.I):
            n += 1
    return n


def has_comparison_table(text, tickers, min_hits=4):
    """A markdown table row mentioning several of the tickers = the side-by-side table."""
    for line in text.split("\n"):
        if line.count("|") >= 3 and sum(1 for t in tickers if t in line) >= min_hits:
            return True
    # or a column-per-metric table whose header row names the tickers
    return sum(1 for t in tickers if re.search(rf"\|\s*{re.escape(t)}\s*\|", text)) >= min_hits


def count_tables(text):
    """Number of markdown tables, counted by SEPARATOR LINES (|---|---|).

    The first version thresholded on "lines with >=3 pipes >= minimum*3", which called a
    perfectly good 5-row table (header + separator + 3 body rows) "no tables" because it
    wanted 6. Counting the separator line is what actually identifies a table, and it
    cannot be fooled by a long table or by prose containing pipes.
    """
    return sum(1 for l in text.split("\n")
               if l.count("|") >= 2 and re.fullmatch(r"[\s|:\-]+", l.strip() or "x") is not None
               and "-" in l)


def has_tables(text, minimum=1):
    return count_tables(text) >= minimum


def states_as_of_date(text):
    return bool(re.search(r"as of\s+\w+\s+\d{1,2},?\s+20\d\d|as-of date|\b20\d\d-\d\d-\d\d\b", text, re.I))


def audit_numbers(text):
    """Pull RAICA's own research-audit footer: evidence, sources, claims, credibility."""
    out = {}
    m = re.search(r"Evidence:\*{0,2}\s*(\d+)\s+results across\s+(\d+)\s+round\(s\),\s*(\d+)\s+unique sources\s*\(([\d,]+)\s*chars\)", text)
    if m:
        out.update(evidence_items=int(m.group(1)), rounds=int(m.group(2)),
                   unique_sources=int(m.group(3)), evidence_chars=int(m.group(4).replace(",", "")))
    # Field ORDER varies between runs ("supported, unverified, contradicted" and
    # "supported, contradicted, unverified" both occur), so parse the fields
    # independently rather than positionally — an order-dependent regex silently
    # returned nothing and would have shipped a permanently-zero metric.
    m = re.search(r"Claims checked:\*{0,2}\s*(\d+)\s*\(([^)]*)\)", text)
    if m:
        checked = int(m.group(1))
        body = m.group(2)
        def _f(k):
            mm = re.search(rf"{k}:\s*(\d+)", body)
            return int(mm.group(1)) if mm else 0
        unver = _f("unverified") + _f("contradicted")
        out.update(claims_checked=checked, claims_unsupported=unver,
                   claims_unsupported_ratio=round(unver / checked, 3) if checked else 0.0)
    m = re.search(r"low_credibility:\s*(\d+)", text)
    out["low_cred_sources"] = int(m.group(1)) if m else 0
    m = re.search(r"Stop reason:\*{0,2}\s*(\w+)", text)
    if m:
        out["stop_reason_max_rounds"] = (m.group(1) == "max_rounds")
    return out


def synth_marker_counts(log_lines):
    """(evidence, placed, required) from the synth chart-marker log lines.

    `evidence=0` while markers were emitted upstream IS the SI-025 bug: the analyzer's
    output was cut before synthesis ever saw it.
    """
    ev = placed = required = None
    for ln in log_lines:
        m = re.search(r"synth chart-markers — evidence=(\d+)", ln)
        if m:
            ev = int(m.group(1))
        m = re.search(r"synth chart-markers \(final\) — required=(\d+) final_draft=(\d+)", ln)
        if m:
            required, placed = int(m.group(1)), int(m.group(2))
    return ev, placed, required


def emitted_chart_tickers(log_lines):
    return len({re.search(r"chart marker EMITTED for ([A-Z.\-]+)", ln).group(1)
                for ln in log_lines if "chart marker EMITTED for" in ln})


def truncation_counts(log_lines):
    """(sources_truncated, total_sources) at the synthesis budgeting step."""
    last = None
    for ln in log_lines:
        m = re.search(r"Evidence budgeted to ~\d+ tokens: (\d+)/(\d+) source\(s\) truncated", ln)
        if m:
            last = (int(m.group(1)), int(m.group(2)))
    return last or (0, 0)


def first_person_thesis(text):
    """Does the piece argue its OWN position rather than summarise others?

    Scored on ARGUMENT markers, not sentiment: a commentary that only reports what others
    think is the failure mode the prompt explicitly forbids.
    """
    own = len(re.findall(r"\bI (?:argue|contend|believe|think|would|see|suspect|reject)\b"
                         r"|\bmy (?:argument|thesis|view|contention)\b"
                         r"|\bthe argument here\b", text, re.I))
    return own


def hedged_summary_ratio(text):
    """Density of attribution verbs — high values suggest a survey rather than a thesis."""
    attrib = len(re.findall(r"\b(?:according to|argues that|writes that|notes that|observes that|contends that)\b", text, re.I))
    words = max(1, len(text.split()))
    return round(attrib / (words / 1000.0), 2)      # per 1000 words


def m(scenario, name, cls, value, unit, direction, tol):
    return {"scenario": scenario, "name": name, "cls": cls, "value": value,
            "unit": unit, "direction": direction, "tolerance": tol}


def retain(scenario, text, log_lines=None, tag=None):
    """Persist the ANSWER (and optionally the log window) for post-hoc forensics.

    Added after the 2026-08-10 spectrum run, where `claims_unsupported_ratio` moved and the
    flagged claims could not be READ because the harness had measured the answer and thrown
    it away. A metric that moves without a retrievable artifact cannot be diagnosed — only
    argued about, which is how the whole day went wrong.
    """
    import os
    out = os.environ.get("BENCH_ARTIFACT_DIR")
    if not out:
        return None
    os.makedirs(out, exist_ok=True)
    suffix = f"_{tag}" if tag else ""
    path = os.path.join(out, f"{scenario}{suffix}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text or "")
    if log_lines:
        with open(os.path.join(out, f"{scenario}{suffix}.log"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(log_lines))
    return path
