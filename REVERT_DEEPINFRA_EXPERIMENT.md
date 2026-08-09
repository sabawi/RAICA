# ⚠️ ACTIVE EXPERIMENT — RAICA is fully converted to DeepInfra

**Started:** 2026-08-09 · **Version:** v1.0.0.241 · **Status:** RUNNING ON LOCAL
**Purpose:** keep NewX bots serving while the Ollama-cloud weekly quota is exhausted
(SI-010), and gather the B-side data for the A/B in
`docs/PROVIDER_AB_TEST_PLAN.md`.

> Delete this file only once the revert below has been applied and verified.

## Reverting — one command

`config_server_cli.py convert` now handles this. It supersedes the manual
line-by-line instructions this file used to carry.

```bash
cd /home/sabawi/Development/RAICA
./config_server_cli.py convert --revert     # shows a table, asks to confirm
./stop_complete.sh && ./start_complete.sh
rm REVERT_DEEPINFRA_EXPERIMENT.md
```

`--revert` reads the inline `# CONVERTED -> deepinfra (was <original>)` tags that
`convert` wrote on every changed line, so it needs **no external backup** and the
round-trip is byte-identical (verified: 36 converted → 36 reverted → same md5).

Add `--yes` to skip the confirmation prompt.

## What is currently converted

36 lines / 11 active lanes, all **same-model** mappings — a provider change must not
change which model runs:

| lane | DeepInfra (now) | Ollama (reverts to) |
|---|---|---|
| `llm.primary` | `deepseek-ai/DeepSeek-V4-Pro` | `deepseek-v4-pro:cloud` |
| `llm.tool_calling` | `zai-org/GLM-5.2` | `glm-5.2:cloud` |
| `arbitrator` | `zai-org/GLM-5.2` | `glm-5.2:cloud` |
| `vision` | `MiniMaxAI/MiniMax-M3` | `minimax-m3:cloud` |
| `vision.fallback_model` | `moonshotai/Kimi-K2.6` | `kimi-k2.6:cloud` |
| `deep_research.engine.model` | `deepseek-ai/DeepSeek-V4-Flash` | `deepseek-v4-flash:cloud` |
| `deep_research.engine.heavy_model` | `deepseek-ai/DeepSeek-V4-Pro` | `deepseek-v4-pro:cloud` |
| `convergence.intent_classifier` | `deepseek-ai/DeepSeek-V4-Flash` | `deepseek-v4-flash:cloud` |
| `convergence.shadow_classifier` | `deepseek-ai/DeepSeek-V4-Flash` | `deepseek-v4-flash:cloud` |
| `code_generation.selected_model` | `deepseek-ai/DeepSeek-V4-Pro` | `deepseek-v4-pro:cloud` |
| `code_generation.classification_model` | `openai/gpt-oss-120b` | `gpt-oss:120b-cloud` |

Plus 6 inert lines (presets / fallback / provider defaults) naming the same models,
and the transport keys (`type`, `base_url`, `api_key`) on each converted lane.

**Not converted:** the `providers:` definition blocks — they define each provider and
must stay intact or `--revert` becomes impossible.

## Verify the revert

```bash
./config_server_cli.py doctor                       # lanes consistent with endpoints
grep -c "# CONVERTED" config/llm_config.yaml        # must be 0
curl -s localhost:5000/health
```

## ⚠️ Do NOT commit the experiment config

`config/llm_config.yaml` is tracked. Committing it while converted would push a
DeepInfra-only configuration to the repo and, on `git pull`, to production. Check
`git status` before any commit while this file exists.

## Cost

Every lane bills DeepInfra per call. Measured on 2026-08-09: **~$0.35 for one full DR
run** (3 rounds, 24 evidence items, 94 URLs, multi-pass synthesis), of which the DR
heavy lane was ~$0.24. Simple non-DR queries are ~$0.01–0.02. Session total was
**~$0.97 of the $5.00 float**. The usage page LAGS — treat a reading as a floor.

## Known behaviour while converted

- `✂️ TRUNCATED` on `loop.assess_max_tokens` / `verification.max_tokens` should no
  longer appear — both caps were raised in v1.0.0.240. If they reappear, raise them
  further and note it in SI-015.
- `/health` reports `"ollama":"healthy"` regardless: that check hits `/api/tags`, a
  LISTING, which succeeds even while every Ollama inference call is 429. Ignore it as
  a signal while the quota is exhausted.

## Next

`docs/PROVIDER_AB_TEST_PLAN.md` — the A/B to run once the Ollama quota resets.
Reverting is part of that procedure (side A), so do not revert ad hoc without
reading it first.
