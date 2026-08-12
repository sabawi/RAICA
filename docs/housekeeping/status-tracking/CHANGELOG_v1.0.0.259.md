# CHANGELOG v1.0.0.259 — benchmark harness fix + disclosure metrics (NO behaviour change)

**Date:** 2026-08-12 · **Server behaviour: UNCHANGED.** This release is measurement only.

## Why

An attempt at the "honest-but-thin" sourcing fix (evidence-block `text_held=` labelling plus two
synthesis directives) could not be evaluated, because the harness itself was defective. Fixing
the harness first then showed the attempt to be a REGRESSION, and it was dropped. Both outcomes
are recorded here.

## Harness defects fixed

### 1. `retain()` destroyed all but one run per arm
It wrote one file per (scenario, tag), so an n=3 arm left ONE arbitrary survivor. That is not a
smaller sample but an UNREPRESENTATIVE one, and it produced a false comparison immediately: the
surviving PRE artifact was a degenerate run whose evidence included **German tea shelf-life
pages** for a question about the Iron Age Near East, and it was about to be compared against the
LARGEST run of the POST arm. Now every run is retained, numbered to match the metrics list order,
with `retained_runs()` to read a whole arm back.

### 2. No metric existed for the actual goal
The goal chosen was DISCLOSURE — where sourcing is thin, say so — and nothing measured it. Added:
- `thin_evidence_disclosures` — count of the model's own statements that evidence for part of the
  request did not arrive.
- `unattributed_encyclopedic_citations` — count of sentences resting on a general-reference source
  with no attribution in the prose.

### 3. Verifier output was about to be credited to a synthesis directive
The verifier appends its own italic notes ("— _This is an inference drawn from …_"). A post-change
answer's honest-looking lines were the VERIFIER's, not the model's. `strip_verifier_notes()` now
removes them before any disclosure metric, and a named test pins it.

### 4. A sentinel was nearly shipped inside a scored metric
The first disclosure metric was an attribution RATIO, undefined when nothing encyclopedic is cited
— which is the BEST outcome, not a missing one — mapped to `-1.0`. With `higher_better` that scores
a clean run WORST. Replaced by a count that is monotone and correct at zero. Same class as SI-026.

## The attempt that was measured and dropped

Evidence blocks were to carry `text_held={n} chars retrieved`, giving the synthesis model the one
fact it could not otherwise know — whether a short block is a short SOURCE or a truncated view —
plus two directives ("what you have read vs what you have only heard of"; "general-reference
sources are a last resort, and must be disclosed").

With the fixed harness, n=3 per arm, the ranges are SEPARABLE and the result is negative:

| metric | PRE runs | POST runs | |
|---|---|---|---|
| `thin_evidence_disclosures` | 0, 0, 0 | 0, 0, 0 | the goal never occurred |
| `unanchored_citation_ratio` | .139, .219, .118 | .308, .478, .278 | WORSE, no overlap |
| `claims_unsupported_ratio` | .062, .053, .203 | .300, .493, .339 | WORSE ~5.5x, no overlap |
| `unattributed_encyclopedic` | 12, 10, 5 | 12, 8, 5 | unchanged |
| `encyclopedic_share` | .278, .438, .071 | .222, .071, .286 | unchanged |

**SUSPECTED mechanism (not verified):** instructing the model not to represent the findings of
stub sources, while leaving it holding mostly stubs, pushed it to assert more from the little full
text it had — so anchoring and groundedness both fell. If that is right, no wording fixes it: the
input is the problem, not the instruction.

## Standing conclusion for the next round

Two consecutive policy-only attempts at DR sourcing quality have now failed under measurement
(v1.0.0.257 reverted after external review; this one dropped before shipping). The next attempt
should change the INPUTS — resolve scholarly identifiers to a readable open-access copy
(DOI → Unpaywall/OpenAlex → PMC/CORE/repository) so "read and digested in context" is achievable —
rather than asking the model to do better with abstracts.

## Changed
- `tests/benchmark/lib/spectrum.py` — `retain()` keeps every run; `retained_runs()` added
- `tests/benchmark/lib/generic_quality.py` — disclosure metrics + verifier-note stripping
- `tests/benchmark/scenarios/s9_ancient_languages.py` — disclosure metrics wired in
- `tests/unit/test_benchmark_retain.py` (new), `tests/unit/test_generic_quality_metrics.py` (+4)
- Version surfaces → 1.0.0.259

`research/synthesis.py` is UNCHANGED from v1.0.0.258.
