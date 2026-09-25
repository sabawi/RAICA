# CHANGELOG v1.0.0.327

**Date:** 2026-09-25
**Theme:** `compute` does plain arithmetic, and its fence closes two resource holes

## Fixed

- **Constant arithmetic (SI-096).** `compute` refused any call without a data series, so `np.sqrt(7921)` or a
  compound-interest formula was rejected — and the fail-closed notice then FORBADE the answer to state the figure.
  The rule protected nothing (a dummy `{"x": [0]}` let the same literals through). `data` is now optional
  (`utils/restricted_numpy_eval._prepare_data`, `required: ["expr"]` in the schema), and the tool description tells
  the model to use `compute` for plain arithmetic rather than doing it in its head. Results from constants say
  "from constants only (no data series)" instead of "over n=0 data point(s)".
- **Unbounded powers (SI-100).** `9**9**9` was evaluated as a Python bignum (>20 s, uninterruptible inside the
  server). Every `**` is now rewritten, after validation, to `np.float_power` — float64, same values; an integer
  power is reported as a float (2**10 → 1024.0). An overflow is an error ("the result overflowed"), never `inf`
  presented as an answer.
- **Sequence repetition (SI-100).** `[1]*300000000` allocated ~2.3 GB; lists have no `.size`, so the result cap
  missed it. A list, tuple or string literal multiplied by a number is now rejected; numpy arrays are unaffected.

## Tests

`tests/unit/test_restricted_numpy_eval.py::TestConstantsPowersRepetition` (7) and two in
`tests/unit/test_compute_argument_shapes.py`. On the pre-fix code the 6 behaviour tests fail (the power bomb in a
subprocess with a 10 s deadline, so it fails instead of hanging) and the 3 controls pass. Unit suite: 989 passed,
4 failed — the same 4 that fail on unmodified v1.0.0.323.

## Verified on the real path

Multi-part request (Tokyo weather + Microsoft price + √7921), configured tool model deepseek-v4-pro, 3 runs:
square root present **3/3** (was 0/3), zero empty-data rejections. Temperature still missing — a search-source
problem, logged as SI-101.

## Breaking changes / migration

None. `compute` accepts everything it accepted before, except repetition of a list/tuple/string literal.
