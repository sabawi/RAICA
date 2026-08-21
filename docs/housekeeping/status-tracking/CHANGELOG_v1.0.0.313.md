# CHANGELOG v1.0.0.313 — the server rejected a reference to the name it had printed

**Date:** 2026-08-21 · **Against:** v1.0.0.311 · **Closes:** SI-085, SI-086, SI-087

**v1.0.0.312 was prepared but never released as its own commit.** Its adversarial audit — the
acceptance gate that every phase must pass — found a defect in the .312 fix itself. That defect is
SI-087, fixed here, and both releases land in this single commit. `CHANGELOG_v1.0.0.312.md` remains
as the record of SI-085/086; this file records SI-087 and the audit that produced it.

---

## SI-087 — a compute result rejected a reference to the name it had just printed

SI-085 (in .312) hardened `extract_column` so that an **expression-shaped** column name matching
nothing RAISES instead of silently returning a different series. That was the right call: a chart
had asked `compute#5` for `d[::60]` (the dates), the output held one series, the old contract
ignored the name, and the x-axis was handed HOUSING STARTS — a y=x diagonal labelled "Date".

"Expression-shaped" was decided by character class:

```python
_EXPRESSION_CHARS = set("[]().:+-*/,")
```

which contains `-`, `.` and `(` — ordinary **English** punctuation. So a plain descriptive label was
classified as an expression and rejected:

```
extract_column(text, "10-Year Treasury")  -> ReferenceError_     # previously resolved
extract_column(text, "CPI (index)")       -> ReferenceError_     # previously resolved
extract_column(text, "10 Yr")             -> resolves            # no punctuation, unaffected
```

**Why this is worse than a strictness tweak.** `compute_tool._format`
(`user_tools/compute_tool.py:419`) renders `f"{label}: "` ahead of a single result, so the output
announces its own human-readable name:

```
10-Year Treasury: [4.3, 4.35, 4.28, 4.41]
computed as: y10
```

RAICA would print `10-Year Treasury` and then reject a reference to it. Real Treasury, CPI and GDP
series labels are exactly this shape.

### The fix

`computed_entries` now carries the label the output itself printed; `extract_column` matches it
**before** raising:

```python
if _named is None:
    _named = next((e for e in _entries
                   if e.get("label") and _col.lower() == e["label"].lower()), None)
```

This reads back a string RAICA emitted — the same basis on which `_COMPUTE_MARKER` is matched — so
it is **not** the forbidden keyword-heuristic pattern. And it only **adds** a resolution path,
placed ahead of the raise, so nothing that previously resolved can change.

---

## Evidence

### Exposure, measured rather than argued

All **3946** real reference payloads were harvested from `logs/server_complete.log` and
`logs/archive/*.log`. The harvest is complete for that corpus: 3946 of 3946 `"column"` occurrences
matched, none in reverse field order.

| population | count | outcome |
|---|---|---|
| distinct `compute#` column names | 55 | the only names that can reach the strict branch |
| plain identifiers (`value`, `y`, `counts`, `diff`, …) | 11 | keep resolving (SI-047 habit) |
| genuine expressions | 41 | raise — the intended SI-085 catch |
| non-references (syntax placeholder, leaked data) | 3 | raise — correct |
| **true regressions** | **0** | |

Every punctuated Treasury label in production (`10 Yr`, `2 Yr`, `3 Mo`, `30 Yr`) is a **tabular**
`lookup_website#N` reference, which never enters the compute branch.

### Monotonicity — the fix cannot narrow

966 pairs (14 output shapes × 71 column names), shapes covering labelled/unlabelled, scalar/array,
single/multi-series, truncated, plus table / JSON / prose controls:

```
NARROWED (resolved -> raises)  [REGRESSION] : 0
ALTERED  (different values)    [REGRESSION] : 0
CRASHES                        [REGRESSION] : 0
WIDENED  (raised -> now resolves)  [INTENT] : 3
```

The 3 widenings are exactly the intended labelled cases. `truncated/labelled` did **not** widen —
the SI-085 truncation guard still fires after the label match, so that half of .312 is intact.

### Tests

| file | tests | falsification |
|---|---|---|
| `tests/unit/test_labelled_series_reference.py` | 21 | **9 fail** on pre-SI-087 code |
| `tests/unit/test_reference_production_replay.py` | 145 | **49 fail** on pre-SI-085 HEAD (`b0c207c`) |

`test_reference_production_replay.py` is seeded with the **real** production column names, not
invented ones, because both SI-085 and SI-087 turn on `_EXPRESSION_CHARS` and on the ORDER of the
branches in `extract_column` — a future edit to either can silently change which references resolve,
and a corpus of invented names would not notice.

---

## Adversarial audit of v1.0.0.312 — completed

Three attack hypotheses were written before re-reading the code. All three are now answered.

| # | attack | verdict |
|---|---|---|
| 1 | Append-in-a-loop (oscillation) in the SI-086 fix | **CLEARED** — the append site is enclosed by two `if`s and no loop, so cycle 2 is impossible; no damper needed |
| 2 | `.startswith()` on a non-string crashes the SI-086 fix | **CLEARED** — all 5 return paths of `arbitrator_validate_tasks` yield `str` or `None`; all 4 writers of `corrected_results` are `"\n\n".join(...)`. `None` is excluded by the existing guard, and a non-`str` would already die on the PRE-EXISTING `corrected_tools_results[:200] + "..."` three lines earlier. 0 crashes in 966 calls |
| 3 | Punctuation in legitimate plain labels | **CONFIRMED** — SI-087 above, fixed here |

---

## Files changed

| file | change |
|---|---|
| `utils/tool_output_reference.py` | SI-085 fix (.312) + **SI-087** label match |
| `fastapi_server_complete.py` | SI-086 fix (.312) — failure sentinel APPENDED, never substituted |
| `tests/unit/test_labelled_series_reference.py` | **NEW** — 21 tests, SI-087 guard |
| `tests/unit/test_reference_production_replay.py` | **NEW** — 145 tests, production-seeded corpus |
| `tests/unit/test_reference_fails_closed.py` | NEW (.312) — 12 tests |
| `tests/unit/test_arbitrator_never_destroys_results.py` | NEW (.312) — 6 tests |
| `tests/unit/test_multi_expression_reference.py` | updated for the new error text |
| `README.md`, `config/logging_config.json`, `version.py` | version → 1.0.0.313 |
| `SUSPECTED_ISSUES.md` | SI-087 added; SI-085/086 marked released in .313 |

## Breaking changes

None. The change is strictly widening — see the monotonicity result above.

## Dependencies

No new imports; `requirements.txt` unchanged.

## Migration

None required.

## Known limitation

An **unlabelled** single-series output referenced by an invented punctuated label still raises.
This is intentional — nothing in the output claims that name — and it has zero occurrences in the
3946-reference corpus.
