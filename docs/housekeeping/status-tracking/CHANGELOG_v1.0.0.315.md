# CHANGELOG v1.0.0.315 — a date axis reads as dates, at every sampling frequency

**Date:** 2026-08-21 · **Against:** v1.0.0.314 · **Closes:** SI-090, SI-091 · **Logs:** SI-092

Both defects were found by **looking at the rendered images** from the v1.0.0.314 verification, not
by a log line or a failing test. Every log reported success throughout.

---

## SI-091 — `plot_data` rendered a DATE axis as decimal years

`plot_data_tool._to_decimal_year` turns `2025-07-02` into `2025.5`, because `DatasetSeries` requires
temporal x values to be finite NUMBERS. Positioning was always correct — daily resolution preserved —
but nothing converted the number back for the TICK LABEL:

```
before:   2025.6   2025.8   2026.0   2026.2   2026.4   2026.6
after:    Oct 2025   Jan 2026   Mar 2026   May 2026   Aug 2026
```

…beneath an axis labelled "Date". Correct data that reads as wrong.

### The fix, and why it cannot touch the catalog

`utils/data_chart_generator.py` gains `_apply_temporal_ticks`, which formats temporal ticks as
calendar dates — **only when the values are not all whole numbers**. The dataset catalog plots annual
means and passes WHOLE years (`range(2016, 2025)`), for which `2016` is already the right label, so
it is provably untouched: a whole-year series can never enter the branch. Content decides the type,
the same rule the reference layer uses.

Format follows span: `%Y` above 3 years, `%b %Y` above 0.7, `%d %b` below.

### Generalisation — where the first version was WRONG

The fix was initially tested only on business-daily data and looked correct. Asked whether it
generalised to weekly and monthly data, it did not. With `%Y` the locator placed ticks at evenly
spaced DECIMAL positions that do not align to 1 January, so two ticks could fall inside one calendar
year:

```
span 3.2y   ->  ['2020', '2021', '2021', '2022', '2023']          duplicate
span 4.1y   ->  ['2020', '2020', '2021', '2022', '2023', '2024']  duplicate
quarterly   ->  ['2020', '2021', '2023', '2024', '2026']          2022 and 2025 SKIPPED
```

An axis that repeats or skips a year is worse than one reading `2025.8`, because it looks
authoritative. Fixed by matching the LOCATOR to the FORMAT's resolution: `integer=True` for `%Y`, and
a day-resolution floor for `%d %b` so a five-day span cannot produce sub-day ticks.

Verified across 14 frequency/edge cases — monthly (10yr/5yr/18mo/12mo), quarterly (6yr/2yr), weekly
(3yr/1yr/8wk), daily (1yr/30d/5d), annual-as-dates, catalog whole years:
**0 duplicate labels, 0 decimal years remaining.**

### The tests were wrong too

The first version of the test file **passed on the broken code** — the duplicate-producing spans were
not in it. After adding the real spans and applying the even-spacing check to every frequency,
**6 tests fail** on the pre-locator-fix code.

---

## SI-090 — the model sliced by ROW COUNT as if rows were calendar days

A chart titled *"Aug 2025–Aug 2026"* plotted ~17 months, because the model computed `d[-365:]` on a
business-daily series (~252 rows/yr). The pipeline drew faithfully what it was asked for; the title
was confidently wrong.

This is a model-reasoning error, so the fix is **policy language** in the `compute` schema the model
reads — not a hardcoded rule, per the project's LLM-policy directive:

> A SLICE COUNTS OBSERVATIONS, NOT CALENDAR DAYS. `[-365:]` takes the last 365 ROWS; in a file of
> daily market data, roughly 252 trading rows per year, that is about 17 months rather than one year
> … select it from the date column rather than guessing a row count.

**The code was checked to agree before the directive was written** — `y[np.array(d) >= "2025-08-21"]`
really evaluates, and SI-088 made the date column referenceable — so this is not a prompt-vs-code
contradiction.

### Measured, on two frequencies

| | daily (DGS10) | monthly (CPIAUCSL) |
|---|---|---|
| before | `d[-365:]` ×5 (~17 months) | not tested |
| after | `d[-252:]`, `d[-250::2]` | **`d[-12:]`** |
| wrong-frequency slices | 0 | 0 (no 252 over-applied) |
| charts published | 2/3 runs | **2/2 runs** |

### A REGRESSION THIS DIRECTIVE CAUSED, caught by the E2E before release

The first version of the directive said a trading year is "roughly 252 trading rows". The model
obeyed — `d[-252:]` appeared **36x** — and `compute` renders at most `_MAX_RETURNED_ELEMENTS` (200)
values, so a 252-row result came back TRUNCATED, which SI-085's guard correctly refuses to
reference:

```
plot_data: could not use the referenced data — this result shows only the first 200 of 252
           values, so it cannot be referenced as the series          (4 occurrences)
```

Charts fell from **2/3 to 0/3** on daily data. This is the prompt-vs-code contradiction the project's
LLM-policy directive exists to prevent: the expression was verified to EVALUATE, but never verified
to be REFERENCEABLE, and the row count named in the directive was the one number guaranteed to
exceed the cap. The previous round had hidden it — the model happened to pick `[-250::2]` and
`[-252::2]` (~126 values, under the cap) and charted 2/3.

**Reconciled:** the directive now states the cap **from the constant itself**, so text and code
cannot drift, drops the 252 anchor, and tells the model to thin:

> AND A SERIES YOU INTEND TO REFERENCE MUST COME BACK WHOLE: this tool renders at most 200 values
> and a TRUNCATED result cannot be referenced at all, so thin a long window until it fits.

**Re-verified, 5 daily runs after the reconciliation:**

| | before directive | first directive | reconciled |
|---|---|---|---|
| truncation refusals | 0 | **4** | **0** |
| reference refusals (any) | some | some | **0** |
| charts published | 2/3 | **0/3** | **3/5**, all URLs HTTP 200 |
| plotted point counts | — | — | 121, 125 (thinned, under cap) |

Three new tests guard it: the directive must name the REAL cap (asserted against the constant), a
thinned window must survive the compute→reference round trip, and an over-cap series must **still**
be refused — the fix is to thin, not to weaken SI-085.

**Honest limit:** date-mask selections remain **0** — the model uses frequency-aware row counts, not the date
column the directive asks for. Correct on both frequencies tested, but still an inference. The
durable fix, if it recurs, is a chart-level sanity signal comparing plotted span against claimed
span, which no prompt can substitute for.

---

## Files changed

| file | change |
|---|---|
| `utils/data_chart_generator.py` | SI-091: `_apply_temporal_ticks`, `_decimal_year_to_date`, locator matched to format |
| `user_tools/compute_tool.py` | SI-090: observations-not-days policy directive in the `expr` schema |
| `tests/unit/test_chart_date_axis.py` | **NEW** — 52 tests incl. a 14-case frequency sweep |
| `README.md`, `config/logging_config.json`, `version.py` | version → 1.0.0.315 |
| `SUSPECTED_ISSUES.md` | SI-090, SI-091 FIXED; **SI-092 logged** |

## Breaking changes

None. Catalog charts are provably unaffected (whole-year values never enter the new branch),
confirmed by rendering the control and inspecting it.

## Dependencies

`matplotlib.ticker` (FuncFormatter, MaxNLocator) — already a matplotlib dependency, no new package.

## Migration

None required.
