"""
Deterministic unit test for the v1.0.0.157 DR per-source `queries` normalization layer.

Proves (without any LLM call):
  1. Backward-compat: with per_source_queries=false (or no `queries` field) the normalized
     sub-question carries queries={} → Round 1 uses the sub-question text (v1.0.0.155 behavior).
  2. String-valued query is kept (single ticker call).
  3. List-valued query is kept (multi-stock → multiple calls under one sub-question).
  4. Only entries for sources actually assigned to the sub-question (and in the allowed list)
     survive; junk/unknown sources are dropped.
  5. Empty/whitespace arg strings are dropped.

NOTE (CLAUDE.md): this tests the normalization DATA shape only — it does NOT verify the live
dispatch. The end-to-end proof is the live multi-stock prompt against the running server.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from research.engine import ResearchPlanner

ALLOWED = ["search_web", "comprehensive_stock_analyzer", "get_stock_and_company_data"]


def _planner(per_source_queries: bool) -> ResearchPlanner:
    cfg = {
        "sources": {"allowed": ALLOWED},
        "planner": {"max_sub_questions": 6, "per_source_queries": per_source_queries},
        "loop": {"max_rounds_ceiling": 4},
    }
    return ResearchPlanner(generate_stream=None, engine_config=cfg)


def _norm(plan, psq=True):
    return _planner(psq)._normalize(plan)


def test_flag_off_ignores_queries():
    plan = {"sub_questions": [{
        "id": "q1", "question": "value PLTR",
        "sources": ["comprehensive_stock_analyzer"],
        "queries": {"comprehensive_stock_analyzer": '{"ticker":"PLTR","detailed":true}'},
        "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=False)
    sq = out["sub_questions"][0]
    assert sq["queries"] == {}, f"flag off must yield queries={{}}, got {sq['queries']}"
    assert sq["sources"] == ["comprehensive_stock_analyzer"]
    print("PASS test_flag_off_ignores_queries")


def test_no_queries_field_is_empty():
    plan = {"sub_questions": [{
        "id": "q1", "question": "value PLTR",
        "sources": ["search_web"], "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=True)
    assert out["sub_questions"][0]["queries"] == {}
    print("PASS test_no_queries_field_is_empty")


def test_string_query_kept():
    plan = {"sub_questions": [{
        "id": "q1", "question": "value PLTR",
        "sources": ["comprehensive_stock_analyzer"],
        "queries": {"comprehensive_stock_analyzer": '{"ticker":"PLTR","detailed":true}'},
        "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=True)
    q = out["sub_questions"][0]["queries"]
    assert q == {"comprehensive_stock_analyzer": ['{"ticker":"PLTR","detailed":true}']}, q
    print("PASS test_string_query_kept")


def test_list_query_multi_stock():
    plan = {"sub_questions": [{
        "id": "q1", "question": "compare PLTR MSFT GOOGL valuations",
        "sources": ["comprehensive_stock_analyzer"],
        "queries": {"comprehensive_stock_analyzer": [
            '{"ticker":"PLTR","detailed":true}',
            '{"ticker":"MSFT","detailed":true}',
            '{"ticker":"GOOGL","detailed":true}',
        ]},
        "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=True)
    q = out["sub_questions"][0]["queries"]
    assert len(q["comprehensive_stock_analyzer"]) == 3, q
    assert q["comprehensive_stock_analyzer"][1] == '{"ticker":"MSFT","detailed":true}', q
    print("PASS test_list_query_multi_stock")


def test_unknown_source_dropped_from_queries():
    plan = {"sub_questions": [{
        "id": "q1", "question": "value PLTR",
        "sources": ["comprehensive_stock_analyzer"],
        "queries": {
            "comprehensive_stock_analyzer": '{"ticker":"PLTR"}',
            "bogus_tool": '{"x":1}',                 # not in this sub-question's sources
            "search_web": "PLTR valuation",          # not assigned to this sub-question
        },
        "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=True)
    q = out["sub_questions"][0]["queries"]
    assert list(q.keys()) == ["comprehensive_stock_analyzer"], q
    print("PASS test_unknown_source_dropped_from_queries")


def test_empty_args_dropped():
    plan = {"sub_questions": [{
        "id": "q1", "question": "value PLTR",
        "sources": ["comprehensive_stock_analyzer", "search_web"],
        "queries": {"comprehensive_stock_analyzer": ["  ", "", '{"ticker":"PLTR"}']},
        "priority": 1,
    }], "max_rounds": 2, "min_rounds": 1, "stop_condition": "x"}
    out = _norm(plan, psq=True)
    q = out["sub_questions"][0]["queries"]
    assert q == {"comprehensive_stock_analyzer": ['{"ticker":"PLTR"}']}, q
    print("PASS test_empty_args_dropped")


if __name__ == "__main__":
    test_flag_off_ignores_queries()
    test_no_queries_field_is_empty()
    test_string_query_kept()
    test_list_query_multi_stock()
    test_unknown_source_dropped_from_queries()
    test_empty_args_dropped()
    print("\n✅ All per-source-queries normalize tests passed")