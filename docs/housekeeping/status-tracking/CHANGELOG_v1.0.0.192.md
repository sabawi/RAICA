# Changelog — v1.0.0.192

**Date:** 2026-07-18
**Scope:** Inline chart cards — **Phase 5, Steps 3 + 4**: wire event-anchored sub-charts into the
stock analyzer (emit) and reconcile the synthesis chart-placement directives (place). This makes the
feature **end-to-end** when `charts.enabled` is on: an `@Ask`/DR stock analysis now emits, per stock,
its main chart PLUS zoomed sub-charts for its dated technical events, floated on alternating sides
beside the relevant discussion. Builds on Step 1 (detection, v190) + Step 2 (`generate_event_chart`,
v191). Design: `docs/DESIGN_event_anchored_subcharts.md` (NewX repo). Flag-gated (OFF by default).

## Changed — Step 3: analyzer emit (`user_tools/comprehensive_stock_analyzer.py`)
- New optional tool param **`analysis_horizon`** (`long_term` | `short_term`) — the **LLM** sets it from
  the user's timeframe so the category (window + zoom) is LLM-decided (LLM-policy gate); omitted → the
  configured default.
- After the main chart, detect dated events (`technical_events.detect_events`), **feature** the
  most-recent occurrence of each distinct signal type up to `max_subcharts_per_stock` (deterministic;
  the category's display window already biases which signals are in view — no hardcoded signal→trend
  routing), render each with `generate_event_chart`, publish, and emit alternating-float
  `[[chart:…|align=left/right|caption="TICKER — <objective dated event>"|w=…]]` markers plus an
  OBJECTIVE dated-event list. Fully graceful (any failure → no sub-charts; text unaffected).
- `utils/chart_publisher.get_or_publish_chart(..., variant=None)` — the cache key now includes a
  `variant` so several charts for the same `(ticker, display_days)` (main + per-event sub-charts) don't
  collide. Backward-compatible (main chart passes no variant).
- `utils/technical_events.event_label()` — one objective, dated label shared by the chart title/caption
  AND the evidence event-list (text↔chart read consistently); `chart_generator._human_event` now delegates.
- Config: `charts.detection.subchart_width_px` (size hint on sub-chart markers → NewX `.chart-md`).

## Changed — Step 4: synthesis placement (`research/synthesis.py`) + NO-INCONSISTENCY AUDIT
Per CLAUDE.md's no-inconsistency clause, ALL THREE chart-placement instructions the writer sees now
speak with one voice — **event-aware** and **multiple-charts-per-stock**:
- Main INLINE-CHARTS directive: **removed the "one chart per stock" assumption** (Step 3 emits several
  per stock) and added event-aware placement (golden-cross by the trend discussion, RSI/MACD by
  momentum, ADX by trend-strength, volume by volume/confirmation).
- AVAILABLE-CHARTS checklist + the `_repair_chart_markers` prompt: same event-aware, several-per-stock
  wording. Alternation stays baked into each marker's `align` (copied VERBATIM) — the LLM decides only
  WHICH SECTION, never the side, so no directive tells it to alter a marker.

## Verification
- `tests/utilities/test_event_charts.py` (+3 new): `variant` cache separation (main + per-event don't
  collide; same variant = hit), `event_label` objective/dated output, tool advertises `analysis_horizon`.
  Full offline suite **16/16 passing**; existing chart-generation/publisher tests still green.
- **Live E2E is the operator's integration test** (real-LLM placement/tool-call behavior): an `@Ask`
  long-term and short-term stock query on prod, with `charts.enabled` — expect main + event sub-charts,
  each zoomed to its event and floated beside the relevant discussion. Per CLAUDE.md, LLM behavior is
  verified on the real code path, not a synthetic test.

## No new dependencies.
Remaining: Step 5 (NewX one-line `.ai-post-content { display: flow-root }` float-containment) before the
floats render correctly; Phase 4 (orphan-chart cleanup) recommended companion given sub-charts multiply file count.
