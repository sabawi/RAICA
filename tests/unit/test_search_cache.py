"""Regression (SI-055, volume half): repeated benchmark runs must stop rate-limiting themselves.

FAILURE THIS PREVENTS
---------------------
v1.0.0.291 made a throttled run report INCONCLUSIVE instead of a false CODE regression. That
stopped the lie but not the traffic, so a repeated A/B still degraded itself:

    run          throttle
    p1_glm            84      PASS
    p1_flash         141      PASS
    p2_glm           226      INCONCLUSIVE   <- unusable
    p2_flash         141      (valid)
    p3_glm           152      INCONCLUSIVE   <- unusable
    p3_flash         142      PASS

Two of six runs could not be used, leaving an unbalanced comparison (GLM n=1 vs Flash n=3).
Spacing does not fix it: at 12-18 minutes apart the counts do not trend down, and the only
low reading in the session followed a ~12-HOUR idle.

WHAT THE MEASUREMENTS RULED OUT
-------------------------------
  * engine fan-out: ddgs uses max_workers = min(providers, ceil(max_results/10)+1) = 2 for
    our max_results=3, escalating only on failure. Trimming engines cuts RESULTS, not 429s.
  * within-run caching: only 14% of one run's queries repeat.
  * ACROSS runs: 395 of 587 queries repeat — 67%. That is the lever, and it is exactly the
    A/B workflow (re-running the same scenarios issues the same queries).

SAFETY
------
Serving stale search results in production would silently stop news, prices and citations
being current. So the cache is inert unless RAICA_SEARCH_CACHE_DIR is set, and the server
declares it loudly at startup so a cached run can never be mistaken for a live one.
"""
import os

import pytest

from utils import search_cache as SC


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("RAICA_SEARCH_CACHE_DIR", raising=False)
    monkeypatch.delenv("RAICA_SEARCH_CACHE_TTL", raising=False)
    SC.reset_stats()
    yield
    SC.reset_stats()


def test_disabled_by_default_so_production_never_serves_stale_results():
    """THE safety property. Off unless explicitly switched on."""
    assert SC.enabled() is False
    SC.put("q", 3, "fresh")
    assert SC.get("q", 3) is None, "the cache stored/served a result while disabled"


def test_enabled_only_by_the_explicit_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(tmp_path))
    assert SC.enabled() is True


def test_a_repeated_query_is_served_from_cache(tmp_path, monkeypatch):
    """The 67%: the same query across runs must not hit the network twice."""
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(tmp_path))
    SC.put("earthquake catalog 2026", 3, "RESULT-BODY")
    assert SC.get("earthquake catalog 2026", 3) == "RESULT-BODY"
    assert SC.stats()["hits"] == 1


def test_distinct_queries_do_not_collide(tmp_path, monkeypatch):
    """A cache that confuses two queries would corrupt every downstream answer."""
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(tmp_path))
    SC.put("KO stock news", 3, "KO")
    SC.put("JPM stock news", 3, "JPM")
    assert SC.get("KO stock news", 3) == "KO"
    assert SC.get("JPM stock news", 3) == "JPM"


def test_max_results_is_part_of_the_key(tmp_path, monkeypatch):
    """Asking for more results must not be answered from a smaller cached set."""
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(tmp_path))
    SC.put("q", 3, "three")
    assert SC.get("q", 10) is None


def test_expired_entries_are_not_served(tmp_path, monkeypatch):
    """A measurement session, not a permanent store."""
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RAICA_SEARCH_CACHE_TTL", "0")
    SC.put("q", 3, "stale")
    assert SC.get("q", 3) is None


def test_a_broken_cache_never_breaks_a_search(tmp_path, monkeypatch):
    """An optimisation must fail open — a search must still happen."""
    bad = tmp_path / "not-a-dir"
    bad.write_text("i am a file")
    monkeypatch.setenv("RAICA_SEARCH_CACHE_DIR", str(bad))
    assert SC.get("q", 3) is None          # no raise
    SC.put("q", 3, "x")                    # no raise


def test_the_server_declares_the_cache_at_startup():
    """A cached run must never look like a live one to whoever reads the log."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "fastapi_server_complete.py")).read()
    assert "SEARCH CACHE ENABLED" in src, "the server does not declare the cache state"


def test_search_web_consults_the_cache_before_the_network():
    """The hook must sit BEFORE the outbound call, or it saves nothing."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "fastapi_server_complete.py")).read()
    i_def = src.index("def ducducgo(")
    i_get = src.index("_sc.get(query, max_results)", i_def)
    i_ddgs = src.index("from ddgs import DDGS", i_def)
    assert i_get < i_ddgs, "the cache is consulted only AFTER the network call"
