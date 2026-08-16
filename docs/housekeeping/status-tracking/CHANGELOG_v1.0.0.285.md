# CHANGELOG v1.0.0.285 — provider parameter translation (the "seamless" switch was not)

**Date:** 2026-08-15 · **Against:** v1.0.0.284
**Class:** the mechanism named in `docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md` §0 —
*a value declared in one layer is silently ignored in another.*

## The failure, as the user saw it

A USGS earthquake query (`fetch → compute stats → plot the distribution`) came back with
**no data, no chart and no table**, and an answer asserting *"2026 has not occurred"* —
on 2026-08-15. Ground truth: the URL returns **HTTP 200, 225 events, in 0.92 s**.

Zero tools ran. `lookup_website`, `compute` and `plot_data` were all whitelisted.

## Root cause

The tool-calling lane had been moved from Ollama to DeepInfra. A provider switch is a
TRANSPORT change and was meant to preserve the model and its limits. It preserved
neither, and nothing reported it:

| | Ollama (before) | DeepInfra (after) |
|---|---|---|
| reasoning | `think: false` sent → **OFF** | **no reasoning parameter existed on this path** → ON |
| output budget | reads `num_predict` only; caller's `max_tokens=4096` **silently dropped** → default **16,384** | `max_tokens=4096` honoured |
| truncation visibility | **none** (`done_reason` never read) | detected (v1.0.0.237) |

A 16,384-token budget with reasoning OFF became a **4,096-token budget with reasoning
ON**. GLM-5.2 spent the budget on `reasoning_content` and hit `finish_reason=length`
**before emitting any tool call — twice in one request** (the initial selection and the
`NO-TOOLS RE-PROMPT` rescue, which ran at the identical cap and so failed identically).

Measured on DeepInfra: GLM-5.2 at `max_tokens=64` with no flag returns
`content=''`, `reasoning=224 chars`. With reasoning suppressed: `content='OK'`.

**Why the parity contract stayed green:** `tests/unit/test_provider_parameter_parity.py`
listed `("think","openai")` as a KNOWN_GAP — *"Ollama-only thinking-mode flag"*. That is
false (DeepInfra accepts it) and, more importantly, **declaring a gap does not make it
harmless**. The entry made a real defect look intentional.

## Changes

### 1. `llm_providers/param_map.py` — NEW: canonical parameter → per-provider wire table
One lookup table mapping `max_output_tokens` / `context_window_size` /
`reasoning_enabled` to each provider's spelling, or an explicit `Unsupported(reason)`.
Providers translate through it instead of each reaching into `kwargs` with its own
dialect. **An inexpressible parameter is reported once, never dropped silently.**

### 2. `openai.py` — honours `think`, cap from config
`_wire_params()` defaults `think` to **False, matching ollama.py's long-standing
default**, and maps it to `chat_template_kwargs.enable_thinking`. Chosen over
`reasoning_effort: none` (both measured working on GLM-5.2 *and* DeepSeek-V4-Pro)
because an unknown chat-template key is ignored rather than rejected by other vendors.

### 3. `ollama.py` — honours `max_tokens`, detects truncation
`max_tokens` and `num_predict` are one intent in two dialects; precedence is explicit
(`num_predict` > `max_tokens` > config). Added `_warn_if_truncated()` on `done_reason`,
mirroring the OpenAI guard — the asymmetry made the *instrumented* transport look
buggier than the silent one.

### 4. `fastapi_server_complete.py` — two hardcoded caps removed
`max_tokens=4096` literals at the tool-selection call and the no-tools re-prompt
outranked config (PARITY §2.2). Removed; the lane's configured cap governs.

### 5. `config/llm_config.yaml` — `tool_calling` lane
`max_tokens: 2048 → 8192` (derived: with reasoning off, one tool call measures 28–40
completion tokens; error is asymmetric — too low = zero tool calls, too high = free).
Added `think: false`. Annotated `context_window_size` as inert on this transport.

## Verification

**Unit:** `tests/unit/test_provider_param_translation.py` — 10 tests, **7 fail on
pre-fix code** (verified by reverting both providers and re-running), 10/10 after.
Full suite **527 passed**, 4 pre-existing failures unchanged. Version sync 5/5.

**E2E, real path, 3 runs** (identical payload, provider and models):

| | before (v1.0.0.284) | after, 3 runs |
|---|---|---|
| `✂️ TRUNCATED` events | 2 per request | **0** |
| tool calls selected | **0** | **3/3 runs** |
| real data fetched (n=225) | no | **3/3** |
| markdown table | none | **3/3** (15/16/7 rows) |
| gather-gate | never ran (0 lines) | **ran 3/3**, 2–3 rounds |
| chart | none | none — see below |

Statistics now computed from the real catalogue: mean **5.87**, median **5.80**,
std **0.41**, min 5.50, range 2.30 (ground truth: 5.8828 / 5.8000 / 0.4218 / 5.50 / 2.30).

## Charting verified end-to-end — the bridge works, the deliverable still does not

NewX started (PROD/HTTPS :9876, 5 workers), `charts.enabled: true`, secrets confirmed matching
(sha256 identical on both sides). 3 further E2E runs:

| layer | result |
|---|---|
| `/internal/chart-upload` reachable + guarded | ✅ 403 without secret |
| RAICA→NewX bridge (direct `publish_chart`) | ✅ minted a URL |
| that URL serves an image | ✅ **HTTP 200, image/jpeg, 640×480** |
| `plot_data` publishes during E2E | ✅ **3/3 runs** (225 / 24 / 24 points) |
| those 3 URLs serve images | ✅ **200, image/jpeg, 42–66 KB** |
| **marker reaches the user's answer** | ❌ **0/3** → **SI-051** |
| statistics computed | ❌ 58 `UFuncTypeError` → **SI-050** |

**Charting was NOT the only remaining gate.** Making it work exposed the next two, exactly as
4.2 did in the parity plan. The chart chain is ALLOWED → SELECTED → INVOKED → PRODUCED →
SURVIVES SYNTHESIS → RENDERS; links 1-4 and 6 are now proven, and **link 5 is failing**.

## Still open

- **No chart, for an unrelated reason — NewX was not running.** Corrected from an earlier
  draft of this file, which blamed `charts.enabled: false` in the YAML. That was wrong:
  `.env` carries `RAICA_CHARTS_ENABLED=true` and **`.env` overrides the YAML**
  (`utils/chart_publisher.py:32-36`), so charts were enabled the whole time. The actual
  log line is `chart_publisher: upload error: HTTPSConnectionPool(host='localhost',
  port=9876) ... NewConnectionError` — a dead host, not a disabled feature. `plot_data`
  drew the chart, publishing failed, and it **correctly refused to fabricate a marker**
  (SI-038 fail-closed). Resolved in the charting verification below.
- **Mean/std differ in the 2nd decimal** (5.87 vs 5.8828, 0.41 vs 0.4218) while min and
  range match exactly. Unexplained; likely a subset or rounding in the compute chain.
  Worth an SI entry rather than a guess.
- The gate stopped at `max_rounds`/`wall_clock` still wanting the plot — correct
  behaviour given publishing was unavailable, but the round budget deserves review once
  charts are live.
