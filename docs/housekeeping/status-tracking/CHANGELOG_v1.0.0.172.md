# Changelog — v1.0.0.172

**Date:** 2026-07-11
**Theme:** Chart-cards hardening (cache + cap + visuals) · Deep-Research output-cap raise · Finance-fetch resilience (AVGO transient-failure fix) · Finance hardening audit (signed off).

> Note: v1.0.0.171 was an in-flight build number during this session; all of its changes are folded into this v172 release. The chart-hardening, DR, and finance changes touch shared files (`config/llm_config.yaml`, `comprehensive_stock_analyzer.py`, the finance test file), so they ship as one coherent commit rather than an impractical hunk-level split.

## Inline chart cards — hardening (builds on v170 Phase 3)
* **Same-window cache** (`utils/chart_publisher.get_or_publish_chart`): a chart keyed by `(ticker, display_days)` is reused for `charts.cache_ttl_seconds` (default 1800s / 30 min). A popular ticker renders **once per window** — every later request (any user, and repeats within one response) reuses the minted URL with no render/upload. Render is deferred (a `lambda`) so a cache hit never builds the figure.
* **Per-response cap** (`charts.max_per_response`, default 6): hard fail-safe so no single response can render an unbounded number of charts (over cap → no image, text unaffected). Shared mutable budget on a contextvar, reset per response at `generate_stream` entry, so it aggregates across sequential AND concurrently-gathered tool calls; a failed render releases its slot.
* **Volume visibility**: opacity `.18→.38`, axis scale `×4→×2.5` (bars fill ~40% of the price panel instead of ~25%).
* **Upload transport fix**: `charts.newx_upload_url` `http→https` (NewX main is HTTPS-only) + new `charts.verify_tls` knob (default true; false for the loopback same-host case where NewX's cert is self-signed/CN-mismatched and the shared secret is the real auth).

## Deep Research — output cap raised
* `deep_research.engine.synthesis.max_answer_tokens` **16000 → 32000** — a 5-stock full-detail report hit 100% of the 16k cap ("AT CAP — may be truncated"). Model ctx=200000 (max ~1M) and the NewX client read-timeout (900s) both allow it (~2× synthesis ≈ +65s → ~260s total run, well under 900s).
* `deep_research.engine.verification.max_tokens` **16000 → 24000** — proportional room for the larger claim-list of a longer answer (salvage parser still backstops).

## Finance-fetch resilience — the AVGO fix
* **New `utils/yf_retry.py`** — `fetch_with_retry(fn, attempts, backoff_seconds, label, log)`: bounded retry with linear backoff for transient Yahoo/yfinance failures; logs every attempt (transparent); re-raises the last exception if exhausted (caller surfaces a clear error, never fakes data). General transient handling — no error-string matching, no per-ticker special-casing.
* **`comprehensive_stock_analyzer._get_real_time_data`** now routes the `.info`/`.history` gate through `fetch_with_retry` (config `stock_analyzer.fetch_retries: 3`, `fetch_backoff_seconds: 0.8`). **Fixes the AVGO incident**: a transient Yahoo `quoteSummary` "Internal Server Error / Server caught an exception" no longer kills the whole ticker (previously → no fundamentals/DCF/technicals/chart + `[unverified]` citations). Confirmed transient (AVGO `.info` succeeds on retry).

## Finance hardening audit (design)
* **New `docs/RAICA_FINANCE_HARDENING_AUDIT.md`** — grounded per-module audit (fetch vs compute), 3 pillars (recovery / transparency / data-integrity), signed off 2026-07-11. Highest-severity open item: `financial_statements_extractor.py:76-91` fetches 7 statements single-shot and `return {}` on failure (silently starves all downstream calculators). Sequenced P1→P2→P3; failure-sentinel `{"_error":…}` approach. **This is the next effort** (not in this commit).

## Config
* `config/llm_config.yaml`: `charts.{verify_tls,max_per_response,cache_ttl_seconds}`, `stock_analyzer.{fetch_retries,fetch_backoff_seconds}`, `deep_research.engine.synthesis.max_answer_tokens`, `deep_research.engine.verification.max_tokens`. **`charts.enabled` ships `false`** (feature stays dark until enabled in production).

## Tests
* `tests/utilities/test_financial_calculators_accuracy.py`: `test_chart_cache_and_cap` (cache hit/miss, cap, slot-release, reset, TTL) + `test_yf_fetch_retry` (recovery on retry, re-raise on exhaustion, analyzer gate recovers from the AVGO-style blip). All offline/deterministic.

## Verification
* Unit: chart cache/cap ✅, yf-retry (incl. analyzer integration) ✅.
* E2E (local, charts flag ON during test): single-stock NVDA chart card rendered in a real NewX reply; 5-stock comparison embedded 4 charts cleanly (cache/cap healthy). AVGO retry validated by fault injection.

## No dependency changes
* `yf_retry` uses stdlib only. matplotlib/requests/pandas-ta-classic/yfinance already required.

## Not pushed / not deployed
* Committed locally only. `charts.enabled=false` by default. Chart end-to-end requires a matching `CHART_UPLOAD_SECRET` in both RAICA and NewX `.env` plus NewX `CHART_CARDS_ENABLED=true`.
