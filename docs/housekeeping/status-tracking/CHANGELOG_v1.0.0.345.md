# CHANGELOG v1.0.0.345 — 2026-10-24

## `compute`: size a plotted grid to fit the returned-series limit

### Changed (`user_tools/compute_tool.py`, policy text only)
- The tool description now says a series meant for plotting must have at most `_MAX_RETURNED_ELEMENTS` (200) points
  — a longer one comes back truncated and cannot be referenced — so the grid should be sized to fit. The number is
  read from the constant, not typed into the text.
- **Why:** after v1.0.0.343, the model's first grid for a formula plot was `np.linspace(…, 201)` in 3 of 4 runs (local
  and the owner's live rerun, NewX post 9009). Its results came back truncated, RAICA said so, and the model computed
  again with fewer points — no failure, but one wasted round each time.

### Verified
- Real path (NewX `call_raica` + Ask.yaml → local RAICA), the wave-equation prompt, 3 runs: first grid 200 points in
  3/3, one `compute` call, no truncation, a chart in every answer (17–25 s). Before: a second `compute` in 3/4 runs.
- Related unit tests (`compute`/`plot_data`/references/retry): 314 passed.

### Migration
None.
