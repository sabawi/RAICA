#!/usr/bin/env python3
"""
Phase 3a BASELINE harness — runs BOTH intent classifiers (legacy keyword `_verify_task_completion`
and the LLM `orchestration.intent.classify_intent_actions`) against the labeled eval corpus and scores
each against GROUND TRUTH. See docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md (Phase 3).

This is a STANDALONE script (not pytest) because it makes real LLM calls. It does NOT change any
behavior — it only measures, to decide per-category cutover and to drive intent-prompt tuning.

RUN:  venv/bin/python3 tests/utilities/run_intent_eval.py
OUT:  prints a per-category + per-case report; writes full results to tests/data/intent_eval_results.jsonl
"""
import os
import sys
import json
import asyncio
from collections import defaultdict

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fastapi_server_complete as F            # noqa: E402
from orchestration import intent as _intent     # noqa: E402
from research.engine import _collect_stream     # noqa: E402
sys.path.insert(0, os.path.join(_ROOT, "tests", "data"))
sys.path.insert(0, os.path.join(_ROOT, "tests", "utilities"))
from intent_eval_corpus import CASES            # noqa: E402
from intent_eval_scoring import delivery_kinds as _delivery_kinds  # noqa: E402

RESULTS_PATH = os.path.join(_ROOT, "tests", "data", "intent_eval_results.jsonl")
SHADOW_MODEL = "deepseek-v4-flash:cloud"
CONCURRENCY = 5
RUNS = int(os.environ.get("EVAL_RUNS", "1"))   # run the LLM N times per case to measure stability


async def _collect(prompt, system_prompt, max_tokens):
    return await _collect_stream(F.llm_manager.generate_stream, prompt, system_prompt=system_prompt,
                                 temperature=0.0, max_tokens=max_tokens, stream=False, model=SHADOW_MODEL)


async def _eval_case(case, catalog, sem):
    truth_needs = bool(case["truth_delivery"])
    truth_kinds = set(case["truth_kinds"])

    # Legacy (deterministic) — pre-execution baseline (tools_called=[])
    legacy = await F._verify_task_completion(case["prompt"], [], "", None)
    legacy_needs = not legacy.get("complete", True)
    legacy_kinds = _delivery_kinds(legacy.get("missing_tools"))

    # LLM — run RUNS times to measure stability (full-mode needs EVERY run correct)
    runs = []
    last_tools = []
    for _ in range(RUNS):
        async with sem:
            r = await _intent.classify_intent_actions(_collect, catalog, case["prompt"])
        last_tools = r.get("tools")
        runs.append((bool(r.get("needs_delivery")), frozenset(_delivery_kinds(r.get("tools")))))
    stable = len(set(runs)) == 1
    # worst-case correctness: every run must match truth (decision + kinds)
    worst_ok = all((nd == truth_needs) and (kf == frozenset(truth_kinds)) for nd, kf in runs)
    rep_needs, rep_kinds = runs[0]

    return {
        "id": case["id"], "category": case["category"], "note": case.get("note", ""),
        "runs": RUNS,
        "truth": {"needs": truth_needs, "kinds": sorted(truth_kinds)},
        "legacy": {"needs": legacy_needs, "kinds": sorted(legacy_kinds),
                   "needs_ok": legacy_needs == truth_needs, "kinds_ok": legacy_kinds == truth_kinds,
                   "raw_missing": legacy.get("missing_tools"), "pattern": legacy.get("pattern")},
        "llm": {"needs": rep_needs, "kinds": sorted(rep_kinds),
                "needs_ok": rep_needs == truth_needs, "kinds_ok": set(rep_kinds) == truth_kinds,
                "stable": stable, "worst_ok": worst_ok,
                "distinct_results": [[nd, sorted(kf)] for nd, kf in set(runs)],
                "raw_tools": last_tools, "ok": True},
    }


