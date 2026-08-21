# CHANGELOG v1.0.0.314 — the content decides the type: a computed date series is data, not noise

**Date:** 2026-08-21 · **Against:** v1.0.0.313 · **Closes:** SI-088 · **Logs:** SI-089

One defect, two symptoms, found by E2E-verifying the previous release rather than by a user report.

---

## SI-088 — a computed DATE series was silently unreferenceable

`_values_from_compute_block` built a series only if EVERY value parsed as a number. A date series
renders as `['2025-09-02', '2025-09-05', …]` (numpy `dtype: <U10`) and parses as no number at all,
so the entire entry was **dropped** — inside `computed_entries`, before `extract_column`'s
`numeric=False` flag could be consulted.

```
d[-252:][::3]  ->  ReferenceError_          # the x-axis of every time-series chart
y[-252:][::3]  ->  [4.28, 4.1, 4.04]        # only the yields survived
```

### Two symptoms, one cause

```
_values_from_compute_block requires every value numeric
      └─> date series dropped from computed_entries
            ├─> SYMPTOM 1: the date reference raises  ->  no x-axis
            └─> entries collapse 2 -> 1
                  └─> fails the `len(_entries) > 1` gate in describe_reference
                        └─> SYMPTOM 2: a bare "text" dump — the model is shown the raw blob
                            with NO series index and NO reference syntax
```

Symptom 2 is why production looked the way it did. The model called its own output *"garbled — the
column headers and row structure are malformed"* and re-issued `compute` until the gather-gate rounds
ran out. **`plot_data` was never invoked in 4 of 4 runs.** Its complaint was substantively correct:
it had never been told what it could reference.

### Controlled experiment

Same output structure, one variable changed:

| first series | what `describe_reference` shows |
|---|---|
| dates (`<U10`) | `=== compute#1 === text, 444 characters` + raw dump — no index, no syntax |
| numeric | `=== compute#1 === 2 computed series` + `[0] expr -> …` + explicit reference syntax |

### Size is NOT the cause

A **3-point** date series fails identically, so the defect is size-independent. What the 16,862 rows
do is close the only workaround: dates ARE referenceable straight from the CSV table, but 16,862
exceeds `plot_data._MAX_POINTS` (5000), forcing the model onto the `compute` path where the defect
lives. This is recorded because "the data was too big" is the intuitive answer and it is wrong.

### The fix

`_values_from_compute_block` now applies **the same rule the tabular path in this module already
uses** — *"if most cells do not parse as numbers, the column is text"* — instead of dropping the
entry. Reuse, not a parallel mechanism. Supporting changes: `_unquote` strips numpy's presentation
quotes; `describe_reference`'s preview no longer formats a `str` with `:g` (which raises ValueError).

A **mixed** series (mostly numeric, a few unparseable) is deliberately still refused — the rescue is
only for a series that is plainly text.

---

## A regression in the fix itself, caught before shipping

Making dates visible turned a dates+values output from ONE entry into TWO, which silently withdrew
the SI-047 habit for every plain label that used to resolve — **13 of them in the production
corpus** (`value`, `diff`, `count`, …). Every other gate stayed green; only the differential replay
saw it.

Resolved by keeping the habit when exactly one **numeric** series is present — a plain label means
"the number I computed", and a date is not a value — and withdrawing it only for genuine ambiguity,
two or more numeric series.

| differential replay (630 pairs) | first attempt | shipped |
|---|---|---|
| NARROWED (resolved → raises) | **13** | **0** |
| ALTERED | 1 | 1 (intentional, below) |
| CRASHES | 0 | **0** |
| WIDENED | 17 | 17 |

**The one intentional change:** index `"0"` on a dates+values output now returns the DATES, because
dates genuinely are series 0 and `describe_reference` now says so (`[0] d[…]`, `[1] y[…]`). Pre-fix
no index was ever shown for such an output, so nothing depended on the old numbering. This satisfies
the module's own rule that description and resolution must agree on what is addressable.

---

## Verification

### Through the real entry point (`POST /v1/chat/completions`, 3 runs, same prompt)

| gate | before | after |
|---|---|---|
| `plot_data` selected | **0/4 runs** | **2/3 runs** |
| date reference resolves | `ReferenceError_` | **0 reference errors** |
| chart rendered | never reached | yes, in the runs that plotted |
| chart published | — | **0 — NewX down on :9876 (environment, not code)** |

**NOT verified: that a user SEES a chart.** `publish_chart` POSTs to NewX, which was not running in
this session, so no marker is minted and the chart pass-rate metric cannot discriminate. Re-run with
NewX up to close this.

**Also not fixed:** 1 of 3 runs still looped on `compute` without plotting. SI-084 (invented marker)
and SI-083 (wrong series plotted) remain the later gates between a rendered chart and a correct one.

### Tests

| file | tests | falsification |
|---|---|---|
| `tests/unit/test_computed_text_series_reference.py` | **19 (NEW)** | **6 fail** on pre-SI-088 code |
| all reference tests | 269 | pass |
| full unit suite | **905 passed**, 4 failed | the same 4 pre-existing, unrelated |

---

## Files changed

| file | change |
|---|---|
| `utils/tool_output_reference.py` | SI-088: text-series rescue, `_unquote`, `_is_text_series`, habit preserved for a unique numeric series, safe preview formatting |
| `tests/unit/test_computed_text_series_reference.py` | **NEW** — 19 tests |
| `README.md`, `config/logging_config.json`, `version.py` | version → 1.0.0.314 |
| `SUSPECTED_ISSUES.md` | SI-088 FIXED with evidence; **SI-089 logged** (model references a non-existent `compute#N`) |

## Breaking changes

None, with one deliberate semantic correction to index-based references on a dates+values output
(above). Measured: 0 narrowed across 630 replay pairs.

## Dependencies

No new imports; `requirements.txt` unchanged.

## Migration

None required.
