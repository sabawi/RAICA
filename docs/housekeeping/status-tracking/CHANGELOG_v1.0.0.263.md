# CHANGELOG — v1.0.0.263

**Date:** 2026-08-14
**Type:** Feature + root-cause fix
**Issues:** SI-036 (root cause found and fixed), SI-028 P2a (`plot_data`, built)

---

## The measurement that ended four failed attempts

Four consecutive fixes had failed at the same point: `compute` — and later `plot_data` — were
built, whitelisted, offered to the model, and **never called**. The only signal was an outcome
line, `SECOND ROUND: no further tools requested`, which said nothing about why.

Instrumentation was added (a diagnosis round, shipped alone) and answered it in one line:

```
🔬 second-round-audit: prompt_chars=43013 tools_offered=10 tool_calls_returned=0
   dispositions=[] truncated=True usage={'completion_tokens': 4096} narrative=''
```

The selector was **cut off mid-output every time**. It was never judging that no tool was needed —
it never finished speaking. `dispositions=[]` refuted "our filter dropped the calls"; `narrative=''`
refuted "it answered in prose".

**Two causes, both required:**

1. **The arguments were impossible.** `compute` and `plot_data` took data as INLINE ARRAYS, so 404
   daily rows meant emitting thousands of numbers as tool arguments.
2. **The budget was too small.** At `max_tokens=4096` the model's own reasoning consumed the whole
   completion budget before reaching the call.

Neither alone explains it. Raising the cap to 32,768 against the 43,013-char prompt changed nothing
but latency (33s → 439s). Shrinking the prompt AND raising the cap produced 5 tool calls with
`truncated=False`.

## What changed

### By-reference data passing — `utils/tool_output_reference.py` (new)

The model names a prior tool's output and a column; RAICA substitutes the real values before
dispatch:

```
{"from": "lookup_website#1", "column": "30 Yr"}          -> [4.79, 4.83, ...]
{"from": ["lookup_website#1", "lookup_website#2"], ...}  -> both years joined
```

Mirrors the existing `{{RESEARCH_OUTPUT}}` / `_dr_inject_research_output` pattern. Two consequences
beyond fitting the budget: the numbers are the ones the tool actually returned rather than a
retyped copy, and the selector prompt drops from the whole file to a schema preview — **20,730
chars → 579** per output, total prompt **43,013 → 10,612**.

### `plot_data` — SI-028 P2a (new tool)

A thin wrapper over primitives already in production: `DatasetSeries` → `generate_data_chart` →
`publish_chart` → `_marker`. Deliberately **not** `analytical_visualizer`, which generates and
executes chart code. Provenance is mandatory and fail-closed: no source URL, no chart. Every
failure path explicitly instructs the model **not** to write a marker itself.

### `selector_max_tokens: 16384` — config, with the measurement recorded beside it

## Defects found by testing against REAL output rather than fixtures

- **The parser read RAICA's formatted preamble as the header**, reporting columns like
  `'As of [Current Date and Time: Thursday'`. A tool result is not a bare file. The table is now
  located structurally — the longest run of lines sharing a field count.
- **A `Date` column requested numerically became `[None, None, …]`**, and `plot_data` refused the
  chart with *"temporal x value None is neither a number nor a recognised date"*. A column's own
  content now decides whether it is numeric or text.
- **`n=249` — a reference addressed only ONE output.** Asked for two years the model computed over
  2025 alone and described the result as "over the full period". Both extremes happened to fall in
  that year, so the number was right **by luck**. `from` now accepts a list.
- **Joined files drew a broken line.** Source files are newest-first; joining 2025 and 2026 each
  descending would run backwards then jump. Points on a temporal/quantitative axis are now ordered;
  categorical order is left alone because it carries meaning.

## Results on the request that started this

| figure | before | now | truth |
|---|---|---|---|
| max 30Y-10Y spread | 0.67 | **0.69** | 0.69 |
| min 30Y-10Y spread | 0.18 | **0.18** | 0.18 |
| observations used | 249 (one year) | **404** | 404 |
| "computed as …" | claimed, no tool ran | **true** — `compute` ran | — |
| fabricated chart marker | 3 runs of 3 | **none** | — |

`compute` now runs on values RAICA extracted, so the provenance claim is accurate rather than
decorative. When chart publishing was unavailable locally, the model followed the honest failure
path instead of inventing a marker — the first run in five without a fabricated `[[chart:...]]`.

## Verification

| check | result |
|---|---|
| unit suite | **415 passed**, 4 pre-existing failures (unchanged, unrelated) |
| version sync | 5 passed |
| real Treasury CSVs, both years | n=404, min 0.18, max 0.69 — exact ground truth |
| chart x ordering | 404 points, ascending, 2025.00 → 2026.61 |

## Not fixed

- **Observation count still reported as 406** against a true 404 — the model's own arithmetic on
  file line counts, not a retrieval defect.
- **No end-to-end published chart yet.** Local NewX is down and chart upload is disabled locally, so
  the publish step is exercised only with a stub. It needs a production run.
- **SI-038 remains open.** `_repair_answer_chart_markers` returns early when no authoritative
  markers exist, so a fabricated marker in an answer where no tool produced a chart still passes
  untouched. This release removes the *reason* to fabricate; it does not close the hole.
