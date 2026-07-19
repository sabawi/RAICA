# Changelog — v1.0.0.193

**Date:** 2026-07-18
**Scope:** Inline chart cards — **Phase 5 bugfix**: event sub-charts silently produced NONE on real
data (tz-aware index). Found by the live @Ask integration test; fixed + regression-tested.

## Bug
`generate_event_chart` returned `None` for every real event, so no event sub-charts ever emitted
(main chart was unaffected). Root cause: **yfinance history has a timezone-AWARE index**
(`America/New_York`) while detected event dates are naive `YYYY-MM-DD` strings. Comparing them
(`event_window` / crop) raised `TypeError: Cannot compare tz-naive and tz-aware`, which the
never-raises guard swallowed → silent None. The synthetic unit-test fixtures used a naive
`date_range`, so they never reproduced it.

## Fix
Normalize the index to tz-naive at the three points it meets the naive event-date strings:
`technical_events._normalize`, `technical_events.event_window`, and
`chart_generator.generate_event_chart` (`.tz_localize(None)` when `index.tz` is set). Detection was
already fine (dates came from index elements); the render path was the failure.

## Verification
- New regression test `test_tz_aware_index_like_yfinance_renders` — localizes the fixture to
  `America/New_York` and asserts detection + render both work. Full suite **17/17 green**.
- Offline repro on real `yfinance` TSLA 2y history: 3 event sub-charts now generate + upload.
- **Live @Ask integration test (short-term, 5-month TSLA vs IBM):** `🖼️ 3 event sub-chart(s)
  EMITTED for TSLA (short_term)` and for IBM; the reply rendered each sub-chart zoomed to its event,
  placed beside the discussion of that event (TSLA: ADX/MACD June-July; IBM: the July-15 crash cluster).

## No new dependencies.
