# CHANGELOG v1.0.0.131

**Date:** 2026-06-17
**Previous:** v1.0.0.130 (delivered .html parity)
**Theme:** **URGENT — vision restored.** Ollama retired the configured vision model, breaking all image
input to `@Ask`. Swapped to a current cloud vision model and wired a real fallback so a future retirement
self-heals instead of breaking image handling.

---

## Symptom (urgent, live)

`@Ask` given an image (post 4999) replied that it saw no image. Image OCR/description was dead for every
user.

## Root cause (external — NOT from recent changes)

RAICA's **vision** model `qwen3-vl:235b-cloud` (`config/llm_config.yaml` `vision.config.model`) was
**RETIRED by Ollama on 2026-06-16** → every image call returns **HTTP 410 (Gone)**. The image reached
RAICA and the vision call fired (`🖼️ Image processing exception: qwen3-vl:235b was retired … status 410`),
but the model is gone. This is the **vision** model — entirely separate from the glm-5.2 **tool-calling**
swap (v1.0.0.127). Compounding it: the configured `fallback_model` was **never actually used** — on a
vision error the code returned an error string and never retried the fallback.

## Fix

- **`config/llm_config.yaml`** (`vision.config`):
  - `model`: `qwen3-vl:235b-cloud` → **`kimi-k2.7-code:cloud`** — verified vision-capable on a real photo
    (~5s, accurate). (Note: `glm-5.2:cloud` is NOT vision-capable — returns HTTP 400 on an image.)
  - `fallback_model`: `qwen2.5vl:3b` → **`gemma3:27b-cloud`** — a verified vision-capable CLOUD backup in a
    DIFFERENT model family. Both vision models MUST be cloud: the live server has **no GPU**, so a local
    vision model (qwen2.5vl:3b) thrashes the CPU and is not viable.
- **`user_tools/image_to_text.py`** — wired the fallback for real: when the primary vision model fails
  (retired/410, 4xx, timeout, any exception), it now **retries once with `fallback_model`** and returns
  that result; only if BOTH fail does it return an error. This is exactly what auto-survives a future
  model retirement like today's.

## Verified

- **End-to-end (local, real image through RAICA `/v1`)**: vision config = `kimi-k2.7-code:cloud`, processed
  in 12.4s, accurate description (blue border, red circle, "RAICA TEST" text). No fallback needed.
- **Unit** `tests/integration/test_vision_fallback.py`: primary-fails→backup-runs→backup result returned;
  both-fail→clear error naming both models; primary-succeeds→backup NOT called. All green.

## Files
- `config/llm_config.yaml`, `user_tools/image_to_text.py`,
  `tests/integration/test_vision_fallback.py` (new), `version.py` (→ 1.0.0.131), `README.md`, this changelog.
