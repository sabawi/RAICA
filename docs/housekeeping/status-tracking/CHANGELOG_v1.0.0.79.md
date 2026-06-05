# CHANGELOG v1.0.0.79

**Date:** 2026-06-04
**Previous:** v1.0.0.78 (log-rotation fix, unreleased intermediate)
**Trigger:** Deep research kept failing at the synthesis stage with intermittent upstream
`Ollama API error: 500 (Internal Server Error)`. Retries (3×120s) could not ride out the failures.
Live log evidence finally pinned the root cause and drove a load-based model split.

---

## Root cause (fully evidenced, not assumed)

A live NewX `@Ask` deep-research run was watched end-to-end in `server_complete.log`:

- Every deep-research LLM call ran on **`deepseek-v4-flash:cloud`** (the DR engine model, injected by
  the `_dr_generate_stream` wrapper). Pro was never used in the pipeline.
- The pipeline reached **synthesis** — the single call that assembles the *entire* evidence pile into
  the paper. That prompt was **596,317 chars** (~149K tokens).
- The synthesis call returned **HTTP 500 in ~12s** (an infra-side reject, not a timeout). All **three**
  retries (11:33, 11:35, 11:37) returned 500 with distinct `ref:` ids → the run failed.
- The call *just before* synthesis (139,076 chars) **succeeded**. So it is not our parameters, not the
  context window (we use ~149K of the model's ~1M), and not a token limit — it is **flash:cloud
  reliability on the large synthesis payload specifically**.

## Fix 1 — Load-based model split (the "break up the one-size-fits-all" design)

Deep research is not one-size-fits-all: the high-frequency *small* calls (gate, planner, roster, grade,
verify — all <~140K chars) run great on the fast/cheap light model; only the single *large* synthesis
call overwhelms the light cloud endpoint. So we now route by **payload size**, not by node name.

**`config/llm_config.yaml` → `deep_research.engine`:**
```yaml
model: deepseek-v4-flash:cloud           # LIGHT — default for all small DR calls
heavy_model: deepseek-v4-pro:cloud       # HEAVY — large-payload calls (e.g. synthesis)
heavy_threshold_chars: 250000            # prompt chars at/above which -> heavy_model
```

**`fastapi_server_complete.py` → `_dr_generate_stream` wrapper:** measures `len(prompt)` and selects
the model per call:
- `prompt_len <  heavy_threshold_chars` → `model` (light/flash)
- `prompt_len >= heavy_threshold_chars` → `heavy_model` (heavy/pro), logged as
  `🔀 DR heavy route: prompt_len=… → deepseek-v4-pro:cloud`

Routing is **purely load-driven** — a *small* synthesis (little evidence) still rides the light model;
it is not "synthesis always → pro." `null model` / `null heavy_model` / `threshold ≤ 0` disables that
tier (falls back to primary). No hardcoded model names or node-name special-casing (per project
directives — the threshold and both model names live entirely in config).

### Why chars, not tokens
The threshold is measured in characters (`len(prompt)`) deliberately: it is exact and dependency-free,
whereas counting real tokens would require running a tokenizer on every call (cost/latency) or
approximating anyway (~4 chars/token, so 250K chars ≈ ~62K tokens).

## Fix 2 — Log persistence across restarts (`start_complete.sh`)

`start_complete.sh` started the server with `> logs/server_complete.log`, which **truncated the log on
every restart** — destroying the 5xx evidence we needed to diagnose this very bug. The script now
rotates the existing log to `logs/archive/server_complete_<timestamp>.log` before starting fresh, and
keeps only the most recent 20 archives (bounded growth). The live `logs/server_complete.log` remains
the single log to monitor. This directly enabled the diagnosis above (the failed run's 2476-line log
was preserved instead of wiped).

## Verification (live, end-to-end — user-confirmed)

Re-ran the identical NewX `@Ask` deep-research query on v1.0.0.79:

| Metric | Before (flash only) | After (load-based split) |
|---|---|---|
| 5xx / retry / failure events | 3× HTTP 500 → total failure | **0** |
| Synthesis (664,820 chars) | 500-ed on every attempt | ✅ **112.8s** on pro (`🔀 DR heavy route`) |
| Verify (373,023 chars) | n/a (never reached) | ✅ 136.3s on pro |
| Grade (small) | — | stayed on flash (35.4s) — light tier working |
| Delivery | failed | ✅ `Email sent successfully via gmail` |
| Outcome | refusal/failure | ✅ **12-page PDF research paper delivered** (user-confirmed) |

Only the two genuinely heavy calls (>250K chars) routed to pro; everything else stayed on cheap/fast
flash — confirming the split behaves as designed.

## Files

- `config/llm_config.yaml` — `deep_research.engine`: add `heavy_model` + `heavy_threshold_chars`,
  reword `model` comment for the load-based split.
- `fastapi_server_complete.py` — `_dr_generate_stream` routes by `len(prompt)` vs threshold; logs
  `🔀 DR heavy route` on heavy selections.
- `start_complete.sh` — rotate `logs/server_complete.log` to `logs/archive/` (keep 20) before start.
- `version.py` (→ 1.0.0.79), `README.md` (badge/version → 1.0.0.79), this changelog.

## Notes / follow-ups

- `heavy_threshold_chars: 250000` cleanly separates synthesis-class payloads (596K–665K observed) from
  the next-biggest call (~139K). Tune in config if evidence volumes change.
- Pro is used only for the rare heavy call(s) per run, so its cost/latency and historical throttling
  exposure stay minimal while the reliability problem is solved.
