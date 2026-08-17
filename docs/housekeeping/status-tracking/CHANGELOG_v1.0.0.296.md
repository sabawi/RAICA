# CHANGELOG v1.0.0.296 — the search cache was poisoning itself; and why the A/B is still blocked

**Date:** 2026-08-16 · **Against:** v1.0.0.295

## A cache that stores a throttled result is worse than no cache

The first cached A/B arm reported `citation_count 0` and `specific_url_ratio 0` — at **133**
throttle events, i.e. *under* the threshold, so the run was NOT flagged degraded and the
number looked real. The uncached run had scored 14.

Inspecting the cache explained it. Entries separated with **no overlap**:

| | sources | size |
|---|---|---|
| degraded (throttled) | **1** | 440–1,590 chars |
| healthy | **2–7** | 7,901–32,536 chars |

Fourteen entries held a *single* source — the `wikipedia` engine surviving while the others
were 429ed. The `if not result` guard only rejected EMPTY strings, so a thin-but-non-empty
result was stored and replayed to every subsequent run. **That is the one way a cache can make
the system worse than having none**: it converts one bad minute into a permanent fixture.

**Fix:** `put()` refuses any result below `_MIN_SOURCES` (default 2, env-tunable), derived
from that separation. A genuinely narrow query simply is not cached — the safe failure mode:
it costs a live search, it can never poison a later run. The 17 poisoned entries were purged.

Two of the module's own earlier tests then failed, using fixtures like `"RESULT-BODY"` with
zero citation markers. **The fixtures were wrong, not the floor** — a real search result never
looks like that — so they now use realistic multi-source bodies.

## Why the A/B is still blocked — and it is not fixable by caching

With the poison-proof cache the balanced 3v3 was restarted. Both R1 arms came back
**INCONCLUSIVE** (GLM 228, Flash 231). Per-scenario attribution says why:

| scenario | GLM | Flash |
|---|---|---|
| S1_news_citation | 6 | 2 |
| S3_vision | 0 | 0 |
| S2_dr_delivery | 82 | 67 |
| **S4_multi_ticker_8** | **140** | **162** |

The cache works exactly where queries are DETERMINISTIC (S1's prompt is fixed: 6 and 2 events,
down from 38–75 uncached). It cannot help S2/S4, and the reason is structural:

**54 of 69 cached queries are MODEL-GENERATED.** Deep Research and the multi-ticker scenario
have the LLM phrase its own searches:

```
PLUG revenue earnings free cash flow growth drivers 2026
BRK-B Berkshire Hathaway latest news catalysts 2026
For each of KO, JPM, BRK-B, ... what are the near-term catalysts
```

Two different models phrase them differently, and the same model phrases them differently
between runs. So they miss the cache **by design** — the thing being varied in the A/B is the
thing that generates the cache keys. No caching strategy can fix that without changing what is
being measured.

## Honest status of the GLM-5.2 vs DeepSeek-V4-Flash decision

- **Functional equivalence: well supported.** Across 4 usable runs every `must_equal` metric
  matched, and Flash's tool lane emits structured tool calls while its arbitrator lane emits
  parseable JSON.
- **Performance parity: still not established.** The one apparent quality win
  (`unique_sources` +46%) was noise — identical at n=3.
- **Blocker:** the search environment has been driven for ~14 hours and is saturated. Throttle
  counts across the session: 84, 141, 226, 141, 152, 142, 133, 228, 231. The only low reading
  followed a ~12-hour idle, and spacing runs 12–18 min apart does not help.

**The remaining requirement is a RESTED search environment, not more code.**

## Verification

`tests/unit/test_search_cache.py` — 12 tests, the thin-result test **fails without the floor**.
Tier-0 **10/10**, unit **586 passed** (4 pre-existing unchanged), version sync 5/5.
