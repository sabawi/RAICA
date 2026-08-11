# CHANGELOG v1.0.0.251 — ETF sentinel crash killed technicals + charts (SI-026)

**Date:** 2026-08-11 · **Previous:** v1.0.0.250 · **Type:** P1 fix, user-reported from production

A user replied to an `@Ask` post — *"Show the 2 years chart of GPIQ"* — and received prose
with **no chart** (sabawi.net/post/6502).

## Gate chain — the first three passed

| gate | result |
|---|---|
| tool ALLOWED (`@Ask` whitelist) | ✅ |
| tool SELECTED (`Generated tool calls: ['comprehensive_stock_analyzer']`) | ✅ |
| tool INVOKED | ✅ |
| **marker PRODUCED** | ❌ — and the `chart NOT emitted` diagnostic never fired either, proving the block was unreachable |

## Cause

`comprehensive_stock_analyzer` fills missing market fields with the **string `"N/A"`**
(`market_cap`, `volume`, `pe_ratio`, `analyst_target`). **GPIQ is an ETF** — `quoteType: ETF`,
`marketCap`/`sector`/`industry` all `None`, and all three financial statements empty.

`"N/A"` is **truthy**, so every guard of the form `if market_cap and …` passed:

```
shares_outstanding = market_cap / current_price    -> TypeError: ufunc 'divide' not supported
enterprise_value   = market_cap + total_debt - cash -> TypeError: can only concatenate str
```

Both sit inside one broad `except`, so the detailed block aborted **silently**, taking the
TECHNICAL ANALYSIS section and the `[[chart:]]` marker with it. The user got short prose and
no explanation.

## Controls (both run before concluding)

- **ETF-specific, not global:** on the same prod build, NVDA returned 12,634 chars / **4
  charts** while GPIQ returned 3,040 / **0**.
- **Red herring killed:** `charts: enabled: false` appears in the config, but `charts_enabled()`
  returns **True** — that key is unused. The master switch was never the problem.

## Fix

Module-level `_num()` coercion applied at the **single entry point** where market values are
read, covering all five arithmetic sites at once:

```python
current_price      = _num(market_data.get('current_price'))
market_cap         = _num(market_data.get('market_cap'))
shares_outstanding = _num(market_data.get('shares_outstanding'))
```

`_num()` returns `None` for `None`, `""`, `"N/A"`, `NaN`, bools and non-numerics — while
preserving a real `0.0`, which is data, not absence.

**Fixing the first crash was not enough.** A second sentinel bug (`+` rather than `/`)
surfaced immediately behind it, which is why the coercion is at the entry point rather than
per-site — a per-site patch leaves the next one to be found in production.

## Verified

| ticker | before | after |
|---|---|---|
| GPIQ (ETF) | 3,040 chars, **0 charts**, no technicals | 5,226 chars, **4 charts**, technicals ✅ |
| QQQI (ETF) | 2,838 chars, **0 charts** | 5,566 chars, **4 charts**, technicals ✅ |
| NVDA / KO / JPM | 4 charts | **4 charts — unchanged** |

Pre-fix: `TypeError: unsupported operand type(s) for /: 'str' and 'float'`. Post-fix: returns
cleanly.

**Scope:** affects every instrument without a market cap — all ETFs, some ADRs and
thinly-traded names.

## Files changed

| file | change |
|---|---|
| `utils/financial_ratio_calculator.py` | `_num()` helper + entry-point coercion |
| `tests/unit/test_etf_sentinel_coercion.py` | **new** — 18 tests |
| `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` | SI-026 |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.250 → 1.0.0.251 |

## Verification

tests/unit 249 passed / 4 failed (those 4 fail identically on the committed baseline).
Tier 0 **9/9**. Live analyzer runs on 2 ETFs + 3 stocks.

## Breaking changes

None.
