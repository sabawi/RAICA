# CHANGELOG v1.0.0.353 — 2026-10-25

## The program writer sees the user's own words; a chart check is built (off)

From NewX post 9091 (the owner's solar-sail request, re-run on prod after 1.0.0.352: same "it can never escape"
answer) and post 9088 (unreadable superimposed 3D charts).

### Changed — `run_python_analysis` gets the user's own request (SI-111)
The tool-calling model writes the task the program writer works from, and in 9091 it fixed the sail face-on, a
choice the user never made. RAICA now keeps the text of the request it is answering (`utils/request_context.py`, a
ContextVar set where `/v1/chat/completions` reads the last message) and the tool appends its last 4000 characters
to the task, fenced, with "the user's words win wherever the two differ".
- **Measured: no effect on the sail.** 3 real-path runs on deepseek-v4-pro: 0/3 computed a steered sail. 3 more with
  Ask's model switched to deepseek-v4.1-flash (writer still pro): 0/3 correct. See SI-111.
- Controls, real path: compound interest $6,847.26; the 9088 wave request 1 chart, no re-run.

### Changed — writer policy
- A check verifies the COMPUTATION, never the outcome the question hopes for; it is never a condition to exit on
  (a sail program asserted the expected answer and exited 1).
- Decide whether a quantity is conserved before checking it; a failed check is a failure, never a warning (9091's
  program failed its energy check and the answer explained it away).
- When a force's direction can be chosen, derive how its size and direction depend on the choice from how the force
  is produced; never assume a force can point anywhere at full strength.
- Tests: `test_the_users_own_words_reach_the_writer`, `test_no_request_text_leaves_the_task_alone`,
  `test_writer_is_told_not_to_assert_the_hoped_for_outcome`.

### Fixed — a doubled opening code fence leaked into the program
A reply starting with ```` ```python ```` twice left the second fence inside the extracted program (SyntaxError on
attempt 1 in 3/3 writer-only runs; not seen on prod). `extract_best_code_block`'s fallback strips leading and
trailing fence lines. Test: `test_a_doubled_opening_fence_does_not_leak_into_the_program`.

### Added, OFF — chart check (SI-115)
`utils/chart_check.py`: each computed chart is shown to the vision model before publishing; an unreadable chart is
redrawn with every earlier rejection quoted, at most `chart_redraws` (2) times; the last redraw is never checked
(no check→redraw cycle); any failure to get a verdict publishes as before.
- Detection agreed with a human reading 17/18. Rescue: a redraw made 1 of 5 flagged charts readable (7 real-path
  runs), at 1-2 extra writer calls each, so `chart_check: false` is the default (also the code default when the key
  is absent). `config_migrate` adds the two keys to an existing site config with these defaults.
- Tests: `tests/unit/test_chart_check.py` (11) — redraw published, cap and unchecked last redraw, history carried,
  fail-open on no verdict / exception / no charts, switch off, off when the key is absent.

Unit suite: 1146 passed, 4 failed — the same 4 fail on 1.0.0.352 (logged, SUSPECTED_ISSUES line ~119).
