# CHANGELOG — v1.0.0.236 (2026-08-09)

**Theme:** add DeepInfra as a selectable LLM provider (dormant), and retire three dead
model slugs found by an invocation-based audit.

---

## 1. New provider: DeepInfra (DORMANT — nothing routes here yet)

DeepInfra serves an OpenAI-compatible API, so it needs **no new provider module** —
`deepinfra` maps onto the existing `OpenAIProvider`, exactly as `openrouter` already
does. Same `/chat/completions` path, same `Authorization: Bearer` scheme.

### Changed

| File | Change |
|---|---|
| `llm_providers/factory.py` | `deepinfra` → `OpenAIProvider` in `_import_provider`, plus both hardcoded provider lists (`get_available_providers`, `_auto_register_providers`) |
| `config/llm_config.yaml` | new `llm.providers.deepinfra` block: `base_url`, `${DEEPINFRA_API_KEY}`, retries, 5 reference model slugs |
| `config_server_cli.py` | `PROVIDER_DEFAULTS`, `API_KEY_ENV_VARS`, `_ENDPOINT_KEY_ENV`, the lane-write provider list, and the `--provider` argparse choices |
| `config/model_aliases.json` | 3 new dormant aliases: `deepinfra_deepseek`, `deepinfra_glm`, `deepinfra_cheap` |
| `.env.example` | `DEEPINFRA_API_KEY` placeholder + no-free-tier note |
| `docs/CLI_MODEL_MANAGEMENT.md` | DeepInfra provider reference; `--provider` list updated |

### Dormancy

Declaring a provider block does **not** activate it. A lane uses DeepInfra only when its
`type:` says `deepinfra`. Verified: `llm.primary` remains `ollama/deepseek-v4-pro:cloud`,
`llm.tool_calling` remains `openai`, the arbitrator is untouched, and `deepinfra` is absent
from `llm.fallback.order`.

### Status — VERIFIED 2026-08-09 (account funded $5.00)

Exercised through RAICA's own code (`ConfigLoader` → factory → `OpenAIProvider` →
manager, **14/14**) and through the real `/v1/chat/completions` endpoint with the
production payload (**33 tool schemas, 25KB prompt, 37K-char context**), **0 errors**.

| Lane | Result |
|---|---|
| primary — completion + SSE streaming | PASS |
| tool_calling — selection **and execution** (`get_stock_and_company_data` → NVDA $223.96) | PASS |
| arbitrator / code_generation — strict JSON | PASS (4/4 models parse) |
| vision — colour, OCR, chart reading | PASS (Qwen3-VL, Llama-4-Maverick) |
| parallel tool calls | PASS (GLM-5.2 emits 2; manager normalises both) |

