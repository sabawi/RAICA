# CHANGELOG v1.0.0.310 — a dead arbitrator, and the reference layer that made computed data unchartable

**Date:** 2026-08-18 · **Against:** v1.0.0.309
**Closes:** SI-079, SI-080, SI-081 · **Opens:** SI-078, SI-082

## What this release is, and is not

It is three plumbing fixes, one of them a production regression of my own making. **It does not
make charts work** — 0 real charts in 18 end-to-end runs, control included. What it does is remove
every fault that was in RAICA's own wiring, leaving a residue (SI-082) that is about the model's
data hygiene rather than the pipeline.

Work that did NOT survive review was reverted rather than shipped: two changes to the gather gate
(round-aware assessment, and passing the gate's verdict to the selector). Both were sound and
tested; both serve a lane that is `enabled: false` in production, and neither moved any measured
outcome. Shipping inert complexity into a hot path is a regression risk with no upside.

## SI-079 — the arbitrator was disabled on local AND live for 13 builds

`manager.py:127` builds the provider only if `arbitrator_config.get('enabled', False)`. The key is
**fail-closed and silent**. `d07ec70` (v1.0.0.297) reverted the arbitrator from DeepInfra back to
Ollama — correct in itself, it stopped a deploy that would have 401'd every lane — but reinstated
an older block that never carried the key:

```yaml
# before d07ec70          # after
arbitrator:               arbitrator:
  enabled: true             type: ollama
```

Dead since: `call_arbitrator` (every caller), `arbitrator_validate_tasks`, the tool-validation
retry path, and `plot_data`'s post-LLM dispatch, which derives its parameters through the
arbitrator. The only notice anywhere was one startup line.

**Verified by invoking, not by reading config:** `arbitrator_provider = OllamaProvider` and a live
call returns `'OK'`; before, it was `None`.

**Scope stated honestly.** I first called this the chart blocker; counting both arms refutes that —
`plot_data` reached `TOOLS EXECUTED` 6 times before the fix and 6 after, failing identically. It
removed 2 failures on a minority route. It is a real regression worth shipping on its own merits;
it is not why charts were missing.

## SI-080 — the SI-044 batch deferral was wired into one path, and not the one that runs

`_split_calls_awaiting_batch_output` had exactly one call site: inside the gather-gate loop, which
is disabled. The phase-1 batch ran unsplit — and round 1 selects every tool *before* any tool has
run, so a consumer scheduled beside its producer is the normal case there. Observed:

```
'x': '{"from": "compute#5", "column": "d2"}'    # correct — and compute#5 is in THIS batch
Tool 'plot_data' error: plot_data: x must be a list
```

Fixed by splitting the batch, running the ready calls, then resolving the deferred ones against
the results — the same sequence the gate used, reusing the same resolver.

**Honest status: correct by inspection and test, never observed firing.** Across 6 later runs the
deferral logged zero times, because the model put fetch in phase 1 and compute/plot in later
rounds. It closes a proven code gap for a scheduling pattern this workload stopped exhibiting.

## SI-081 — computed data could not be charted at all

Two faults, compounding:

1. `extract_column` reached its computed-series branch only when `not _looks_tabular(text)`.
   `_looks_tabular` counts commas, and a computed array prints as `- [-0.03, -0.04, 0.03, ...]`.
   So the branch was skipped for exactly the outputs it exists to serve, `_parse_table` read the
   VALUE line as a header, and the model was told its available columns were
   `['- [-0.03', '-0.04', '0.03', ...]` — the data itself, offered as column names.
2. `compute` evaluates a LIST of expressions in one call (up to 12), but `computed_series` splits
   on the FIRST `computed as:` and could only ever see the first entry. There was no way to address
   expression #3. The model tried `{"column": "d[::10]"}` (the expression) and `{"column": "0"}`
   (an index) — both reasonable, neither supported, neither announced.

New `computed_entries()` parses a compute result into `(expression, values)` pairs using RAICA's
own output markers (a state machine over `computed as:` and the entry bullet — not wording).
`extract_column` now recognises a compute result by that marker **before** the tabular guess, and
resolves by expression text or index. `describe_reference` announces every series with the exact
syntax that resolves, so description and resolution cannot disagree.

Verified against the real production output shape, not an invented one.

## Verification

| | |
|---|---|
| `test_multi_expression_reference.py` | 11 tests, **8 fail on pre-fix**; the 3 that pass are the controls |
| `test_phase1_batch_deferral.py` | 7 tests, **2 fail on pre-fix** — precisely the two WIRING tests |
| Unit suite | **688 passed**, same 4 pre-existing failures |
| Tier-0 | 10/10 |
| Version sync | 19/19 |

One control in the SI-081 suite was wrong on first writing — it demanded that a single computed
series honour the column name, contradicting the deliberate SI-047 contract. The test was corrected,
not the code.

## SI-082 — what is left, and it is not plumbing

```
plot_data: quantitative x values must all be finite numbers
plot_data: temporal  x values must all be finite numbers
'd[::4]' does not name one of the 2 computed series
unknown output reference(s) ['compute#10']
```

`x` now resolves to a real numeric series and reaches the validator, which rejects it because
DGS10 carries missing observations as NaN — the model computes NaN-aware statistics and then plots
the raw series. That is a prompt/policy decision (strip non-finite pairs in `plot_data`, or require
a finite series), not a pipeline defect. Logged, not fixed.

## Docs

Reviewed README (version surfaces only) + `config/logging_config.json` + SUSPECTED_ISSUES
(SI-079/080/081 resolved, SI-082 opened, SI-076/077 entries removed with their code) +
`RAICA_NONDR_GATHER_GATE.md` reverted to HEAD. `RAICA_GENERALIZED_EXTRACT_CHART.md` and
`DESIGN_unified_artifact_pathway.md` were read before changing anything and need no update: this
release restores the reference layer to the contract they already describe.

## Tier-1 (real-LLM) — REGRESSION verdict, cleared with evidence

The suite reported `SUITE: REGRESSION` on two S2_dr_delivery PERF rows (88.5 vs base 42.4;
278.7 vs base 140.7). **Zero CODE regressions; 14 PASS.** Cleared, not waved away:

1. **The arbitrator fired 0 times during the benchmark window**, so SI-079 — the only change that
   adds LLM calls — is not in this path. `research/*.py` contains no arbitrator reference at all.
2. **Control group across the last five runs** puts this run mid-range, with v303 worse:

   | run | S2 latencies |
   |---|---|
   | v301 | 61.7, 84.7, **344.8** |
   | v302 | 39.6, 81.5, 197.5 |
   | v303 | 92.4, 138.0, **321.6** |
   | v306 | 70.0, 75.9, 264.7 |
   | **v310** | 74.2, 88.5, 278.7 |

3. Both rows are **n=1** on a stochastic metric, and the run logged 142 rate-limit responses
   (limit 150) with 58 on S2 alone.

This is the stale S2 PERF baseline already tracked as **SI-063**, which still needs a deliberate
rebaseline on a rested run. It is not evidence against this release.
