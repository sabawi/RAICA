# Scope — Forward-Aware Growth for the Projection Engine

**Status:** ✅ **IMPLEMENTED 2026-08-10 in v1.0.0.248** (SI-022). Was: SIGNED OFF
2026-08-09, gated on the provider A/B.

> **Delivered with one documented DEVIATION from §4.2.** That section said "keep the 20%
> cap unchanged". Shipping it unchanged would have left the defect that prompted the whole
> review still firing on hyper-growth names: NVDA's median blend landed on 43.3% (analysts)
> and the flat cap pushed it to 20%, a rate NEITHER real signal supported, producing an
> $83.05 intrinsic against a $221.57 price. The cap is now *evidence-aware* — it steps
> aside only when BOTH independent signals clear it, and can only ever be RAISED. §4.2's
> intent (stop one transient outlier being extrapolated) is preserved intact; CROX and KO
> are byte-identical.
**Against:** v1.0.0.242 · **Origin:** user review of a real CROX analysis, 2026-08-09

> **DO NOT IMPLEMENT BEFORE THE A/B COMPLETES.** This change alters the numbers the
> synthesising LLM reasons over for every stock with a forward estimate. Landing it
> mid-experiment would confound `docs/PROVIDER_AB_TEST_PLAN.md` — a quality delta could
> then be the provider OR this change, and the two would be inseparable. Same class of
> error as substituting a model during a transport migration.

---

## 1. The defect

`utils/projection_engine.py` extrapolates a **capped historical CAGR** with **no
forward signal**. `utils/dcf_calculator.py` already does the right thing and has since
v1.0.0.176. The two sit in the same report and disagree.

For CROX the report printed:

> "The historical-CAGR model projects **20.0%** growth (capped) … Analyst forward EPS
> consensus is $14.92, implying **+7.1%** growth. The divergence … reflects the model's
> extrapolation of a **32.6% raw historical CAGR**, which is **likely inflated by the
> HEYDUDE acquisition**."

RAICA **detected the distortion, stated it, and then used the distorted number anyway**.
The 20% growth flowed into the projections, and the LLM built a "65.8% upside / BUY /
best risk-adjusted opportunity in this group" conclusion on top of it.

The reviewer's verdict: *"You recognized the distortions … but still built your valuation
on them."* That is accurate, and it is a code defect, not a prompt problem — the engine
offers the LLM an indefensible number with equal standing to a defensible one.

## 2. Why the DCF is immune and the projections are not

`dcf_calculator.py:468-489` (v1.0.0.176) already solved this exact class:

```python
_signals = [('trailing 3-yr FCF growth', historical_growth)]
if analyst_growth is not None:            # sanity-bounded
    _signals.append(('analyst forward growth', _ag))
_signals.append(('sustainable anchor', 0.05))
projection_growth = float(np.median([v for _, v in _signals]))
projection_growth = max(projection_growth, self.terminal_growth_rate)
projection_growth = min(projection_growth, 0.20)
```

A **median of three signals** is robust to one transient outlier in either direction —
it ignored KO's −17.8% trailing collapse *and* NVDA's +100% surge. It was introduced for
exactly the failure now seen in the projections, one release earlier, and never applied
there.

**The wiring gap is one line.** `comprehensive_stock_analyzer.py`:

```python
:776  _analyst_estimates = AnalystEstimates().get_estimates(...)
:778  _g = _analyst_estimates.get('fwd_eps_growth_pct')
:787  dcf_calc.calculate_intrinsic_value(..., analyst_growth=_analyst_g)   # DCF gets it
:793  projector.generate_projections(ticker, financials)                   # projections do NOT
```

The analyst data is already fetched, already converted, and already in scope. It simply
is not passed.

## 3. Measured effect (real CROX data, 2026-08-09)

| metric | raw hist CAGR | **current (capped)** | analyst fwd | **median blend** |
|---|---|---|---|---|
| **earnings** | 32.6% | **20.0%** | 7.08% | **7.1%** |
| revenue | 4.4% | 4.4% | 2.46% | 4.4% |
| FCF | 9.7% | 9.7% | *n/a* | 7.4% |

Earnings is the one that matters: **20.0% → 7.1%**, landing on the analyst consensus and
removing the number the reviewer called indefensible. Revenue is unchanged (the median
picks the middle signal, which is already the historical one) — good evidence the change
is targeted rather than a blanket haircut.

## 4. Proposed change

### 4.1 Signals per metric

| projection | signal 1 | signal 2 (forward) | signal 3 |
|---|---|---|---|
| earnings | historical CAGR | `fwd_eps_growth_pct` | 5% anchor |
| revenue | historical CAGR | `fwd_rev_growth_pct` | 5% anchor |
| FCF | historical CAGR | `fwd_eps_growth_pct` *(proxy)* | 5% anchor |

