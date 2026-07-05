# CHANGELOG v1.0.0.134

**Date:** 2026-07-05
**Previous:** v1.0.0.133 (source-provenance Phase 0 — shadow role-grading)
**Theme:** **Deep-Research citation liveness (Phase 0, shadow).** Fetch each *cited* URL in a DR answer and
log how many are dead ("Page not found") — a baseline for the real dead-link rate — **without changing any
answer yet**. Bundles a grading-JSON resilience fix so one malformed entry can't collapse all credibility
grades.

---

## Symptom (operator-reported, live)

A live `@Ask deep research …` reply (07/04/2026, energy-market/geopolitics; server run 11:04–11:08 PM UTC)
and its follow-up "email me a PDF" carried **multiple dead "Page not found" citation links**. Fetching all
49 cited URLs from the delivered PDF: **15 (31%) return hard HTTP 404** (World Bank, Federal Reserve, SF Fed,
CNBC ×2, USA Today, NAM, IEA, Kitces, Fortune, a BBC opaque-ID article, …). The same run also logged
`🏷️ Credibility grading failed (Expecting ',' delimiter…) → all 'unknown'`.

## Root cause

1. **Evidence-URL over-capture** — `research/engine.py:410` builds each evidence item's URL set with
   `_URL_RE.findall(content)` over the *whole* block, capturing not just each result's fetched `source_url`
   but URLs embedded in **search snippets and page-body cross-references** that were **never fetch-verified**.
2. The gather-time live check (`citation_verify`) only covers each block's fetched `source_url`, and is
   time-of-check, not time-of-use.
3. `research/citation_grounding.py ground_citations()` is **by-reference only** (pure/offline) — it can strip
   *fabricated* links (not in evidence) but **cannot detect an in-evidence dead link**; it is additionally in
   `shadow` mode and was called **without `dead_urls`**.
4. **No output-side liveness pass** ever fetched the final cited URLs. The PDF renders from the same answer
   body, so it inherits the dead links (not a separate bug).
5. **G1 (compounding):** `grade_sources` parsed the grader JSON via `extract_json_object`, which is
   **all-or-nothing** — one malformed `reason` (or truncation at the fixed `max_tokens=3000` with 100+ domains)
   raised and mapped **every** domain to `unknown`.

Full analysis + design: `docs/RAICA_DR_CITATION_LIVENESS.md`.

## Fix (Phase 0 — shadow; answer unchanged)

- **`research/link_liveness.py` (NEW)** — shared home for the lenient, empirical verifier
  (`verify_url_live`, `filter_live_article_urls`, `is_homepage_redirect`), **moved verbatim** from
  `fastapi_server_complete.py`. Depends only on `requests_compatible_get` (http_helpers) + stdlib, so the DR
  pipeline can reuse it **without** the `research/`→server circular import. Policy is stated once: drop a URL
  **only** when verified dead (hard 404/410 or an article→homepage redirect); keep 200/401/403/429/5xx/
  paywall/JS/timeout (a bot-blocked valid article is never dropped).
- **`fastapi_server_complete.py`** — the three functions above are now imported from `research.link_liveness`
  under their original `_`-prefixed names, so every existing gather-time call site
  (`get_text_from_url_simplified`, `get_news_summaries`) is **unchanged**.
- **`research/citation_grounding.py`** — added `extract_cited_urls(answer)` (reuses the existing HTML/Markdown
  link regexes so "cited" means exactly what grounding acts on).
- **`research/pipeline.py`** — new gated step at the grounding call site: extract cited URLs →
  `filter_live_article_urls` → **always log** `🩺 citation-liveness [SHADOW]: dead=X/N cited` (dead=0 included,
  so the baseline has its denominator and execution is confirmed). In **shadow** it feeds nothing to the strip
  (answer byte-unchanged). Phase-1 flip (`verify_live.shadow:false`) will pass the dead set as `dead_urls` to
  `ground_citations` → dead links stripped as ROTTED (headline text kept, only the broken link removed).
- **G1 grading resilience** — `research/engine.py salvage_json_map()` (tolerant partial-JSON recovery via
  `json.JSONDecoder.raw_decode` per top-level entry); `research/synthesis.py grade_sources` now **auto-sizes**
  the grading `max_tokens` to the domain count and, on a parse failure, **salvages the domains that parsed**
  instead of collapsing the whole batch to `unknown`.

## Config

`config/llm_config.yaml` → `deep_research.engine.citation_grounding`:
```yaml
      verify_live:
        enabled: true
        shadow: true            # Phase 0: fetch + log only (answer UNCHANGED). false = enforce (strip dead).
        timeout_seconds: 6      # lenient per-URL liveness timeout (a timeout KEEPS the URL)
        max_workers: 8
```
Fail-open: any error in the liveness step (extraction, fetch) → today's behavior; the answer is never discarded.

## Tests

- **`tests/integration/test_dr_citation_liveness.py` (NEW, 11 tests)** — `extract_cited_urls` (MD+HTML,
  dedupe), `salvage_json_map` (recovers good entries around a malformed/truncated one), `filter_live_article_urls`
  (lenient drop-only-dead, verify monkeypatched — no network), and `ground_citations(dead_urls=…)` ROTTED strip
  keeping the headline (the Phase-1 enforce path) + shadow leaves the answer byte-unchanged.
- 19/19 pass (11 new + 8 existing `test_citation_grounding.py`).
- **Verified live-local e2e:** two real DR runs → `🩺 citation-liveness [SHADOW]: dead=0/32 cited`, answer
  unchanged; grading healthy (`Graded 62 domains`, no collapse); server v1.0.0.134 healthy, 0 tracebacks,
  gather-time citation paths intact.

## Dependencies

None added. `research/link_liveness.py` uses `urllib.parse` (stdlib), `concurrent.futures` (stdlib), and the
existing `http_helpers.requests_compatible_get`.

## Breaking changes

None. Behavior is shadow-only (no answer changes). The moved verifier is re-exported under its original names,
so no call site changed.

## Migration guide

- Deploy: `git pull` on the live host, then restart (`./stop_complete.sh && ./start_complete.sh`).
- No config migration required — the `verify_live` block ships enabled in shadow.
- To later ENFORCE (Phase 1): set `deep_research.engine.citation_grounding.verify_live.shadow: false` (after
  reviewing the shadow baseline).
- Rollback: set `verify_live.enabled: false` (disables the liveness step) — or revert this commit.

## Rollout status

Phase 0 (shadow) shipped. Baseline (`🩺 citation-liveness`) accrues on live `@Ask` DR traffic; after a few days,
aggregate the dead-link rate, then decide Phase 1 (enforce strip) and the optional Phase 2 (stop over-capturing
unverified embedded URLs at `engine.py:410`).
