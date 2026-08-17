# CHANGELOG v1.0.0.295 — SI-055 volume half: repeated runs stop rate-limiting themselves

**Date:** 2026-08-16 · **Against:** v1.0.0.294

## The remaining half

v1.0.0.291 made a throttled run report **INCONCLUSIVE** instead of a false CODE regression.
That stopped the lie; it did not reduce the traffic. A real A/B then lost **2 of 6 runs**:

| run | throttle | suite |
|---|---|---|
| p1 GLM | 84 | PASS |
| p1 Flash | 141 | PASS |
| p2 GLM | **226** | **INCONCLUSIVE** |
| p2 Flash | 141 | REGRESSION (PERF only) |
| p3 GLM | **152** | **INCONCLUSIVE** |
| p3 Flash | 142 | PASS |

Leaving GLM n=1 against Flash n=3 — not a comparison.

## What the measurements ruled OUT before anything was built

- **Spacing.** At 12–18 min between runs the counts do not trend down (141, 226, 141, 152,
  142). The only low reading (84) followed a **~12-hour** idle, so 20–30 min was never going
  to be enough.
- **Engine fan-out.** ddgs computes `max_workers = min(providers, ceil(max_results/10)+1)`,
  which is **2** for our `max_results=3`; it escalates to the other engines only when those
  fail. Trimming the engine list would cut RESULTS, not 429s.
- **Within-run caching.** Only **14%** of a single run's queries repeat — I assumed this was
  the lever and it was not.

## What it IS

**Across runs, 395 of 587 queries repeat — 67%**, because re-running the same scenarios
issues the same queries. That is exactly the A/B workflow, and that is the lever.

`utils/search_cache.py`: an opt-in on-disk cache consulted **before** the outbound call in
`search_web`. Measured on the real path: **5.58s → 0.00s**, byte-identical search body (the
only difference is the freshly regenerated timestamp in the wrapper, which is correct).

## Safety — why it cannot leak into production

- Inert unless `RAICA_SEARCH_CACHE_DIR` is set. Disabled, `put()` stores nothing and `get()`
  returns nothing.
- The **server declares it at startup** (`🗂️ SEARCH CACHE ENABLED: …`) at WARNING level, and
  the benchmark reads that line rather than its own environment — the cache lives in the
  server process, so the runner's env says nothing about it. Reporting a cache that was not
  actually on would be worse than not reporting one.
- TTL-bounded (24h default): a measurement session, not a permanent store.
- Fails open: a broken cache directory never breaks a search.

**Honest trade-off, stated in the runbook:** a cached run measures the pipeline against FIXED
retrieval, so it cannot detect a live-search regression. Use it for model A/Bs — where fixing
retrieval removes the variance that made `unique_sources` look like +46% on one run and
*identical* at n=3 — and unset it when validating retrieval itself.

## Verification

`tests/unit/test_search_cache.py` — 9 tests: off by default (the safety property), enabled
only by the env var, repeated query served from cache, distinct queries do not collide,
`max_results` is part of the key, expiry honoured, a broken cache never breaks a search, the
server declares it, and the hook sits **before** the network call rather than after.

Tier-0 **10/10**, unit **583 passed** (4 pre-existing unchanged), version sync 5/5.
