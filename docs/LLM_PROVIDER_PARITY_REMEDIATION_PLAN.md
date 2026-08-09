# LLM Provider Parity — Remediation Plan

**Status:** PROPOSED — awaiting sign-off. **No code changes beyond what is already
uncommitted (§1) until approved.**
**Date:** 2026-08-09 · **Against:** v1.0.0.236 (uncommitted)
**Constraint set by the user:** *NO REGRESSION. Improvement only.*

---

## 0. Why this document exists

Four defects were found in one session, **one at a time**, each while verifying the
previous one. That is the sequential-patching antipattern: every step looked rigorous
and each fix was real, but the shared mechanism went unexamined. This plan stops the
hunt, names the mechanism, maps its full surface, and scopes the response.

**The mechanism, stated once:**

> A value declared in one layer is silently ignored or overridden in another layer,
> and nothing detects the discrepancy.

Every defect below is an instance. None throws an error; all degrade silently. That
is what made them survive — a loud failure would have been fixed months ago.

---

## 1. Current uncommitted state (must be accounted for before anything new)

This work is **already on disk, unverified end-to-end, and uncommitted**. It is the
baseline the plan builds on, not part of the plan.

| File | Change | Risk |
|---|---|---|
| `llm_providers/openai.py` | **(a)** `tool_calls`/`content` null-guard (SI-013) | LOW — strictly widens accepted input |
| `llm_providers/openai.py` | **(b)** `generate_stream` now sends `system_prompt` (SI-014) | **HIGH — behaviour change, see §4.1** |
| `llm_providers/factory.py` | `deepinfra` → `OpenAIProvider` | LOW — additive |
| `config/llm_config.yaml` | dormant `deepinfra` block; 3 retired slugs replaced | LOW — no lane repointed |
| `config/model_aliases.json` | 3 dormant aliases; 1 dead alias repointed | LOW — no lane repointed |
| `config_server_cli.py` | `deepinfra` in 5 CLI surfaces | LOW — additive |
| `.env` *(untracked)* | `DEEPINFRA_API_KEY`, `OPENROUTER_API_KEY` copied | LOW |
| `version.py`, `README.md` | 1.0.0.235 → 1.0.0.236 | LOW |
| `tests/unit/test_openai_provider_null_tool_calls.py` | 4 tests (2 fail pre-fix) | LOW — new |
| docs + `SUSPECTED_ISSUES.md` + changelog | SI-008..SI-014 | none |

**Decision required (D1):** commit this baseline first, or carry it into the plan's
first change-set? Recommendation: **commit first** — a large uncommitted pile is
itself a risk, and item (b) deserves an isolated, revertable commit.

---

## 2. Evidence map — the full surface

All rows measured, not inferred. Provider parity from source inspection; token
figures from DeepInfra `usage`; batch distribution from `logs/archive/*.log`.

### 2.1 Parameter parity — does the provider READ what callers pass?

| parameter | ollama | openai | gemini | qwen |
|---|---|---|---|---|
| `system_prompt` | yes | yes *(§1b)* | yes | **NO** |
| `context_window_size` | yes | **NO** | **NO** | **NO** |
| `num_predict` | yes | **NO** | **NO** | **NO** |
| `think` | yes | **NO** | **NO** | **NO** |
| `stream` | yes | yes | **NO** | **NO** |
| `retry_attempts` / `retry_delay` | **NO** | yes | **NO** | **NO** |
| `reasoning_effort` | **NO** | **NO** | **NO** | **NO** |

- `qwen.py` carries the **identical SI-014 defect**. Qwen is not in use today.
- `reasoning_effort` is unreachable from RAICA — no provider forwards it.

### 2.2 Hardcoded overrides that outrank config

Providers read `kwargs.get('x', self.get_x())`, so a literal kwarg **wins over
`llm_config.yaml`**.

| site | value | consequence |
|---|---|---|
| `manager.py:316` | `temperature: 0.1` | arbitrator temperature config is inert |
| `manager.py:317` | `max_tokens: 1024` | **arbitrator max_tokens config is inert** |
| `manager.py:318` | `stream: False` | inert — `generate_stream` always streams |
| `openai.py:200-201` | `0.1` / `2048` fallbacks | mask a missing config key |
| `ollama.py:195`, `qwen.py:142-143` | same | same |

