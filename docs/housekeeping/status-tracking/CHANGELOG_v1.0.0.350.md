# CHANGELOG v1.0.0.350 — 2026-10-24

## `run_python_analysis` — the program checks itself; adjustable things are optimised (P3, ON for Ask)

Owner test on local (NewX post 8349, solar sail, 300 × 300 m "adjustable" sail): the conclusion was right, but the
program's orbit fell into the Sun at 3.68 years (speed −503,000 km/s) where the true orbit is a closed 1.00–3.22 AU
ellipse, and the answer called the crash an "artifact". The orbit chart was also scaled to 120 AU.

### Changed (writer instructions — `WRITER_POLICY`)
- **Self-check:** conserved quantities must stay conserved, values physically possible, the integration must reach
  its end; on failure the program writes why to stderr and exits 1, so the existing repair attempt runs. Never
  report, explain away or plot a failed result.
- **Charts:** paths fill most of the chart; only reference objects within that view are drawn.
- **Decision variables:** anything the user calls adjustable, controllable, steerable or choosable is searched or
  optimised over (including over time), reported next to the fixed case; no "impossible" before that search fails.
- The task the selector writes is logged (`🧪 run_python_analysis: task (N chars): …`, first 600 chars).

### Verified (local, real NewX path, owner's prompt)
Orbit correct 6/6 after the fix (closed ellipse 1.0–3.2 AU, period ~3.8 yr); the fixed-sail conclusion correct 6/6;
47–196 s (one earlier run 642 s with 10 programs). Controls (ball, a news question) unchanged.

### Known limitation (SI-111)
0 of 15 runs computed a STEERED sail, which escapes (~4 yr to escape velocity, ~65 yr to 120 AU in an independent
simulation). Four instruction changes did not move it: the model believes a Sun-facing sail is the best an adjustable
sail can do and states "it can never escape". Follow-up proposed: a reviewer pass that checks an "impossible"
conclusion against the user's words.

### Tests
`tests/unit/test_run_python_analysis_tool.py`: the self-check and decision-variable rules must be in the writer's
message (the self-check assertion fails with the rule removed). Unit suite 1097 passed (4 = SI-107); tool smoke passed.