**Open question (Q1):** using EPS growth as the FCF forward proxy is an assumption — no
analyst FCF consensus exists in yfinance. The alternative is two signals (historical +
anchor), which is a mean, not a median, and loses outlier robustness. **Recommend the
proxy, clearly labelled as a proxy in the output.**

### 4.2 Keep, unchanged
- the 20% cap and the existing floors
- `best_case` / `worst_case` derivation (they key off `base_growth`, so they inherit)
- the raw historical CAGR **still reported**, so the divergence stays visible

### 4.3 Transparency — non-negotiable
The output must SHOW the derivation, as the DCF does:

```
Projected Growth: 7.1%
  [median of: historical CAGR 32.6% | analyst forward 7.1% | sustainable anchor 5.0%]
  NOTE: historical CAGR diverges >2x from analyst consensus — likely reflects
        acquisitions or one-time items rather than organic growth.
```

That divergence NOTE is the part that answers the reviewer directly: RAICA already
detected the distortion; it must now say so **in a way that changes the number**, not
merely annotate it.

## 5. Risk

| risk | assessment |
|---|---|
| **Changes numbers the LLM reasons over** | MEDIUM — this is the point, but it means output shifts for every stock with a forward estimate |
| Analyst data unavailable | LOW — falls back to (historical, anchor); must not crash. `ltg_pct` is often `None`, `earningsGrowth` is `None` for CROX |
| Analyst estimates are themselves wrong | **REAL** — the median mitigates but does not remove it. This makes RAICA *track consensus more closely*, which is a defensible default and a stated one |
| Suppressing genuine hyper-growth | MEDIUM — a real 30%-grower with lagging analysts gets pulled down. The median needs 2 of 3 signals to agree; the anchor is deliberately low. **Mitigated by still reporting the raw CAGR** |
| Regression in existing tests | LOW-MEDIUM — `test_dr_ttm_sourcing.py` and `test_financial_calculators_accuracy.py` assert projection values; expect updates |

## 6. Verification

1. **Named tests that FAIL on pre-fix code**, CROX as fixture (earnings 20.0% → 7.1%).
2. **Mixed-cap basket** per the standing rule — FUBO / CROX / RIVN / KO / JPM, plus NVDA
   as the hyper-growth control and KO as the transient-outlier control (the two cases
   v1.0.0.176 was built to handle).
3. **Fallback paths**: no analyst data; `None` fields; negative historical CAGR.
4. **E2E through `/v1`** — confirm the derivation line and the divergence NOTE reach the
   synthesised answer, not just the calculator output.

## 7. Explicitly NOT in scope

The rest of the reviewer's critique is **analytical judgment, not arithmetic**, and does
not belong in the calculator:

- cyclicality of footwear/discretionary names
- whether HEYDUDE is a success
- reverse-DCF sensitivity to WACC / terminal assumptions
- whether a large DCF-vs-analyst gap should itself be read as a warning

These belong in the synthesis prompt if anywhere. Hardcoding sector judgments would
violate the generalization directive in `CLAUDE.md`.

## 8. Decisions needed

**All four APPROVED by the user, 2026-08-09.**

| id | question | **decision** |
|---|---|---|
| **Q1** | FCF forward signal: EPS-growth proxy, or 2 signals only? | ✅ **proxy, explicitly labelled as a proxy in the output** |
| **Q2** | Divergence NOTE threshold | ✅ **>2× OR >15pp** between historical CAGR and analyst forward |
| **Q3** | Apply to `best_case`/`worst_case`? | ✅ **base only** — the scenarios derive from `base_growth` and inherit it |
| **Q4** | Ship with the A/B pending, or after? | ✅ **AFTER the A/B** |

## 9. Implementation checklist (when unblocked)

- [ ] A/B complete and reported (`docs/PROVIDER_AB_TEST_PLAN.md`)
- [ ] `generate_projections()` accepts analyst estimates; wire from
      `comprehensive_stock_analyzer.py:793` (data already fetched at :776)
- [ ] median-blend in all three projections, mirroring `dcf_calculator.py:468-489`
- [ ] FCF proxy labelled; divergence NOTE at >2× or >15pp
- [ ] raw historical CAGR still reported — the divergence must stay visible
- [ ] tests FAIL on pre-fix code, CROX fixture (earnings 20.0% → 7.1%)
- [ ] mixed-cap basket: FUBO / CROX / RIVN / KO / JPM + NVDA (hyper-growth control)
      and KO (transient-outlier control)
- [ ] fallback paths: no analyst data, `None` fields, negative historical CAGR
- [ ] E2E through `/v1` — derivation line and NOTE reach the synthesised answer
