# Changelog — v1.0.0.194

**Date:** 2026-07-18
**Scope:** Inline chart cards — Phase 5 selection + ADX-chart polish, from live-test feedback: the
featured event sub-charts didn't mirror the prose's emphasis (two redundant MACD cards, and the
structural SMA death cross the analysis LEADS with had no chart), and the ADX-weakening card drew
only the 25 line.

## Changed — sub-chart SELECTION (`utils/technical_events.select_featured_events` + analyzer)
Replaced the inline "most-recent per exact type" pick with a testable helper:
- **One card per indicator FAMILY** (rsi / macd / adx / sma / volume) — `macd_cross` + `macd_zero_cross`
  now collapse to a single (most-recent) MACD card; no more duplicate MACD charts.
- **Structural families guaranteed a slot when present** via config
  `charts.detection.subchart_priority_families: [sma]` — the SMA golden/death-cross trend regime is
  featured even though it isn't the most *recent* event (it's what the analysis leans on).
- Remaining slots fill by recency; result is chronological. Pure deterministic selection (LLM-policy
  gate: which structured events to visualize, not meaning classification). `comprehensive_stock_analyzer`
  now calls the helper.
- Effect (verified on real TSLA short-term): was `macd_cross, macd_zero_cross, adx_weakening` → now
  `sma_cross (death cross), adx_weakening, macd_cross` — matches the prose's "death-cross regime" lead.

## Changed — ADX sub-chart reference lines (`utils/chart_generator.generate_event_chart`)
The ADX card now draws BOTH regime thresholds — **25** (strong) and **20** (weak) — so an
"ADX weakening (<20)" event shows the line it actually crossed (previously only 25 was drawn, leaving a
<20 event with no visible reference).

## Verification
- `tests/utilities/test_technical_events.py` +2 tests (family de-dup, structural priority, cap, empty);
  full suite **19/19 green**.
- Visual spot-check on real TSLA: the new selection renders a correct death-cross card (SMA 50 crossing
  below SMA 200 at the marker) and the ADX card shows the 20 line with ADX dipping through it.

## No new dependencies.
