# CHANGELOG v1.0.0.140

**Date:** 2026-07-06
**Previous:** v1.0.0.139 (content-quality gate — shadow)
**Theme:** **Ollama model-retirement sweep (2026-07).** Ollama is retiring a batch of cloud models; this swaps
every retiring model RAICA references to a verified-available replacement. **No core path was affected** — the
production hot paths already ran on non-retiring models.

---

## Context

Ollama retirement notice (2026-07) + recommended alternatives, cross-referenced against every model RAICA
uses. Each replacement was **verified live** on the Ollama cloud (`127.0.0.1:11434`) before swapping —
availability, and for the vision fallback, actual image capability.

## Core paths were already safe (unchanged)

`primary=deepseek-v4-pro` · `tool_calling`/`arbitrator=glm-5.2` · `DR engine=deepseek-v4-flash`/`-pro` ·
`intent`/`research` classifiers=`deepseek-v4-flash` · `classification_model=gpt-oss:120b` ·
`vision primary=kimi-k2.7-code` — **none retiring.**

## Swaps (all replacements verified available on the cloud)

**`config/llm_config.yaml`:**
| Where | Retiring | → Replacement |
|---|---|---|
| vision `fallback_model` | `gemma3:27b-cloud` | **`gemma4:31b-cloud`** (vision-verified: correctly described a test image) |
| fallback chain ×2 | `qwen3-coder:480b-cloud` | `qwen3.5:397b-cloud` |
| fallback chain | `deepseek-v3.1:671b-cloud` | `deepseek-v4-flash:cloud` |
| catalog `glm-4.7` | `glm-4.7:cloud` | `glm-5.2:cloud` |
| catalog `deepseek-v3` | `deepseek-v3.1:671b-cloud` | `deepseek-v4-flash:cloud` |
| catalog `qwen-coder` | `qwen3-coder:480b-cloud` | `qwen3.5:397b-cloud` |
| catalog `qwen3-coder-next` | `qwen3-coder-next:cloud` | `qwen3.5:397b-cloud` |
| catalog `ministral-3:14b` | `ministral-3:14b-cloud` | **removed** (no cloud equivalent) |

**`config/agents_config.yaml`:** coding-agent verification `glm-4.7:cloud` → `glm-5.2:cloud`.

**Tests:** batch-swapped `deepseek-v3.1:671b-cloud` → `deepseek-v4-flash:cloud` (65 refs across ~20 files) and
one `gemma3:4b` → `gemma4:31b-cloud`, so the suite keeps running post-retirement.

Catalog **keys** (e.g. `glm-4.7`, `deepseek-v3`, `qwen3-coder-next`) are KEPT (only their model values changed)
so a client selecting a preset by name still resolves — a transparent upgrade; each swap is documented inline.

## Notes

- Ollama cloud naming: `model:cloud` for un-tagged (`glm-5.2:cloud`, `minimax-m3:cloud`) vs `model:SIZEtag-cloud`
  for size-tagged (`gemma4:31b-cloud`, `qwen3.5:397b-cloud`). `minimax-m3:cloud` IS available but not needed
  (RAICA doesn't use its predecessors gemini-3-flash-preview / minimax-m2.1).

## Dependencies / breaking changes / migration

None. Config-only swaps to verified-available models. Deploy: `git pull` + restart.
