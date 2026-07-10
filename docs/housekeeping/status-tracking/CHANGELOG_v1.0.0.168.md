# Changelog — v1.0.0.168

**Date:** 2026-07-10
**Scope:** Add **technical analysis** to the stock analyzer (item #3 of the finance-DR plan) — a curated indicator set emitted as a `TECHNICAL ANALYSIS` SOURCE block for the LLM. Uses `pandas-ta-classic`. Text-only; chart generation is a separate future line item.

## Library decision (joint, with the user)
The user researched the TA-library landscape and prototyped a wrapper; I researched independently. Outcome:
* **pandas-ta-classic 0.6.52** chosen. Critical fact that settled it: unlike the old `pandas-ta 0.4.x` (which hard-requires **Numba**, capped at numpy ≤ 2.2 and fails to import on RAICA's pinned **numpy 2.3.2**), the classic fork requires **only numpy + pandas** (no Numba, no C). Verified in RAICA's exact venv: installs with **zero changes** to the pinned numpy 2.3.2 / pandas 2.3.1 and computes SMA/RSI/MACD/ADX/ATR/Bollinger. Rejected: TA-Lib (system C-lib install friction on the live box), `pandas-ta 0.4.x` (Numba/numpy-2.3 incompatible + being archived), `ta`/`finta` (stalled).

## What was added
New `utils/technical_indicators.py` (`TechnicalIndicators`), wired into `comprehensive_stock_analyzer` detailed mode (flag `DETAILED_ANALYSIS_TECHNICAL`). From ~2y of daily history it computes and renders a SOURCE block of **objective values + states** (per CLAUDE.md, **no hardcoded buy/sell signals** — the LLM interprets):
* **Trend:** 50-/200-day SMA, price-vs-SMA, and **golden/death-cross regime**.
* **Momentum:** RSI-14 (with overbought >70 / oversold <30 / neutral zones), MACD (line vs signal + histogram).
* **Trend strength:** ADX-14 (strong >25 / developing / weak <20) + −DI/+DI.
* **Volatility:** ATR (% of price) + annualized realized volatility.
* **Position:** 52-week range position (%), Bollinger %B.
* **Momentum returns:** 1 / 3 / 6 / 12-month price returns.

Every indicator is wrapped defensively; short/missing history → empty block (never a crash or half-rendered SOURCE).

## Files changed
* `utils/technical_indicators.py` — **new** `TechnicalIndicators`.
* `user_tools/comprehensive_stock_analyzer.py` — import + gated detailed-mode block.
* `config/feature_flags.py` — `DETAILED_ANALYSIS_TECHNICAL = True`.
* `requirements.txt` — `pandas-ta-classic==0.6.52`.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_technical_indicators_states_and_guards`.
* `version.py` — `1.0.0.167` → `1.0.0.168`.

## Verification
* **Compat:** pandas-ta-classic 0.6.52 confirmed in RAICA's pinned env (numpy 2.3.2), no numba, no dependency changes.
* **Mixed-cap E2E:** NVDA/CROX/FUBO/JPM/KO — all render correct objective states. Notably it **adds value where fundamentals fall short**: JPM (bank, no DCF) gets a full technical read; FUBO (distressed small-cap) shows death-cross / 2%-of-range / −78% 12M. Zero crashes.
* **Unit tests:** 33/33 PASS (was 32). New test covers computed states (golden cross), objective rendering (overbought/strong-trend/MACD state), and no-data guards.

## Deferred (separate line item)
* **"Generate TA Charts and embed them in the response"** — pandas-ta-classic + the user's `plot()` prototype can render multi-panel charts into HTML/PDF email (already supported). Open question for inline display in NewX/OpenWebUI: whether those clients render **justified inline image blocks** (markdown `![](url)` shows inline in most, but left/center/right float usually needs HTML/CSS that chat renderers sanitize) — needs per-client investigation. Parked intentionally.
