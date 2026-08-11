# CHANGELOG v1.0.0.252 — dataset charts described at their real resolution (SI-027)

**Date:** 2026-08-11 · **Previous:** v1.0.0.251 · **Type:** policy (prompt + tool description), no logic

A user asked for a "past two years" chart of 30/20/10/5-year Treasury yields and read it as the
10y and 30y **diverging**. They were not: the 30y−10y spread went **0.52 → 0.54 over 13 months**
(10y +0.39, 30y +0.41) — a parallel shift.

**The data was perfect.** All 12 annual averages matched FRED to the basis point; all four series
resolved to the right identifiers (DGS30/20/10/5). **Zero fabrication.** The defect was entirely
in how the chart was *described*.

## Three misrepresentations

1. **Three annual points narrated as a two-year path.** `search_datasets`/`compare_datasets` plot
   ANNUAL MEANS, so "2024–2026" is three dots per line. A constant gap between two rising lines
   reads as spreading when there is no path to see.
2. **A partial year labelled as annual.** The 2026 point covered **151 trading days** (Jan–Aug).
   30y was shown as **4.93%** against an actual latest of **5.19%**.
3. **A statistic the sample cannot support.** "Trend correlation of **+1.00**" from **three**
   observations carries no information, however precise it looks.

## Why policy, not code

`shape: fred_observations` aggregates every FRED series to annual means and exposes **no frequency
parameter**. A directive telling the model to fetch daily data would be silently defeated by the
code — the LLM-policy gate's exact trap. The directives therefore ask only for what the system
CAN do: **disclose** granularity, **label** a partial period, **refrain** from unsupported claims.

## Two surfaces

| surface | when the model reads it |
|---|---|
| `compare_datasets` **description** | choosing/using the tool — sets expectations *before* writing |
| `_ARTIFACT_MARKER_RELAY` (non-DR answer) | composing — governs how the chart is described |

The specific misreading is named so it cannot recur silently:
*"Two lines rising together with an unchanged gap are NOT diverging; check the gap before you call
it one."*

## Known limitation — NOT fixed

Dataset charts remain **annual-mean only**. A true daily yield path requires a frequency-capable
data path — a code change, deliberately out of scope for a policy-only fix.

## Files changed

| file | change |
|---|---|
| `fastapi_server_complete.py` | three directives added to `_ARTIFACT_MARKER_RELAY` |
| `user_tools/compare_datasets_tool.py` | GRANULARITY paragraph in the tool description |
| `tests/unit/test_chart_granularity_policy.py` | **new** — 8 tests |
| `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` | SI-027 |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.251 → 1.0.0.252 |

## Verification

8 policy tests, including one asserting the policy **never promises** daily/weekly/monthly data the
tool cannot serve. tests/unit 257 passed / 4 failed (identical on baseline). Tier 0 **9/9**.

## Breaking changes

None. Prompt and description text only.
