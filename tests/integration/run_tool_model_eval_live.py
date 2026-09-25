#!/usr/bin/env python3
"""
LIVE TOOL-MODEL EVALUATION — can a candidate tool-calling model replace the incumbent
without losing ACCURACY (right tools) or COMPLETENESS (every requested part answered)?

Each case goes through the running server's /v1 endpoint with the FULL tool catalogue
(no allowed_tools filter) and a per-request `tools_calling_model`, so the only variable
between arms is the tool model. Every arm runs every case N times, arms interleaved.

Scored per request:
  tools_ok      every REQUIRED tool family was called (any round)
  precision_ok  nothing outside the ACCEPTABLE set was called (the date tool is always fine)
  answer_ok     the final answer contains each requested part — numbers are checked against
                ground truth computed independently of any model
  rounds / tool-model calls / input + output tokens / latency   (cost)
  leak          calls made by a DIFFERENT tool model than the arm's (per-request override ignored)

Tool names come from the log's `OLLAMA TOOL CALLS` lines for that request; tokens from the
tool model's own `prompt_eval_count` / `eval_count`.

    python tests/integration/run_tool_model_eval_live.py --arms glm-5.3:cloud,deepseek-v4.1-flash:cloud --runs 3
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.argv, _argv = sys.argv[:1], sys.argv          # the sanity module parses nothing, but be safe
import run_model_sanity_live as S                 # noqa: E402  (log helpers, config)
sys.argv = _argv

DATE_TOOL = "get_the_secret_tool"                  # temporal context; acceptable on any case
STOCK = {"get_stock_and_company_data", "comprehensive_stock_analyzer"}
CALC = {"calculator", "compute", "sandboxed_executor", "process_executor"}
NEWS = {"get_news_summaries", "search_web", "lookup_website"}
PAPERS = {"published_papers_search", "search_research_papers", "search_web"}


def has(*words):
    return lambda a: all(w.lower() in a.lower() for w in words)


def num(n):
    """The answer states the number n (commas ignored)."""
    return lambda a: re.search(rf"(?<![\d.]){re.escape(str(n))}(?![\d])", a.replace(",", "")) is not None


TEMP = lambda a: re.search(r"-?\d+(\.\d+)?\s*(°|degrees|deg\b)", a, re.I) is not None  # noqa: E731
WEATHER = {"weather_info", "search_web", "lookup_website"}    # any tool that can FETCH current weather


def urls(k):
    return lambda a: len(set(re.findall(r"https?://[^\s)\]>\"']+", a))) >= k


def all_of(*checks):
    return lambda a: all(c(a) for c in checks)


# (id, prompt, required tool FAMILIES (each a set; one member must be called),
#  acceptable tools, answer check)
CASES = [
    ("weather", "What's the weather in Paris right now?",
     [WEATHER], WEATHER, all_of(has("paris"), TEMP)),
    ("stock_price", "What is Apple's current stock price?",
     [STOCK], STOCK | {"search_web"}, all_of(has("$"), lambda a: "apple" in a.lower() or "aapl" in a.lower())),
    ("compound_interest", "Compute the value of $5,000 invested at 4.5% annual interest for 7 years, compounded monthly.",
     [CALC], CALC, num("6847.26")),
    ("code_primes", "Write and run Python code to find the 25th prime number and the sum of the first 100 prime numbers.",
     [CALC], CALC, all_of(num(97), num(24133))),
    ("wikipedia", "Summarize the Wikipedia article on the Treaty of Westphalia.",
     [{"wikipedia_query", "search_web"}], {"wikipedia_query", "search_web", "lookup_website"}, num(1648)),
    ("news", "What are the latest news headlines about the Federal Reserve? Include source links.",
     [NEWS], NEWS | {"wikipedia_query"}, all_of(has("fed"), urls(2))),
    ("papers", "Find recent research papers on CRISPR base editing.",
     [PAPERS], PAPERS | {"lookup_website", "wikipedia_query"}, all_of(has("crispr"), urls(1))),
    ("website", "What does https://www.python.org/about/ say about Python?",
     [{"lookup_website"}], {"lookup_website", "search_web"}, has("python")),
    ("sec", "Show me information from Tesla's latest 10-K filing.",
     [{"get_sec_filings"}], {"get_sec_filings", "search_web", "get_stock_and_company_data", "lookup_website"},
     all_of(has("10-k"), lambda a: "tesla" in a.lower() or "tsla" in a.lower())),
    ("flights", "Search for flights from New York to London next Friday.",
     [{"flight_search"}], {"flight_search", "search_web"}, has("london")),
    ("deep_stock", "Give me a detailed investment analysis of NVIDIA including a DCF valuation.",
     [{"comprehensive_stock_analyzer"}], STOCK | {"search_web", "get_news_summaries", "compute", "calculator"},
     all_of(has("dcf"), lambda a: "nvidia" in a.lower() or "nvda" in a.lower())),
    ("multi_part", "Give me the current weather in Tokyo, Microsoft's current stock price, and the square root of 7921.",
     [WEATHER, STOCK], WEATHER | STOCK | CALC,
     all_of(has("tokyo"), TEMP, lambda a: "microsoft" in a.lower() or "msft" in a.lower(), num(89))),
    ("multi_research", "Compare the populations of Canada and Australia and cite a source for each.",
     [{"wikipedia_query", "search_web"}], {"wikipedia_query", "search_web", "lookup_website", "compute", "calculator"},
     all_of(has("canada"), has("australia"), urls(1))),
    ("no_tool", "Hi! How are you today?",
     [], set(), lambda a: len(a.strip()) > 0),
]


def run_case(arm, prompt):
    mark = S.log_mark()
    t0 = time.time()
    payload = {"prompt": prompt, "model": S.CFG["llm"]["primary"]["config"]["model"], "toolsInUse": True,
               "deep_research": False, "tools_calling_model": arm}
    req = urllib.request.Request(S.SERVER + "/v1", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=900).read().decode("utf-8", "replace")
    latency = round(time.time() - t0, 1)
    answer = "".join((json.loads(l).get("response", "") if l.strip().startswith("{") else "")
                     for l in raw.splitlines())
    lg = S.log_since(mark)
    called = set()
    for line in lg.splitlines():
        if "OLLAMA TOOL CALLS:" in line:
            called |= set(re.findall(r"'name': '([A-Za-z0-9_]+)'", line))
    name = arm.split(":")[0]
    tool_models = {"glm-5.3", "glm-5.2", "deepseek-v4.1-flash", name}
    per_model = {}
    for line in lg.splitlines():
        m = re.search(r"OLLAMA RAW RESPONSE: \{'model': '([^']+)'", line)
        if m and m.group(1) in tool_models:
            c = per_model.setdefault(m.group(1), [0, 0, 0])
            c[0] += 1
            c[1] += sum(int(x) for x in re.findall(r"'prompt_eval_count': (\d+)", line))
            c[2] += sum(int(x) for x in re.findall(r"'eval_count': (\d+)", line))
    own = per_model.get(name, [0, 0, 0])
    leak = sum(v[0] for k, v in per_model.items() if k != name)
    if "usage limit" in lg or "API error 429" in lg:
        # The model account is shared with PRODUCTION: a usage-limit reply means this run is now
        # spending live's budget. Stop everything rather than finish the matrix.
        print("\nABORT: provider usage limit hit -- stopping so production keeps its quota.", flush=True)
        sys.exit(3)
    return {"latency": latency, "answer": answer, "called": called, "rounds": lg.count(f"Tool calling request: {arm}"),
            "calls": own[0], "tok_in": own[1], "tok_out": own[2], "leak": leak}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="glm-5.3:cloud,deepseek-v4.1-flash:cloud")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    arms = a.arms.split(",")
    cases = [c for c in CASES if not a.only or c[0] in a.only.split(",")]
    rows = []
    for r in range(a.runs):
        for case_id, prompt, required, acceptable, check in cases:
            order = arms if (r + len(rows)) % 2 == 0 else arms[::-1]
            for arm in order:
                try:
                    res = run_case(arm, prompt)
                except Exception as e:  # noqa: BLE001 -- a failed request is a scored failure
                    res = {"latency": None, "answer": "", "called": set(), "rounds": 0, "calls": 0,
                           "tok_in": 0, "tok_out": 0, "leak": 0, "error": str(e)[:200]}
                called = res["called"] - {DATE_TOOL}
                tools_ok = all(called & fam for fam in required) if required else True
                precision_ok = called <= acceptable
                answer_ok = bool(res["answer"]) and check(res["answer"])
                row = {"arm": arm, "case": case_id, "run": r, "tools_ok": tools_ok, "precision_ok": precision_ok,
                       "answer_ok": answer_ok, "called": sorted(res["called"]),
                       **{k: res[k] for k in ("latency", "rounds", "calls", "tok_in", "tok_out", "leak")},
                       "error": res.get("error"), "answer_tail": res["answer"].strip()[-160:]}
                rows.append(row)
                print(f"EV {arm:26} {case_id:17} r{r} tools={'✓' if tools_ok else '✗'} "
                      f"prec={'✓' if precision_ok else '✗'} answer={'✓' if answer_ok else '✗'} "
                      f"lat={row['latency']} calls={row['calls']} out={row['tok_out']} leak={row['leak']} "
                      f"called={row['called']}" + (f" ERR={row['error']}" if row.get("error") else ""), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1))

    print("\nSUMMARY (per arm)")
    for arm in arms:
        rs = [x for x in rows if x["arm"] == arm]
        n = len(rs)
        lat = sorted(x["latency"] for x in rs if x["latency"] is not None)
        print(f"  {arm:26} tools {sum(x['tools_ok'] for x in rs)}/{n}  precision {sum(x['precision_ok'] for x in rs)}/{n}"
              f"  answers {sum(x['answer_ok'] for x in rs)}/{n}  median_latency {lat[len(lat)//2] if lat else None}s"
              f"  tool_calls {sum(x['calls'] for x in rs)}  tok_in {sum(x['tok_in'] for x in rs)}"
              f"  tok_out {sum(x['tok_out'] for x in rs)}  leaks {sum(x['leak'] for x in rs)}")
    print("\nPER CASE (answers ok / tools ok, per arm)")
    for case_id, *_ in cases:
        cells = []
        for arm in arms:
            rs = [x for x in rows if x["arm"] == arm and x["case"] == case_id]
            cells.append(f"{arm.split(':')[0]} {sum(x['answer_ok'] for x in rs)}/{len(rs)} ans, "
                         f"{sum(x['tools_ok'] for x in rs)}/{len(rs)} tools")
        print(f"  {case_id:17} " + "  |  ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
