"""
Benchmark scoring engine — metric verdicts, baseline deltas, CODE/ENV/PERF classification, rendering.

Design: docs/RAICA_QUALITY_BENCHMARK.md. Pure + deterministic (no I/O except baseline.json load/save).

A metric a scenario emits:
    {"scenario","name","cls","value","unit","direction","tolerance"}
  cls       : "CODE" (our regression -> FAIL) | "ENV" (world changed -> WARN) | "PERF" (latency)
  direction : "higher_better" | "lower_better" | "must_equal"

Verdict vs baseline: IMPROVEMENT | PASS | REGRESSION | WARN.
  - ENV metrics NEVER produce REGRESSION (a model 410 / site 403 / news churn -> WARN, never a red bar).
  - No baseline yet -> INFO (treated as PASS; the value becomes the candidate baseline).
Suite verdict = REGRESSION if ANY CODE/PERF metric REGRESSED, else PASS (with IMPROVEMENTS + ENV WARNs listed).
"""
import json
import os
import statistics

IMPROVEMENT, PASS, REGRESSION, WARN, INFO = "IMPROVEMENT", "PASS", "REGRESSION", "WARN", "INFO"
# SI-055 — a THIRD suite verdict. A run whose retrieval was rate-limited into the ground cannot
# tell a code regression from the environment, so it must report neither. PASS would hide a real
# regression; REGRESSION would block a good deploy and teach people to ignore the suite. The
# honest answer is that the measurement did not happen.
INCONCLUSIVE = "INCONCLUSIVE"
_C = {IMPROVEMENT: "\033[36m", PASS: "\033[32m", REGRESSION: "\033[31m", WARN: "\033[33m",
      INFO: "\033[2m", INCONCLUSIVE: "\033[35m"}
_RESET = "\033[0m"


def key(scenario, name):
    return f"{scenario}.{name}"


def verdict_for(value, baseline, *, cls, direction, tolerance):
    """Verdict of one metric value against its baseline. Pure."""
    if baseline is None:
        return INFO  # first run / new metric — record it, don't fail
    if value is None:
        return WARN if cls == "ENV" else REGRESSION  # the run couldn't measure it
    bad = WARN if cls == "ENV" else REGRESSION
    if direction == "must_equal":
        return PASS if value == baseline else bad
    if direction == "higher_better":
        if value > baseline + tolerance:
            return IMPROVEMENT
        return PASS if value >= baseline - tolerance else bad
    if direction == "lower_better":
        if value < baseline - tolerance:
            return IMPROVEMENT
        return PASS if value <= baseline + tolerance else bad
    return PASS


def median_runs(per_run_metrics):
    """Collapse N runs (each a list of metric dicts) into one list of metric dicts using the MEDIAN of
    numeric values per metric (booleans -> majority True). Noise control for non-deterministic LLM runs."""
    by_key = {}
    for run in per_run_metrics:
        for m in run:
            by_key.setdefault(key(m["scenario"], m["name"]), []).append(m)
    out = []
    for _, ms in by_key.items():
        base = dict(ms[0])
        vals = [m["value"] for m in ms if m["value"] is not None]
        if not vals:
            base["value"] = None
        elif isinstance(vals[0], bool):
            base["value"] = sum(1 for v in vals if v) * 2 >= len(vals)   # majority True
        else:
            base["value"] = statistics.median(vals)
        # RETAIN THE SPREAD, not just the centre.
        #
        # These raw values were computed here and then thrown away, so a saved scorecard held
        # one number per metric and nothing about how much it moved between repeats. That made
        # the only question an A/B actually asks — "is this delta bigger than the noise?" —
        # unanswerable after the fact. Measured 2026-08-16: a GLM-vs-Flash comparison showed
        # unique_sources +46% on one pair of runs and ~0% at n=4, and there was no way to tell
        # which was signal because the per-repeat numbers no longer existed.
        base["samples"] = vals
        base["n"] = len(vals)
        out.append(base)
    return out


