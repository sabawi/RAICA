# CHANGELOG v1.0.0.343 — 2026-10-24

## Plotting a formula works; the arbitrator's retry stays inside the bot's whitelist and keeps what it made

Reported by the owner: NewX post 8834 (production, 2026-10-22) — `@Ask solve \[ u_tt = c^2 ∇²u \] and plot the
solution for a set of typical u values` — answered with numbers and no chart; the chart appeared only after
"were you unable to plot it?". SI-108.

### Fixed — a formula could not be plotted reliably (`user_tools/compute_tool.py`, `user_tools/plot_data_tool.py`)
- **Cause (production log, 2026-10-22 21:02):** both tool descriptions said they work on data "ALREADY retrieved";
  `plot_data` added "If you have no data to pass, do not call this". A formula has nothing to fetch, so the model
  pointed `compute`'s `data` at `lookup_website#1` (never ran) and then at `compute#1` (failed), used up the
  gather-gate rounds, and found the self-contained form (`np.linspace` inside each expression) only in the last
  round — too late for `plot_data`. Locally, one baseline run never called `compute` at all: the gate asked for
  `plot_data` and the model made no call.
- **Change (policy text only, no code path):** `compute` says it also GENERATES values — `data` omitted, the grid
  built inside each expression, names do not carry between expressions, never point `data` at a tool that has not
  run or failed. `plot_data` says it draws values `compute` generated, referenced by expression, with `source` naming
  the formula and `url` the page it came from (the `url` field says the same; `DatasetSeries` requires it non-empty).

### Fixed — the arbitrator's retry ran a tool the bot may not use, and lost its chart (`fastapi_server_complete.py`)
- **Whitelist:** the retry offered ALL tools (35; Ask allows 10) and did not filter what came back, so a failed
  `compute` was "corrected" into `analytical_visualizer`, and it ran. New `_retry_permitted_tools()`: the request's
  whitelist + the tools that failed (they were permitted when first dispatched — the `social_media_wordpress` retry
  the old comment protects still runs) + the system-injected clock. Offered tools and returned calls are both
  filtered against it; a dropped call logs `🔒 BLOCKED off-whitelist tool call(s) [retry]`. Unrestricted clients
  (no whitelist) are unchanged. The other regeneration path already filtered its offered tools.
- **Lost result:** `_merge_corrected_results` matched corrections to failed tools BY NAME, so a successful call of a
  different tool matched nothing and was discarded — chart included — while the loop reported success. It is now
  kept as an entry of its own; the failed entry stays, so the answer can state both.

### Verified
- Real path (NewX `build_context_messages` + `call_raica` with Ask.yaml → local RAICA): before — chart in 1 of 3
  runs (one more lost to the retry, one never tried `compute`); after — **3 of 3** with a chart, no `compute` errors,
  no retries, 18–24 s (was 20–64 s). The retry path itself was not reached in the 3 runs (nothing failed); its
  whitelist is set and awaited in the same coroutine (`generate_stream`), and it is covered by unit tests.
- `tests/unit/test_retry_substitute_tool.py` (6): each of 3 planted defects (no filter on returned calls, no
  substitute kept, an extra tool in the permitted set) turns it red.
- `tests/unit` 1076 passed, 4 failed — the 4 pre-existing SI-107 failures, unchanged. Tool smoke PASSED.
  `run_mu_e2e_verify.py` exit 0.

### Not changed / known
- In the 3 verified answers the model labelled the two travelling components "½sin(…)" while plotting them at full
  amplitude (the sum curve is correct). A labelling slip by the answering model, not the pipeline.

### Migration
None. No configuration keys added or removed.
