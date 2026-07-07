# CHANGELOG — RAICA v1.0.0.145

**Date:** 2026-07-07
**Type:** Feature — humanities/cross-disciplinary repositories for `published_papers_search` (layer A, part 1)

## Summary
`published_papers_search` was STEM-skewed: of its corpora, four are STEM/biomedical (arXiv, PubMed, Europe PMC,
bioRxiv) and only two cross-disciplinary (Semantic Scholar, CORE, DOAJ) — and Semantic Scholar is 429-throttled.
That is why a medieval-history DR (post 5589) got arXiv CS-homonym papers. This adds **real humanities coverage**
so history/law/arts queries have appropriate sources to draw on (and gives the upcoming domain-fit judge, layer A,
somewhere to route them).

## Changes (`user_tools/published_papers_search_tool.py`)
- **+4 source clients** (free APIs), all live-verified:
  - **OpenAlex** — 250M+ works, all disciplines; robust (also a resilient alternative to the Semantic-Scholar 429s).
  - **Crossref** — DOI metadata incl. **books** & humanities journals.
  - **DOAB** — Directory of Open Access **Books** (humanities-heavy); via the legacy DSpace REST endpoint.
  - **Internet Archive** — digitized **books / primary-source texts** (`mediatype:texts` filter to exclude
    video/audio).
  - (CORE was already integrated.) Total corpora now 11.
- `_fetch_json_content` hardened: sends a UA (OpenAlex/Crossref polite pools + DOAB) and parses regardless of
  the server's content-type header (archive.org/DOAB return JSON as text).
- Tool description + `sources` enum updated to advertise the humanities set and instruct callers to OMIT
  arxiv/pubmed/biorxiv for non-STEM topics (grounds the layer-A routing).

## Verification (live APIs)
- OpenAlex → "Political Memory in and after the Persian Empire"; Crossref → "The Byzantine Empire 1025–1402";
  **Internet Archive → "Khalid Ibn Al Walid And The Military Foundation Of Islamic Expansion"** (exactly on
  topic); DOAB → real OA books ("medieval history" → "The Juggler of Notre Dame…"). Restart clean (health 200,
  0 tracebacks); tool loads.

## Risk / rollback
- Additive: humanities queries now get real coverage; STEM queries get a few more (mostly relevant) sources.
  Each source is independently try/except'd (a failing/blocked API returns [] and never breaks the search).
  Slightly more parallel API calls per paper search until layer A (domain-fit judge) scopes the `sources` subset.
  Version → 1.0.0.145.

## Next
- **Layer A judge**: LLM domain-fit routing — for humanities topics, set `sources` to the humanities subset and
  OMIT arxiv/pubmed/biorxiv; for STEM, the reverse. Plus infra: Semantic-Scholar backoff/key, arXiv keyword
  (not full-sentence) queries.