### 2.3 Truncation is undetectable

`finish_reason` appears **only where RAICA writes it for clients** — never read.
A model cut off mid-JSON is indistinguishable from a model that failed to comply.

### 2.4 Measured token requirements (arbitrator)

`tokens(n) = base + marginal × (n−1)` — gpt-oss: 477 + 131n · GLM: 577 + 160n

| batch | gpt-oss | GLM-5.2 | vs cap 1024 |
|---|---|---|---|
| 3 | 739 | 897 | ok |
| **6** *(prod peak)* | **1097** | **1419** | **both EXCEED** |
| 12 | 1918 | 2337 | both exceed |

Production batch distribution (`logs/archive`): 2×10, 3×5, 4×1, 5×2, 6×1 — **peak 6**.
Batch size is **unbounded** in code (`fastapi_server_complete.py:5293`).

`reasoning_effort=xhigh` on gpt-oss-120b: 4 runs at 1711–2354 tokens, **plus one
run that consumed 8000 and was cut off**. Fat tail — no fixed cap is safe against it.

### 2.5 Dead config

`llm.providers.gemini.models.{pro,flash,stable_flash,stable_pro}`,
`llm.providers.deepinfra.models.cheap` — never read.

---

## 3. Explicit non-goals

To keep the blast radius small, this plan does **NOT**:

- change which model any lane uses (tool_calling stays GLM-5.2; arbitrator decision deferred to §6)
- activate DeepInfra on any lane
- refactor the provider class hierarchy
- touch `gemini.py` behaviour, or `qwen.py` beyond the parity fix
- fix `config_server_cli.py set` comment destruction (SI-011) — separate, already logged
- alter tool schemas, the tool catalogue, or prompts

---

## 4. Proposed changes

Ordered by risk. Each states its regression surface and how it is proven safe.

### 4.1 VERIFY the already-applied system-prompt fix — **highest risk item**

Not a new change; §1(b) is already on disk. It is listed first because it is the
only change that **alters what an already-working lane sends**.

- **What changed:** `generate_stream` now prepends a system message when one is passed.
- **Who is affected today:** the **arbitrator only** (`type: openai`). `llm.primary`
  is `ollama` (unaffected); `llm.tool_calling` uses `generate_tools`, which already
  handled system prompts.
- **Why it is an improvement, measured:** arbitrator verdict accuracy **0% → 100%**
  (schema compliance 0% → 100%) once the spec actually arrives.
- **Regression risk — the honest one:** it adds ~3,450 tokens of input to every
  arbitrator call, and the longer, correct schema output is what pushes GLM past
  `max_tokens` (§2.4). **Fixing SI-014 is what exposes the truncation.** They must
  ship together or the arbitrator gets worse, not better.
- **Verification before commit:**
  1. arbitrator E2E on the **real Ollama path** after quota reset (SI-010)
  2. confirm no lane exceeds its real context window
  3. confirm `llm.primary` output is byte-comparable (it must be — ollama path untouched)
- **Rollback:** revert one hunk in `openai.py`.

### 4.2 Detect truncation — the systemic guard  ✅ **DONE — v1.0.0.237**

> Shipped 2026-08-09. `_warn_if_truncated()` in `llm_providers/openai.py`, used by
> both request paths; `generate_tools` also returns `truncated: bool`.
> Tests: `tests/unit/test_openai_provider_truncation_detection.py` — 5 tests,
> **4 fail on pre-fix code**. Real-path proof: live GLM-5.2 call at batch 6 /
> `max_tokens=1024` emitted the warning and returned **0 chars** of content.
> Tier-0 9/9.


- **Change:** in `openai.py` (both methods) read `finish_reason`; if `length`, log an
  explicit warning naming model + token count, and surface it to the caller.
- **Why first among new work:** it converts every future cap mistake from silent
  corruption into a visible error. It is the only change here that makes the *next*
  bug of this class cheap to find.
- **Regression risk:** **none** — additive observation. It changes no payload and no
  return value on the success path.
- **Verification:** unit test with a mocked `finish_reason: length` asserting the
  warning fires; must FAIL on current code.

### 4.3 Make `max_tokens` config-driven, set 4096

- **Change:** `manager.py:317` stop hardcoding `1024`; read the arbitrator lane's
  configured `max_tokens`. Set `arbitrator.config.max_tokens: 4096` in YAML.
