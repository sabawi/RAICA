# CHANGELOG v1.0.0.235 — revive 3 dead academic sources + expose publication dates

**Date:** 2026-08-06
**Type:** Bug fix (academic retrieval) + smoke-coverage gap
**Runtime impact:** `published_papers_search` returns materially more, and more current, results.
Affects **Deep Research** (its academic retrieval path) and the `@scibot` NewX bot.

---

## Why

Investigating "@scibot cites only 1 URL per post" found the thin sourcing was a symptom. The tool was
returning papers **11–15 months old** under a prompt demanding "the LAST DAYS OR WEEKS", and a query
for "CRISPR gene editing" returned a **2016** paper at rank 1. Measured: **4 of 11 databases returned
nothing**.

| Source | Root cause (verified by invocation) |
|---|---|
| **pubmed** | `from Bio import Entrez` (line 18) but **`biopython` was never in `requirements.txt`** and was not installed locally *or* on live. It logged "BioPython not available, skipping PubMed search" and returned 0 rows in **every environment, always**. |
| **doaj** | Called `/api/search/articles` → **HTTP 404**. DOAJ versioned its API; the live path is `/api/v2/search/articles/{query}`, which takes the query in the PATH. Response body shape is unchanged. |
| **biorxiv** | Requested a **2-year window** (111,186 papers) at cursor 0 and took 5 rows → the five *oldest*, all dated the window's first day, then relevance-filtered those five. Compounded by a filter requiring the **entire query as a literal substring** ("antibiotic resistance discovery" verbatim). Never matched. |
| **semantic_scholar** | HTTP 429 — rate limited, no API key. **Not fixed** (needs a key). |

Separately, the result format actively hid staleness: every block rendered a prominent
`📅 Retrieved: <today>` while the real `Published: 2016-02-04` sat buried inside the content blob. The
most visually salient date on every source was always today's.

## Fixed

1. **`requirements.txt`** — added `biopython==1.85` with a comment naming the import site. Installed
   into the local venv. **The live server still needs `venv/bin/pip install -r requirements.txt`.**
2. **bioRxiv** (`_search_biorxiv` / `_build_biorxiv_url` / `_filter_biorxiv_results`) — the endpoint
   caps a page at **30 rows** regardless of what is asked, and cursor 0 is the **oldest** row. Now
   reads `total` from the feed and pages **backward from the end**, where the newest papers are
   (verified: cursor 19270/19301 returned papers dated that same day), bounded to 8 pages ≈ 240
   recent candidates over a 90-day window. A single failed page no longer discards the pages already
   gathered — the walk makes ~9 requests and bioRxiv intermittently drops one.
   The relevance filter now matches on a majority of query **terms** rather than a verbatim phrase,
   and ranks by match count then recency (the feed arrives oldest-first, so truncating without
   sorting kept the worst rows).
3. **DOAJ** — rebuilt onto `/api/v2/search/articles/{query}`. `_parse_doaj_data` needed no change.
4. **Publication date surfaced** — the per-paper block title now carries `[published YYYY-MM-DD]`, so
   it sits directly above the `📅 Retrieved: <today>` line:
   ```
   Title: Primer on the Gene Ontology  [published 2016-02-04]
   📅 Retrieved: Thursday, August 06, 2026
   ```
   Kept **local to this tool**: `format_source_block` is shared by 11 modules and must not change shape.

## Smoke coverage gap (found while fixing)

`published_papers_search` was **not in the smoke suite** — which is exactly how it rotted. Worse, the
suite could not have covered it: `tool_smoke.py` read `tool_manager.available_functions` after a bare
import, which holds only the **7 built-in** tools. The **17 user tools** are registered by an async
loader that importing never runs, so the mandatory pre-deploy gate was blind to all of them
(`comprehensive_stock_analyzer`, `get_sec_filings`, `document_search`, …).

- `_invoke()` now awaits `_load_user_tools_async()` when a name is missing (idempotent) — the registry
  goes 7 → 24.
- Added a `published_papers_search` check pinned to `sources: [arxiv, pubmed]` (2.8s). The full
  11-database call takes **~85s**, far past `PER_CALL_TIMEOUT`. PubMed is named deliberately so the
  check fails if biopython ever goes missing again.

## Verification

Per-source URL counts, same query, before vs after:

| | before | after |
|---|---|---|
| pubmed | **0** | 15 |
| doaj | **0** | 15 |
| biorxiv | **0** | 3 (see limitation) |
| semantic_scholar | 0 | 0 (unfixed — needs API key) |
| **sources alive** | **7/11** | **10/11** |

- 3 queries × 11 sources; arxiv/pubmed/europe_pmc/openalex/crossref/core/doaj/doab/internet_archive
  all **3/3**.
- bioRxiv now returns papers dated **the same day**, but only **1/3** queries match. Structural, not a
  regression: bioRxiv has no query API, so a keyword filter over ~240 recent papers legitimately finds
  nothing for a narrow query. **Europe PMC indexes the bioRxiv corpus** and is 3/3, so coverage is not
  lost.
- Publication date renders in the block title (shown above).
- `make smoke` **6/6 PASS**; Tier 0 **9/9 PASS**.

## Follow-ups

- **LIVE INSTALL PENDING** — `biopython` must be installed on `sabawi.net` at the next RAICA deploy or
  PubMed stays dead there.
- **Item 5 (scoped separately, not in this release):** add a recency control to the tool schema. The
  only date knob today is a coarse `year`, and arXiv is hardcoded `sortBy=relevance`
  (`_build_arxiv_url`), which is why a 2016 paper ranks first. Changing the schema touches the contract
  Deep Research also calls, so DR's call sites need review first.
- `semantic_scholar` needs an API key to stop 429-ing.
- **~85s** for a full 11-database call is slow for a DR gather step; worth profiling.

## Migration

Run `pip install -r requirements.txt` (adds `biopython`). No config changes.
