# CHANGELOG v1.0.0.305 — `compute` and `plot_data` are finally *documented* to the tool model

**Date:** 2026-08-17 · **Against:** v1.0.0.304 · **Closes:** SI-070

## The real cause of the USGS failure, and it was never the code

v303 and v304 fixed `compute` argument handling. Both were correct, both had passing tests, and
**neither changed the outcome**, because `compute` was never being called. The reason, measured
in `pre_tool_model_system_prompt.txt` — the 807-line file that IS RAICA's tool-calling
architecture:

| tool | mentions |
|---|---|
| `search_web` | 38 |
| `sandboxed_executor` | **29** |
| `analytical_visualizer` | 19 |
| `comprehensive_stock_analyzer` | 12 |
| `lookup_website` | 7 |
| **`compute`** | **1 — the English verb, never the tool** |
| **`plot_data`** | **0** |

Worse, line 621 commanded the exact analysis the user asked for — *"If those numbers have not
been computed yet, COMPUTE THEM FIRST and plot afterwards"* — **without naming a tool**. The model
was told to compute statistics and given 29 worked examples of `sandboxed_executor`. It picked
the tool the prompt actually taught it.

That file is external and editable precisely so tools can be added, removed and explained without
hardcoding anything in code. Two tools were added to the codebase and never described in it.

## The fix: elaborate coverage, in the file's own idiom

**Section M — `compute()`** and **Section N — `plot_data()`**, written to the same structure as
the existing lettered scenarios (A–L), each covering: what it is · when to use it · why · **when
NOT to** · how to call it · what it returns · a worked example · the WRONG patterns.

Points that carry the most weight:

- **"Use it for EVERY derived figure"**, with the failure that created the tool: two yields quoted
  correctly, their spread reported as +0.19 when the numbers give +0.67.
- **"DO NOT USE `sandboxed_executor` FOR ARITHMETIC. It CANNOT see data that `lookup_website`
  fetched"** — the exact reason the model's script died on
  `ERROR: Could not find the USGS earthquake CSV file.`
- The three argument shapes that failed in production, shown as CORRECT/WRONG pairs: the reference
  must sit *inside* the `data` mapping, not bare and not as a top-level argument.
- The **list form** for several figures in one call, so the model stops writing scripts.
- `plot_data` added to section J's chart-routing list, which previously named every other chart
  route and omitted it entirely.
- Line 621 now reads **"COMPUTE THEM FIRST with `compute(...)` — see section M"**.

Mentions after: `compute` **1 → 14**, `plot_data` **0 → 6**. File integrity checked against a
backup: 127 lines added, 2 removed (exactly the two rewritten).

## Verified through the REAL entry point

Not a hand-built call this time — the actual prompt through `/v1`:

```
Generated tool calls: ['get_the_secret_tool', 'lookup_website']
Generated tool calls: ['compute', 'compute']
Generated tool calls: ['plot_data']
compute invocations: 3 | plot_data: 3 | rejections: 0 | sandboxed_executor for arithmetic: 0
```

Expressions actually evaluated: `np.size(mag)`, `np.mean(mag)`, `np.median(mag)`,
`np.std(mag, ddof=1)`, `np.histogram(mag, bins=12)[0]`, `np.histogram(mag, bins=12)[1]` — the
correct methodology, including indexing the histogram tuple.

Answer figures, against independently verified truth:

| statistic | before (fabricated) | now | truth |
|---|---|---|---|
| sample size | 225 | 225 | 225 |
| mean | 5.87 ✗ | **5.88** | 5.8828 |
| median | 5.70 ✗ | **5.80** | 5.8 |
| std dev | 0.39 ✗ | **0.42** | 0.421845 |

Each labelled with its expression (`Mean (np.mean)`, `Standard deviation (np.std, ddof=1)`), a
`[[chart` marker present, and the model reasoning from its own computed values: *"the mean of 5.88
sits slightly above the median of 5.80, indicating a mild right skew"* — which is what the line-621
directive asks for, now that it has real numbers to measure the shape with.

## NEW: `docs/compute_and_plot_prompts.md`

Twelve graduate-level prompts over **verified** US government sources, for reuse with `@Ask`.
Every source was fetched and column-parsed before the prompts were written — USGS FDSN, the
Treasury daily yield curve (13 tenors), and 10 FRED series (`DGS10`, `T10Y2Y`, `FEDFUNDS`,
`MORTGAGE30US`, `PAYEMS`, `GDPC1`, `VIXCLS`, `M2SL`, `HOUST`, `UNRATE`, `CPIAUCSL`).

Written against the real constraints: the 500-character expression cap, the 200,000-element array
cap, the 98 permitted functions (no scipy, no `linalg`, and **no `skew`/`kurtosis`** — built from
standardised moments instead), and the fact that **`DGS10` carries 719 NaNs in 16,859 rows**, so
`np.mean` returns `nan` where `np.nanmean` returns 5.8063. Several prompts require the nan-aware
family deliberately.

Three are marked as regression testcases: **#1 USGS** (verified expected values), **#2 Treasury
yield curve** (multi-column table, spaces in column names, two charts), **#5 Phillips curve** (two
sources joined on a common period — the `from` list form — plus a derived series and a causal
caveat).

## Verification status

Tier-0 **10/10**, version sync **19/19**, and one **full real-path run** confirming correct tool
selection and correct figures.

**Explicitly NOT yet established:** reliability. Tool selection is a stochastic LLM decision and
this repo's own rule requires **≥3 runs** before calling such a change verified. One green run is
evidence, not proof. That is why this release is committed but **not deployed**.
