# CHANGELOG v1.0.0.290 — the converter was single-use; a full-circle test proved it

**Date:** 2026-08-16 · **Against:** v1.0.0.289 · **Closes:** SI-058

## Why this exists

The user asked for a full-circle switch test before any model change:
Ollama → DeepInfra → OpenRouter → Ollama. The first attempt failed on every arm, and the
failure was in the converter, not the providers.

## SI-058 — a converted line could never be converted again

`_write_conversion` skipped any line already carrying the `# CONVERTED` tag:

```python
if self._CONVERT_TAG in line:
    continue
```

So each line was **convert-once-only**. Every subsequent provider switch skipped everything
the previous one had touched. Lanes converted per arm decayed:

| arm | lanes converted (before fix) |
|---|---|
| → ollama | 9 |
| → deepinfra | 2 |
| → openrouter | 4 |
| → ollama | 0 |
| → deepinfra | 0 |

Result: the config was left permanently half on each provider — `primary` on Ollama while
`deep_research`, `convergence` and `code_generation` kept DeepInfra slugs and inherited the
Ollama endpoint. **That is SI-057 re-created by the very tool meant to prevent it**, and only
a round trip could expose it: a single forward conversion always looks perfect.

**Fixed:** tagged lines are re-converted. The tag preserves the ORIGINAL value in `(was ...)`
— never the intermediate — so `--revert` returns to where the config started rather than to
whichever provider happened to be mid-loop. Transport keys (`type`/`base_url`/`api_key`)
carried the same tag and were skipped the same way; they now strip the tag, run the normal
matchers, and re-attach the preserved original.

## Other fixes found on the way

- **Ollama catalog was unreachable.** `_provider_catalog` requested `{base}/models`, but
  Ollama's base is `:11434` and its OpenAI-compatible listing is at `/v1/models`.
  `convert --to ollama` failed outright with "Cannot reach the ollama model catalog", and the
  invocation check would have called every Ollama model UNSERVED. Verified: `:11434/models`
  → 404, `:11434/v1/models` → 200 (40 models). Added `_openai_compat_base()`, used by both.
- **NEW `_MODEL_MAP`** — explicit, admin-sanctioned cross-provider substitutions, consulted
  ONLY when no exact equivalent exists. Printed as **`MAPPED — model CHANGES`**, never as
  `same`, so a deliberate model change can never be skimmed as an identity conversion.
  Entries (each with its reason inline): Llama-3.2-90B-Vision → `google/gemini-2.5-flash`
  (openrouter) / `kimi-k2.6:cloud` (ollama); Qwen3-VL-235B → `minimax-m3:cloud` (ollama);
  DeepSeek-V4-Pro-0813 → `deepseek-v4-pro:cloud` (ollama, date-pin has no counterpart).

## Full-circle result (after the fix)

| arm | converted | consistency problems | live lanes | exit |
|---|---|---|---|---|
| setup → ollama | 23 | **0** | FAILED 11/11 | 1 |
| **(a) ollama → deepinfra** | 25 | **0** | **ALL 11 LIVE** | **0** |
| **(b) deepinfra → openrouter** | 26 | **0** | FAILED 11/11 | 1 |
| **(c) openrouter → ollama** | 25 | **0** | FAILED 11/11 | 1 |
| final → deepinfra | 29 | **0** | **ALL 11 LIVE** | **0** |

**No lane was ever stranded on the old provider on any arm** — requirement met.

The live-lane failures are EXPECTED and external, not conversion faults. Only two causes
appear in the logs:
- Ollama: `HTTP 429 you (seedhom) have reached your weekly usage limit`
- OpenRouter: `HTTP 402 Insufficient credits. This account never purchased...`

DeepInfra passed **11/11 twice**, proving the circle returns to a fully working state.

## Known limitation — round-trips through a MAPPED lane are LOSSY

A → B → A does not restore A's original model where a substitution occurred, because the map
is one-way and the return trip maps the SUBSTITUTE back. Observed across the circle:

| lane | before | after |
|---|---|---|
| primary | `DeepSeek-V4-Pro-0813` | `DeepSeek-V4-Pro` (pin lost) |
| vision | `Qwen/Qwen3-VL-235B` | `MiniMaxAI/MiniMax-M3` |
| vision fallback | `Llama-3.2-90B-Vision` | `moonshotai/Kimi-K2.6` |

All three drifted lanes were verified LIVE, so this is drift, not breakage — but it is drift.
The original is preserved in each line's `(was ...)` tag, so `convert --revert` recovers it.
Config was restored to the intended baseline after the test.

## Verification

Circle re-run end to end; `doctor` clean; Tier-0 lane gate passes; **ALL 11 LANES LIVE** on
the restored baseline (`DeepSeek-V4-Pro-0813`, Qwen3-VL vision).