**Capability caveats — measured, not assumed:**
- `reasoning_effort` is **accepted but largely inert**. DeepSeek-V3.1 completion tokens
  across low/medium/high/**xhigh**: 233/234/232/241. gpt-oss-120b varies only at the low
  end (39/171/166/166). **`xhigh` never errors** — it is silently accepted, so absence of
  an error must NOT be read as the effort level taking effect.
- `reasoning_content` is model-dependent: GLM-5.2 1097 chars, gpt-oss-120b 159,
  **DeepSeek-V3.1 returns `None`** and leaks chain-of-thought into `content` instead.
- Llama-3.1-8B-Turbo **fails multi-tool selection** (answers in prose). Fine as a cheap
  smoke model, unusable as a tool lane.

### Cost — verified against the DeepInfra usage page

Session total **$0.0726** of the $5.00 float. Per-model, from the vendor's usage page:

| Model | in | cached in | out | cost | share |
|---|---|---|---|---|---|
| **zai-org/GLM-5.2** (tool lane) | 62,699 | 73,728 | 4,882 | **$0.06906** | **95.1%** |
| deepseek-ai/DeepSeek-V3.1 (primary) | 6,486 | 180 | 1,261 | $0.00284 | 3.9% |
| Llama-4-Maverick / gpt-oss-120b / Qwen3-VL / Llama-3.1-8B | — | — | — | $0.00072 | 1.0% |

**The tool lane is 95% of spend** — driven by tool-schema bulk (~12,400 input tokens per
call for 33 schemas), not by answer length. Prompt caching is ACTIVE on GLM-5.2 and saved
**$0.045** (cached input $0.14/M vs $0.75/M).

**Estimation lesson:** a pre-check derived from logged token counts came in at $0.0504 —
**30% under** the true $0.0726. Per-call `usage.estimated_cost` was exact (verified
token-for-token on 3 models); the error was entirely in the calls that were *estimated*,
because (a) prompt caching was not known to be active and (b) tool-schema size was
underestimated 2.8×. **RAICA's logged "~N tokens" is chars÷4, not real tokenization** —
do not cost from it.

### Status — original pre-funding note (superseded above)

The key authenticates (`GET /models` → 200, 182 models) and all 14 probed slugs are valid,
but **DeepInfra has no free tier**: inference returns `HTTP 402 "You need positive balance
to do inference"`. Tool calling, streaming, think flags and effort levels are **UNTESTED**.
A 402 proves only that slug and credentials are real.

Useful property discovered: **404 vs 402 discriminates**, so model names can be validated
at zero cost (`404 model_not_found` = bad slug, `402` = valid slug awaiting balance).

---

## 2. Retired model slugs replaced (SI-008)

Every slug we hold credentials for was **invoked** with a 1-token generation — a catalog
listing is evidence in neither direction (SI-005 lesson). 13 probed: **8 LIVE, 2 DEAD,
3 inconclusive** (402/429 — never recorded as dead).

| Dead slug | Sites | Evidence | Replacement |
|---|---|---|---|
| `deepseek/deepseek-r1:free` | `llm_config.yaml:116,119` | 404 — *"use this slug instead: deepseek/deepseek-r1"* | `deepseek/deepseek-r1`; free lane → `openai/gpt-oss-20b:free` |
| `gemini-2.0-flash` | `llm_config.yaml:733,779,806` | 404 — *"no longer available"* | `gemini-flash-latest` |
| `deepseek-v3.1:671b-cloud` | alias `deepseek_ollama_cloud` | 410 — *"retired at 2026-07-15"* | `deepseek-v4-flash:cloud` |

**Not changed, deliberately:** all Ollama-cloud slugs (account is 429 weekly-limited →
unverifiable, see SI-010) and `claude-*` in `code_generation` (`ANTHROPIC_API_KEY` unset).
Replacing an unverifiable slug with another unverifiable slug is not a fix.

---

## 3. Configuration / secrets

- `OPENROUTER_API_KEY` **copied** from `~/.bashrc` into `.env` so the server no longer
  depends on shell inheritance (a systemd/cron launch inherits no `~/.bashrc`). The
  `~/.bashrc` export is **left intact** — other tools on the dev machine use it.
- `DEEPINFRA_API_KEY` added to `.env`.
- `.env` remains gitignored, untracked, mode `600`. No key appears in any tracked file.

---

## 3b. Provider bug fixes (`llm_providers/openai.py`)

Two defects found while evaluating DeepInfra. Both are **provider-layer**, not
DeepInfra-specific, and both failed silently.

### SI-013 — `tool_calls: null` crashed the tool lane on every correct abstention
`message.get('tool_calls', [])` — a dict default fires only when the key is **absent**.
OpenAI omits it; other OpenAI-compatible vendors send it present-and-null, so the
default never applied and the formatting loop iterated `None` → `TypeError`. It fired
precisely when a model correctly declined to call a tool. `content` had the same flaw.
Fixed with `or []` / `or ''`.

### SI-014 — `generate_stream` silently discarded the system prompt  ⚠️ production-affecting
`generate_stream` built `messages` from the user turn ALONE, dropping the
`system_prompt` callers pass (`manager.py:315`). The **arbitrator lane is
`type: openai`**, so RAICA's arbitrator has been running without its 13,802-char
JSON schema spec — on the normal Ollama-proxy path, not only under test.

Measured effect on arbitrator quality (6 cases × 3 runs, DeepInfra):

| | pure-JSON | schema | correct verdict |
|---|---|---|---|
| before | gpt-oss 89% / GLM **0%** | **0%** | **0%** |
| after | **100%** / **100%** | **100%** | **100%** |

`ollama.py:69-70` received this same fix in v1.0.2.101; the OpenAI path never did, and
`generate_tools` handled it correctly all along — which is exactly why the gap stayed
invisible.

> **⚠️ KNOWN INTERACTION — read before deploying.** Fixing SI-014 makes the arbitrator
> emit the full nested schema, which is LONGER than the ad-hoc JSON it produced while
> blind. That output now exceeds the hardcoded `max_tokens: 1024`
> (`manager.py:317`) at batch sizes ≥4. **Fixing SI-014 is what EXPOSES the
> truncation.** The remediation is scoped in
> `docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md` §4.2–4.3 and lands in v1.0.0.237.
> Until then the arbitrator is *more correct but token-capped* — better than blind,
> not yet fully fixed.

**Tests:** `tests/unit/test_openai_provider_null_tool_calls.py` — 4 named tests;
**2 FAIL on pre-fix code** (verified by temporarily reverting), all 4 pass after.

## 3c. Model evaluation (no lane changed)

DeepInfra was used to compare candidates on RAICA's **real** 33-tool payload
(`tool_manager.get_tools_definitions()`, 37,981 chars) and real tool system prompt,
16 cases × 3 runs, scored on selection accuracy and stability:

| lane | gpt-oss-120b | GLM-5.2 | outcome |
|---|---|---|---|
| tool_calling | 29.2% | **89.6%** | **keep GLM-5.2** — not close |
| arbitrator | 100% | 100% | **deferred** — see plan §6 D3 |

gpt-oss-120b returned a *date/time* tool for a weather query and scored 0% on four
near-duplicate disambiguations. **No lane was repointed in this release.**

## 4. Issues logged

| ID | Priority | Summary |
|---|---|---|
| **SI-011** | P1 | `config_server_cli.py set` destroys **all** comments in `llm_config.yaml` (PyYAML round-trip). Blocks the planned quick-switch feature, which calls `set` repeatedly. |
| **SI-010** | P1 | Entire Ollama-cloud stack 429 weekly-limited — primary, tool_calling, DR, code-gen, both vision lanes. Also blocks liveness verification. |
| **SI-009** | P2 | `doctor --probe` reports a FALSE 400 for any alias whose key is still `${VAR}` — it sends no auth header. Produced a wrong "mis-declared gemini aliases" note; both aliases are LIVE. |
| **SI-012** | P3 | An UNSET `${VAR}` key stays literal and truthy, so the fail-fast guard misses it → confusing vendor 401. An EMPTY value fails correctly. Pre-existing, all providers. |
| **SI-014** | P1 → **FIXED** | `generate_stream` discarded the system prompt; arbitrator ran blind. Production-affecting, not DeepInfra-specific. |
| **SI-013** | P1 → **FIXED** | `tool_calls: null` → `TypeError` on every correct abstention. |
| **SI-012** | P3 | An UNSET `${VAR}` key stays literal and truthy, so the fail-fast guard misses it → confusing vendor 401. Pre-existing, all providers. |
| **SI-008** | resolved | The retired-slug audit above. |

---

## 5. Verification

- **Adversarial audit:** 8 attack hypotheses (dormancy, credential leak, unset-var, merge
  order, tool gate, provider identity, registration drift, config integrity) written
  **before** re-reading the implementation — **28/28 assertions pass**.
- Factory constructs `deepinfra` → `OpenAIProvider` with the DeepInfra `base_url`;
  auto-registers at import.
- Provider-block → lane merge verified, including that a lane **overrides** provider defaults.
- Real-path CLI test: `add` → `show` → `set` → restore. `set` correctly writes
  `base_url`/`api_key` into the lane — and revealed SI-011.
- `pytest tests/integration/test_version_sync.py` → **5 passed**.
- Config parses and loads through `utils.config_loader.ConfigLoader`; `doctor` clean.

**Docs:** updated `README.md` (5 version surfaces), `docs/CLI_MODEL_MANAGEMENT.md`
(DeepInfra reference, `--provider` list, SI-011 warning on `set`), `.env.example`,
`SUSPECTED_ISSUES.md`.

## 6. Migration

None required. The change is additive and dormant. To activate once funded:

```bash
cp config/llm_config.yaml /tmp/llm_config.bak      # SI-011 — set() eats comments
./config_server_cli.py set --alias deepinfra_glm --as tool_calling
./stop_complete.sh && ./start_complete.sh
```

## 7. Dependencies

No new dependencies.
