# RUNBOOK — GLM-5.2 vs DeepSeek-V4-Flash, benchmarked on Ollama

**Created:** 2026-08-16 · **Against:** v1.0.0.292
**Why Ollama:** DeepInfra funds are nearly exhausted (>$5 spent reaching a benchmarkable
state). Two Tier-1 runs on DeepInfra would blow the remaining budget. Ollama has no per-call
cost, so both arms run free once the weekly quota resets.

**Goal:** decide whether DeepSeek-V4-Flash is a functional + performance equivalent for
GLM-5.2. If it is, switch on DeepInfra and realise the measured **9.4× input-token saving**
($0.7509 → $0.0801 per 1M input tokens).

---

## Preconditions

- [ ] Ollama weekly quota reset (was exhausted 2026-08-16 ~07:00; resets ~11h later)
      Check: `curl -s -m 30 http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"glm-5.2:cloud","messages":[{"role":"user","content":"Say OK"}],"max_tokens":8}'`
      Must NOT contain `weekly usage limit`.
- [x] Ollama serves every needed model (verified 2026-08-16, local catalog):
      `glm-5.2:cloud`, `deepseek-v4-flash:cloud`, `deepseek-v4-pro:cloud`,
      `minimax-m3:cloud`, `kimi-k2.6:cloud`
- [x] `convert --to ollama` resolves 11/11 lanes (8 `same`, 3 `MAPPED`)

---

## Sequence

### 1. Convert to Ollama (self-verifying)

```bash
./config_server_cli.py convert --to ollama --yes
```

Must end `SUCCESS — conversion happened and ALL 11 lanes now run on ollama.`
If it ends FAILURE, STOP and read which lanes failed — do not benchmark a broken config.

```bash
./stop_complete.sh && sleep 10 && ./start_complete.sh
python tests/integration/test_all_lanes_live.py     # ~11s, must be ALL 11 LANES LIVE
```

### 2. Arm A — incumbent GLM-5.2

```bash
python tests/benchmark/run_benchmark.py --tier 1
cp tests/benchmark/scorecard.json tests/benchmark/scorecard_ARM_glm.json
```

Check `THROTTLE BY SCENARIO` in the output. If the suite reports **INCONCLUSIVE**, the run
could not measure — fix the volume (the per-scenario numbers say which scenario) and re-run
before treating any of it as a result.

### 3. Swap ONLY the variable under test

GLM-5.2 occupies **two** lanes, and `tool_calling.gather_gate` inherits the tool lane:

```bash
./config_server_cli.py set --alias <flash_ollama_alias> --as tool_calling
./config_server_cli.py set --alias <flash_ollama_alias> --as arbitrator
./config_server_cli.py doctor          # must be clean
python tests/integration/test_all_lanes_live.py
```

Create the alias first if absent:
```bash
./config_server_cli.py add --alias flash_ollama --provider ollama \
    --model deepseek-v4-flash:cloud --description "DeepSeek-V4-Flash on Ollama (A/B vs GLM-5.2)"
```

**Nothing else may change between the arms.** Same build, same scenarios, same repeats.

### 4. Arm B — DeepSeek-V4-Flash

```bash
python tests/benchmark/run_benchmark.py --tier 1
cp tests/benchmark/scorecard.json tests/benchmark/scorecard_ARM_flash.json
```

### 5. Compare the two arms directly

Compare `scorecard_ARM_glm.json` vs `scorecard_ARM_flash.json` metric by metric.

**Do NOT use `--update-baseline` for either arm.** `baseline.json` is the DeepInfra
regression reference; an Ollama-served run is a different system and would corrupt it. This
exercise is an **A/B between two scorecards**, not a rebaselining.

---

## What this proves — and what it does NOT

**Proves:** GLM-5.2 vs DeepSeek-V4-Flash on identical scenarios, *as served by Ollama*.

**Does NOT prove** they are equivalent on DeepInfra — though the gap is now much smaller
than it was, and the specific hazard is CLOSED.

**CORRECTION (2026-08-16):** an earlier draft of this runbook cited GLM-5.2's reasoning
tokens on DeepInfra as an OPEN risk. That is wrong — it was fixed in v1.0.0.285 and the fix
is live. Verified by inspecting the actual wire payload for the tool lane:

```
lane config think: False
ON THE WIRE     -> {'max_tokens': 8192, 'chat_template_kwargs': {'enable_thinking': False}}
```

So reasoning is suppressed on DeepInfra exactly as `think: false` does on Ollama — the two
transports now agree on both the reasoning switch and the output budget, which is the whole
point of `llm_providers/param_map.py`.

What remains is ordinary prudence, not a known defect: a vendor can still differ in
tokenizer, sampling defaults or served weights, and no config table can rule that out. That
is why the closing check below exists — it is cheap insurance, not a fix for something
outstanding.

**Cheap closing check (well under one cent), after Flash wins on Ollama:**

```bash
./config_server_cli.py convert --to deepinfra --yes    # runs the lane suite automatically
```

Plus 1–3 real E2E prompts through `/v1`. That targets the transport difference specifically
without paying for a second full Tier-1.

**Also note:** the vision lanes are `MAPPED` on Ollama (`minimax-m3` / `kimi-k2.6`) rather
than the DeepInfra Qwen3-VL / Llama-3.2-90B. Vision is not the variable under test, but S3's
numbers are therefore not comparable to a DeepInfra run.

**Round-trip is lossy** through MAPPED lanes (SI-058): returning to DeepInfra will restore
`deepseek-v4-pro` unpinned and MiniMax/Kimi vision rather than the `-0813` pin and Qwen3-VL.
The originals are preserved in each line's `(was ...)` tag — use `convert --revert`, or
re-set those three lanes explicitly.
