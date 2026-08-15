# CHANGELOG v1.0.0.283

**Date:** 2026-08-15
**Focus:** SI-045 — the numpy allow-list held 97 names and not one mathematical constant.

## The failure

The second live re-test of the USGS distribution request failed to render its chart for a third,
unrelated reason. This time the answer said so plainly:

> "the normal-PDF curve values (which required `np.pi` in the density formula) were rejected by the
> compute tool's allowed-function list"

Log: `Expression rejected: np.pi is not in the allowed function list` ×5.

`np.pi` parses as an `ast.Attribute`, and the attribute check tested a single set holding
**functions only**. An audit of all 97 allowed names found **zero** constants.

## Why the restriction exists (and why this wasn't it)

`compute` evaluates expressions **authored by the LLM**. That is `eval` over untrusted input, so the
fence must be an ALLOW-list, never a deny-list — `np.load` alone executes pickles, and
`vectorize`/`apply_along_axis` take a callable. The fence is right.

Blocking `np.pi` was not part of that fence. A constant allocates nothing, executes nothing, and
takes no argument. It was an incomplete list, not a safety property.

## Changes

- **`ALLOWED_NUMPY_CONSTANTS = {pi, e, inf, nan, euler_gamma}`** — permitted for attribute access,
  and **rejected when called**: `np.pi(3)` now returns "np.pi is a constant, not a function — use it
  as a value", which beats numpy's opaque `'float' object is not callable` surfacing inside a tool
  result.
- **Added `histogram` and `polyfit`** — the two functions a distribution question actually needs.
  Without `histogram` the model hand-rolled every bin as `np.sum((mag >= 5.5) & (mag < 5.75))`, ten
  times over. Both join `_SIZE_TAKING`, so `bins` and `deg` are bounded exactly like `linspace`'s
  `num`.
- **Removed the dead `flatten` entry** — `np.flatten` does not exist; it is an ndarray method
  (`np.ravel` is the real function and was already allowed).
- **Error wording** — "not in the allowed function list" → "not an allowed numpy name", since the
  permitted set is no longer functions only.

## The fence is unchanged — verified

```
np.load("/etc/passwd")               -> rejected: not an allowed numpy name
np.zeros(10**9)                      -> rejected: not an allowed numpy name
np.vectorize(len)                    -> rejected
__import__('os').system('id')        -> rejected
np.histogram(mag, bins=10**9)        -> rejected: argument 1e+09 exceeds the 200000 element cap
np.polyfit(np.arange(3), mag, 10**8) -> rejected: argument 1e+08 exceeds the 200000 element cap
np.pi(3)                             -> rejected: np.pi is a constant, not a function
```

And the expression that failed in production now evaluates:

```
(1/(np.std(mag)*np.sqrt(2*np.pi)))*np.exp(-0.5*((np.linspace(...)-np.mean(mag))/np.std(mag))**2)
  -> [0.33283 0.61217 0.66191 0.42074 0.15722]
```

## Pattern worth naming

This is the **same class as SI-041(a)**, where `linspace`/`arange` were blocked and cost a request
47 rejections and its chart. Two occurrences make it a pattern:

> **Audit the allow-list against the WORK, not just against the threat.** Before shipping a numeric
> capability, run the expression a real analysis would actually write.

## Tests

`tests/unit/test_restricted_numpy_eval.py` — 6 added (56 total in that file), including the literal
production expression, which fails on pre-fix code with
`RestrictedEvalError: np.pi is not in the allowed function list`.

Suite: **501 passed**, 4 pre-existing failures unchanged.

## Files

- `utils/restricted_numpy_eval.py` — constants set, histogram/polyfit, size bounds, error wording
- `tests/unit/test_restricted_numpy_eval.py`
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-045
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.283
