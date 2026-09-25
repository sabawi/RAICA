# CHANGELOG v1.0.0.326

**Date:** 2026-09-25
**Theme:** tool calling moves from glm-5.3 to deepseek-v4-pro — same accuracy, a fraction of the output

## Config (owner decision)

| Where | Before | After |
|---|---|---|
| `llm.tool_calling` | glm-5.3:cloud | **deepseek-v4-pro:cloud** |
| `code_generation.model_presets` | `glm-5.3` → glm-5.3:cloud | `deepseek-v4-pro` → deepseek-v4-pro:cloud |
| `code_generation.providers.ollama.model` | glm-5.3:cloud | **deepseek-v4-pro:cloud** |

glm-5.3-flash lanes (arbitrator, vision, agents verification) are unchanged — a different model, not part of
the evaluation. Aliases: `deepseek_v4pro_toolcall` (new, active), `glm_toolcall_ollama` (glm-5.3) and
`glm52_toolcall_alt` (glm-5.2) kept as switchable alternatives.

Edited as targeted line changes, not `config_server_cli.py set`: `set` saves with `yaml.dump`, which would
strip every comment from `llm_config.yaml`. Validated with `doctor` (clean) and `test_all_lanes_live.py`
(11/11).

## Evidence

`tests/integration/run_tool_model_eval_live.py` (new): 14 real requests through `/v1` with the full tool
catalogue, per-request `tools_calling_model`, scoring required tools, precision, answer completeness
(numbers checked against independently computed ground truth), tokens, latency, and override leaks. Aborts
on a provider usage-limit reply — the model account is shared with production.

- glm-5.3 vs deepseek-v4.1-flash, 14 cases × 3: answers 37/42 each; flash REJECTED — it skipped the
  calculator and got compound interest wrong in 2/3 runs.
- deepseek-v4-pro on the 4 discriminating cases × 3 (vs glm-5.3's rows on the same cases): answers 9/12
  and tools 9/12 each; compound interest 3/3 vs 2/3; median 38 s vs 96 s; ~620 vs ~8,300 output
  tokens per request.
- Post-change, configured lane (no override): compound interest via `compute` correct (29 s), primes via
  `sandboxed_executor` correct (21 s).

## Known, not changed here

- `compute` rejects constant-only expressions when `data` is empty (SI-096) — hurts any tool model.
- Some path ignores the per-request `tools_calling_model` (seen as stray calls to the configured model).

## Breaking changes / migration

None.
