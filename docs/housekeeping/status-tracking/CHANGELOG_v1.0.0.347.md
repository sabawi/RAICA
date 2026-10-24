# CHANGELOG v1.0.0.347 — 2026-10-24

## `run_python_analysis` — write a program, run it in the sandbox, answer from it (phase P1; OFF)

Owner request 2026-10-24: when no ready tool fits but code can solve it, write the program, run it and answer from
its results and chart. Design and P1 results: `docs/DESIGN_run_python_analysis.md` (§11).

### Added
- `user_tools/run_python_analysis_tool.py` — `task` → `writer_model` (deepseek-v4-pro) writes one program → the P0
  gVisor sandbox runs it → one repair attempt with the error → printed results, the program, and `[[chart:…]]`
  markers for images this tool re-encoded and published (never a marker the program printed). Refuses unless
  `user_tools.run_python_analysis.enabled` is true. Not on any bot's whitelist.
- Config: `writer_provider`, `writer_model`, `writer_fallback: false` (no paid fallback for a public bot),
  `writer_max_tokens`, `max_attempts`.
- `tests/unit/test_run_python_analysis_tool.py` (9; writer and sandbox are fail-closed stand-ins, no model calls).

### Fixed
- `utils/tool_output_reference.describe_reference`: text containing a small table was described as ONLY that table,
  so the gather gate and second-round selector lost everything else in it (here: a program's results and its chart
  marker, hidden behind a "table" made of three lines of source code). A table that is less than half of the text is
  described as before and followed by the text. Guard: `TestTableInsideLargerText` (fails on the old code).
- `utils/py_sandbox`: images re-encoded as PNG (what `publish_chart` uploads), still from decoded pixels.

### Logged
- SI-109 (gate verdict never reaches the selector), SI-110 (CodeGenLLMClient ignores `selected_model`, walks paid
  fallbacks, drops `system_prompt` on Ollama — may affect the coding agent).

### Verified (local, real NewX path, 9 runs)
Chart in 9/9 answers; figures correct in 9/9 against independent results (ball, Lotka-Volterra, solar sail for the
Sun-facing reading). Unit suite: 1087 passed; the 4 failures are the pre-existing SI-107 set. Red-team suite 25/25.

### Migration
None. New keys are added to a site's config at start-up; the tool stays OFF.
