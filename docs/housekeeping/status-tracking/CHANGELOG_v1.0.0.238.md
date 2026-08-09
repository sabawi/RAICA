# CHANGELOG — v1.0.0.238 (2026-08-09)

**Theme:** arbitrator `max_tokens` becomes config-driven and is raised to a
**derived** 4096 — plan step **4.3** of
`docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md`.

This is the change that actually **fixes** the arbitrator truncation that
v1.0.0.237 made visible. **.236 / .237 must not be deployed without it.**

---

## 1. The dead knob

`LLMManager.call_arbitrator` built its kwargs with `'max_tokens': 1024` as a
**literal**. Providers resolve the parameter as:

```python
kwargs.get('max_tokens', self.get_max_tokens())
```

so a literal kwarg **always outranks** `llm_config.yaml`. The configured
`arbitrator.config.max_tokens` was dead — raising it changed nothing.

That is the worst kind of knob: one that *looks* adjustable and is not. An
operator responding to truncation by raising the YAML value would have seen no
effect and concluded the model was at fault.

**Fix:** `manager.py` now reads `self.arbitrator_provider.get_max_tokens()`, and
logs the resolved value so the effective cap is visible in the log rather than
inferred from source.

`temperature` and `stream` remain literal **deliberately** (plan D2): both are
inert today, and changing temperature would alter arbitration behaviour — out of
scope for a no-regression change.

## 2. The value: 4096, derived

The arbitrator must emit a **complete** `tasks[]` JSON, one entry per executed
tool. Truncated, it is unparseable — the lane fails wholesale rather than
degrading.

Measured requirement (DeepInfra, real system prompt):
`477 + 131n` (gpt-oss-120b) · `577 + 160n` (GLM-5.2)

| batch | gpt-oss | GLM-5.2 | vs old 1024 |
|---|---|---|---|
| 3 | 739 | 897 | ok |
| **6** *(observed production peak)* | **1097** | **1419** | **both EXCEED** |
| 12 | 1918 | 2337 | both exceed |

Production batch distribution (`logs/archive`): 2×10, 3×5, 4×1, 5×2, 6×1.
**4096 covers batch 28 (gpt-oss) / batch 22 (GLM) — 3.7× the observed peak.**

Headroom matters because batch size is **unbounded in code**
(`fastapi_server_complete.py:5293` zips over all `tools_called`). And the error is
asymmetric: too low = total lane failure; too high = **free**, since billing is on
actual `completion_tokens`, not on the cap.

**Not covered:** a `reasoning_effort=xhigh` tail — one measured run consumed
>8000 tokens. **No fixed cap covers that**; that is what truncation detection
(v1.0.0.237) is for. `reasoning_effort` is unreachable in RAICA today — no
provider forwards it.

## 3. Verification

**The falsification test.** The same harness that previously measured GLM-5.2 at
**0% complete JSON at batch 6** was re-run at 4096, 3 runs per batch:

| batch | 1024 (before) | 4096 (after) |
|---|---|---|
| 1 / 2 | 100% / 100% | 100% / 100% |
| **4** | GLM **50%** | **100%** |
| **6** | GLM **0%** | **100%** |
| 8 | *(not reached)* | **100%** |

Both models, all batches, all runs: complete JSON **and** the correct number of
`tasks[]` entries.

**Unit tests:** `tests/unit/test_arbitrator_max_tokens_from_config.py` — 5 tests,
**2 FAIL on pre-4.3 code** (verified by reverting the hunk). One asserts the
*shipped config value* clears the measured peak-6 requirement, not merely that the
plumbing works — a plumbing-only test would pass with `max_tokens: 100`. Another
guards that an explicit caller kwarg still overrides config, since that ordering
is intentional.

Full unit suite 14/14. Tier-0 9/9.

## 4. Scope

No lane repointed. No model changed. No prompt altered. DeepInfra still dormant.

## 5. Remaining before deploy

- **4.4** qwen `system_prompt` parity (same defect as SI-014; qwen is on no lane)
- **4.5** parameter-parity contract test
- **4.1** E2E verification on the real Ollama path — blocked on the SI-010 quota
  reset. **Deploy gate.**

## 6. Dependencies

None.