- **Rationale for 4096 (derived, not chosen):** covers batch **22** on the hungrier
  model — 3.7× the observed production peak of 6, with batch size unbounded in code.
  Error is asymmetric: too low = unparseable JSON = total lane failure; too high =
  **free**, because billing is on actual `completion_tokens`.
  **4096 does NOT cover the xhigh tail (§2.4)** — that is what 4.2 is for, and
  `reasoning_effort` is unreachable today anyway.
- **Regression risk:** LOW. Strictly raises a ceiling; no currently-succeeding call
  changes behaviour. Also removes a config/code contradiction.
- **Verification:** re-run the ceiling test at batch 1/2/4/6/8 for both models,
  ≥3 runs each; expect 100% complete JSON where 1024 previously truncated.
- **Open question (D2):** `temperature: 0.1` and `stream: False` at `manager.py:316,318`
  are inert the same way. Fix now or leave? Recommendation: **leave** — inert today,
  and changing temperature alters arbitration behaviour, which contradicts "no regression."

### 4.4 Close the qwen `system_prompt` gap

- **Change:** `qwen.py` — mirror the `openai.py` fix.
- **Regression risk:** **none in practice** — qwen is configured on no lane.
- **Why do it:** it is the same defect, already found; leaving it is knowingly
  shipping a landmine for whoever enables qwen.
- **Verification:** extend the parity test (4.5).

### 4.5 Parameter-parity contract test

- **Change:** one test asserting that for every provider, each parameter callers pass
  is actually consumed — the table in §2.1 becomes executable.
- **Regression risk:** none — test-only.
- **Value:** this is the change that prevents recurrence. SI-014 existed because
  `ollama.py` was fixed in v1.0.2.101 and nothing checked the others.
- **Scope note:** asserts **parity for parameters callers actually pass**. It does
  NOT demand every provider support every parameter — `think` is legitimately
  Ollama-only. Gaps are declared in an explicit allow-list with a reason, so an
  *undeclared* gap fails.

### 4.6 Remove dead config (optional, cosmetic)

Delete the 5 unread keys (§2.5) or comment them as informational. **Recommendation:
comment, not delete** — they document intended models and removing them loses that.

---

## 5. Sequencing

```
D1: commit the §1 baseline (isolated commit for the SI-014 hunk)
      │
4.2  truncation detection      ── additive, zero risk, do first
      │
4.3  max_tokens config + 4096  ── needs 4.2 to prove it worked
      │
4.4  qwen parity  +  4.5 contract test
      │
4.1  E2E verification on the REAL path (needs Ollama quota reset)
      │
    commit v1.0.0.237  →  deploy only after 4.1 passes
```

4.2 before 4.3 is deliberate: raise the cap **after** truncation is observable, so
the fix can be proven rather than assumed.

---

## 6. Deferred decisions

| id | question | recommendation |
|---|---|---|
| D1 | commit §1 baseline separately? | **yes** |
| D2 | fix inert `temperature`/`stream` at `manager.py:316,318`? | **no** — inert; changing temperature alters behaviour |
| D3 | move arbitrator to gpt-oss-120b? | **defer** — parity on verdicts (100% vs 100%), but GLM showed 2 quality defects (never uses the `{{PRIMARY_LLM_RESPONSE}}` placeholder → silently abbreviates long content; unparseable JSON at 800 words). Decide **after** 4.3, on a re-run at the corrected cap — the earlier comparison measured both against a cap neither could meet. |
| D4 | raise `max_tokens` beyond 4096? | **no** — 4096 covers batch 22; the xhigh tail needs 4.2, not a bigger number |

**Tool lane is NOT deferred: keep GLM-5.2.** 89.6% vs 29.2% on RAICA's real 33-tool
payload. Not a close call.

---

## 7. Regression protection

1. **Nothing repoints a lane.** Every change is a guard, a ceiling raise, or a test.
2. **The one behaviour change (4.1) is already isolated** to a lane measured as
   0% → 100%.
3. **Every fix gets a test that FAILS on pre-fix code** — the standard already met by
   `tests/unit/test_openai_provider_null_tool_calls.py` (2 of 4 fail on revert).
4. **E2E on the real path before deploy**, not just unit tests (SI-010 gates this).
5. **Each change is independently revertable** — no fix depends on another's internals.
