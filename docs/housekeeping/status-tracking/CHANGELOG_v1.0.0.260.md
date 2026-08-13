# CHANGELOG — v1.0.0.260

**Date:** 2026-08-13
**Type:** Bug fix (P1) — Deep Research retrieval layer
**Issue:** SI-032 — academic search substantially broken in production
**Files:** `research/engine.py`, `user_tools/published_papers_search_tool.py`,
`tests/unit/test_si032_academic_query_syntax.py` (new)

---

## Summary

Deep Research was sending each planner sub-question to the academic catalogues **verbatim**.
Those catalogues parse their argument as a **query expression, not as free text**, and every
planner sub-question ends in `?` — which OpenAlex reads as a wildcard operator and DOAJ rejects as
a disallowed Lucene feature. In the retained production logs this cost **OpenAlex 47 of 58 calls
(81%)** and **DOAJ 51 of 55 calls (93%)**, as hard HTTP 400s.

With five academic channels degraded, general web search was what remained — and the encyclopedia
is what general web search returns. This is the retrieval-layer cause behind the standing "Deep
Research leans on Wikipedia" complaint that two consecutive prompt-only attempts (v1.0.0.257,
reverted after external review; the v1.0.0.259 attempt, dropped) failed to move. No directive can
cite scholarship the retrieval layer never fetched.

## Root cause

Confirmed by falsification through the real code path, not by inspection:

| source | arm | n results | chars |
|---|---|---|---|
| openalex | LONG (the exact string from the prod log) | 0 | 243 |
| openalex | SHORT (keyword query) | 5 | 34 |
| doaj | LONG | 0 | 215 |
| doaj | SHORT | 3 | 33 |

The servers name their own rule in the 400 body:

```
OpenAlex -> {"error":"Invalid query parameters error.",
             "message":"Wildcards (* or ?) require exact (no-stem) search..."}
DOAJ     -> {"status":"bad_request","error":"Query contains disallowed Lucene features"}
```

A competing cause — "our URL building mis-encodes the `?`" — was **refuted**: re-issuing the same
query with strict yarl/aiohttp encoding returned an identical 400 from both APIs, while removing
the `?` alone returned 200.

The instruction that produced it was in the planner prompt itself (`research/engine.py`), which
listed `published_papers_search` among the sources that take "a natural-language search string"
and for which the planner should therefore OMIT a per-source query.

### Measured scope — wider than first logged

| effect | sources | mechanism |
|---|---|---|
| hard HTTP 400 | `openalex`, `doaj` | query-DSL operators |
| silent 0 results | `pubmed`, `core`, `doab`; `europe_pmc` 5→1 | over-long AND-ed term lists |
| unaffected | `arxiv`, `crossref` | — |

Two claims in the original SI-032 entry were **withdrawn** on measurement: DOAJ's URL *path* does
not break on a long query (a 131-char punctuation-free query returns 200 with 0 matches), and
PubMed does **not** tolerate the sentence — it returns an empty set, which is worse than a 400
because nothing errors.

## Changes

### Fix A — planner policy (`research/engine.py`)

- `published_papers_search` removed from the "OMIT the queries entry" list; the planner is now
  told what the source actually accepts — a bibliographic keyword query — and supplies it through
  the existing `per_source_queries` mechanism (shipped v1.0.0.157, no new machinery).
- The assessor's `next_queries` prompt carries the same guidance, so rounds 2+ match round 1.
- Policy language, LLM-judged. No keyword lists, no regex, no per-source branching in code.

### Fix B — transport safety (`user_tools/published_papers_search_tool.py`)

- New `_query_for_source()` renders the query valid in each source's own query syntax, applied at
  the single chokepoint `_prepare_search_tasks()` so all 11 searches and **every** caller (DR or
  not) are covered — including when `per_source_queries` is configured off, which would otherwise
  disable Fix A entirely.
- Operator sets are **protocol constants measured against the live APIs**, not an interpretation
  of meaning; sources with no declared operator set are passed through byte-identical.
- Operators become spaces rather than deletions, so `multipolarity(hegemony)` stays two searchable
  terms instead of fusing into one nonexistent word.

### Parity defect (found by the adversarial audit)

`DeepResearchEngine._plan_tasks()` extracted and now shared by **both** callers. The
below-`min_rounds` re-issue previously rebuilt the plan's tasks inline **without** consulting
`queries`, so on that path `published_papers_search` silently received the raw sub-question again —
re-opening the bug for exactly the runs that gather hardest.

### Robustness (found by the adversarial audit)

`_query_for_source()` is total. Task building runs *outside* the per-source `try/except`, so a
non-string query raising there would have aborted all eleven searches instead of one.

## Verification

| check | result |
|---|---|
| Retrieval, real tool entry point, 3 scholarly topics | papers **42 → 104**, HTTP 400s **6 → 0** |
| Real planner + real model, n=3 (non-deterministic) | **3/3** runs emitted bibliographic queries for every paper task |
| `tests/unit/test_si032_academic_query_syntax.py` | 30 passed; **all 30 fail on pre-fix code** |
| Full unit suite | 333 passed, 4 pre-existing failures (identical pre-fix, unrelated) |
| `tests/smoke/tool_smoke.py` | PASSED — `published_papers_search` 7384 chars of real content |
| `tests/integration/test_version_sync.py` | 5 passed |

## Not fixed by this release

- **Rate limiting is a separate cause and remains open:** Semantic Scholar (73 × 429) and CORE
  ("likely needs API key") are SI-006, awaiting free API-key registration by the operator;
  Crossref 429s were newly noted in the same window.
- The **sourcing-mix outcome** this was expected to improve (`encyclopedic_share` /
  `academic_share` on the S9 scenario) is **not yet re-measured**. The retrieval layer is fixed;
  that it moves the mix is a hypothesis, not a result.
- All measurements above are local, through the tool's real entry point. Production 400-rates must
  be re-measured on live DR traffic before SI-032 is cleared.

## Migration / breaking changes

None. No config keys added or changed; no API surface change. `per_source_queries: false` remains
a working one-line rollback for Fix A, and Fix B continues to protect the wire format underneath it.
