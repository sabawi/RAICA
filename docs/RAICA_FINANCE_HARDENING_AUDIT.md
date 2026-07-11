# RAICA Finance Code — Pre-Production Hardening Audit

**Status:** DRAFT — awaiting sign-off before code changes
**Owner:** (finance/DR)
**Created:** 2026-07-11
**Motivating incident:** In a 5-stock analysis (AMAT/AMD/AVGO/NVDA/QCOM), **AVGO silently vanished** — a transient Yahoo `quoteSummary` error (`{'code':'Internal Server Error','description':'Server caught an exception'}`) on `stock.info` with **no retry** killed the entire ticker (no fundamentals, DCF, technicals, or chart). It surfaced only as two `[unverified]` citations and a "data unavailable" note. Root-caused + a first fix shipped (`utils/yf_retry.py` + analyzer gate retry, v1.0.0.172). **This audit generalizes that fix across ALL finance code.**

---

## 1. Goal & definition of "iron-clad"

Every finance data path must be **either**:
- **(A) Seamlessly recovered** — transient upstream failures (Yahoo/network) are retried and absorbed so a single blip never fails a ticker; **or**
- **(B) Transparently failed** — when data genuinely can't be obtained/computed, the failure is **visible**: logged, distinguishable from "legitimately empty," and reflected in the output as a clear "unavailable / computation failed" label. **Never a silent wrong number, never faked data.**

