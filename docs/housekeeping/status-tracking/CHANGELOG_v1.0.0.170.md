# Changelog — v1.0.0.170

**Date:** 2026-07-11
**Scope:** Inline chart cards — **Phase 3 (RAICA side)**, behind a flag (default OFF). RAICA generates a per-stock technical chart, uploads it to NewX, and embeds a `[[chart:...]]` marker in the analysis so NewX renders it as an inline figure card. Pairs with NewX v1.0.0.59/.60 (Phases 1–2). Design: `NewX/docs/DESIGN_inline_chart_cards.md`.

## What was added
* **`utils/chart_generator.py`** — `generate_main_chart(ticker, history, display_days=126) -> bytes|None`. The enriched main chart (candlesticks + SMA 50/200 + volume overlay + RSI/MACD/ADX stacked panels + h+v gridlines + real date axis) via `pandas-ta-classic`, computed on ~2y so the MAs are warmed up across the display window (no edge artifacts). **Thread-safe** (matplotlib OO `Figure`/Agg canvas, not pyplot global state, since the analyzer runs in a thread pool). Never raises → None on any failure.
* **`utils/chart_publisher.py`** — `publish_chart(png, hint) -> url|None`: POSTs the PNG to NewX's `/internal/chart-upload` with the shared secret; returns the same-origin URL. Fail-closed + graceful (`charts_enabled()` requires the flag AND a URL AND the secret; any error → None).
* **`config/llm_config.yaml`** — new `charts:` block: `enabled: false` (default), `newx_upload_url`, `display_days`. Shared secret is a **.env** secret (`CHART_UPLOAD_SECRET`), never in the yaml.
* **`user_tools/comprehensive_stock_analyzer.py`** — detailed mode now fetches ~2y history ONCE (shared by the indicators and the chart), and (flag-gated) generates + uploads the main chart and **prepends** a `[[chart:<url>|align=center|caption=...]]` marker to the TECHNICAL ANALYSIS block. Fully graceful — disabled/gen-error/upload-error → no marker, unchanged text.
* **`research/synthesis.py`** — INLINE CHARTS directive: relay a `[[chart:...]]` marker from the evidence **verbatim** into the relevant section; never invent, reuse across stocks, or alter one.

## Security / safety
* Charts default **OFF** (RAICA `charts.enabled=false` + NewX `CHART_CARDS_ENABLED=false`); with the flag off behavior is byte-identical (verified: analyzer emits no marker).
* RAICA only ever emits a marker with the **same-origin URL NewX minted** on upload; NewX independently validates the `<img src>` against its media prefix (Phases 1–2). No raw HTML from RAICA.
* No new dependency (matplotlib, requests, pandas-ta-classic, yfinance already required).

## Verification
* **Unit tests:** 35/35 PASS (new `test_chart_generator_and_publisher`: valid PNG, graceful None on short/None input, publisher fail-closed when disabled, display_days config).
* **Chart output** visually verified (identical to the approved PoC — candles/SMA/volume/RSI/MACD/ADX, date axis).
* **Analyzer graceful** with charts OFF (default): no marker, TECHNICAL block unchanged.

## Not done yet (deferred)
* **End-to-end visual test** — needs both servers running with the flags ON and a matching `CHART_UPLOAD_SECRET` in both `.env`s; that's the real-UI check to judge together.
* **Non-DR @Ask path directive** — the non-DR answer prompt is the `system` field NewX sends (not in RAICA); the chart directive there is a small follow-up. DR synthesis (where detailed stock analysis runs) is covered.
* Sub-charts (enlarged single-indicator RSI/MACD per section) — main chart first; sub-charts are a follow-up.
