# CHANGELOG — v1.0.0.239 (2026-08-09)

**Theme:** close the last known parity gap, and make the whole class of defect
**testable** — plan steps **4.4** and **4.5** of
`docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md`.

**No lane repointed. No model changed. `qwen` is configured on no lane, so this
release changes nothing at runtime.**

---

## 4.4 — `qwen.py` dropped the system prompt in BOTH methods

The same defect as SI-014, and worse: `openai.py` at least handled `system_prompt`
in `generate_tools`, while `qwen.py` discarded it in **both** `generate_stream`
(:64) and `generate_tools` (:137), building `messages` from the user turn alone.

Fixed in both. Each now logs the system-prompt char count or `⚠️ NO SYSTEM
PROMPT`, so a future silent drop is visible rather than inferred.

**Not reachable today** — no lane uses qwen. Fixed anyway because leaving a known
landmine for whoever enables it later is not a decision worth deferring, and
because the contract test below would have failed otherwise.

## 4.5 — parameter-parity contract (`tests/unit/test_provider_parameter_parity.py`)

**This is the change that prevents recurrence.** SI-014 survived for months
because `ollama.py` was fixed in v1.0.2.101 and **nothing checked the other
providers**; `generate_tools` in the same class handled the parameter correctly,
so the gap was invisible from every angle a reviewer would look.

The parity table in the plan (§2.1) is now executable:

- **Required parameters** (`system_prompt`, `temperature`, `max_tokens`,
  `timeout`) must be consumed by **every** provider.
- **Optional gaps are allowed but must be DECLARED** in `KNOWN_GAPS` with a
  reason. `think` really is Ollama-only; `headers` really is OpenAI-specific.
  An *undeclared* gap fails. Closing a gap means deleting its entry, and a stale
  entry also fails — so the allow-list cannot rot into a blanket exemption.
- **`system_prompt` must reach the payload**, not merely be referenced. A
  provider that reads the kwarg and discards it fails.
- **A new provider module must be registered**, or the suite fails — which is
  exactly how `openai.py` escaped the v1.0.2.101 fix.

Static analysis by design: constructing a provider needs real credentials and has
side effects (`GeminiProvider.__init__` calls `genai.configure`), and this must
run offline in Tier-0.

## Verification

Both falsification directions were exercised:

| injected defect | result |
|---|---|
| revert the 4.4 qwen fix | **2 tests FAIL** — the reference check *and* the reaches-the-payload check |
| delete a `KNOWN_GAPS` entry | **1 test FAILS** — undeclared gap |
| restored | 49 passed |

Full unit suite **63 passed**. Tier-0 9/9.

## Current parity state

| parameter | ollama | openai | gemini | qwen |
|---|---|---|---|---|
| `system_prompt` | ✅ | ✅ *(.236)* | ✅ | ✅ **this release** |
| `temperature` / `max_tokens` / `timeout` | ✅ | ✅ | ✅ | ✅ |
| `context_window_size` | ✅ | declared gap | declared gap | declared gap |
| `think` | ✅ | declared gap | declared gap | declared gap |
| `reasoning_effort` | — | — | — | — |

`reasoning_effort` is consumed by **no** provider, so it is unreachable from
RAICA. Relevant to any future decision about effort levels: setting it in config
today would do nothing.

## Remaining before deploy

- **4.1** E2E verification on the real Ollama path — **deploy gate**, blocked on
  the SI-010 quota reset.
- A/B baseline (Ollama vs DeepInfra) once the quota returns, to settle production
  ceiling and cost estimates.

## Dependencies

None.
