# CHANGELOG v1.0.0.352 — 2026-10-25

## A failed program that a later run already redid is not run again; "solve" gives the exact solution

From NewX post 9088 (`@Ask solve ∂²u/∂t² = c²∇²u and plot the solution in 3D for 3 different solutions superimposed`):
the answer carried two programs and duplicate charts, presented the duplicate as a deliberate second experiment,
solved only numerically, drew three surfaces that hid one another, and blamed an energy loss on "absorbing
boundaries" the code did not have.

### Fixed — retry engine re-ran superseded failures (SI-114)
`run_python_analysis` failed its self-check; the gather loop ran it again and it succeeded; the retry engine then
regenerated the FAILED call twice more. Before retrying a failure, `intelligent_retry_with_circuit_breakers` now asks
the model (`_failure_already_done`) whether a later SUCCESSFUL call of the same tool already did that work — the model
decides; two different searches by one tool are different work. Asked only when such a later success exists; any
failure of the check keeps the retry as before. An empty regeneration is logged as "nothing to retry", not an error.
- First tried: telling the regenerating model to skip finished work. 0/3 effect on the real 9088 context (it kept
  regenerating), so that wording was reverted and the separate question added.
- Measured: the check on the real 9088 context 3/3 "done"; two controls (different searches, different pages) 3/3
  "not done". Through the real NewX path, 5/5 runs that had a superseded failure did not re-run it, one chart each (1 more run had no failure).
- Tests: `tests/unit/test_retry_superseded_failure.py` (5; fail with the check disabled).

### Changed — `run_python_analysis` policy
- An equation with a known exact solution: the program gives it first and uses numerics only where none applies or
  as a check. 5 of 6 real-path runs answered with analytic solutions (9088: numerical only); the sixth chose Gaussian pulses in a box and solved by finite differences.
- Describe only what the code models (a fixed zero boundary reflects); conserved quantities measured at one time
  level, tolerance and drift printed.
- Superimposed 3D surfaces: transparency is named as not enough; stacked offsets or wireframes, full grid
  resolution, legend in each surface's colour, even when the task names colormaps. The caller is told to describe
  what to plot, not how to style it, and to present one run's result, not several attempts as a comparison.
  **Partial:** 1 of 3 final runs was clearly readable (wireframes); one stacked but was dominated by a 1/r spike,
  one drew an aliased opaque surface over the others. Open as SI-115.
- Test: `test_writer_policy_carries_the_9088_rules`.

Pairs with NewX 1.0.0.465 (math with `|` inside a table cell).
