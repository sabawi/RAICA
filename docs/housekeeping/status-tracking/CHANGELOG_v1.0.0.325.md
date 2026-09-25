# CHANGELOG v1.0.0.325

**Date:** 2026-09-25
**Theme:** glm-5.2 kept as a switchable tool-calling alternative; tool-model cost measured

## Config

- `config/model_aliases.json`: new alias `glm52_toolcall_alt` (ollama, `glm-5.2:cloud`, tool-lane params:
  temp 0.1, max_tokens 8192, timeout 600), added with `config_server_cli.py add`. No lane changes —
  tool_calling stays `glm-5.3:cloud` (owner decision). To switch:
  `./config_server_cli.py set --alias glm52_toolcall_alt --as tool_calling`, then run
  `tests/integration/test_all_lanes_live.py`.

## Findings (SUSPECTED_ISSUES.md SI-099)

Three-way A/B on the S1 news-citation prompt, only the tool model varied, 3 rotated runs each:
glm-5.3 median 59 s, 2–3 requests, 1.5k–3.2k output tokens; glm-5.2 55 s, 2 requests, ~120 output
tokens; deepseek-v4.1-flash 35 s, 2 requests, ~185 output tokens but fewer citations (median 12 vs
15–16). glm-5.3's reasoning volume (12–25× glm-5.2's output) and extra rounds can offset a lower
per-token price. deepseek-v4.1-flash is the candidate third option, pending the 33-tool selection and
compute-combo checks.

## Monitoring

The RAICA model-lane watcher ships in NewX v1.0.0.263 (`scripts/lanes_watch.py`, daily); it runs
this repo's `tests/integration/test_all_lanes_live.py --json` and RAICA `/health`.

## Breaking changes / migration

None.
