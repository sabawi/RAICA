# Changelog — v1.0.0.167

**Date:** 2026-07-10
**Scope:** Make the DCF model actually *useful* (item #2 of the finance-DR plan). Three fixes so it stops flagging every stock as 80–94% overvalued and can discriminate quality: Blume-adjusted beta, a quarterly-TTM FCF base, and a WACC-sensitivity band. Validated on a mixed small/mid/large-cap + bank basket.

## Problem
Across two live 5-stock runs the DCF called **every** name 80–94% overvalued — it couldn't tell NVDA (73% ROIC) from AMD (6% ROIC), so the LLM (correctly) dismissed it as a "stress test," making the whole component noise. Two root causes:
1. **Raw CAPM beta** → high-beta names got absurd discount rates (AMD β2.47 → 21.3% cost of equity; NVDA β2.21 → 19.5%), far above the 8–12% typical for large-cap tech.
2. **`info.freeCashflow` FCF base** (v1.0.0.159) **systematically understates** — verified across tickers: NVDA $46.34B vs $119B true TTM; AMAT $3.04B vs $5.34B; QCOM $9.59B vs $12.50B — roughly halving the intrinsic value for those names.

## Fixes (`utils/dcf_calculator.py`)
* **Blume-adjusted beta** (`calculate_cost_of_equity`): `β_adj = 0.67·β_raw + 0.33·1.0` (Blume 1971 — betas mean-revert). Lowers the discount rate into a defensible band while preserving relative ordering (higher-β still costs more): NVDA 2.21→1.81, AMD 2.47→1.99, AMAT 1.57→1.38.
* **Quarterly-TTM FCF base** (new `_ttm_fcf_from_quarterly`): current FCF = TTM sum of the 4 most-recent quarters of (OCF + CapEx) from the **quarterly** cash-flow statement — both current AND auditable. Falls back to the annual statement, then (last resort) `info.freeCashflow`. This supersedes the v1.0.0.159 info-first approach and also solves its original staleness concern (the quarterly-TTM captures recent quarters directly).
* **WACC-sensitivity band** (new `_intrinsic_at_wacc`): reports an intrinsic-value range by flexing WACC ±1.5% (intrinsic value is far more sensitive to the discount rate than any other input) instead of a single false-precision point estimate.
* Display: renders the sensitivity range + a "Blume-adjusted beta" method note; the "adjusted from X%" WACC label now shows only when a blue-chip adjustment actually changed it.

## Result (before → after)
| | FCF base | WACC | Intrinsic | Implied downside |
|---|---|---|---|---|
| NVDA | $46B→**$119B** | 17.4→**14.6%** | $27.66→**$83.21** (range $73–$96) | 86% → **59%** |
| QCOM | $9.6B→**$12.5B** | 14.5→**13.1%** | $116→**$175** | 39% → **8.3%** |
| AVGO | $27B→**$32.8B** | 11.9→**10.9%** | $80→**$112** | 80% → **72%** |
| AMAT | $3B→**$5.3B** | 14.8→**13.5%** | $38→**$74** | 93.5% → **87.5%** |
| AMD | $7.2B→**$8.6B** | 21.2→**17.8%** | $45→**$65** | 91.7% → **88%** |

The DCF now **discriminates** (QCOM near-fair at 8% vs AMD still-rich at 88%) instead of a uniform "~90% overvalued."

## Mixed-cap validation (small / mid / large + bank)
* **FUBO** (small, unprofitable): FCF −$0.47B → **N/M** (neg-equity guard); analyst block renders (8 analysts).
* **CROX** (mid, profitable): $201.51 intrinsic, **+58.5% upside** (DCF can now show upside).
* **RIVN** (cash-burner): FCF −$3.04B → **N/M**; analyst fwd EPS **−$2.31** handled.
* **KO** (large div staple): dividend 2.57%, FCF $12.56B, intrinsic $33.48.
* **JPM** (bank): D/E `N/A` handled; DCF **"Unable to calculate FCF"** (correct — banks have no normal capex/FCF) instead of garbage.
* Scale fixes (revenue growth / dividend / D/E) correct on every name; zero crashes.

## Files changed
* `utils/dcf_calculator.py` — Blume beta, `_ttm_fcf_from_quarterly`, `_intrinsic_at_wacc`, quarterly-TTM FCF selection, sensitivity band, display updates.
* `tests/utilities/test_financial_calculators_accuracy.py` — `test_dcf_blume_beta_ttm_fcf_and_sensitivity`.
* `tests/utilities/test_dr_ttm_sourcing.py` — updated the two v1.0.0.159 DCF tests to the v1.0.0.167 contract (quarterly-TTM primary; added a quarterly fixture) + docstring.
* `version.py` — `1.0.0.166` → `1.0.0.167`.

## Verification
* **Unit tests:** 32/32 PASS. **Mixed-cap E2E:** 5 diverse names (above) all sane or gracefully degraded.

## Notes
* When quarterly cash flow is unavailable (rare; e.g. banks), FCF falls back to annual with a directional note, then to `info.freeCashflow`. Banks correctly yield "Unable to calculate FCF" (FCF-DCF isn't applicable to financials — a candidate future explicit "not applicable to financials" message).
* No new dependency.
