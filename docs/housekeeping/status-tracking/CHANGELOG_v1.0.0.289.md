# CHANGELOG v1.0.0.289 — provider switching becomes one self-verifying command

**Date:** 2026-08-16 · **Against:** v1.0.0.288 · **Closes:** SI-057

## What went wrong, and why this exists

The Ollama→DeepInfra migration was done by hand-editing `llm_config.yaml` instead of running
the configurator that already existed for exactly this job. The result:

- **v1.0.0.288** fixed 2 lanes left behind (arbitrator, vision) — SI-056.
- **This release** found **6 MORE**, all still broken at that point:
  `deep_research.engine.model`, `.heavy_model`, `convergence.shadow_classifier`,
  `convergence.intent_classifier`, `code_generation.selected_model`, `.classification_model`.
  Every one carried an Ollama `name:cloud` slug while **inheriting** the DeepInfra endpoint.
  Verified: `deepseek-v4-flash:cloud` → **HTTP 404 "does not exist"**.

So Deep Research, the authoritative intent classifier, and code generation were all dead —
and `doctor` printed **"✓ Every active lane's model matches its endpoint."**

**Cost:** a night of debugging and a paid 40-minute benchmark run against a config where six
lanes 404'd on every call. A single lane check takes **11 seconds**.

## Root cause of the blindness (SI-057)

`_ENDPOINT_MODEL_PREFIXES` had no entry for `api.deepinfra.com`, so a DeepInfra endpoint
matched no host rule, fell past the Ollama-only branch (`'11434' in endpoint`), and returned
"no problem". Stated now as a provider-agnostic invariant instead of a per-vendor row, so a
NEW provider is covered the day it is added:

- Ollama → `name:tag` (a colon, never a slash)
- remote → `vendor/model` (a slash)

## Changes

### 1. Configurator — exhaustive and honest
- `_lane_mismatch` catches the mirror case: an Ollama `name:tag` on ANY remote endpoint.
  `doctor` went from "✓ all clear" to correctly reporting all 6 broken lanes.
- `convert` no longer trusts a `/models` **listing** to decide a model is unserved. On a
  catalog miss it now **INVOKES** the model (`_model_answers_on`), because a listing is
  evidence in neither direction — this repo recorded that lesson in 2026-08-05 and the
  converter was still repeating it. It had been blocking a valid conversion by declaring
  `meta-llama/Llama-3.2-90B-Vision-Instruct` NOT SERVED; it answers normally.
  A 404/410 means unserved; 402/429/400 mean the slug exists and was rejected for an
  unrelated reason.

### 2. NEW `tests/integration/test_all_lanes_live.py` — one file, every lane, real prompts
Not a reachability check. Each lane must return something only a WORKING model produces:

| probe | lanes | assertion |
|---|---|---|
| `probe_chat` | primary, deep_research ×2, convergence ×2, code_generation ×2 | solves 17+25, "42" must appear |
| `probe_tools` | tool_calling, gather_gate | must emit a structured `tool_call` naming the offered tool |
| `probe_json` | arbitrator | must emit parseable JSON with the requested key |
| `probe_vision` | vision + fallback | must name red/blue shapes **AND read the word SEVEN** (OCR) |

Lane inventory comes from the configurator's own `_discover_lanes`, so a lane added to
`llm_config.yaml` is covered automatically and cannot be silently skipped. Runs in ~11 s.
Exit 0 = all lanes valid, 1 = at least one broken. `--json` for machine consumption.

### 3. Verification is MANDATORY after every switch
`convert` (and `convert --revert` — a revert is a switch) now always runs, unskippable by
any flag:
1. **Consistency** — no lane may still resolve to the old provider, and no lane's model may
   contradict the endpoint it now resolves to.
2. **Live lanes** — the suite above, called for real.

Then it reports plainly:
- `SUCCESS — conversion happened and ALL 11 lanes now run on <provider>.`
- `FAILURE — …` naming which lanes are still on the old provider, which have an unservable
  model, and which returned no valid result, plus the revert command.

`--no-verify` now only skips the PRE-write probe; it cannot skip this.

### 4. Tier-0 gate widened
`test_lane_transport_consistency.py` had its own hand-rolled inventory that read each block's
OWN base_url — so it missed every INHERITING lane, i.e. exactly where the 6 defects lived. It
now reuses the configurator's discovery, so gate / `lanes` / `doctor` / `convert` share ONE
inventory and cannot disagree.

## The command

```
./config_server_cli.py convert --to <provider> --yes
```

That is the whole procedure. Do not hand-edit `llm_config.yaml` to change providers.

## Verification

- **Ran the real conversion:** 14 lanes converted, consistency ✓, **ALL 11 LANES LIVE**.
  The six 404-ing lanes are fixed — by the tool, not by hand.
- **Falsified, not just passed.** Injecting one left-behind lane makes the gate report
  `✗ MODEL/ENDPOINT MISMATCH` *and* `LANE SUITE FAILED — 1/11`, ending in `FAILURE`.
  Exit codes discriminate: **1 broken / 0 good** (CI-usable).
- The widened Tier-0 gate fails on an injected INHERITED-lane defect — the class the previous
  version missed — and passes when restored.
- Tier-0 **10/10**, unit **552 passed** (4 pre-existing unchanged), version sync 5/5.

## Still open

SI-052 (no output-size guard), SI-053 (latent reference form), SI-054 (flaky smoke gate),
SI-055 (Tier-1 self-throttles — still blocks capturing a baseline).
