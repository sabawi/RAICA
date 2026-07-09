# Changelog — v1.0.0.157

**Date:** 2026-07-08
**Scope:** Deep Research now actually calls the structured finance user-tools (`comprehensive_stock_analyzer`, `get_stock_and_company_data`) for stock/valuation queries, instead of fanning them out to `search_web`.

## Problem
An OpenWebUI prompt such as *"investigate … the valuation and prospect of PLTR stock … and generate a full report"* triggered **Deep Research Mode** (correctly, per the gate). But inside DR the request was routed entirely to `search_web`, never calling the finance tools under `./user_tools`:

- **Root cause (Layer A — selection):** the DR retrieval vocabulary (`deep_research.engine.sources.allowed`) listed only `search_web, get_news_summaries, wikipedia_query, published_papers_search, get_sec_filings, document_search`. The dedicated finance tools — `comprehensive_stock_analyzer` (yfinance real-time price + fundamentals + ratios + DCF) and `get_stock_and_company_data` — were **not in that list**, so the DR planner was structurally unable to choose them. The engine even strips any non-allowed source and defaults to `search_web` (`engine.py:_normalize`).
- **Root cause (Layer B — arg shape):** even after the tools were added to the allow-list, Round 1 of the gather loop passed the **sub-question text** as the tool argument (`engine.py:run()` task construction: `"query": sq["question"]`). The stock tools expect a ticker (`{"ticker":"PLTR","detailed":true}`), so yfinance received the whole question as a symbol → `"possibly delisted; no price data found"` → the assessor dropped the stock source and fell back to `search_web` for the rest.
- **User-visible symptom:** the report had the price/market-cap (scraped from news) but was **missing the valuation multiples** the user asked for (`P/E`, `P/S`, `EV/EBITDA` all 0), and was padded with 62× `_No evidence discusses…` caveats (thin grounding).

## Fix (policy-language + config, no hardcoded meaning logic — CLAUDE.md compliant)

### Layer A — make the finance tools selectable
- `config/llm_config.yaml` → `deep_research.engine.sources.allowed`: added `comprehensive_stock_analyzer` and `get_stock_and_company_data`.
- `research/engine.py` planner prompt: added a STOCK/VALUATION/COMPANY-FINANCIALS guidance bullet (policy language) telling the LLM to route DATA sub-questions to the structured finance tools FIRST and reserve `search_web`/news for qualitative context.

### Layer B — per-source `queries` (the dispatch arg-shape fix)
The planner may now emit an OPTIONAL `queries` map per sub-question so a source whose argument is **not** a natural-language search string receives the exact arg it expects:
```json
"queries": {"comprehensive_stock_analyzer": "{\"ticker\":\"PLTR\",\"detailed\":true}"}
```
- Value may be a **string** (one call) or a **list of strings** (one call per entry → multi-stock, e.g. PLTR + MSFT + GOOGL under one sub-question, each dispatched separately to the single-ticker tool).
- Round-1 task construction fans out list entries; `_dispatch_round` de-dupes by `(source, query)`.
- For search-style sources the LLM is told to OMIT `queries` → the sub-question text is used (unchanged).

### Backward-safety guarantee (no regression for non-stock queries)
- `queries` is optional. Absent / no entry / flag off → Round 1 uses the sub-question text → **byte-for-byte v1.0.0.155 behavior**.
- The existing `sources` field, normalization, fallback, and the Round-2+ `_assess` → `next_queries` path are all **unchanged**.
- Config kill-switch `deep_research.engine.planner.per_source_queries` (default `true`). Set `false` for a one-line rollback to v1.0.0.155 behavior everywhere.

## Files changed
- `config/llm_config.yaml` — added 2 finance tools to `sources.allowed`; added `planner.per_source_queries` flag.
- `research/engine.py` — `_per_source_queries` property; planner prompt (queries guidance + schema); `_normalize` queries passthrough (str|list, allowed-only); Round-1 task fan-out.
- `version.py` — 1.0.0.156 → 1.0.0.157.
- `tests/utilities/test_dr_per_source_queries.py` — new deterministic unit tests for the normalize layer (6 tests: flag-off ignores queries, no-field=empty, string kept, list/multi-stock kept, unknown-source dropped, empty-args dropped). All pass.

## End-to-end verification (live server, v1.0.0.157)
Multi-stock prompt: *"investigate and compare the valuation and 6-12 month prospects of PLTR and MSFT … full report"*.

Evidence from `logs/server_complete.log`:
- DR gate engaged; planner produced 6 sub-questions.
- `comprehensive_stock_analyzer` called with correct tickers and **succeeded** for BOTH stocks:
  ```
  Extracting financial statements for PLTR → Successfully extracted → Calculating comprehensive financial ratios → Calculating DCF for PLTR → Generating projections for PLTR
  Extracting financial statements for MSFT → Successfully extracted → Calculating comprehensive financial ratios → Calculating DCF for MSFT → Generating projections for MSFT
  ```
- **No "possibly delisted" / "No data found" errors** (the v1.0.0.156 failure is gone).
- Round 1: dispatched 12 sources (incl. both stock-tool calls); Rounds 2–3 gathered qualitative context via `search_web`.

Final answer (35,245 chars) — figure counts vs. the v1.0.0.155 failure:

| Metric in answer | v1.0.0.155 (broken) | v1.0.0.157 (fixed) |
|---|---|---|
| `P/E` | 0 | 12 |
| `P/S` | 0 | 6 |
| `EV/EBITDA` | 0 | 2 |
| `DCF` | 0 | 24 |
| `market cap` | 11 (scraped from news) | 9 (structured via yfinance) |
| `_No evidence discusses…` caveats | 62 | **0** |

The TL;DR carries real structured figures for both tickers (e.g. MSFT $2.85T mkt cap / P/E 27.96 / $281.72B revenue; PLTR $317B mkt cap / P/E 195.06 / 82.37% gross margin / DCF intrinsic value $14.46) — exactly the data `comprehensive_stock_analyzer(detailed=true)` returns. The 62→0 drop in `_No evidence…` caveats confirms the report is now grounded in retrieved evidence rather than fabricated forward-looking claims.

## Migration / rollback
- No schema break. Existing configs without `per_source_queries` behave as `true` (the safe default).
- Rollback: set `deep_research.engine.planner.per_source_queries: false` (and optionally remove the two finance tools from `sources.allowed`) → exact v1.0.0.155 behavior.

## Dependencies
- None new. `yfinance` already required by `user_tools/comprehensive_stock_analyzer.py`.