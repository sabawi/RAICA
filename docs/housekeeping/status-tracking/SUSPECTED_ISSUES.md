# Suspected Issues Log

Per the global directive *"NEVER dismiss a possible bug without evidence — if busy, log it with a priority
call; clear it only on evidence or a verified fix."* Open items are things NOTICED but not yet confirmed
as bug-or-not. **Do not delete an item on a hunch** — resolve it with evidence (real bug filed/fixed, or
proven not-a-bug) and move it to Resolved with that evidence.

Priority: **P1** act now · **P2** investigate soon · **P3** watch / low-impact.

---

## Open

### SI-015 — Hardcoded `max_tokens` on JSON-returning DR calls, truncating into SILENT fallbacks  [P1 — CONFIRMED in production traffic]
- **Observed (2026-08-09, first real DR query after the full-DeepInfra conversion):** the
  v1.0.0.237 truncation detector fired within minutes, on a cap nobody knew existed:
  ```
  12:26:21  🔎 Round 1: dispatched 6 source(s), gathered 6 evidence item(s)
  12:27:32  ✂️ TRUNCATED by max_tokens: deepseek-ai/DeepSeek-V3.1 hit the 900-token output cap
  12:27:32  🧪 Gap-assessment failed (Expecting ',' delimiter: line 90 column 6 (char 3589))
            → treating as sufficient
  12:27:32  🔎 Round 2: dispatched 6 source(s), gathered 6 evidence item(s)
  ```
  3,589 chars ≈ 900 tokens exactly — the model was cut off mid-JSON.
- **The pattern (this is a CLASS, not one bug).** Three DR-critical calls share it:
  *hardcoded cap → `extract_json_object()` → `try/except` that degrades to a benign-looking
  fallback.* The request succeeds, the log reads reassuring, and capability is silently lost.

  | site | cap | what it decides | what truncation SILENTLY does |
  |---|---|---|---|
  | `research/pipeline.py:271` | 2000 | splits request into `research_request` / `deliverable_spec` / **`actions`** | falls back to `actions: []` — **every delivery action (email, PDF) is DROPPED**, and the user simply never receives the file |
  | `research/engine.py:529` | 1200 | the **DR planner** (sub-questions, stop condition) | plan unparseable; 3 retries all truncate identically, so DR planning fails wholesale |
  | `research/engine.py:703` | 900 | **gap assessment** — `gaps` + `next_queries` | returns `status: sufficient` with EMPTY gaps/next_queries → later rounds lose their targeted follow-ups and fall back to generic ones |

  Also `user_tools/analytical_visualizer.py:215,231` (1024) generates **chart CODE** — a
  truncated program is a broken chart.
- **Severity ranking:** `pipeline.py:271` is the worst. It is the request-decomposition stage,
  and dropping `actions` means a "research X and email me the PDF" request completes with no
  email and no error — precisely the failure class the architecture-first gate in `CLAUDE.md`
  was written about.
- **NOT a DeepInfra artifact.** All caps are hardcoded and model-agnostic; they would truncate
  on Ollama too. **Unverified on Ollama** — the account is 429 weekly-limited (SI-010), so
  frequency may differ if the Ollama model is terser. Check in the A/B.
- **Same class as `manager.py:317`** (fixed in v1.0.0.238): a literal outranking config, on a
  call that must return complete JSON. Belongs with that fix, not as a one-off patch.
- **Low-risk siblings, deliberately NOT grouped here:** `fastapi_server_complete.py:6316,6343,
  6372` (24), `:7557` (60), `:3618` (120), `:3553` (200), `research/gate.py:65` (200). These
  emit a label or a yes/no; the cap is proportionate. Listed so a future sweep does not
  re-derive the triage.
- **Fix when picked up:** plan step **4.7**. Make each cap config-driven and size it from a
  measured requirement (as 4.3 did), AND make the `except` handlers distinguish *truncation*
  from *malformed output* — the provider now returns that signal, so a truncated response can
  be retried at a higher cap instead of silently degraded.
