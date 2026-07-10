# Changelog — v1.0.0.164

**Date:** 2026-07-10
**Scope:** Two more yfinance field-scale bugs found in the live @Ask output (F6 + debtToEquity), plus a synthesis "comparative/superlative" guard to stop the prose-vs-table ranking errors seen across two live runs.

## F6 — Revenue Growth rendered 100× too small (confirmed bug)
`user_tools/comprehensive_stock_analyzer.py:598`.

`revenueGrowth` from yfinance is a **fraction**, but the display rendered it with `_format_change` (which only formats the number) then appended `%` → e.g. NVDA `0.852` → **"+0.85%"** instead of **85.20%**. Verified empirically against yfinance 0.2.65: NVDA 0.852, AMAT 0.114, AVGO 0.479, QCOM −0.035. Every stock's revenue-growth line in the live report was wrong, and the synthesis LLM tried to rationalize it ("misleadingly low"). Fixed by rendering via `_format_percentage` (`:.2%`, ×100), matching the adjacent Profit Margin / ROE lines. Same class as the v1.0.0.162 dividend-yield fix.

## debtToEquity display units (confirmed, minor)
`user_tools/comprehensive_stock_analyzer.py:601`.

yfinance `debtToEquity` is a **percentage number** (verified: NVDA 6.555, AMAT 30.399, AVGO 74.018), i.e. `30.4` means `0.30x`. The display block rendered it raw ("30.4"), so it read as *30× leverage* and **contradicted the computed leverage block** in the same tool output (which correctly said `0.30x`). New `_format_debt_to_equity` helper divides by 100 and renders `0.30x`. Low impact (the LLM used the computed block both runs) but removes a self-contradiction in the evidence.

## Leaderboard guard — synthesis comparative/superlative directive
`research/synthesis.py` (draft system prompt).

Across two live 5-stock runs the synthesis made a factual ranking error each time that contradicted its own table:
- Run 1: "AVGO forward P/E is the second-lowest (after QCOM)" — false; NVDA (15.9x) is lower.
- Run 2: "NVDA has the cheapest / lowest trailing P/E" — false; QCOM (20.6x) is lower. NVDA is cheapest on **forward** P/E only.

Both stem from the LLM asserting an extreme from a subset / conflating metric variants (trailing vs forward P/E). Added a policy directive (not hardcoded ranking — CLAUDE.md compliant): before any superlative/ranking claim, assemble that metric for EVERY entity, order them, confirm the extreme across ALL of them; name WHICH variant (trailing vs forward, gross/operating/net, historical vs projected); and never contradict the report's own comparison table. Chose a policy directive over parsing RAICA's own tool text (fragile, and against the no-text-parsing rule); a fully-deterministic precomputed leaderboard would require the tool to return a structured metrics dict + DR aggregation — noted as a heavier follow-up.

## Files changed
* `user_tools/comprehensive_stock_analyzer.py` — F6 revenueGrowth via `_format_percentage`; new `_format_debt_to_equity`; label "Revenue Growth (YoY)".
* `research/synthesis.py` — comparative/superlative verification directive.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_revenue_growth_and_debt_to_equity_scale` (+ `__main__` runner).
* `version.py` — `1.0.0.163` → `1.0.0.164`.

## Verification
* **Empirical (yfinance 0.2.65):** revenueGrowth fraction + debtToEquity percent-number confirmed for NVDA/AMAT/AVGO/QCOM.
* **Live analyzer path:** NVDA `Revenue Growth (YoY): 85.20%` / `Debt/Equity: 0.07x`; AMAT `11.40%` / `0.30x`; QCOM `−3.50%` / `0.56x`.
* **Unit tests:** 29/29 PASS (was 28). `research.synthesis` imports cleanly.

## Notes
* Local server needs a restart to pick up F6/debtToEquity for live @Ask; the synthesis directive is prompt-only (no schema change).
* Deferred finance-DR items (not in this release): DCF Blume-beta adjustment + sensitivity band (the "every stock 80–94% overvalued, no discrimination" problem); risk-adjusted composite score for pick stability; technical-analysis component; structured analyst-consensus estimates from yfinance (replace web-scraped targets); valuation-vs-own-history; quarterly fundamental momentum.
