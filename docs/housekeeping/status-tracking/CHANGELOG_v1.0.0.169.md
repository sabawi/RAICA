# Changelog — v1.0.0.169

**Date:** 2026-07-10
**Scope:** Add a **reverse-DCF / implied-growth readout** to the DCF block, reframing "X% overvalued" into "what FCF growth is the market pricing in?". Addresses the concern that a uniform FCF-DCF misleadingly brands most growth/tech names as severely overvalued — solved via **inputs/framing driven by each company's own data**, NOT a hardcoded sector factor.

## Problem / design decision
A single conservative FCF-DCF (5-yr explicit, capped growth, 2.5% terminal) tags durable-growth companies as "severely overvalued" (AVGO −72%, NVDA −60%, etc.) because its *assumptions* are wrong for them, not because tech deserves a magic multiplier. The user proposed "factoring up the DCF by sector/industry/cycle." We deliberately did NOT do that — a `sector → factor` lookup is (a) the exact hardcoded, meaning-encoding pattern the LLM-Policy-Gate / Generalization directives forbid, and (b) circular (tuning the model to match the market makes it uninformative). Instead we reframe the DCF around the company's own numbers and let the LLM judge sector/cycle fit.

## What was added (`utils/dcf_calculator.py`)
* **Reverse-DCF solver** — `_implied_growth()` bisects the explicit-phase FCF growth rate that makes THIS SAME model's intrinsic value equal the current market price (all other inputs held at the forward base case; intrinsic value is monotonic in growth, so bisection is exact). `_intrinsic_at_growth()` helper. Returns a growth + a bound flag (`above`/`below`) when the price is outside the [−50%, +150%] solvable band.
* **Readout in the DCF SOURCE block** — clearly labeled "REVERSE-DCF — IMPLIED GROWTH (RAICA MODEL METHODOLOGY)", explains the calculation, and contrasts the implied growth against the base-case model growth and the historical FCF CAGR, with a directive to compare against analyst forward estimates and judge vs the company's growth durability / sector / cycle. DCF content cap raised 1000 → 1600 to fit it.

## Why it fixes the concern (mixed-name reads)
| | Base "downside" | **Implied growth** | Historical | Reframed read |
|---|---|---|---|---|
| AVGO | 72% | ~45%/yr | 18.2% | priced for hypergrowth ~2.5× history |
| NVDA | 60% | ~48%/yr | ~100% | priced **below** its own history → deceleration, not "overvaluation" |
| CROX | (48% up) | ~0%/yr | 9.7% | priced for zero growth → pessimistic |
| KO | 60% | ~12%/yr | −18% | priced for a FCF turnaround history doesn't support |
| QCOM | 7% | ~16%/yr | 23.3% | priced near base — roughly fair |

The NVDA case is the proof: the market implies growth *below* NVDA's track record, so the "60% overvalued" verdict was the misleading artifact. All sector-neutral, driven by each name's own numbers — zero hardcoded factors.

## Files changed
* `utils/dcf_calculator.py` — `_intrinsic_at_growth`, `_implied_growth`, computed in the positive-equity branch, rendered in `format_dcf_for_llm`; content cap 1000→1600; "-0%" cosmetic fix.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_dcf_reverse_implied_growth` (solver reproduces the price; monotonic; out-of-band bound).
* `version.py` — `1.0.0.168` → `1.0.0.169`.

## Verification
* **Unit tests:** 34/34 PASS (was 33).
* **Live analyzer:** implied-growth reads sensible/insightful across AVGO/NVDA/CROX/KO/QCOM (table above); readout renders in full (no truncation).

## Notes
* This is item **A** of the DCF-tempering plan. Deferred (user will do comparative analysis first): **B** = two-stage/fade DCF driven by analyst-consensus growth (a genuinely better *fair-value* estimate); **C** = LLM-led sector/cycle judgment on the presented scenarios. No sector multiplier — ever.
