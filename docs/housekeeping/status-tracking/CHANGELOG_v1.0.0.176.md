# Changelog — v1.0.0.176

**Date:** 2026-07-11
**Scope:** DCF valuation — forward-aware, transient-robust **stage-1 growth**, and a **transparent, self-explaining** DCF output. Fixes the pathological under-valuation of mature/quality names.

## The bug
The DCF projected stage-1 FCF growth from **trailing 3-yr FCF growth only** (`(trailing + 5%)/2`), extrapolating a **transient** trailing number forward. Example: **KO**'s trailing FCF growth was **−17.8%** (a one-time payment / working-capital swing), so the model projected KO's FCF *shrinking 6.4%/yr* for a dividend aristocrat → intrinsic **$33** (−60%), while analysts saw **+6.6%**. A single bad trailing year crushed the valuation.

## The fix (`utils/dcf_calculator.py`)
* **Stage-1 growth = MEDIAN(trailing FCF growth, analyst FORWARD growth, 5% sustainable anchor)** — floored at the terminal rate (a profitable, positive-FCF company is never projected to shrink forever) and capped at 20%. The median is the key: it is **robust to a single transient outlier** (KO's −17.8% and NVDA's +100% are both ignored) while pulling in **forward-looking** analyst growth.
* `calculate_intrinsic_value` gains an optional `analyst_growth` param (fraction). `comprehensive_stock_analyzer` now computes `AnalystEstimates` **once** and feeds its forward EPS growth into the DCF (and reuses the object for the analyst block — no extra network call).
* **Transparent output** (`format_dcf_for_llm`): the DCF now prints its derivation — the three growth signals and the chosen median, the WACC (with Blume-beta note), terminal rate, and the method line — so every intrinsic value is self-explaining and auditable.

## Impact (validated)
| Stock | before | after | why |
|---|---|---|---|
| **KO** | $33 (−60%) | **$61 (−27%)** | transient −17.8% ignored → median 5.0% |
| JNJ / PG / PEP | — | $173 / $122 / $157 | median smooths trailing + analyst |
| **NVDA** | $83 (−61%) | **$83 (−61%)** | median(100%,42%,5%)=42% → capped 20% — **unchanged, stays conservative** |
| RIVN / PLUG / FUBO (neg FCF), JPM (bank) | refuse | **refuse** | untouched — still labeled "not meaningful" |

## Verification
* Unit: new `test_dcf_median_blend_growth` (transient negative trailing ignored, forward growth used, floored, derivation shown) + all existing DCF tests (negative-equity guard, Blume/TTM/sensitivity, marketable-securities, reverse-DCF) pass. Full suite green.
* Live validation: continues on sabawi.net (finance testing to surface any anomalies).

## Honest note
The median is deliberately conservative — for several mature names it lands on the 5% anchor, and a name whose FCF is genuinely depressed (e.g. MSFT, AI capex) still reads rich because the median picks 5% over the higher analyst figure. Defensible (robust, not over-optimistic); the reverse-DCF line contextualizes it. Deferred DCF item C (LLM sector/cycle judgment) remains open.

## No config / dependency changes.