- **Clear only when:** a DR run at the observed evidence volume completes with no `✂️ TRUNCATED`
  on any of the three sites, and a named test asserts that a truncated gap-assessment does NOT
  report `sufficient`.

### SI-011 — `config_server_cli.py set` DESTROYS every comment in `llm_config.yaml`  [P1 — CONFIRMED, blocks the quick-switch feature]
- **Observed (2026-08-09, during the v1.0.0.236 DeepInfra build):** running
  `config_server_cli.py set --alias deepinfra_glm --as tool_calling` rewrote the whole config and
  stripped **all 525 comment markers** — every retirement note, every scaling guide, every
  "was X — retired (2026-07)" breadcrumb. The lane change itself was correct; the collateral damage
  was total. Caught only because the change was made against a backup and diffed.
- **Cause:** the writer round-trips through `yaml.safe_load()` → `yaml.dump()`. PyYAML's loader
  discards comments (they are not part of the YAML data model), so the dump cannot re-emit them.
  Key ORDER is preserved by the dumper's config, which is what makes the loss easy to miss — the
  file still looks structurally right.
- **Why this is P1 and not cosmetic:** the next planned feature is *quick switching back and forth
  between DeepInfra and the other providers*. That feature calls `set` by design, repeatedly. The
  FIRST switch would permanently delete the documentation that records which slugs were retired and
  why — including the SI-008 audit trail written the same day. Comments are the only place that
  history lives; git history alone would not stop a future reader re-adding a dead slug.
- **Fix when picked up:** write with `ruamel.yaml` in round-trip mode (`YAML(typ='rt')`), which
  preserves comments and ordering, OR surgically patch only the changed scalar lines instead of
  re-dumping the document. `ruamel.yaml` is the smaller change and is already a common transitive
  dep — check `venv` before adding it to `requirements.txt`.
- **Interim mitigation:** back up `config/llm_config.yaml` before any `set`, and diff after.
- **Clear only when:** a `set` invocation is shown to change the intended lane while leaving the
  comment count unchanged, asserted by a named test that FAILS on the current implementation.

### SI-012 — An UNSET `${VAR}` API key fails as a confusing 401, not a config error  [P3 — CONFIRMED, pre-existing, all providers]
- **Observed (2026-08-09, adversarial audit A3 of the DeepInfra build):** `os.path.expandvars` leaves
  an *undefined* variable as the literal string `${DEEPINFRA_API_KEY}`. That string is truthy, so the
  guard at `llm_providers/openai.py:31` (`if not self.api_key: raise ValueError`) does **not** fire;
  the provider constructs happily and sends `Authorization: Bearer ${DEEPINFRA_API_KEY}`, producing a
  401/403 from the vendor at request time with nothing pointing back at the real cause.
- **Asymmetry worth knowing:** a variable set to the EMPTY string expands to `''`, which is falsy, so
  that case *does* fail fast at construction. Unset fails late and confusingly; empty fails early and
  clearly — the opposite of what intuition suggests.
- **Scope:** not specific to DeepInfra. Every provider that resolves its key through `${VAR}` in
  `llm_config.yaml` behaves this way — openai, openrouter, gemini, qwen, deepinfra.
- **Fix when picked up:** after expansion, reject any config value still matching `^\$\{.+\}$` with a
  message naming the missing variable. One check in `utils/config_loader.py` covers every provider.
- **Clear only when:** a lane with a deliberately-unset key raises a named-variable configuration
  error at load time instead of a vendor 401.

### SI-010 — Entire Ollama-cloud stack is 429 weekly-limited  [P1 — CONFIRMED by invocation]
- **Observed (2026-08-09, `config_server_cli.py doctor --probe --aliases`):** every Ollama-cloud lane
  returns the same refusal:
  ```
  HTTP 429: you (seedhom) have reached your weekly usage limit, upgrade for higher
  ```
