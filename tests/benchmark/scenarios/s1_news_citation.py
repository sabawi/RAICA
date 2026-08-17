"""
S1 — News mention citation quality. Locks in: the tool model gathers real web evidence and cites SPECIFIC
article URLs (not homepages/sections), and they resolve. (glm-5.2 tool-selection + citation Layers 1-3.)
"""
from lib import raica_client as RC

SCENARIO = "S1_news_citation"
PROMPT = ("Give me a briefing on the latest breaking world news right now, with a clickable source URL "
          "(specific article headline as the link) for every item. End with 2-4 hashtags.")
TOOLS = ["search_web", "lookup_website", "wikipedia_query", "get_news_summaries", "get_stock_and_company_data"]


def _m(name, cls, value, unit, direction, tol):
    return {"scenario": SCENARIO, "name": name, "cls": cls, "value": value,
            "unit": unit, "direction": direction, "tolerance": tol}


def run(base, repeats=3):
    runs = []
    for _ in range(repeats):
        r = RC.post_v1(PROMPT, base=base, deep_research=False, allowed_tools=TOOLS, timeout=240)
        urls = r["urls"]
        runs.append(RC.unmeasured_if_no_response(r, [
            _m("citation_count",      "CODE", len(urls),                    "count",   "higher_better", 2),
            _m("specific_url_ratio",  "CODE", RC.specific_url_ratio(urls),  "ratio",   "higher_better", 0.15),
            _m("url_resolve_ratio",   "ENV",  RC.resolve_ratio(urls),       "ratio",   "higher_better", 0.25),
            _m("latency_s",           "PERF", r["latency_s"],               "seconds", "lower_better",  30),
        ]))
    return runs
