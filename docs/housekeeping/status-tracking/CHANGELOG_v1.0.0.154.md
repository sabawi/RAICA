# CHANGELOG — RAICA v1.0.0.154

**Date:** 2026-07-08
**Type:** Feature — grounded quantitative TABLES directive (zero-fabrication)

## Summary
Operator feedback: economic/data-driven DR answers read as prose essays; they should present concrete facts
and figures in TABLES (before/after, current vs historical, by-region, trends). Hard requirement: ZERO
fabricated numbers.

## Change (`research/synthesis.py`)
- Added a **QUANTITATIVE DATA → TABLES** rule to the synthesis GROUNDING block: when the topic is
  economic/statistical/financial/scientific AND the evidence provides concrete figures, present them as clean
  Markdown tables and lead the analysis from the data. ABSOLUTE rule: tabulate ONLY figures the evidence
  actually provides, each cited; NEVER invent/estimate/extrapolate to fill a cell; leave gaps empty or 'n/a
  (not in sources)'; when in doubt, DROP the table and state sourced figures in prose. Conditional — do not
  tabulate purely narrative topics.

## Verification
- NewX renders Markdown tables (`render_ai_content` → `md.enable('table')`), confirmed.
- Re-ran the energy query: **0 tables AND 0 fabricated figures** — CORRECT behavior. The evidence genuinely
  lacked hard figures (the only numbers were AI-chip funding, not oil prices/production), so the directive
  honored zero-fabrication and skipped tabulation. This exposed the true bottleneck: the gather reaches news
  NARRATIVE, not DATA sources (EIA/IEA/OPEC/Our World in Data) — a follow-on.

## Risk / rollback
- Prompt-only, conditional, zero-fabrication by directive. Version → 1.0.0.154.