def load_baseline(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_baseline(path, metrics, reason, measured_at):
    """Write/refresh baseline.json from a run's metrics. NEVER silent — `reason` is mandatory."""
    if not reason or not reason.strip():
        raise ValueError("baseline update requires a non-empty reason")
    data = load_baseline(path)
    for m in metrics:
        data[key(m["scenario"], m["name"])] = {
            "value": m["value"], "cls": m["cls"], "direction": m["direction"],
            "tolerance": m["tolerance"], "unit": m.get("unit", ""),
            "measured_at": measured_at, "reason": reason.strip(),
        }
    data["_meta"] = {"measured_at": measured_at, "reason": reason.strip()}
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return data


def retrieval_collapsed(rows):
    """(collapsed: bool, reasons: list[str]) — did a measured quantity fall to NOTHING?

    This is the signature of retrieval dying, taken from the run where it actually happened
    (2,806 throttle events): `citation_count 0` against a baseline of 13, `answer_chars 0`,
    `dr_completed False`. Not "worse than baseline" — *zero*, where the baseline was not.

    Deliberately NOT a list of metric names. Any CODE metric that is higher-better and had a
    non-zero baseline qualifies, so a metric added tomorrow is covered with no edit here, and
    nobody has to remember to register it. (A name list in one file that must track constants
    in another is the exact class of bug that made the runner run S4 three times per run.)

    Metrics with no baseline are skipped: without one, zero cannot be distinguished from a
    legitimately-zero measurement. That gap is covered by throttle.CEILING.
    """
    reasons = []
    for r in rows:
        if r.get("cls") != "CODE" or r.get("direction") != "higher_better":
            continue
        base, val = r.get("baseline"), r.get("value")
        if isinstance(base, bool):
            if base is True and val is False:
                reasons.append(f"{r['scenario']}.{r['name']}: True -> False")
            continue
        if not isinstance(base, (int, float)) or base <= 0:
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        if val == 0:
            reasons.append(f"{r['scenario']}.{r['name']}: {base} -> 0")
    return bool(reasons), reasons


def score_run(metrics, baseline, environment=None):
    """Compare a run's metrics to baseline. Returns a scorecard dict.

    `environment` (optional): {"degraded": bool, "message": str, "throttle_events": int} from
    lib/throttle. SI-055 — when the run's retrieval was throttled into the ground, EVERY
    verdict here is unreliable, so the suite reports INCONCLUSIVE instead of inventing one.
    The per-metric rows are still rendered (they are evidence) but carry `unreliable: True`.
    """
    rows = []
    for m in metrics:
        b = baseline.get(key(m["scenario"], m["name"]))
        bval = b["value"] if b else None
        v = verdict_for(m["value"], bval, cls=m["cls"], direction=m["direction"], tolerance=m["tolerance"])
        rows.append({**m, "baseline": bval, "verdict": v})
    # ── CONJUNCTIVE degradation (v1.0.0.298) ────────────────────────────────────────────
    # Old rule: throttle over a threshold => INCONCLUSIVE. That called four healthy runs
    # unmeasurable, most clearly one with 33/33 rows PASS and zero within-arm variance.
    #
    #   ceiling exceeded              -> INCONCLUSIVE (count alone is disqualifying)
    #   elevated AND metrics collapsed-> INCONCLUSIVE (genuinely cannot attribute the cause)
    #   elevated, metrics healthy     -> score it normally; noisy is not broken
    #   NOT elevated, metrics collapsed -> REGRESSION. A collapse without heavy traffic has
    #                                    no environmental excuse -- that is the bug case, and
    #                                    the old rule could never express it.
    env = environment or {}
    collapsed, collapse_reasons = retrieval_collapsed(rows)
    elevated = bool(env.get("elevated"))
    ceiling_exceeded = bool(env.get("ceiling_exceeded", env.get("degraded")))
    degraded = ceiling_exceeded or (elevated and collapsed)

    env["collapsed"] = collapsed
    env["collapse_reasons"] = collapse_reasons
    env["degraded"] = degraded

    suite = PASS
    if any(r["verdict"] == REGRESSION for r in rows):
        suite = REGRESSION
    if degraded:
        # Do NOT rewrite the individual verdicts — they are the raw observation. Only the
        # SUITE conclusion changes, because it is the conclusion that was never earned.
        suite = INCONCLUSIVE
        for r in rows:
            r["unreliable"] = True
    return {"rows": rows, "suite": suite, "environment": env}


def render(scorecard):
    lines = []
    rows = scorecard["rows"]
    by_scen = {}
    for r in rows:
        by_scen.setdefault(r["scenario"], []).append(r)
    for scen, rs in by_scen.items():
        lines.append(f"\n  {scen}")
        for r in rs:
            v, c = r["verdict"], r["cls"]
            col = _C.get(v, "")
            val = r["value"]
            base = r["baseline"]
            vs = f"{val:.3g}" if isinstance(val, float) else str(val)
            bs = "—" if base is None else (f"{base:.3g}" if isinstance(base, float) else str(base))
            lines.append(f"    [{col}{v:<11}{_RESET}] {c:<4} {r['name']:<32} {vs:>10}  (base {bs}, {r['direction']})")
    s = scorecard["suite"]
    env = scorecard.get("environment") or {}
    lines.append(f"\n  {'='*70}")
    lines.append(f"  SUITE: {_C.get(s,'')}{s}{_RESET}")
    if env.get("message"):
        lines.append(f"  ENVIRONMENT: {env['message']}")
    # Name the collapsed metrics. "INCONCLUSIVE" without them just looks like the suite
    # giving up; with them the reader can see the retrieval-died signature for themselves.
    if env.get("collapsed"):
        lines.append("  RETRIEVAL COLLAPSE — measured quantities fell to nothing:")
        for reason in env.get("collapse_reasons", []):
            lines.append(f"      {reason}")
    # Per-scenario attribution, so the NEXT volume decision is made from data instead of from
    # reading timestamp clusters out of a log after the fact.
    per_scen = env.get("per_scenario") or {}
    if per_scen:
        worst = max(per_scen.values(), key=lambda v: v["throttle_events"])["throttle_events"]
        lines.append("  THROTTLE BY SCENARIO (events / repeats):")
        for name, info in sorted(per_scen.items(),
                                 key=lambda kv: -kv[1]["throttle_events"]):
            n, r = info["throttle_events"], info["repeats"]
            bar = "#" * min(40, (n * 40 // worst) if worst else 0)
            lines.append(f"    {name:<24} {n:5}  (x{r})  {bar}")
    if s == INCONCLUSIVE:
        lines.append("  The verdicts above are RAW OBSERVATIONS, not conclusions: under this much")
        lines.append("  throttling an empty result is indistinguishable from a real regression.")
        lines.append("  This run MUST NOT be used as a baseline. Re-run when retrieval is healthy.")
    imps = [r for r in rows if r["verdict"] == IMPROVEMENT]
    warns = [r for r in rows if r["verdict"] == WARN]
    if imps:
        lines.append(f"  IMPROVEMENTS: {', '.join(key(r['scenario'], r['name']) for r in imps)}")
    if warns:
        lines.append(f"  ENV WARNINGS (world changed, not a code regression): "
                     f"{', '.join(key(r['scenario'], r['name']) for r in warns)}")
    return "\n".join(lines)
