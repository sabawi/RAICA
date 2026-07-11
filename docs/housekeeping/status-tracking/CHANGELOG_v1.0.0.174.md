# Changelog — v1.0.0.174

**Date:** 2026-07-11
**Theme:** Inline-chart reliability at scale (multi-stock DR) + finance ticker robustness + **pro deep-research baseline**. Validated end-to-end across three live runs: big-5 tech, an 8-name mixed-cap edge basket, and a personalized cash-vs-TSLA-vs-IBM decision question.

## Charts — reliable at multi-stock scale

* **Chart-completeness in DR synthesis (the headline fix).** Multi-stock DR reports were **silently dropping chart markers** — a stochastic, all-or-nothing behavior of the synthesis model (it treated `[[chart:…]]` markers buried in EVIDENCE blocks as reference to summarize, not content to reproduce; ~⅔ drop rate). Two rule-compliant layers, both keeping the LLM as the placement decider (`research/synthesis.py`):
  - **Salient "AVAILABLE CHARTS" inventory** — the evidence's chart markers are surfaced as a distinct "you MUST place each" checklist *outside* the evidence blob (first-pass relay ~33% → ~100%).
  - **Completeness verify → re-place loop** — after the draft, RAICA does a structural set-difference (markers present?) and, if any are missing, feeds them back to the LLM to reinsert (bounded 3 passes, content-preservation guard). RAICA never positions a marker; the LLM does. Mirrors the existing claim-verification / `enumeration_two_pass` pattern.
  - Config: `deep_research.engine.synthesis.chart_completeness` (`enabled: true`, `max_repair_passes: 3`, `min_content_ratio: 0.85`).
* **Chart regression fixed** — a function-local `import logging` inside `execute()` shadowed the module-level one, so the chart-history fetch hit `UnboundLocalError` (swallowed → `_hist=None` → chart silently skipped). Added module-level `import logging`, removed the local one. Regression test `test_no_function_local_logging_shadow`.
* **Chart cap `max_per_response` 6 → 10** — an 8-stock basket capped the last 2 charts.
* **Transparency probes kept** — `🖼️ chart marker EMITTED`, `🖼️ chart NOT emitted (reason)`, and `🖼️🔎 synth chart-markers (final) required=N final_draft=N` — low-noise operational logs that caught these issues and give ongoing completeness visibility.

## Finance — ticker robustness

* **De-hardcoded the ticker-format gate** (`comprehensive_stock_analyzer.execute()`). `if not ticker.isalpha()` (+ schema `^[A-Z]{1,5}$`) silently rejected every class-share / dual-listing symbol — **BRK-B**, BF-B, BRK.B, HEI-A — dropping it from the analysis (and the report title). Replaced with a sanity-only guard (single token, ≤8 chars); the **fetch decides validity** (no data → transparent error). Schema pattern → `^[A-Za-z0-9.\-]{1,8}$`. Test `test_ticker_gate_allows_class_shares`.
* **Removed `DOW`** from the `general_market_tickers` misuse list — it is a real ticker (Dow Inc.). (`INDEX` and the 7 no-data words remain guarded; full removal deferred — see the audit doc, `INDEX` resolves to a real ETF.)

## Deep Research — pro quality baseline

* **`deep_research.engine.heavy_threshold_chars` 250000 → 20000.** After a flash-vs-pro study (see the flash/pro comparison), every real DR synthesis (~30K+ prompt) and verify (100K+) now routes to **deepseek-v4-pro:cloud** for more professional, persuasive output; only the small mechanical sub-calls (plan/grade/relevance, <~8K) stay on flash. Dev == prod (identical). Cost-reduction tuning deferred.
* `synthesis.max_answer_tokens` 16000 → 32000 and `verification.max_tokens` 16000 → 24000 (shipped v172) keep the longer pro reports from truncating.

## Verification (all live, end-to-end through NewX)

* **Big-5 tech** (AMAT/AMD/AVGO/NVDA/QCOM): 5/5 charts, pro routing, `draft=5`.
* **Mixed-cap edge basket** (KO, JPM [bank/FCF=None], BRK-B [hyphen], CROX, RIVN [neg earnings], PLUG [−227% margin], FUBO [micro], RBRK [recent IPO]): after the fixes, **8/8 full analysis + 8 cards**, BRK-B back in the title, no cap hit, `draft=8`.
* **Personalized decision question** (cash vs TSLA vs IBM, 2-yr hold): auto-invoked the analyzer on both, 2 cards, decision-focused pro advice.
* Unit suite green (`test_financial_calculators_accuracy.py`, incl. the new gate/completeness/logging tests).

## Config / no new dependencies
* `config/llm_config.yaml`: `charts.max_per_response` (10), `charts.enabled` ships **false**, `deep_research.engine.synthesis.chart_completeness`, `heavy_threshold_chars` (20000). No new Python dependencies.

## Deferred (tracked in `docs/RAICA_FINANCE_HARDENING_AUDIT.md`)
* Finance hardening **P2 (transparency sentinels)** + **P3 (`_safe_div` sweep)** — next.
* Full removal of `general_market_tickers` (needs the `INDEX`-resolves-to-a-fund ambiguity handled).
* Advice-quality prompt tweaks (cite beta; name long-term capital-gains benefit).