- **Scope — measured, not assumed.** This is not one lane. It hits `llm.primary`
  (`deepseek-v4-pro:cloud`), `llm.tool_calling` (`glm-5.2:cloud`), `deep_research.engine.model`
  (`deepseek-v4-flash:cloud`), `code_generation.classification_model` (`gpt-oss:120b-cloud`), **and
  both vision lanes** (`minimax-m3:cloud`, `kimi-k2.6:cloud`) — i.e. the primary conversation path,
  tool selection, Deep Research, code generation and image understanding simultaneously.
- **Impact:** while the limit holds, the main serving path is down. Non-Ollama lanes still answer
  (`gpt-4o-mini`, `gemini-flash-latest` verified 200), so a provider switch is a viable mitigation.
- **Secondary impact — blocks verification.** A 429 is a fact about the ACCOUNT, not a verdict on a
  model, so no Ollama-cloud slug in `llm_config.yaml` can currently be proven live or dead. The
  retired-slug audit in SI-008 therefore covers OpenAI/Gemini/OpenRouter only; the Ollama slugs are
  **unaudited**, not clean.
- **Clear only when:** the quota resets or is upgraded AND `doctor --probe --aliases` returns a real
  verdict (not `?`) for every Ollama-cloud slug.

### SI-009 — `doctor --probe` reports a FALSE failure for any alias whose key is still `${VAR}`  [P2 — CONFIRMED]
- **Observed (2026-08-09):** `doctor --probe --aliases` reported `gemini_flash_36` and `gemini_pro_25`
  as `probe failed: HTTP 400: Please pass a valid API key`, which reads as "these aliases are
  misconfigured". **They are not.** Invoking both slugs directly with the expanded key returns HTTP
  **200** — `gemini-3.6-flash` and `gemini-2.5-pro` are LIVE and correctly declared.
- **Cause (code):** `config_server_cli.py::_probe_model` sends the auth header only when the key is
  already expanded —
  ```python
  if api_key and not api_key.startswith('${'):
      request.add_header('Authorization', f'Bearer {api_key}')
  ```
  Aliases are stored in `model_aliases.json` as the LITERAL `${GEMINI_API_KEY}` (JSON does no env
  expansion), so the probe deliberately sends no credentials and the endpoint answers 400. The guard
  exists to avoid sending a bogus literal as a bearer token; the cost is an unauthenticated probe
  that cannot distinguish "misconfigured" from "not expanded".
- **Why it matters:** this is the SI-005 lesson resurfacing in the tool built to enforce it. A false
  negative here is actively misleading — a prior note in project memory recorded these two aliases as
  "mis-declared" on the strength of this output. That note was **wrong** and was corrected 2026-08-09.
- **Fix when picked up:** expand `${VAR}` from the environment before probing (`os.path.expandvars`,
  the same mechanism `utils/config_loader.py:72` already uses) and report a distinct
  `UNRESOLVED-CREDENTIAL` status when the variable is genuinely unset — never a bare 400.
- **Clear only when:** an alias carrying `${VAR}` probes to a true verdict, and a named test asserts a
  `${VAR}` alias with the env var SET probes OK (must fail on pre-fix code).

### SI-006 — 2 academic sources rate-limited without an API key (`semantic_scholar`, `core`)  [P2 — CONFIRMED, not a bug]
- **Observed (2026-08-06):** after v1.0.0.235 revived pubmed/doaj/biorxiv, `published_papers_search`
  reaches **9 of 11** databases. The two that stay dark are `semantic_scholar` and `core`.
- **Confirmed cause (invocation-based, both environments):** HTTP **429 Too Many Requests**, with no
  API key configured — `CORE_API_KEY` is unset locally AND on live. This is **not** a code defect and
  **not** environment-specific.
  ```
  local: ClientResponseError: 429 … api.core.ac.uk/v3/search/works
  live : ClientResponseError: 429 … api.core.ac.uk/v3/search/works
  ```
- **Falsification note — nearly logged wrong.** CORE first measured 15 URLs locally vs 0 on live, which
  read as a live-only failure. Probing BOTH environments showed 429 on each: the local run had simply
  not yet tripped the unauthenticated rate limit after repeated test calls. An environment-specific
  claim must be checked against the other environment before it is recorded.
