"""Opt-in on-disk cache for outbound web searches (SI-055, volume half).

WHY THIS EXISTS
---------------
The Tier-1 suite trips the search engines' own rate limiters, and the empty results that
follow used to be scored as CODE regressions. v1.0.0.291 made a throttled run report
INCONCLUSIVE instead of lying — but that only stopped the false verdict. It did not reduce
the traffic, so back-to-back runs still degrade: measured 84 -> 226 -> 141 -> 152 -> 142
throttle events across one A/B session, and TWO of six runs came back unusable.

Spacing does not fix it. At 12-18 minutes between runs the counts do not trend down; the only
low reading in the session followed a ~12-HOUR idle.

WHAT THE MEASUREMENTS SAID — and what they ruled OUT
----------------------------------------------------
  * engine fan-out is NOT the lever. ddgs computes
    `max_workers = min(providers, ceil(max_results/10)+1)`, which is 2 for our max_results=3;
    it escalates to the other engines only when those fail. Trimming the engine list would
    cut RESULTS, not 429s.
  * within-run caching is NOT the lever either: only 14% of a single run's queries repeat.
  * ACROSS runs, 395 of 587 queries repeat — **67%**. Re-running the same scenarios issues
    substantially the same queries, which is precisely the A/B workflow.

So the cache is session-scoped rather than run-scoped, and that is where the saving is.

SAFETY — why this is OFF unless explicitly enabled
--------------------------------------------------
Serving stale search results silently in production would be a correctness disaster: news,
prices and citations would quietly stop being current. So this does nothing at all unless
`RAICA_SEARCH_CACHE_DIR` names a directory. The benchmark runner sets it for the duration of
a measurement session and records in the scorecard that it did.

HONEST TRADE-OFF: with the cache on, the suite measures the PIPELINE against fixed retrieval
instead of live retrieval. For an A/B between two MODELS that is better — it removes the
retrieval variance that swamped every quality delta in the first comparison. But a cached run
cannot detect a live-search regression, so it is not a substitute for an uncached run.
"""
import hashlib
import json
import os
import time

_ENV_DIR = "RAICA_SEARCH_CACHE_DIR"
_ENV_TTL = "RAICA_SEARCH_CACHE_TTL"
_DEFAULT_TTL = 24 * 3600          # a measurement session, not a persistent store

_stats = {"hits": 0, "misses": 0, "writes": 0, "rejected_thin": 0}

# MINIMUM distinct sources a result must carry to be worth caching.
#
# A cache that stores a DEGRADED result is worse than no cache: it freezes one throttled
# moment and serves it to every subsequent run. Observed exactly that — a benchmark arm
# reported `citation_count 0` and `specific_url_ratio 0` because the cache had captured a
# single-source result and kept handing it back.
#
# The floor is DERIVED from the poisoned cache, not chosen. Source counts separated
# perfectly, with no overlap:
#     degraded (throttled) : 1 source,   440-1,590 chars   (only the wikipedia fallback
#                                                           survived; the rest were 429ed)
#     healthy              : 2-7 sources, 7,901-32,536 chars
# search_web queries several engines, so one surviving source is the signature of
# throttling rather than of a genuinely narrow query.
#
# A legitimately niche query that returns one source simply is not cached. That is the SAFE
# failure mode: it costs an extra live search, it can never poison a later run.
_MIN_SOURCES = int(os.getenv("RAICA_SEARCH_CACHE_MIN_SOURCES", "2"))


def _source_count(result) -> int:
    return str(result or "").count("CITATION URL:")


def enabled() -> bool:
    return bool(os.getenv(_ENV_DIR))


def _path(key: str):
    d = os.getenv(_ENV_DIR)
    if not d:
        return None
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return os.path.join(d, key + ".json")


def _key(query: str, max_results) -> str:
    raw = f"{(query or '').strip().lower()}|{max_results}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


def get(query, max_results):
    """Cached result for this query, or None. Never raises — a cache must not break a search."""
    if not enabled():
        return None
    p = _path(_key(query, max_results))
    if not p or not os.path.exists(p):
        _stats["misses"] += 1
        return None
    try:
        with open(p) as fh:
            rec = json.load(fh)
        ttl = int(os.getenv(_ENV_TTL, _DEFAULT_TTL))
        if time.time() - rec.get("stored_at", 0) > ttl:
            _stats["misses"] += 1
            return None
        _stats["hits"] += 1
        return rec.get("result")
    except Exception:                                    # noqa: BLE001
        _stats["misses"] += 1
        return None


def put(query, max_results, result):
    """Store a result. A failure here is silent by design — caching is an optimisation.

    REFUSES to store a thin result (see _MIN_SOURCES): freezing a throttled moment and
    replaying it is the one way a cache can make the system WORSE than having none.
    """
    if not enabled() or not result:
        return
    if _source_count(result) < _MIN_SOURCES:
        _stats["rejected_thin"] += 1
        return
    p = _path(_key(query, max_results))
    if not p:
        return
    try:
        with open(p, "w") as fh:
            json.dump({"query": query, "max_results": max_results,
                       "stored_at": time.time(), "result": result}, fh)
        _stats["writes"] += 1
    except Exception:                                    # noqa: BLE001
        pass


def stats():
    """(hits, misses, writes) since process start — reported so a cached run is never silent."""
    return dict(_stats)


def reset_stats():
    _stats.update({"hits": 0, "misses": 0, "writes": 0, "rejected_thin": 0})