The forbidden middle ground (today's reality in places): a failure swallowed into `{}`/`None`/`0`/`"N/A"` that downstream code processes as if it were real, producing a plausible-but-wrong answer with no signal that anything broke.

### Guardrails (LLM-policy gate compliance)
These are **resilience / data-integrity** fixes, not "meaning/intent" decisions — but they must still be **general**: no per-ticker special-casing, no error-*string* matching to decide control flow. Retry catches transient failures generically; guards check for missing/zero operands generically.

---

## 2. Architecture map (what fetches vs. what computes)

| Kind | Modules | Risk class |
|---|---|---|
| **FETCH** (hit Yahoo/yfinance — transient-failure exposure) | `comprehensive_stock_analyzer` (gate + chart history), `financial_statements_extractor`, `analyst_estimates`, `technical_indicators` | Pillar 1 (recovery) + Pillar 2 (transparency) |
| **COMPUTE** (receive data as args, do arithmetic — division/None exposure) | `dcf_calculator`, `financial_ratio_calculator`, `projection_engine` | Pillar 2 (transparency) + Pillar 3 (data-integrity) |

Data flow: `comprehensive_stock_analyzer.execute(detailed=true)` → `financial_statements_extractor.extract_financials()` (statements) + `_get_real_time_data()` (quote/info) → feeds `dcf_calculator`, `financial_ratio_calculator`, `projection_engine`, `analyst_estimates`, `technical_indicators` → formatted into the DR evidence.

---

## 3. The three pillars

### Pillar 1 — Seamless recovery (retry every fetch)
Route **every** yfinance touchpoint through the tested `utils/yf_retry.fetch_with_retry(fn, attempts, backoff, label, log)`. Config-driven via `stock_analyzer.fetch_retries` / `fetch_backoff_seconds` (already added). No fetch stays single-shot.

### Pillar 2 — Transparent errors (never silent, never faked)
Audit every broad/bare `except`. Each must resolve to one of:
- **recover** (retry — Pillar 1), or
- **graceful-degrade with a signal**: return a value that is *distinguishable* from real data (e.g. an explicit `unavailable=True` / a sentinel the formatter renders as "unavailable — fetch failed"), **and** log at `warning`/`error`.

Specifically kill the "`return {}` / `return None` on fetch failure that looks identical to genuinely-empty" pattern. Callers must be able to tell **"no data exists"** from **"the fetch/compute failed."**

### Pillar 3 — Data-integrity guards (division / None arithmetic)
Audit heavy-division sites. Any division must guard denominator `None`/`0`/`NaN` and any arithmetic must guard `None` operands → emit a labeled "n/a" rather than crash, `inf`, `NaN`, or a wrong number. (Extends the F1–F6 hardening.)

---

## 4. Module-by-module audit (grounded in current code)

Legend: ✅ done · ⚠️ gap · 🔴 high-severity gap. Line refs are current as of v1.0.0.172.

### 4.1 `user_tools/comprehensive_stock_analyzer.py` (844 lines · 11 yf calls · 24 broad excepts · ~85 div)
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:236-238` quote gate (`.info`/`.history`) | transient Yahoo error | ✅ **retried** (v172) | done | 1 |
| `:783` chart history (`.history(2y)`) | transient error | ⚠️ in graceful try → skips chart | route through `fetch_with_retry` | 1 |
| `:258-259` gate `except → {"error":…}` | — | ✅ surfaces clear error | keep | 2 |
| 24 broad excepts across detailed block | mixed | ⚠️ audit each | classify recover/graceful-signal | 2 |
| ~85 division sites (display formatting) | None/0 operands | ⚠️ partial (F1–F6) | guard sweep | 3 |

### 4.2 `utils/financial_statements_extractor.py` (354 lines) — 🔴 **highest blast radius**
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:76-91` fetches `financials`, `quarterly_financials`, `balance_sheet`, `quarterly_balance_sheet`, `cashflow`, `quarterly_cashflow`, `info` — **7 single-shot calls** | any transient blip on any one | 🔴 no retry | wrap **each** (or the whole block) in `fetch_with_retry` | 1 |
| `:24-26` `except → logger.error; return {}` | any failure | 🔴 **masks failure as empty** — every downstream calculator (DCF/ratios/projections) gets `{}` and emits N/A everywhere with no "fetch failed" signal | return a distinguishable failure sentinel (e.g. `{"_error": str(e)}`) so callers/formatter show "statements unavailable — fetch failed", not silent blanks | 1+2 |

### 4.3 `utils/analyst_estimates.py` (171 lines · 8 yf calls)
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:52` `yf.Ticker(ticker)` / `:61` `t.info` | transient | ⚠️ `:62-64 except → info={}` silent | retry fetch; on real failure signal "analyst data unavailable — fetch failed" | 1+2 |
| `:~80` `get_earnings_estimate()` / `:~92` `get_revenue_estimate()` | transient/missing | ⚠️ `:87/:95 except → log + skip` (graceful but unretried) | retry; keep graceful skip only for genuinely-absent | 1 |
| `:77` `tm/cp` upside | div-by-zero | ✅ guarded `if tm is not None and cp` | keep | 3 |

### 4.4 `utils/technical_indicators.py` (226 lines · 3 yf calls)
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:53-54` `yf.Ticker` / `.history(2y)` | transient | ⚠️ single-shot; `:142 except → log + unavailable` | retry the history fetch | 1 |
| indicator math (RSI/MACD/ADX, ~12 div) | short/NaN series | mostly guarded (min-length checks) | verify NaN/short-series guards | 3 |

### 4.5 `utils/dcf_calculator.py` (786 lines · ~30 div) — COMPUTE
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:53`, `:156` **bare `except:`** | swallows everything (incl. bugs) | ⚠️ `except: return None` | narrow to `except Exception`, log | 2 |
| `:237-239` WACC `except → warning; return None` | — | ✅ logged + None | ensure formatter labels "WACC unavailable" | 2 |
| ~30 division (WACC, terminal value, per-share) | 0/None denominators | ⚠️ partial (F1–F6) | guard sweep (shares, WACC−g, equity) | 3 |

### 4.6 `utils/financial_ratio_calculator.py` (733 lines · ~78 div) — COMPUTE, heaviest division
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:42`, `:56` **bare `except:`** | swallows everything | ⚠️ `return default`/`None` | narrow to `except Exception`, log when non-trivial | 2 |
| ~78 division (every ratio) | 0/None denominators | ⚠️ partial | systematic `_safe_div` helper returning labeled n/a | 2+3 |

### 4.7 `utils/projection_engine.py` (486 lines) — COMPUTE
| Site | Failure mode | Current | Fix | Pillar |
|---|---|---|---|---|
| `:43`, `:75` **bare `except:`** | swallows everything | ⚠️ `return None` | narrow + log | 2 |
| `:169-171`, `:224-226`, `:281-283` `except → error; return {}` | any failure | ⚠️ masks as empty | distinguishable sentinel + formatter label | 2 |

---

## 5. Cross-cutting standards to introduce

1. **Finance-fetch contract:** every yfinance access goes through `fetch_with_retry` (already the primitive). No direct `yf.Ticker().<x>` without it.
2. **`_safe_div(num, den, *, label)` helper:** single shared guard for division — returns `None` (→ formatter "n/a") when `den` is `None`/`0`/`NaN` or `num` is `None`. Replaces ad-hoc guards in ratios/DCF.
3. **Failure sentinel over empty:** fetch/compute failures return a value the caller can distinguish from "legitimately empty" (e.g. `{"_error": "..."}`), and the LLM-facing formatter renders it as an explicit "**unavailable — fetch/computation failed**" line (so the model states it plainly instead of fabricating).
4. **No bare `except:`** in finance code — always `except Exception` (never swallow `KeyboardInterrupt`/`SystemExit`), always log the swallowed error.

---

## 6. Test strategy (test-driven, fault-injected)

- **Mixed-cap basket** (data shapes differ by cap/sector): `FUBO` (small, neg FCF), `CROX` (mid), `RIVN` (neg earnings), `KO` (large dividend), `JPM` (bank — breaks FCF-DCF). Not just large-cap semis.
- **Fault injection** (monkeypatched, offline — like `test_yf_fetch_retry`):
  - transient `.info`/statement/`.history` failure N times → assert **recovery**;
  - permanent failure → assert **clear labeled error** surfaces (not blank/fake);
  - missing statement rows / zero denominators / `None` fields → assert **labeled n/a**, no crash/`inf`/`NaN`/wrong number.
- Extend `tests/utilities/test_financial_calculators_accuracy.py`; all fault-injection tests offline & deterministic (Tier-0 eligible).

---

## 7. Proposed sequencing (each phase = tests + one restart + E2E)

| Phase | Scope | Risk |
|---|---|---|
| **P1 Recovery** | Route all fetch sites (§4.2–4.4, +analyzer chart) through `fetch_with_retry` | low (reuses tested helper) |
| **P2 Transparency** | Failure sentinels + formatter labels (§4.2, 4.3, 4.7); kill bare `except:` (§4.5–4.7) | medium (changes return contracts — needs caller/ formatter updates + tests) |
| **P3 Data-integrity** | `_safe_div` sweep across ratios/DCF (§4.5, 4.6); NaN/short-series guards (§4.4) | medium (wide but mechanical) |

Each phase validated on the mixed-cap basket + fault injection before moving on. P1 first (immediate resilience win, lowest risk).

---

## 8. Sign-off checklist (before starting code) — ✅ SIGNED OFF 2026-07-11
- [x] Scope agreed: all 7 modules, 3 pillars.
- [x] **Failure-sentinel approach agreed** — on failure return a distinguishable `{"_error": "..."}` value; the LLM-facing formatter renders an explicit "⚠️ unavailable — fetch failed (not blank data)" line. (Chosen over raise-to-caller: less invasive, preserves graceful degradation.)
- [x] Test basket agreed: FUBO/CROX/RIVN/KO/JPM + fault injection (transient-fail → recover; permanent-fail → labeled error; missing/zero → labeled n/a).
- [x] **Sequencing agreed: P1 (retry-everywhere) → P2 (transparency sentinels) → P3 (`_safe_div` sweep)**, each a tested increment (tests + restart + E2E) before the next.
- [x] Confirmed **separate** effort from the chart work — chart hardening + AVGO-gate retry committed first (v1.0.0.172) so the audit starts on a clean base.

### Progress
- **✅ P1 (Recovery) — DONE (v1.0.0.173).** Added `yf_retry.configured_fetch` (config-driven convenience) and routed EVERY remaining single-shot fetch through it: `financial_statements_extractor` (7-statement build), `analyst_estimates` (info + earnings/revenue/growth estimates), `technical_indicators` (2y history), `comprehensive_stock_analyzer` chart history (the `.info`/`.history` gate was already retried in v172). Retry triggers only on a THROWN transient error; genuinely-absent data (empty return) skips as before. Tests: `test_yf_fetch_retry`, `test_finance_fetch_retry_p1` (extractor recovers from a transient blip instead of `return {}`). Live smoke: AVGO statements + analyst + technicals all fetch through the retry path.

### Additional fixes shipped alongside (v1.0.0.174)
- **Ticker-format gate de-hardcoded** — `comprehensive_stock_analyzer.execute()` used `if not ticker.isalpha()` (+ schema `^[A-Z]{1,5}$`), which silently rejected every class-share / dual-listing symbol (**BRK-B**, BF-B, BRK.B, HEI-A) — the mixed-cap basket caught it. Replaced with a sanity-only guard (single token, ≤8 chars); the **fetch decides validity** (no data → transparent error). Removed **DOW** from the `general_market_tickers` misuse list (it is a real ticker, Dow Inc.).
- **Chart cap 6 → 10** (`charts.max_per_response`) — an 8-stock basket capped the last 2 charts.

### Deferred (validated, tracked — do deliberately in the hardening pass)
- **Remove the `general_market_tickers` hardcoded list entirely.** Empirically checked (2026-07-11): of the 8 remaining words, 7 resolve to no yfinance data (still clean misuse errors), but **`INDEX` resolves to a real obscure ETF ("CYBER HORNET S&P 500")** — a blind removal would silently analyze it. So the full removal needs a deliberate design (fetch-decides + ambiguity note for index-like words), not a one-liner. Not urgent (no active problem).
- **Advice-quality prompt tweaks** (from the TSLA-vs-IBM decision test): the answer argued risk qualitatively ("speculative gamble") without citing **beta**, and covered the tax holding period without naming the **long-term capital-gains** rate benefit. Prompt-level, not code.

**▶ RESUME HERE:** Start **Phase P2 (Transparency)** — replace failure-as-empty with a distinguishable **failure sentinel** `{"_error": "..."}` + a formatter line "⚠️ unavailable — fetch failed (not blank data)":
- `financial_statements_extractor.py:97-99` `except → return {}` → return `{"_error": str(e)}`; update `format_for_llm` + all callers (analyzer detailed block, dcf/ratio/projection inputs) to detect `_error` and render the label instead of blank N/A.
- `analyst_estimates` / `technical_indicators`: on a *fetch* failure (vs genuinely-absent) mark the block "unavailable — fetch failed".
- `projection_engine.py:169-171/224-226/281-283` `except → return {}` → sentinel.
- Kill bare `except:` (dcf `:53/:156`, ratio `:42/:56`, projection `:43/:75`) → `except Exception` + log.
Add tests: permanent-failure → labeled error surfaces (not blank/fake). Then P3.