async def main():
    defs = await F.tool_manager.get_tools_definitions()
    catalog = [{"name": d.get("function", {}).get("name", ""),
                "description": d.get("function", {}).get("description", "")}
               for d in defs if d.get("function", {}).get("name")]
    registered = sorted(t["name"] for t in catalog)
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*[_eval_case(c, catalog, sem) for c in CASES])

    with open(RESULTS_PATH, "w") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")

    # ── Report ────────────────────────────────────────────────────────────────────────────────
    def pct(n, d):
        return f"{100.0*n/d:5.1f}%" if d else "  n/a"

    print("\n" + "=" * 100)
    print(f"INTENT CLASSIFIER BASELINE  —  {len(results)} cases  —  registered tools: {registered}")
    print("=" * 100)
    print(f"{'id':22} {'category':12} {'truth':16} {'LEGACY needs/kinds':26} {'LLM needs/kinds':26}")
    print("-" * 100)
    for r in results:
        t = f"{r['truth']['needs']!s:5} {','.join(r['truth']['kinds']) or '-'}"
        lg = (f"{r['legacy']['needs']!s:5} {','.join(r['legacy']['kinds']) or '-':10} "
              f"{'✓' if r['legacy']['needs_ok'] and r['legacy']['kinds_ok'] else '✗'}")
        lm = (f"{r['llm']['needs']!s:5} {','.join(r['llm']['kinds']) or '-':10} "
              f"{'✓' if r['llm']['needs_ok'] and r['llm']['kinds_ok'] else '✗'}")
        print(f"{r['id']:22} {r['category']:12} {t:16} {lg:26} {lm:26}")

    # Aggregates
    n = len(results)
    lg_needs = sum(r["legacy"]["needs_ok"] for r in results)
    lm_needs = sum(r["llm"]["needs_ok"] for r in results)
    lg_kinds = sum(r["legacy"]["needs_ok"] and r["legacy"]["kinds_ok"] for r in results)
    lm_kinds = sum(r["llm"]["needs_ok"] and r["llm"]["kinds_ok"] for r in results)
    lm_worst = sum(r["llm"]["worst_ok"] for r in results)
    lm_stable = sum(r["llm"]["stable"] for r in results)
    print("-" * 100)
    print(f"OVERALL  delivery-decision correct:  LEGACY {pct(lg_needs,n)} ({lg_needs}/{n})   "
          f"LLM {pct(lm_needs,n)} ({lm_needs}/{n})")
    print(f"OVERALL  full (decision+kinds) match: LEGACY {pct(lg_kinds,n)} ({lg_kinds}/{n})   "
          f"LLM {pct(lm_kinds,n)} ({lm_kinds}/{n})")
    print(f"OVERALL  LLM stability ({RUNS} runs/case): all-runs-correct {pct(lm_worst,n)} ({lm_worst}/{n})   "
          f"stable(identical across runs) {pct(lm_stable,n)} ({lm_stable}/{n})")

    # Per-category delivery-decision accuracy
    by_cat = defaultdict(lambda: {"n": 0, "lg": 0, "lm": 0})
    for r in results:
        c = by_cat[r["category"]]
        c["n"] += 1
        c["lg"] += r["legacy"]["needs_ok"]
        c["lm"] += r["llm"]["needs_ok"]
    print("\nPER-CATEGORY  delivery-decision correct (legacy | llm):")
    for cat in sorted(by_cat):
        c = by_cat[cat]
        print(f"  {cat:14} n={c['n']:2}   legacy {pct(c['lg'],c['n'])}   llm {pct(c['lm'],c['n'])}")

    # Disagreement / failure spotlight
    print("\nCASES WHERE LEGACY IS WRONG vs TRUTH (delivery decision):")
    for r in results:
        if not r["legacy"]["needs_ok"]:
            print(f"  ✗ {r['id']:22} truth={r['truth']['needs']} legacy={r['legacy']['needs']} "
                  f"(pattern={r['legacy']['pattern']}) — {r['note']}")
    print(f"\nCASES WHERE LLM IS WRONG or UNSTABLE across {RUNS} run(s):")
    for r in results:
        if not (r["llm"]["worst_ok"] and r["llm"]["stable"]):
            flag = "WRONG" if not r["llm"]["worst_ok"] else "UNSTABLE"
            print(f"  ✗ [{flag}] {r['id']:22} truth=({r['truth']['needs']},{r['truth']['kinds']}) "
                  f"llm_runs={r['llm']['distinct_results']} tools={r['llm']['raw_tools']} — {r['note']}")
    print(f"\nFull results → {RESULTS_PATH}\n")


if __name__ == "__main__":
    asyncio.run(main())
