# CHANGELOG v1.0.0.324

**Date:** 2026-09-25
**Theme:** model refresh (owner decisions), a retired model replaced, and two vision fixes — the
vision step no longer invents figures (SI-097) and a model that cannot see the image is no longer
reported as a success (SI-098)

## Model changes (owner decisions, 2026-09-24/25)

| Lane | Before | After |
|---|---|---|
| tool_calling | glm-5.2:cloud | **glm-5.3:cloud** |
| arbitrator | glm-5.2:cloud | **glm-5.3-flash:cloud** |
| agents verification (`agents_config.yaml`) | glm-5.2:cloud | **glm-5.3-flash:cloud** |
| vision | minimax-m3:cloud | **glm-5.3-flash:cloud** |
| vision fallback | kimi-k2.6:cloud | **minimax-m3:cloud** |
| deep_research.engine.model, both convergence classifiers | deepseek-v4-flash:cloud | **deepseek-v4.1-flash:cloud** |
| code_generation presets | Kimi-k2.5 / glm-5.2 / qwen3.5:397b ×2 / deepseek-v4-flash | glm-5.3 / glm-5.3-flash / deepseek-v4.1-flash ×3 |
| code_generation Ollama default | kimi-k2.6:cloud | **glm-5.3:cloud** |
| code_generation fallback order | qwen3.5:397b ×2, deepseek-v4-flash | deepseek-v4.1-flash once (duplicates dropped) |

- **deepseek-v4-flash:cloud was RETIRED by Ollama at 2026-09-25 00:00 PDT** (HTTP 410). Deep Research's
  small-call model and both intent classifiers were dead from that moment, locally and on live, until
  this release. Caught by `test_all_lanes_live.py` during this release's gates.
- **Kimi-k2.5 was retired 2026-07-31**; its preset had silently fallen back to gpt-oss:120b since (SI-095).
- `config_server_cli.py` `_MODEL_MAP`: the Ollama vision entries now map to glm-5.3-flash / minimax-m3,
  so a future `convert --to ollama` cannot silently reintroduce kimi-k2.6.
- `model_aliases.json`: the glm/deepseek alias model values follow the lanes above.

## SI-097 — the vision step invented figures

An image containing only "Ticker: KO", with "look up its current price and how many shares $10,000
buys", produced a vision report containing a made-up price ("hypothetical price of $62.50 → 160
shares") that entered the evidence context.

- **Cause (falsified, not assumed):** three different models did it 3/3 each — a code/prompt issue. SI-016
  (v1.0.0.245) forwards the full user question to the vision model; nothing limited its scope.
- **Fix:** a SCOPE policy in `config/image_to_text_system_prompt.txt` (report only what is visible; never
  estimate or illustrate figures the image does not show; say when the request needs data the image does
  not contain) — and removed an inherited cap in `image_to_text.py` that silently replaced any system
  prompt of 500+ chars with a generic one-liner, which would have discarded the policy.
- **Measured:** fabricated price 3/3 → **0/3**; reading accuracy unchanged (OCR/shapes/chart 9/9 tool path,
  9/9 server); combo answers still correct 3/3.

## SI-098 — a blind vision model counted as a success

deepseek-v4.1-flash:cloud read images 27/27, then answered 12/12 "I can't see an image attached" (HTTP 200)
while glm-5.3-flash read the same bytes. That reply was returned as a SUCCESS, so the fallback never ran.

- **Fix:** OUTPUT CONTRACT — the vision model returns `{"image_received": bool, "report": str}`.
  `_report_from_reply` reads those fields (structural only; reuses `research.engine.extract_json_object`).
  `image_received:false`, or a reply without that field, is a failure → the fallback runs **once**.
- **Second shape of the same bug:** the OpenAI-compatible transport RETURNS `{"success": False}` instead of
  raising, so its failures never reached the fallback either. `_run` now treats any unsuccessful result as
  a primary failure.
- **Measured (real tool path):** blind primary + sighted fallback → primary rejected, fallback reads the
  text, 3/3. Dead primary + blind fallback → honest `success:false` 3/3 (was a blind "success").

## New tests

- `tests/unit/test_image_to_text_prompt.py` — the configured prompt reaches the model as written (2 tests;
  both fail on the pre-fix code).
- `tests/integration/test_vision_fallback.py` — +5 SI-098 cases mocking `ollama.chat` so the real reply
  parsing runs (all 5 fail on the pre-fix code, 3 original cases still pass).
- `tests/integration/run_model_sanity_live.py` — live model sanity suite: vision (each model, tool path,
  fallback branch, server), coding (generated code EXECUTED against asserts, per preset and per NewX bot,
  plus server write-and-run), and a multi-model combo; every case repeated, pass rates printed.

## Verification (local, before deploy)

- `test_all_lanes_live.py`: ALL 11 LANES LIVE. `config_server_cli.py doctor`: clean.
- `make smoke`: all 6 core tools return real content.
- `run_model_sanity_live.py --runs 3`: vision + combo ALL PASS (fallback minimax-m3 9/9 + 3/3); coding
  (previous run, same code) glm-5.3 preset 9/9, NewX bots 18/18, server write+execute 3/3.
- `tests/unit`: 980 passed, 4 failed — the same 4 fail on unmodified HEAD (pre-existing, SI-062 class).
- `tests/utilities/run_mu_e2e_verify.py`: exit 0, 5/5 stocks × 4 analyses, no tracebacks (chart upload
  refused locally only because the local NewX was not running).

## Open (see SUSPECTED_ISSUES.md)

- SI-096: glm-5.3's first `compute` call sometimes references a non-tabular tool output; recovered next
  round, answers correct.
- SI-098: deepseek-v4.1-flash is blind to images today — no longer in any vision lane; its text lanes are
  unaffected (verified).

## Breaking changes / migration

None. Config-only model changes plus the vision reply contract; no new dependencies, no DB changes.
