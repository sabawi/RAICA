# CHANGELOG v1.0.0.248 — forward-aware growth (SI-022)

**Date:** 2026-08-10 · **Previous:** v1.0.0.247 · **Type:** correctness fix, valuation models

Implements `docs/PROJECTION_GROWTH_BLEND_SCOPE.md` (signed off 2026-08-09, gated on the
provider A/B) **plus** a second defect of the same class found during a user review of a
real NVDA/AAPL report.

The user's reviewer put it exactly right: *"rigorous-looking model → biased assumptions →
predetermined conclusion."* Both defects are one thing — **a constant standing in for
evidence.**

---

## (1) The DCF cap overrode its own blend — NEW

`dcf_calculator.py` median-blends three growth signals, then applied a flat 20% cap
**after** the blend. NVDA, live 2026-08-10:

```
trailing 3-yr FCF growth 100.0% | analyst forward 43.3% | anchor 5.0%
median -> 43.3%          then capped -> 20.0%
```

20% was supported by **neither** real signal. The consequences were not cosmetic:

| | before | after |
|---|---|---|
| stage-1 growth | 20.0% | **43.3%** |
| intrinsic value | $83.05 | **$179.44** |
| vs market ($221.57) | **−62.6%** | **−19.0%** |

At −62.6% the synthesising LLM had to write a paragraph explaining away its own tool
("a standard DCF is notoriously conservative for hyper-growth companies"). **A model whose
output must be talked around in prose is not conservative, it is wrong.**

**Fix — `evidence_aware_growth_cap()`.** The cap's real job is stopping ONE transient
outlier being extrapolated for five years (KO's −17.8%, CROX's acquisition-inflated 32.6%).
But when **both** independent signals clear it, the high rate is agreement between a
backward and a forward measurement, not an outlier. So the cap never binds below the lower
of the two. It can only ever be **raised**, never lowered, and the injected 5% anchor is
excluded from the vote — otherwise one real signal could masquerade as two.

## (2) The projections had no forward signal at all — the signed-off scope

`projection_engine.py` extrapolated a capped historical CAGR while the DCF beside it in the
same report already blended a forward one. For CROX it printed 20.0% while stating the raw
32.6% CAGR was *"likely inflated by the HEYDUDE acquisition"* and that analysts implied
7.1%. It detected the distortion, said so, and used it anyway.

| CROX | raw CAGR | before | analyst fwd | **after** | scope doc predicted |
|---|---|---|---|---|---|
| earnings | 32.6% | 20.0% | 7.1% | **7.1%** | 7.1% ✓ |
| revenue | 4.4% | 4.4% | 2.5% | **4.4%** | 4.4% ✓ |
| FCF | 9.7% | 9.7% | *(EPS proxy)* | **7.1%** | 7.4% |

The wiring gap was the one line the scope doc identified: `analyst_estimates` was already
fetched for the DCF and simply not passed to the projections.

**Deviation from scope §4.2** ("keep the 20% cap unchanged"): shipping it unchanged would
have left the originating defect firing on hyper-growth names. §4.2's *intent* is preserved
— CROX and KO are byte-identical. Recorded in the scope doc.

## Transparency (scope §4.3, non-negotiable)

Every projected growth rate now shows its derivation instead of asserting a number:

```
Projected Growth: 7.1%
    [median of: historical CAGR 32.6% | analyst forward growth 7.1% | sustainable anchor 5.0%]
    NOTE: historical CAGR diverges sharply from analyst consensus — likely reflects
          acquisitions or one-time items rather than organic growth
```

---

## Found by adversarial audit, before shipping

**The scenario-ordering invariant broke.** The 25% best-case ceiling was safe only while the
base was hard-capped at 20%. Once a corroborated signal can lift the base above 25%, NVDA
produced **base 42.6%, best case 25.0%** — an optimistic scenario more pessimistic than the
base. Fixed; pinned by a parametrised test.

**Two strings the change made false**, caught by reading the real tool output rather than
trusting the diff:
- the DCF printed `capped at 20%` beside a 43.3% number;
- all three projection blocks said `NOT analyst consensus estimates` when they now blend
  exactly that.

A third self-inflicted bug: the first version of the "Growth ceiling" explanation was gated
on `"default" not in reason` — and the raised-cap message contains the word "default"
(*"exceed the 20% default"*), so the explanation silently suppressed itself. Replaced with a
structured flag; substring-matching our own prose is the pattern the project directive
forbids.

## Behavioural change, stated not buried

A stock with **no analyst coverage** now blends two signals, and the median of two is their
mean — growth is pulled toward the 5% anchor (0.10 → 0.075). Accepted deliberately:
`dcf_calculator` has behaved this way since v1.0.0.176, and the point of SI-022 is that the
two must not disagree in the report they share.

## Known limitation — NOT fixed

**AAPL still reports −49.1%.** Its cap never binds (only one signal clears it); the low
intrinsic comes from ~$90B/yr of buybacks suppressing trailing FCF growth to −3.9%. DCF for
buyback-heavy mega-caps is a separate problem and is not addressed here.

## Files changed

| file | change |
|---|---|
| `utils/dcf_calculator.py` | shared `evidence_aware_growth_cap()`; cap-aware transparency string |
| `utils/projection_engine.py` | `_blend_growth()`, `_divergence_note()`, derivation output, best-case ceiling fix, corrected NOTEs |
| `user_tools/comprehensive_stock_analyzer.py` | pass `analyst_estimates` into `generate_projections` |
| `tests/unit/test_growth_blend_and_cap.py` | **new** — 17 tests |
| `docs/PROJECTION_GROWTH_BLEND_SCOPE.md` | marked IMPLEMENTED + deviation recorded |
| `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` | SI-022 |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.247 → 1.0.0.248 |

## Verification

- `tests/unit/test_growth_blend_and_cap.py` — 17 passed; the suite cannot pass pre-fix
  (the shared rule does not exist).
- Finance suite (`-k "financial or dcf or projection or growth or stock"`) — **27 passed**.
- `tests/unit` — 215 passed, 4 failed; those 4 fail identically on the committed baseline.
- Live real-path runs through `ComprehensiveStockAnalyzerTool(detailed=True)` for NVDA,
  AAPL, CROX and KO.
- Ordering invariant re-verified live: NVDA 21.3 / 42.6 / 47.6, CROX −0.6 / 4.4 / 9.4,
  KO −1.3 / 3.7 / 8.7.

## Breaking changes / migration

None. Numbers change for any stock with a forward estimate — that is the intent.
