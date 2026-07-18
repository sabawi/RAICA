# Changelog — v1.0.0.190

**Date:** 2026-07-18
**Scope:** Inline chart cards — **Phase 5, Step 1 (foundation)**: deterministic, dated technical-event
detection + one-edit long/short-term category config. Groundwork for **event-anchored technical
sub-charts** (small/medium RSI/MACD/ADX/SMA-cross/volume-confirm charts zoomed to the exact time
segment an event occurred, floated beside the relevant text). Design: `docs/DESIGN_event_anchored_subcharts.md`
in the **NewX** repo (RAICA↔NewX integration contract; Phases 1–3 render/upload/main-chart emit are
already live, Phase 4 cleanup still open). **Flag-off and NOT wired into any pipeline yet** — this
module is inert until Step 3 (analyzer wiring). No runtime behavior changes.

## Added — `utils/technical_events.py`
Deterministic detection of DATED technical events from daily OHLCV, over the indicator SERIES (not the
`iloc[-1]` snapshot `technical_indicators.py` reports). `detect_events(history, category)` returns, for
each occurrence, `{type, date, value, direction, magnitude, timeframe_nature, category}`:
- **RSI** crossing into <30 / >70 · **MACD** line/signal + zero-line crossings · **ADX** ↑25 / ↓20 ·
  **SMA 50/200** golden/death sign-flip · **volume spike** (≥ N× trailing avg) *confirming* another
  signal within ±W sessions.
- **Accuracy principle:** the one detected event (with its exact trading date) is meant to drive BOTH a
  sub-chart's zoom window AND what the LLM narrates — so text and chart stay bound to the same
  occurrence. Detection is pure math; selection/placement/relevance stay the LLM's job (LLM-policy gate).
- Mirrors `technical_indicators.py`'s "OBJECTIVE readings, NOT a buy/sell signal" discipline — reports
  OBJECTIVE *dated states*, nothing more.
- `event_window()` helper returns the zoom crop bounds (event ± category zoom).

## Changed — `config/llm_config.yaml` (`charts.*`) — the one-edit tweak surface
- **`charts.trend_categories`** — `long_term` / `short_term` boundaries in ONE place
  (`display_sessions`, `fetch_sessions`, `prior_sessions`, `event_zoom_sessions`) + `default` for an
  ambiguous horizon. Tweak the long/short bands here with no code change.
- **`charts.detection`** — every threshold (RSI 30/70, ADX 25/20, SMA 50/200, volume spike mult 2.0×,
  confirm window ±3, `max_subcharts_per_stock` 3) is config-tunable.

## Config-directive compliance (ZERO-TOLERANCE)
`technical_events.py` reads ALL values from `config/llm_config.yaml` — **no hardcoded config, no
hardcoded fallbacks**. Missing/partial `charts.trend_categories` or `charts.detection` raises
`ChartConfigError` (**fail fast**, never a silent default). The analyzer-facing `detect_events()` still
never breaks the analyzer: it catches, logs, and returns `[]`.

## Verification
`tests/utilities/test_technical_events.py` — **9 unit tests, all passing**, no network / no LLM:
- Golden cross & RSI-oversold detected on the **exact independently-recomputed crossing date** (the
  accuracy claim, proven offline); volume-confirm only near another event; deterministic; display-window
  filtering; `event_window` crop bounds; graceful on empty/short history.
- `test_config_boundaries_are_adjustable_and_loaded` reads 504/126/25/12 **straight from the yaml**
  (the tweak-knob is wired); `test_missing_config_fails_fast` proves fail-fast on missing config.
- Regression: yaml parses with existing `charts` keys intact; existing chart-generation/publisher tests
  still green.

## No new dependencies.
`pandas-ta-classic` / pandas / numpy already pinned. Next: Step 2 — `generate_event_chart` (zoomed,
annotated sub-chart) with PNG unit tests.
