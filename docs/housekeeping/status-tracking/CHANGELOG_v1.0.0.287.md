# CHANGELOG v1.0.0.287 — one discarded list caused three user-visible defects

**Date:** 2026-08-15 · **Against:** v1.0.0.286
**Closes:** SI-048 (fabricated statistics), SI-051 (chart never reaches the user)
**Downgrades:** SI-052 (trigger removed, class still unguarded)

## The measurement that found it

Both defects sat at synthesis, so the deciding question was whether the synthesis model *receives*
the data — plumbing — or receives it and ignores it — policy. A prompt directive would have been
wasted effort on the wrong half. Extracted from the real synthesis prompt of a Treasury run:

```
TOOLS EXECUTED: lookup_website          ← the gate had run 10 computes + plot_data
'4.29321' in prompt : False             ← compute returned exactly this
'4.77731' in prompt : False
real chart marker   : False             ← every [[chart: hit was the INSTRUCTION text
🔧 PARSED RESULTS: Generated 1 tool entries from corrected results
```

**Plumbing.** The synthesis model never saw the computed values or the marker, so it eyeballed the
statistics from the raw CSV and hand-drew a chart.

## Root cause — two assignments

```python
tools_results_list = regenerated_tools_results
tools_called = [tc['function']['name'] for tc in regeneration_response['tool_calls']]
```

The arbitrator's regeneration step **replaced** both lists with only the regenerated subset. On the
first of five attempts it therefore discarded every result gathered before it: phase-1 fetches, all
gather-gate compute outputs, and plot_data's chart marker. In the Treasury run regeneration returned
`['lookup_website']`, so both lists collapsed to that single entry.

Three separate user-visible defects, one discarded list:

| | consequence |
|---|---|
| SI-048 | statistics eyeballed from the CSV: **4.27 / 4.62** vs computed **4.29321 / 4.79** |
| SI-051 | no marker in the answer, though the chart was rendered and served |
| SI-052 | with no marker the model drew ASCII art: **2,924,215 chars, 99.8% whitespace** |

## Change

`_merge_regenerated_results()` (module-level, so it is testable) keeps every entry whose tool was
NOT regenerated, appends the regenerated ones, and derives names **from the entries** so the two
lists are parallel *by construction*. Plus a loud warning at `arbitrator_validate_tasks`'s
`zip(tools_called, tools_results_list)` — zip truncates to the shorter list silently, and those
lists are maintained by appends at eight different sites.

## Verification — 6 E2E runs, 2 datasets, real path

`tests/unit/test_regeneration_preserves_results.py` — 10 tests, **3 fail on pre-fix
replace-semantics** (verified by patching the helper back). Suite **552 passed**, 4 pre-existing
failures unchanged. Version sync 5/5.

Live proof the fix is on the real path: `🔧 REGENERATION MERGE: kept 161 prior result(s), added 2
regenerated → 163 total`. Pre-fix, those 161 were deleted.

| | before | after (6 runs) |
|---|---|---|
| synthesis sees compute results | ✗ (1 entry) | ✓ `TOOLS EXECUTED: compute, lookup_website, wikipedia_query` |
| charts published vs **markers delivered** | 4 vs **0** | **4 vs 4 — zero loss** |
| delivered markers serve an image | n/a | **4/4 HTTP 200, 51-67 KB, image/jpeg** |
| Treasury statistics correct | 4.27 / 4.62 ✗ | **4.293 / 3.97 / 4.79 / 4.777 / 4.41 / 5.08 — 3/3 runs** |
| fabricated 4.62 / 4.27 present | yes | **absent from all 3 answers** |
| refusals | 2/3 | **0/6** |
| synthesis truncations (whitespace runaway) | 1 | **0** |
| answer size | 2.9 MB @ 99.8% ws | 3.0-5.9 KB @ 14-17% ws |

The 2 runs without a marker published **0** charts — the model did not select `plot_data`. That is
tool-selection variance, not delivery: every chart that was produced was delivered.

## Still open

- **SI-052 stays open at P2.** The trigger is gone, the class is not: nothing in RAICA stopped the
  2.9 MB runaway — the vendor's 32,768-token ceiling did. Needs an explicit output-size guard.
- **SI-053** — column-less reference form, latent, pinned by a test.
- **Residual SI-048 (minor):** one USGS answer rendered std as "≈ 0.43" where compute returned 0.42;
  mean and median were exact.
- **`plot_data` selection is not reliable on the USGS prompt** (1/3 runs). Separate from delivery.
