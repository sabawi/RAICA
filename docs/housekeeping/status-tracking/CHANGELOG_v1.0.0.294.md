# CHANGELOG v1.0.0.294 — SI-053: column-less references resolve, safely

**Date:** 2026-08-16 · **Against:** v1.0.0.293 · **Closes:** SI-053

## The latent defect

A `compute` output has no columns (SI-047), so `{"from": "compute#1"}` with no `column` is a
shape the model can plausibly emit. `_is_reference` required **both** keys, so such a dict was
not recognised as a reference at all: it passed through untouched, reached the tool raw, and
numpy rendered it as `array(['from'])` — the SI-050 signature, where `<U4` is `len('from')`.

Found by the SI-050 generalization matrix, not by an E2E run. Three runs of one prompt could
never have surfaced it.

## Why the obvious fix was refused

Treating a bare `from` as a reference would also capture ordinary arguments that happen to use
the word:

```json
{"from": "2026-01-01", "to": "2026-06-30"}      <- a date range, NOT a reference
```

Substituting over that would destroy the call — trading a latent bug for an active one.

## The fix — index-aware recognition

A column-less dict is a reference **only when its `from` names an id that exists in this
batch's reference index**:

- `{"from": "compute#1"}` → `compute#1` is in the index → resolves
- `{"from": "2026-01-01", …}` → not an id → left untouched
- `{"from": "nosuch#9"}` → not an id → left untouched, not half-substituted

Precise in both directions, and it needs no keyword list — the index is the authority. The
two-key form is unchanged, and callers that pass no index keep the strict old behaviour, so
nothing silently changes shape for them.

## Verification

`tests/unit/test_corrected_tools_generalization.py` — 14 tests:

- a column-less reference to a compute output resolves (**fails on pre-fix code**)
- a `{"from": …, "to": …}` date range is NOT mangled into a reference (passes both ways by
  design — this is the guard against over-widening)
- an unknown id is left alone rather than half-substituted

The resolver's own suites are unaffected: `test_tool_output_reference.py`,
`test_computed_series_reference.py`, `test_intra_batch_references.py` — **45 passed**.

Tier-0 **10/10**, unit **574 passed** (4 pre-existing unchanged), version sync 5/5.

## A note on the edit itself

Replacing the old pin-the-behaviour test initially deleted three neighbouring column-type
tests (date-as-text, gaps preserved, case-insensitive lookup) because they sat inside the
replaced range. Caught by diffing the test inventory against the committed file and restored
verbatim. Recorded because "the suite still passes" would not have caught it — a deleted test
passes by being absent.
