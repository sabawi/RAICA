# CHANGELOG v1.0.0.348 — 2026-10-24

## `run_python_analysis` — phase P2 security audit fixes (tool still OFF)

Audit recorded in NewX `docs/SECURITY_SPEC_AND_AUDIT.md` §5 (NewX 1.0.0.463 fixed a chart-link defect found in the
same audit). Details: `docs/DESIGN_run_python_analysis.md` §12.

### Fixed
- `utils/py_sandbox.check_host_memory`: refuse to start a program unless `min_host_available_mb` (new, default 400)
  remains after the program's whole `memory` limit — the server is shared with NewX and has ~1 GB available on
  production. Inside the lock's `try`, so a refusal releases it. Tests: `tests/unit/test_py_sandbox_host_memory.py`
  (8; the lock-release and the removed-check plants are red).
- `utils/py_sandbox.run_program`: when the runner dies without its result, the sandbox's exit status is reported
  (137 → "most often the memory limit"); the red-team memory-bomb test asserts it (red with it removed).
- `run_python_analysis` writer instructions now state the memory limit and the per-image pixel limit (from config).

### Verified
Red-team 25/25 on real containers, 16/16 plants red, no leftover container; unit 1095 passed (4 = SI-107); pip-audit of
all 17 packages in `raica-pysandbox:1`: none known (positive control flagged). Smoke through NewX's real path, one run
per prompt: chart 3/3, figures correct 3/3 for the reading chosen.

### Migration
`min_host_available_mb` is added to a site's config at start-up. P3 must size `memory` / `min_host_available_mb` for
production's headroom.