- **Impact:** degrades breadth for **Deep Research** and `@scibot`, both of which call this tool. Not
  fatal — 9 sources remain, and `europe_pmc` covers the bioRxiv corpus — but CORE and Semantic Scholar
  are the two broadest cross-disciplinary indexes, so humanities/interdisciplinary queries lose most.
- **Fix when picked up:** obtain free API keys (CORE: `core.ac.uk/services/api`; Semantic Scholar:
  `semanticscholar.org/product/api`), put them in `.env` as secrets (**never** in `llm_config.yaml`,
  per the configuration directive), and read them in `_build_core_url` / `_search_semantic_scholar`.
  Requires the user to register — cannot be done unattended.
- **Clear only when:** a keyed request returns results in BOTH environments, or the sources are
  deliberately dropped from the tool's source list.

### SI-007 — Stray files in repo root violate the documented directory organization  [P3]
- **Observed (2026-08-06, during the v1.0.0.235 checkpoint):** 10 `.py` files sit in the repo root
  outside the documented "core modules only" allow-list — `debug_pygobject.py`, `dependency_analyzer.py`,
  `image_utils.py`, `llm_tools_processor.py`, `main.py`, `RAG_helper.py`, `scratch_puzzle.py`, and three
  test files (`test_google_news_rss.py`, `test_main.py`, `test_news_sources.py`).
- **Why it matters:** `CLAUDE.md` states *"NEVER leave test files in root directory"* and *"debug_*.py,
  analyze_*.py → archive/experimental/"*. Pre-existing debt, not introduced by any recent change.
- **Deliberately NOT fixed during the deploy:** moving Python files requires comprehensive dependency
  analysis first (`CLAUDE.md`: *"ALWAYS check dependencies before moving Python files"*), and some of
  these may be live imports. Bundling that into a production deploy would add unrelated risk.
- **Clear when:** each file is grep-analysed for importers and either moved to its documented home
  (`tests/…`, `archive/experimental/`) or explicitly added to the root allow-list with a reason.

### SI-002 — aiohttp `Unclosed client session / connector` warnings under direct tool calls  [P3]
- **Observed (2026-07-12):** running `tests/smoke/tool_smoke.py` (imports the module, calls tools
  directly, then exits) printed several `Unclosed client session` / `Unclosed connector` warnings.
- **Evidence gathered:** the **running server** log shows **0** such warnings → looks like a standalone-
  script teardown artifact (tools create sessions the script never closes on exit), NOT a server-runtime
  leak (the server pools/reuses via `http_pool_manager`).
- **Watch condition:** if `server_complete.log` ever starts accruing `Unclosed` warnings under load,
  re-open as a real leak. Until then, low.

### SI-003 — Vestigial MySQL pool: dead code + a boot footgun  [P3 — SCOPED, awaiting sign-off]  *(spun off from SI-001)*
- **Finding:** the MySQL `db_pool` (`init_db_pool`, `execute_query`, `get_db_connection`) is **unused** —
  `execute_query()` has **0 callers** anywhere; the only references are `health_check` (cosmetic report)
  and the dead helper itself. All real storage is SQLite + FAISS. (RAICA uses **no** Postgres — the
  SQLite→Postgres-in-prod stack belongs to the separate **NewX** repo, confirmed live 2026-07-18.)
- **Two cleanup items:**
  1. `ServerConfig` (fastapi_server_complete.py:195–198) **hard-requires `DB_PASSWORD` or the server
     refuses to boot** — for a DB that is never queried. A fresh install fails to start without a
     meaningless secret. Relax (only require it if the DB is actually used) or remove the pool.
  2. `/health` reports `database: "unavailable"` (alarming for ops) for something intentionally unused —
     remove the MySQL pool entirely, or report `"not_configured"`.
- **Impact:** none functional today (nothing uses it); pure tech-debt + fresh-install footgun.

#### Scoped cleanup plan (2026-07-18 — verified against live prod; not yet implemented)

