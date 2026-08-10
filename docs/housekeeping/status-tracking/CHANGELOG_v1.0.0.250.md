# CHANGELOG v1.0.0.250 — restore multi-entity Deep Research (SI-025)

**Date:** 2026-08-10 · **Previous:** v1.0.0.249 · **Type:** P0 fix — flagship feature

An 8-stock `@Ask` query returned "No technical chart markers were provided in the evidence"
for **all 8** stocks and **zero DCF values**, while the tools had succeeded (8/8 DCFs
computed, 8/8 chart markers emitted). The output was produced and then discarded.

## Three compounding defects

**1. Duplicate YAML key — pre-existing, present in prod.** `verification:` sat at
synthesis-child depth with its five children at the *same* depth, so YAML made them
`synthesis` siblings; the verifier's `evidence_token_budget: 87000` then silently overrode
`synthesis.evidence_token_budget: 160000` (last key wins). The code reads verification at
ENGINE level, so its settings were never read at all.

| setting | intended | in effect |
|---|---|---|
| `synthesis.evidence_token_budget` | 160,000 | **87,000** |
| `verification.evidence_token_budget` | 87,000 | **47,850** |
| `verification.max_tokens` | 24,000 | **12,000** |

**2. SI-021 removed an accidental safeguard.** Prod's gap assessor was broken by a
900-token cap, so DR stopped at 2 rounds / ~34K tokens — under budget *by luck*. Reviving
it (correctly) took gathering to 4 rounds / ~206K tokens, overflowing an already-undersized
budget. This is why the user hit the failure and prod did not.

**3. Flat fair-share truncation cut the wrong content.** Web prose is redundant; a tool
block is not — its DCF, ratios and rendered chart exist in one place. Being largest, they
were cut hardest, and `_tok_truncate` keeps the HEAD while the analyzer appends its
`[[chart:…]]` marker LAST.

## Measured on the user's exact profile (78 items / ~206K tokens)

| allocator | analyzer block kept | DCF + chart |
|---|---|---|
| OLD flat-share @87k *(what ran)* | **9%** | LOST |
| OLD flat-share @160k *(config fix alone)* | **52%** | **still LOST** |
| **NEW priority @160k** | **100%** | **SURVIVE** |

The middle row is the point: the config fix alone would **not** have fixed the report.

## The fix

- **(a)** MERGE the stranded settings into the existing `engine.verification:` block and
  delete them from `synthesis:` — restores all four values, leaves exactly one block.
  **My first attempt simply dedented the stranded block, which created a SECOND engine-level
  `verification:` and silently downgraded `max_tokens` 32000 → 24000 — the same duplicate-key
  bug I was fixing. The repo's own `test_no_duplicate_yaml_keys_under_engine` caught it
  before commit.**
- **(b)** priority-aware allocation: computed sources (`synthesis.priority_sources`) served
  first up to `priority_budget_ceiling` (0.70); remainder shared fairly. Small runs are
  byte-identical to before (early return when everything fits)
- **(c)** rescue `[[chart:|image:|file:]]` markers from a truncated block and re-attach

## Verified end-to-end — the user's exact 8-stock prompt

```
BEFORE: synth chart-markers — evidence=0  prompt=1  draft=0
AFTER:  synth chart-markers — evidence=20 prompt=40 draft=20
        charts_required=20  charts_placed=20
```

8/8 tickers with DCF values, 8/8 with charts and technicals. The phrase *"no technical
chart markers"* appears **0** times (was 8).

**Now exceeds prod on the same class of request:**

| | prod 7-stock (Jul 19) | local BROKEN | **local FIXED** |
|---|---|---|---|
| rounds | 2 | 4 | 4 |
| evidence items | 23 | 78 | **110** |
| unique sources | 88 | 293 | **277** |
| charts rendered | 7 | 0 | **20** |
| DCF values | 7 | 0 | **8** |

## Correction on the record

I initially claimed prod had never been asked a multi-ticker question. The user refuted it
with a 7-stock prod report carrying per-stock charts and DCFs. **That claim was false and is
retracted** — it also let me wrongly conclude this was not a regression. Defect 2 is mine.

## Files changed

| file | change |
|---|---|
| `config/llm_config.yaml` | dedent `verification:` (1 line); + `priority_sources`, `priority_budget_ceiling` |
| `research/synthesis.py` | priority-aware `_allocate_token_budget`, marker rescue, `_ARTIFACT_MARKER_RE` |
| `tests/unit/test_evidence_budget_priority.py` | **new** — 10 tests |
| `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` | SI-025; SI-024 superseded |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.249 → 1.0.0.250 |

## Breaking changes

None. Small/medium runs behave identically; only over-budget runs change, and there the
change is that computed results survive.
