# CHANGELOG — v1.0.0.261

**Date:** 2026-08-13
**Type:** Feature (SI-028 P2b) — restricted numpy expression evaluator
**Signed off by:** the user, 2026-08-13
**Design:** `docs/RAICA_GENERALIZED_EXTRACT_CHART.md` §P2b

---

## Summary

Deep Research and @Ask could retrieve real data and then get the arithmetic over it wrong. The
motivating production failure (2026-08-11) fetched 401 real daily Treasury rows and reported the
minimum 30Y-10Y spread as **+0.19** while quoting the two yields that produce **+0.67**, and named
a maximum of **+0.53** when the true maximum is **+0.69**, a year earlier. Every value it *quoted*
was exact; only values it **derived** were wrong. The model was eyeballing extrema over a 401-row
table.

`compute` exposes numpy behind a restricted expression evaluator so derived figures are
**calculated, not read** — and returns the expression alongside the number so the calculation is
citable.

## Why not a `series_stats` tool

It would fix min/max and leave correlation, percentiles, diffs, normalisation and rolling windows
to be added one at a time — the per-case proliferation the Generalization Directive forbids. The
LLM picks the function instead.

## What was added

| file | role |
|---|---|
| `utils/restricted_numpy_eval.py` | the fence: AST allow-list, attribute rule, name binding, empty builtins, numpy allow-list, element caps |
| `user_tools/compute_tool.py` | tool wrapper, result formatting, wall-clock timeout |
| `tests/unit/test_restricted_numpy_eval.py` | 27 tests — 12 pre-registered escape vectors + correctness |

`numpy==2.3.2` was already a declared dependency; **no new dependencies**.

## The fence

This is **not** sandboxed Python and **not** code execution — it is a restricted expression
language that happens to use Python syntax. The AST is validated in full *before* anything is
evaluated. `sandboxed_executor` was explicitly rejected as a substrate: it is a command whitelist
over `subprocess` with no seccomp, no container and no isolation boundary.

1. **AST allow-list** — validated before eval; comprehensions, lambdas, f-strings, walrus, starargs
   and imports are rejected by omission and by name
2. **Attribute rule** — `np.<name>` only, `<name>` in the allow-list; no chaining, no leading `_`
3. **Name binding** — every name is `np` or a caller-supplied data key
4. **Builtins** — `eval` runs with `{"__builtins__": {}}`
5. **numpy ALLOW-list** — pure maths only. Deliberately excluded, with reasons recorded in the
   source: `load`/`loadtxt`/`fromfile`/`memmap` (I/O; `np.load` executes pickles),
   `vectorize`/`apply_along_axis`/`fromfunction`/`piecewise` (take a callable),
   `zeros`/`ones`/`arange`/`linspace` (allocate by size), `outer`/`tile`/`repeat`/`meshgrid`
   (expand small input into a memory bomb)
6. **Resource caps** — 200k elements per array, 1M total, 500-char expression, 5s wall clock

**One case the function allow-list cannot see:** `y30[:, None] * y10` calls nothing, yet on
200k-element inputs it is a 4×10¹⁰-element outer product — an OOM kill of the worker. The
axis-insertion token is therefore blocked at the AST level, rather than trying to predict
intermediate sizes.

## Verification

Reproduces the motivating failure exactly:

```
np.min(y30 - y10)           = 0.18      <- production answer said +0.19
np.max(y30 - y10)           = 0.69      <- production answer said +0.53
np.corrcoef(y30, y10)[0][1] = 0.760612
```

**The 12 pre-registered escape vectors were shown to DISCRIMINATE**, not merely to pass. The suite
was run against a deliberately permissive plain-`eval` build: **27/27 pass on the real evaluator,
and all 12 vectors FAIL on the permissive one.**

Two vectors initially passed against the permissive build — i.e. proved nothing — and were
rewritten:

- **V2** (globals reach-through): numpy 2.3.2 wraps the allowed functions in
  `_ArrayFunctionDispatcher`, which has no `__globals__`, so the payload raised `AttributeError`
  instead of being blocked. Re-anchored on `y30.dtype`, a chained attribute that genuinely resolves
  under plain `eval`.
- **V12** (unicode homoglyph): Cyrillic 'а' does not NFKC-normalise to Latin 'a', so `np.loаd` was
  a nonexistent attribute on every implementation. Mathematical-bold and fullwidth forms *do*
  normalise to `load`; the test now also writes a real `.npy` first, because aiming at a missing
  path made it fail with `FileNotFoundError` for the wrong reason.

Suite: 360 unit tests pass (4 pre-existing failures unrelated and unchanged). Version-sync 5 pass.

## Known limitation — NOT yet reachable from the failure it was built for

`@Ask` sends an `allowed_tools` whitelist and the server filters the offered tools against it
(`fastapi_server_complete.py:9808`). `compute` is therefore **invisible to @Ask** until it is added
to `../NewX/newx/ai_plugins/Ask.yaml` — that is SI-028 P3, in a separate repository. This is the
same mechanism that kept `calculator` out of the 8 tools the production log showed.

## Also in this commit

Suspected-issues log updates carried over from the SI-032 work in the same session:
SI-032's S9 benchmark result and its confound analysis, plus new entries **SI-033** (OpenAlex rate
limit is the next binding constraint; RAICA is likely not in the polite pool), **SI-034** (higher
retrieval volume overruns the synthesis budget) and **SI-035** (two files register the tool name
`analytical_visualizer`; which one is live depends on filesystem order).

## Migration / breaking changes

None. New tool, additive. No config keys changed, no dependencies added.
