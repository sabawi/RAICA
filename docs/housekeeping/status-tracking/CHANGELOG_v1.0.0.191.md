# Changelog — v1.0.0.191

**Date:** 2026-07-18
**Scope:** Inline chart cards — **Phase 5, Step 2**: `generate_event_chart` — a compact, single-indicator
sub-chart ZOOMED to one detected event's window with the exact occurrence annotated. Builds on Step 1
(v1.0.0.190) event detection. Design: `docs/DESIGN_event_anchored_subcharts.md` (NewX repo). Still
**not wired into any pipeline** (inert until Step 3 analyzer wiring); no runtime behavior change.

## Added — `utils/chart_generator.generate_event_chart(ticker, history, event, category)`
- Crops to `event ± category.event_zoom_sessions` by REUSING `technical_events.event_window` (one
  config-driven source of truth for the zoom width — no duplicated boundary numbers).
- Renders the ONE indicator relevant to the event type (deterministic PRESENTATION of a structured
  event, like the main chart's fixed panels — not meaning classification):
  - `sma_cross` → Close + SMA 50/200 (crossover in view)
  - `rsi_*` → RSI with 30/70 shaded zones
  - `macd_*` → MACD line + signal + histogram, zero line
  - `adx_*` → ADX + ±DI, the 25 line
  - `volume_confirm` → Close + volume bars
- Annotates the **exact event date** (vertical marker + dated, objective label — a STATE, never a
  buy/sell call), themed to match the main chart. Unknown event type → None (fail closed, never a
  wrong chart). Thread-safe matplotlib OO API; never raises → None so a chart problem can't break the
  analysis.

## Verification
`tests/utilities/test_event_charts.py` — **4 unit tests, all passing** (no network / no LLM):
- Every event family (sma/rsi/macd/adx/volume) renders a valid PNG; the Step-1 → Step-2 detect→render
  handoff works on a real detected event; both long/short zoom categories render; bad input
  (None/empty/unknown-type/no-date/non-dict) degrades to None.
- **Visual spot-check** (rendered to PNG and inspected): a golden-cross card shows SMA50 crossing above
  SMA200 exactly at the dashed event marker over a ~5-week window; an RSI-oversold card shows the dip
  below the shaded 30 line at the marked date. Zoom, annotation, and theme are correct.

## No new dependencies.
matplotlib / pandas-ta-classic already present. Next: Step 3 — wire the analyzer (detect → select by
trend → publish featured sub-charts → emit markers) + Step 4 synthesis placement directive.
