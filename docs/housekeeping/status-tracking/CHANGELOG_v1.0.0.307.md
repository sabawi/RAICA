# CHANGELOG v1.0.0.307 — `expr` as a JSON string returned the expressions as the answer

**Date:** 2026-08-18 · **Against:** v1.0.0.306 · **Closes:** SI-072 · **Logs:** SI-073

## Found by running testcase #2 (Treasury yield curve) on live

The answer reported, correctly and honestly:

> "the initial compute call returned only the expression labels (as string values) rather than
> the numeric results … I cannot report the mean, standard deviation, minimum, maximum, or
> peak-to-peak range … because the compute tool did not return those numeric values."

## SI-072 — a silent wrong answer, not a rejection

From the live log, the model sent:

```
'expr': '["np.size(y3mo)", "np.mean(y3mo)", "np.std(y3mo, ddof=1)", ...]'
```

a **JSON string containing a list**, not a list. That string is a perfectly valid Python
**list-literal of strings**, so the evaluator computed it and returned **the expression texts**
as the result — with `success: True`, `dtype: <U12`.

Reproduced in one line:

```
expr sent as: '["np.size(y10)", "np.mean(y10)"]'
result      : ['np.size(y10)', 'np.mean(y10)']
```

This is worse than a rejection: a rejection is visible and the model retries. This looked like
success, so every per-tenor statistic was silently lost.

Same defect class as SI-067 (`data` as a JSON string), on the sibling parameter. **Fix:** decode
`expr` when it is a JSON string whose elements are all strings, before the batch check. A genuine
numeric literal (`[1, 2, 3]`) still evaluates as data — pinned by a control test.

## SI-073 (prompt, not code) — a name is not a calculation

The same answer reported spread statistics that were **the raw tenor series**, exact to five
decimals:

| reported | true spread | what it actually was |
|---|---|---|
| 10Y−2Y mean **4.37752** | 0.50860 | 10Y series mean 4.37752 |
| 10Y−2Y min **3.97** | 0.2700 | 10Y series min 3.97 |
| 30Y−3Mo mean **4.94293** | 1.19745 | 30Y series mean 4.94293 |
| 30Y−3Mo min **4.64** | 0.9700 | 30Y series min 4.64 |

The model wrote `data={"spread_10y_2y": {…, "column": "10 Yr"}}` — naming a series "spread" while
binding it to a single column. The subtraction never happened. "Inversion count: 0" was counting
days the **10-year yield** was negative. The conclusion "never inverted" is accidentally true
(real inverted days = 0) but derived from the wrong data.

**It then rationalised the anomaly instead of reporting it:** *"appears to be expressed in the
same units as the mean … suggesting the spread values were multiplied by 100"*. A spread of 4.4
between yields of 4.7 and 4.2 is impossible; the model invented a scaling story to make it fit.

Section M now states that a difference between two columns is **arithmetic in `expr`**, not a
name in `data`, with the CORRECT/WRONG pair and this exact production case — plus a standing
instruction: *if a result looks wrong, say so; never invent a unit conversion to explain it.*

## Verification

- **24 tests** in `test_compute_argument_shapes.py`; the 2 new behavioural ones **fail pre-fix**,
  the 2 new controls pass both ways by design.
- **Ground truth re-derived independently** from the Treasury CSV (n=157): 10Y−2Y mean 0.50860 /
  min 0.2700; 30Y−3Mo mean 1.19745 / min 0.9700; 0 inverted days on both — confirming the
  reported figures were the raw series.
- Tier-0 **10/10**, unit **671 passed** (same 4 pre-existing), version sync **19/19**.

## Testcase #1 (USGS) independently verified — all 19 statistics exact

Re-derived from the catalog: n=225, mean 5.8828, median 5.8, std(ddof=1) 0.4218, min 5.5,
max 7.8, p25 5.6, p75 6.0, p90 6.4, p95 6.68, p99 7.476; tail counts 71/21/8/3 and probabilities
0.3156/0.0933/0.0356/0.0133; the full 15-bin histogram matched element-for-element, and all eight
M≥7.0 events matched on magnitude, date and place. Only discrepancy: the Venezuela doublet gap is
32s, reported as 31s — a sub-second rounding artifact from reading the table by eye.