**Complete reference map** (everything the pool touches, in `fastapi_server_complete.py`):
- `import aiomysql` / `from aiomysql.pool import Pool` — `:137-138`
- `db_pool: Optional[Pool] = None` — `:309`
- `ServerConfig` DB block (`DB_HOST/DB_USER/DB_PASSWORD` + fail-fast raise / `DB_NAME/DB_POOL_SIZE`) — `:191-200`
- `init_db_pool()` — `:454-472`  ·  `close_db_pool()` — `:474-479`  ·  `get_db_connection()` — `:481-493`
- `execute_query()` (**0 callers**) — `:2537-2546`
- lifespan startup/shutdown calls — `:2398` (init) / `:2472` (close)
- readers of the pool: `/health` DB check — `:11750-11760` · `/metrics` `db_stats` — `:12127-12131`
- `.env.example` `DB_*` block (incl. phantom `DB_MAX_OVERFLOW` the code never reads) — `:2-7`

**Zero-regression boundary** (verified this session):
- **0** cross-module imports of the pool symbols (`coding_agent._execute_query_step` is an unrelated method).
- Only reader of `/health`'s `database` field is `tests/utilities/test_ollama.py:45` — it **prints** the value,
  no assertion → relabel is safe.
- ⚠️ **LANDMINE:** the overall-`status` computation whitelists `"unavailable"` (`:11766-11768`). Relabeling
  `database` → `"not_configured"` **without** adding `"not_configured"` to that whitelist would flip the
  top-level `/health` `status` to `"unhealthy"` (which the AWS LB / monitoring may act on). The relabel is
  therefore **two coordinated edits**, not one.
- Prod `.env` already has `DB_PASSWORD` set → relaxing the boot-raise is **identical** behavior on prod
  (pool still tries + fails soft with `1698 Access denied for 'root'@'localhost'`), and strictly better for
  fresh installs (boot instead of crash).
- Security: keep `os.getenv('DB_PASSWORD')` with **no default** → does **not** reintroduce the hardcoded
  `Down2earth!` credential removed in v1.0.0.61.

**Phase 1 — RECOMMENDED (tiny diff, zero functional change):**
1. Relax boot footgun (`:193-198`): drop the `raise RuntimeError`; `DB_PASSWORD` stays optional (`None` ok).
2. Honest health label (2 coordinated edits): `:11760` `"unavailable"` → `"not_configured"` **and** `:11767`
   add `"not_configured"` to the whitelist. Overall `status` stays `healthy`.
3. (Optional) `/metrics` `db_stats` (`:12127`) cosmetic touch — can skip to minimize the diff.
4. Version bump + `CHANGELOG_v1.0.0.190.md`.

**Phase 2 — OPTIONAL (full dead-code removal, only after Phase 1 verified):** delete imports/`db_pool`/
`init_db_pool`/`close_db_pool`/`get_db_connection`/`execute_query`/`DB_*` config/lifespan calls; simplify
`/health` + `/metrics`; drop `aiomysql` + `PyMySQL` from `requirements.txt`; remove the `DB_*` block from
`.env.example`. ~60-line diff, still **0 functional callers** → best as a separate follow-up commit.

**Verify plan (local first, per DEPLOYMENT PROTOCOL):** restart → `/health` = `status:healthy` +
`database:not_configured`; fresh-install sim (unset `DB_PASSWORD`) → server **boots**; prod-parity (with
`DB_PASSWORD` set) → identical soft-fail + same log line; `pytest` + `make smoke` green; then push + deploy
+ re-verify prod `/health`.

**Status:** SCOPED, **no code changed** (user chose memory/doc update only on 2026-07-18). Ready to implement
verbatim on sign-off.

---

## Resolved

### SI-014 — `OpenAIProvider.generate_stream` SILENTLY DISCARDED the system prompt  →  **FIXED 2026-08-09**  [was P1, production-affecting]
- **Observed (2026-08-09, arbitrator lane evaluation):** both candidate models scored **0% schema
  compliance and 0% correct verdicts** on the arbitrator task. The models were not at fault — they
  never received the schema.
