#!/usr/bin/env python3
"""
RAICA Quality & Performance Benchmark — runner.

Design + decisions: docs/RAICA_QUALITY_BENCHMARK.md
Policy: run before committing a change that touches a CORE workflow file (see the pre-commit hook,
tools/benchmark_precommit.sh). Locks in the hardened baseline; catches degradations; surfaces improvements.

Tiers:
  0  Deterministic gates (offline unit/contract tests) — FAST, blocks commits. IMPLEMENTED.
  1  Real-LLM golden scenarios vs baseline.json scorecard — ~15 min, local-by-default. (Phase B)
  2  Per-stage latency budgets parsed from logs.                                       (Phase C/with T1)

Pillars (so it isn't a flaky alarm):
  - assert on INVARIANTS, never exact LLM text
  - tag every metric CODE (our regression -> FAIL) vs ENV (model 410 / site 403 / news churn -> WARN)
  - baseline-as-data + deltas; baseline bumps only via --update-baseline --reason (never silent)
  - tiered cadence (T0 every commit; T1/T2 pre-deploy + nightly)

Usage:
  python tests/benchmark/run_benchmark.py            # Tier 0 (default)
  python tests/benchmark/run_benchmark.py --tier 0
  python tests/benchmark/run_benchmark.py --tier 1 [--live] [--repeats 3]      # Phase B
  python tests/benchmark/run_benchmark.py --tier all
Exit code: 0 = no CODE regression; 1 = a CODE regression (blocks the commit).
"""
import argparse
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BENCH_DIR)   # so `lib` and `scenarios` import even when run via the hook/subprocess

# ── Tier 0: deterministic offline gates (each file is a standalone script exiting 0 on pass) ──────────
# These are the locked-in behaviors as machine-checkable contracts. Keep this list in sync as we add
# deterministic guards. Paths are relative to the repo root.
TIER0_TESTS = [
    "tests/integration/test_citation_grounding.py",          # fabricated/rotted/valid classification
    "tests/integration/test_citation_source_filtering.py",   # homepages/sections/feeds not cited
    "tests/integration/test_citation_link_verification.py",  # lenient live verify (fail-open)
    "tests/integration/test_tool_calling_retry.py",          # tool-call 5xx/timeout retry, no-retry-4xx
    "tests/integration/test_dr_title_extraction.py",         # DR doc title != section heading
    "tests/integration/test_html_single_workflow_styling.py",# one HTML template + @media screen; PDF intact
    "tests/integration/test_vision_fallback.py",             # primary vision fail -> backup runs
    "tests/integration/test_delivery_failure_reporting.py",  # failed send reported as failed (no false ok)
    "tests/integration/test_lane_transport_consistency.py",  # SI-056: lane model must match its base_url
    "tests/integration/test_version_sync.py",                # version.py == README/logging_config//health
]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _run_script(rel_path):
    """Run one Tier-0 test script. Returns (ok: bool, seconds: float, tail: str)."""
    abs_path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.exists(abs_path):
        return False, 0.0, "FILE MISSING"
    t0 = time.time()
    proc = subprocess.run([sys.executable, abs_path], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    dt = time.time() - t0
    ok = proc.returncode == 0
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = ""
    for line in reversed(out.strip().splitlines()):
        if line.strip():
            tail = line.strip()[:80]
            break
    return ok, dt, tail


def run_tier0():
    print(f"\n{'='*78}\n  RAICA BENCHMARK — Tier 0 (deterministic gates)\n{'='*78}")
    results = []
    for rel in TIER0_TESTS:
        ok, dt, tail = _run_script(rel)
        results.append((rel, ok, dt, tail))
        mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
        name = os.path.basename(rel)
        print(f"  [{mark}] {name:<44} {dt:5.1f}s  {DIM}{tail}{RESET}")
    n_fail = sum(1 for _, ok, _, _ in results if not ok)
    total = len(results)
    print(f"{'-'*78}")
    if n_fail == 0:
        print(f"  {GREEN}Tier 0: {total}/{total} PASS — locked-in behaviors intact (no CODE regression).{RESET}\n")
        return 0
    print(f"  {RED}Tier 0: {n_fail}/{total} FAILED — a locked-in behavior regressed. Commit should be blocked.{RESET}")
    for rel, ok, _, tail in results:
        if not ok:
            print(f"     {RED}✗{RESET} {rel}  — {tail}")
    print()
    return 1


def run_tier1(live, repeats, update_baseline, reason):
    import json
    from datetime import datetime, timezone
    from lib import scoring as S
    from lib import raica_client as RC
    from scenarios import s1_news_citation, s2_dr_email_delivery, s3_vision, s4_multi_ticker_dr

    base = RC.LIVE_BASE if live else RC.LOCAL_BASE
    print(f"\n{'='*78}\n  RAICA BENCHMARK — Tier 1 (golden scenarios)  [{'LIVE' if live else 'LOCAL'} {base}]\n{'='*78}")
    SCENARIOS = [s1_news_citation, s3_vision, s2_dr_email_delivery, s4_multi_ticker_dr]  # S2 (DR) last — it's the slow one
    baseline_path = os.path.join(BENCH_DIR, "baseline.json")
    baseline = S.load_baseline(baseline_path)

    all_metrics = []
    for mod in SCENARIOS:
        reps = 1 if mod.SCENARIO in ("S2_dr_delivery", "S4_multi_ticker_dr") else repeats   # DR ~5 min: single run
        print(f"  ▶ {mod.SCENARIO}  (x{reps}) ...", flush=True)
        try:
            all_metrics.extend(S.median_runs(mod.run(base, reps)))
        except Exception as e:  # noqa: BLE001 — a scenario crash shouldn't lose the others
            print(f"    {RED}scenario {mod.SCENARIO} errored: {e}{RESET}")

    if update_baseline:
        S.save_baseline(baseline_path, all_metrics, reason, datetime.now(timezone.utc).isoformat())
        print(f"\n  {GREEN}baseline.json updated{RESET} ({len(all_metrics)} metrics) — reason: {reason}")
        baseline = S.load_baseline(baseline_path)

    sc = S.score_run(all_metrics, baseline)
    json.dump(sc, open(os.path.join(BENCH_DIR, "scorecard.json"), "w"), indent=2, default=str)
    print(S.render(sc))
    print()
    return 0 if sc["suite"] != S.REGRESSION else 1


def main():
    ap = argparse.ArgumentParser(description="RAICA quality/performance benchmark")
    ap.add_argument("--tier", choices=["0", "1", "2", "all"], default="0")
    ap.add_argument("--live", action="store_true", help="Tier 1/2: run against LIVE RAICA (default: local)")
    ap.add_argument("--repeats", type=int, default=3, help="Tier 1 runs per scenario (median); default 3")
    ap.add_argument("--update-baseline", action="store_true", help="rewrite baseline.json (requires --reason)")
    ap.add_argument("--reason", default="", help="why the baseline is being updated (mandatory with --update-baseline)")
    args = ap.parse_args()

    if args.update_baseline and not args.reason.strip():
        print(f"{RED}--update-baseline requires --reason '<why>' (baseline bumps are never silent).{RESET}")
        return 2

    rc = 0
    if args.tier in ("0", "all"):
        rc |= run_tier0()
    if args.tier in ("1", "all"):
        rc |= run_tier1(args.live, args.repeats, args.update_baseline, args.reason)
    # Tier 2 latency lands with Tier 1 (Phase C).
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main())