- **Cause (code, confirmed):** `generate_stream` built its payload as
  `"messages": [{"role": "user", "content": prompt}]` — the user turn ALONE. Callers pass the system
  prompt in kwargs (`manager.py:315`, `call_arbitrator`), and it was dropped on the floor.
- **Production impact — NOT DeepInfra-specific.** The arbitrator lane is `type: openai`
  (`llm_config.yaml`, `enabled: true`), so RAICA's arbitrator has been running **without its
  13,802-char "🚨 CRITICAL JSON-ONLY RESPONSE REQUIRED" schema spec** (`fastapi_server_complete.py:5400`)
  — on the normal Ollama-proxy path, not just under test. Measured consequence, pre-fix:

  | model | pure-JSON | schema | correct verdict |
  |---|---|---|---|
  | gpt-oss-120b | 89% | **0%** | **0%** |
  | GLM-5.2 | **0%** (```json fences) | **0%** | **0%** |

  Any lane on an OpenAI-compatible provider is affected, so switching `llm.primary` to such a
  provider would silently drop the citation/anti-hallucination rules too.
- **Why it stayed invisible:** `generate_tools()` in the SAME class always handled `system_prompt`
  correctly (and logs loudly about it), and `ollama.py:69-70` was fixed for this exact defect in
  **v1.0.2.101**. The OpenAI path was never given the same fix, and the lane that used it produced
  plausible-looking JSON, just not the required shape.
- **Fix:** prepend `{"role": "system", ...}` when `system_prompt` is present, plus a log line that
  states the char count or `⚠️ NO SYSTEM PROMPT` — so a future silent drop is visible.
- **Residual (must verify before this is fully closed):** adding a 13.8K-char system message raises
  token usage on every affected call; confirm no lane now exceeds its `context_window_size`, and
  re-verify arbitrator behaviour end-to-end on the real Ollama path once its quota resets (SI-010).

### SI-013 — `tool_calls: null` crashed the tool lane on every correct abstention  →  **FIXED 2026-08-09**  [was P1 for any OpenAI-compatible vendor]
- **Observed:** 2 of 16 tool-selection cases died with `TypeError: 'NoneType' object is not iterable`
  — specifically the ABSTENTION cases, i.e. exactly when the model correctly decided no tool was needed.
- **Cause (code, confirmed by reproduction through the real provider):** `openai.py:227` used
  `message.get('tool_calls', [])`. **A dict default fires only when the KEY IS ABSENT.** OpenAI omits
  the key when no tool is called, so the bug never surfaced there; DeepInfra (and other
  OpenAI-compatible vendors) send it **present and null**:
  ```json
  "message": {"role": "assistant", "content": "Hi!", "tool_calls": null}
  ```
  `.get(..., [])` therefore returned `None` and the formatting loop iterated it. `content` had the
  identical flaw.
- **Impact:** would have made DeepInfra unusable for the `tool_calling` lane — every greeting or
  pure-knowledge question that correctly declined a tool would raise. Latent for any future
  OpenAI-compatible provider.
- **Fix:** `message.get('tool_calls') or []` and `message.get('content') or ''`.
- **Tests:** `tests/unit/test_openai_provider_null_tool_calls.py` — 4 named tests; **2 FAIL on the
  pre-fix code**, all 4 pass after (verified by temporarily reverting the fix).

### SI-008 — Retired model slugs in `llm_config.yaml`  →  **RESOLVED 2026-08-09** (3 dead slugs replaced)
- **Observed:** while evaluating DeepInfra as a new provider, the OpenRouter block was found to name a
  model that no longer exists. A full invocation audit of every slug we hold credentials for followed.
- **Method:** each slug INVOKED with a 1-token generation (per the SI-005 lesson that a catalog listing
  is evidence in NEITHER direction). Script: `scratchpad/audit_config_models.py`. 13 slugs probed:
  **8 LIVE, 2 DEAD, 3 inconclusive** (402 no-credits / 429 transient — never recorded as dead).
- **Confirmed DEAD, with the vendor's own words:**

  | Slug | Was at | Evidence | Replaced with |
  |---|---|---|---|
  | `deepseek/deepseek-r1:free` | `llm_config.yaml:116,119` | `404 — "This model is unavailable for free… use this slug instead: deepseek/deepseek-r1"` | `deepseek/deepseek-r1` (primary/reasoning) + `openai/gpt-oss-20b:free` (free lane) |
  | `gemini-2.0-flash` | `llm_config.yaml:733,779,806` | `404 — "This model models/gemini-2.0-flash is no longer available"` | `gemini-flash-latest` |
  | `deepseek-v3.1:671b-cloud` | alias `deepseek_ollama_cloud` | `410 — "retired at 2026-07-15"` | `deepseek-v4-flash:cloud` |

- **Falsification note — the fix was incomplete on the first pass.** A grep anchored on
  `^\s*model:` found 2 of the 3 `gemini-2.0-flash` references; the third (`code_generation.providers.
  gemini.model`, line 806) was missed and was caught only because the verification asserted
  `'gemini-2.0-flash' not in str(parsed_config)` over the whole document rather than re-reading the
  lines just edited. **Assert absence across the parsed config, not across the diff.**
- **Verified:** YAML parses; loads through the real path (`utils/config_loader.ConfigLoader`);
  `doctor` reports every lane's model consistent with its endpoint; both replacement slugs
  re-probed **HTTP 200 LIVE**; `openai/gpt-oss-20b:free` additionally verified to emit well-formed
  `tool_calls`.
- **Residual (tracked as SI-010):** all Ollama-cloud slugs remain **unaudited** — the account is 429
  weekly-limited, so they can be proven neither live nor dead. `claude-sonnet-4-20250514` /
  `claude-opus-4-20250514` (`code_generation`) are likewise unverifiable: `ANTHROPIC_API_KEY` is unset,
  so that whole provider path is inert. Both look stale but neither was changed — replacing an
  unverifiable slug with another unverifiable slug is not a fix.

### SI-005 — Vision lane swapped off two models  →  **CAUSE RETRACTED 2026-08-05; lane works, cause UNKNOWN**
- **Status:** the vision lane is HEALTHY (verified replacements, below). What is retracted is the
  *diagnosis*. The original entry claimed Ollama served **neither** `kimi-k2.7-code:cloud` nor
  `gemma4:31b-cloud`. **BOTH CLAIMS ARE FALSE.**
- **Refutation (2026-08-05):** re-probed by INVOKING each model. `kimi-k2.7-code:cloud` and
  `gemma4:31b-cloud` both answer normally, on this machine AND on live `sabawi.net`; `gemma4:31b-cloud`
  also correctly described a test image, so it is vision-capable. The false claim came from reading
  `/api/tags`, which lists only models **pulled locally** and is evidence in NEITHER direction.
  Contrast: genuinely retired models return an explicit `HTTP 410 "… was retired at <date>"`. Neither of
  these two produces anything of the kind, which is the strongest sign they were never retired at all.
  (Caveat — this does not *prove* they were reachable on 2026-07-31; cloud availability shifts. But the
  recorded cause was never established by invocation, so it was never evidence.)
- **Therefore the real cause of the 2026-07-31 vision break is UNKNOWN** and could recur. Do NOT treat
  this entry as explaining it. Next step if it recurs: capture the ACTUAL error from
  `image_to_text.py` at the moment of failure rather than inferring from a model listing.
- **Fix still stands (independently verified):** primary `minimax-m3:cloud`, fallback `kimi-k2.6:cloud`.
  Each was sent a generated image (red circle, blue square, the word "SEVEN"); minimax-m3 named all three
  including reading the TEXT (genuine OCR, not a guess from the prompt), kimi-k2.6 named the shapes and
  colours. Different families, so one vendor retirement cannot take out both. Verified end-to-end through
  RAICA's real `ImageToTextTool` (not a raw API call): all five cues matched.
- **Rejected with evidence (invocation-based, still valid):** `qwen3-vl:235b-cloud` HTTP 410 "retired at
  2026-06-16"; `minimax-m2.7:cloud` and `glm-5.2:cloud` HTTP 400 "does not support image input".
- **Guard installed (2026-08-05):** `doctor --probe` / `--aliases` no longer read a listing — they INVOKE
  each model with a 1-token generation (`config_server_cli.py::_probe_model`). Measured before the fix,
  the listing check was wrong in BOTH directions: it PASSED the one genuinely dead model
  (`qwen3-vl:235b-cloud`, 410) and FAILED two working ones. The new probe classifies 6/6 correctly and,
  on its first real run, caught a dead alias the old check was blind to — `deepseek_ollama_cloud` →
  `deepseek-v3.1:671b-cloud`, HTTP 410, retired 2026-07-15. Auth/billing/rate-limit responses are
  reported as inconclusive `?`, never as "dead model".
- **Lesson (escalated):** availability is established ONLY by invoking. A registry listing is not
  evidence — in either direction. The earlier version of this entry already knew listings could produce a
  false PASS and still reasoned from one to record a false FAIL.

### SI-004 — data-charts `fbi_cde` endpoint dead (404)  →  **RESOLVED 2026-07-23** (endpoint rediscovered + rewired)
- **Was:** the configured `https://api.usa.gov/crime/fbi/cde/estimate/national/{measure}` returned HTTP 404
  for every offense, so US crime charts could not render (the original post/5955 use case).
- **Root cause (evidence):** the FBI reorganized the CDE API. ALL public documentation is stale — the
  documented `sapi` base, the `fbi-cde/crime-data-api` + `crime-data-frontend` repos, the `jacobkap/fbiAPI`
  R wrapper and every Swagger/cloud.gov host (`crime-data-api.fr.cloud.gov/swagger-ui/`) return 404. Even a
  developer blog's verbatim working example (`sapi/api/summarized/agencies/{ORI}/{offense}`) now 404s.
- **Fix:** deep web research + empirical probing by analogy from a live route found the CURRENT endpoint:
  `https://api.usa.gov/crime/fbi/cde/summarized/national/{offense}?type=counts&from=MM-YYYY&to=MM-YYYY&api_key=`
  Rewired `config/llm_config.yaml` (`endpoint`, `params` MM-YYYY, `shape: fbi_cde_summarized`, `min_year: 1985`)
  + new `datasources/shapes.py::fbi_cde_summarized` handler (nested `offenses.rates|actuals →
  "United States Offenses" → {MM-YYYY: v}`; aggregates MONTHLY→ANNUAL, complete 12-month years only) +
  `_fmt` `min_year` clamping (the API 400s on a pre-1985 start instead of clamping).
- **Verified (2026-07-23):** live extract = 41 annual points 1985–2025, peak **1991 = 798.1/100k**, low
  **2025 = 328.6/100k** (matches the known US violent-crime curve). violent-crime/property-crime/homicide all
  build markers in ~1s, images served 200 by NewX. **End-to-end through `/v1`** on "show me the change in
  crime rate in the USA in the last 50 years" → 1 real chart marker, cited values match the dataset exactly
  (1985=570.27, 2025=328.64), 0 fabrication signals.
- **Residual:** coverage starts 1985, so a "last 50 years" ask renders ~40 years (clamped, not an error).

 (kept for the audit trail)

### SI-001 — `database: unavailable` on local AND prod  →  NOT a functional bug  (resolved 2026-07-12)
- **Concern was:** silent memory-cache fallback might be degrading a DB-backed feature everywhere.
- **Evidence / proof:** the MySQL pool's only functional consumer, `execute_query()`, has **0 callers**
  across the whole codebase; the pool is referenced only by `health_check` (cosmetic) and its own dead
  helper. RAG/persistence run on SQLite (`document_interrogator` metadata_db) + FAISS, both healthy. MySQL
  is running on live; the pool just fails auth (`root@localhost` — the `DB_USER`/`DB_HOST` defaults) and
  **fails soft**. So `database: unavailable` is cosmetic — **no feature is degraded.**
- **Outcome:** not a functional bug. The real (low-priority) tech-debt it exposed is tracked as **SI-003**.
