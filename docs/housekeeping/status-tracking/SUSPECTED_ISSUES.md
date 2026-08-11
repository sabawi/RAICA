# Suspected Issues Log

Per the global directive *"NEVER dismiss a possible bug without evidence — if busy, log it with a priority
call; clear it only on evidence or a verified fix."* Open items are things NOTICED but not yet confirmed
as bug-or-not. **Do not delete an item on a hunch** — resolve it with evidence (real bug filed/fixed, or
proven not-a-bug) and move it to Resolved with that evidence.

Priority: **P1** act now · **P2** investigate soon · **P3** watch / low-impact.

---

## Open

### SI-028 — Generalized search → extract → chart fallback  [P1 **DONE** v1.0.0.253; P2-P4 awaiting sign-off]
- **P1 SHIPPED 2026-08-11 (v1.0.0.253):** `lookup_website` now dispatches on the SERVER-declared
  `Content-Type` (`_probe_content_type` → `_extract_data_content`), passing CSV/TSV/JSON/XML through
  verbatim with the line count stated and truncation DISCLOSED. Unknown types are returned labelled
  rather than rejected. HTML/PDF paths unchanged. Verified against the exact file that failed:
  **153 lines, complete, `text/csv`**. Plus routing guards (policy, not ticker regex) sending listed
  securities to the specialized analyzer, and a requirement to name the fetched source/rows/columns.
- **P2-P4 still NOT started** (generic `plot_data` tool, whitelist, fallback-ordering policy).
- **Reframed 2026-08-11 by the user.** Originally logged as "add a Treasury daily yield-curve
  source". **Withdrawn as a per-site band-aid** — the Generalization Directive forbids it: the next
  request is BLS, then ECB, then a CSV on GitHub, each needing its own tool. The right question was
  *why can RAICA not read a CSV?*
- **ROOT CAUSE (traced on a live prod run, not assumed):** `fastapi_server_complete.py:2167`
  `lookup_website` dispatches on the URL STRING with two branches — PDF, else assume HTML. CSV /
  JSON / XML / TSV all fall into the HTML extractor and fail **closed and silent**
  (`ERROR: Failed to extract content`). The server's honest `text/csv; charset=UTF-8` header is
  never consulted. This blocks EVERY machine-readable data file on the web.
- **Live evidence:** `@Ask` selected `lookup_website` correctly and called it TWICE (one file per
  year, exactly as prompted), built both URLs correctly — and got zero rows. The endpoint returns
  HTTP 200, 12,422 bytes, 153 rows, 15 maturities, fresher than FRED.
- **KEY FINDING — the generic chart mechanism ALREADY EXISTS** and is only ever fed from the
  dataset catalog: `publish_chart(png,hint)->url` (`chart_publisher.py:184`), `_marker()`
  (`data_chart_builder.py:29`), `generate_data_chart(series,kind)`, and `DatasetSeries`
  (`dataset_block.py:50`) whose provenance fields are MANDATORY and fail-closed. `_TIERS` already
  contains `bulk_file` — precisely the fidelity tier for a downloaded CSV.
- **Design + sizing:** `docs/RAICA_GENERALIZED_EXTRACT_CHART.md`. P1 content-type dispatch (~0.5
  day) · P2 thin `plot_data` tool over the existing primitives, NO code-gen and NO sandbox (~1–1.5
  days) · P3 whitelist (1 line) · P4 fallback-ordering policy. **≈3 days total.** P1 alone would
  have answered the user's actual question.
- **Explicitly rejected:** wiring `analytical_visualizer` — it generates and EXECUTES chart code,
  emits no `[[chart:]]` marker, and writes to a sandbox path.
- **Do NOT start without sign-off.** Open questions are listed in §7 of the design doc.


### SI-024 — Evidence budgeting silently DISCARDS computed tool output  →  **SUPERSEDED by SI-025, FIXED 2026-08-10 (v1.0.0.250)**  [was P1]
- **Observed (2026-08-10, user's 8-stock @Ask query):** the report said *"No technical chart
  markers were provided in the evidence"* for **all 8 stocks** and contained **zero DCF
  intrinsic values** — despite the user explicitly asking for the structured analyzer at
  full detail and for DCF values to be labelled.
- **The tools RAN and SUCCEEDED.** Log: 8/8 `Calculating DCF for {KO,JPM,BRK-B,CROX,RIVN,
  PLUG,FUBO,RBRK}` and 8/8 `🖼️ chart marker EMITTED`, all during the DR gather
  (11:22:02–11:23:17), before `Deep research complete` at 11:24:39.
- **CAUSE (confirmed by contrast, not by inspection alone):**
  `SynthesisEngine._allocate_token_budget` divides `evidence_token_budget: 87000` across
  the evidence pool. Two runs in the SAME log:

  | run | items | chars | truncated | markers reaching synthesis |
  |---|---|---|---|---|
  | 10:33 (2 stocks) | 28 | 242,127 | 6/28 | **evidence=2** ✅ |
  | 11:21 (8 stocks) | 78 | 824,053 | **50/78 (~100,729 tokens)** | **evidence=0** ❌ |

  `fair = 87000 // 78 ≈ 1,115 tokens/item`. `_tok_truncate` keeps `toks[:max_tokens]` —
  the **HEAD**. The analyzer appends `tech_block` (which carries the `[[chart:…]]` marker)
  LAST, at `comprehensive_stock_analyzer.py:907`, after fundamentals/ratios/DCF/projections.
  So the cut lands squarely on the technical + chart + DCF sections.
- **Falsifying detail that CONFIRMS rather than merely fits:** the report DID carry 50-day
  MA, 200-day MA, RSI and 52-week range for all 8 — those sit in the HEAD of the block and
  survived. Only tail-resident content vanished. A different cause (tool failure, marker
  stripping, whitelist) would have removed both.
- **The LLM was honest.** "No technical chart markers were provided in the evidence" was
  literally TRUE of the evidence it received. The pipeline starved it; the model reported
  the starvation correctly. This is NOT a synthesis-prompt defect.
- **Severity:** the MORE entities a user asks about, the LESS computed detail each one gets,
  silently, and the loss falls on the most expensive content (DCF, charts) purely because
  of where it sits in the block. Scales exactly the wrong way.
- **Fix direction (NOT yet implemented, needs sign-off):** (a) extract `[[chart:…]]`
  markers from a block BEFORE truncation and re-attach after — they cost ~100 chars each,
  so survival is nearly free; (b) give COMPUTED tool blocks a larger budget share than
  scraped web prose, which is redundant and compressible; (c) reorder the analyzer so
  computed results (DCF, technicals) precede bulk narrative. (a)+(b) are the targeted pair.
- **Clear only when:** an 8-ticker query renders per-ticker charts and DCF values, asserted
  by a test that fails on current code.


### SI-017 — `convert` cannot ADD an `api_key` to a lane that lacks one  [P2 — CONFIRMED]
- **Observed (2026-08-10, A/B run):** every DeepInfra-arm vision call failed
  `API error: 401 - missing API key`.
- **Cause:** `_write_conversion` REWRITES an existing `api_key:` line but cannot INSERT one.
  The `vision` lane has no `api_key` in the Ollama baseline (a local endpoint needs none), so
  converting it to a credentialed provider leaves it uncredentialed. Same applies to any lane
  moving from a keyless to a keyed provider.
- **Why the tests missed it:** the unit fixture HAD an `api_key` line. The test asserted the
  rewrite path and never exercised the insert path.
- **Fix when picked up:** after converting a lane's `type`/`base_url`, ensure an `api_key` line
  exists — insert one from `_target_transport` if absent. Add a fixture WITHOUT an api_key.
- **Clear only when:** converting a keyless lane to a keyed provider produces a working call,
  asserted by a test that fails on the current code.

### SI-016 — The user's prompt never reaches FORCED IMAGE PROCESSING  →  **FIXED 2026-08-10 (v1.0.0.245)** [residual intermittent, see below]
- **Symptom:** vision requests report failure even when the image is perfectly readable.
  0/3 on BOTH arms of the A/B (so NOT provider-specific). User sees *"I'm unable to
  transcribe the image…"*
- **VERIFIED CAUSE.** `fastapi_server_complete.py:9469` invokes the tool with NO prompt:
  ```python
  result = await image_tool.execute(images=images_data,
                                    processing_mode="sequential", quality="high")
  ```
  `image_to_text` then falls back to its generic default
  (`user_tools/image_to_text.py:146-150`): *"Analyze this image thoroughly and describe
  what you see in detail. Extract any visible text accurately.\n\nUSER PROMPT: "* —
  with the user prompt **empty**. The vision model is asked to DESCRIBE, never to answer
  the user's actual question.
- **FALSIFIED, not asserted** — same image, same model, 3 runs each:

  | prompt | transcribed the text? |
  |---|---|
  | forced-processing default (no user question) | **False / False / False** — "# Image Analysis … a simple, minimalist rectangular box" |
  | same prompt **+ the user's question** | **True / True / True** — "The text in the image reads: **RAICA AB TEST8317**" |

  A 0/3 vs 3/3 discriminator on the one variable that changed.
- **Explains the intermittency**, which the retracted cause could not: whether a "describe
  this image" answer happens to contain the requested text is luck, so N6 passed once and
  failed six times. A deterministic bug cannot produce that pattern.
- **The arbitrator was RIGHT, and is exonerated.** It observed that a "blue border, white
  background" description did not answer the question and marked the task BAD — correct.
  Its retry was the correct instinct; it could not succeed only because of the second
  defect below. The earlier claim that it "strips the image" was wrong and is retracted.
- **SECOND, SEPARATE DEFECT (contributory, not the cause):** forced processing resets
  `image_exists = False` immediately after running
  (`🔄 FORCED IMAGE PROCESSING: Reset image_exists flag to False`), so the image is
  single-use. Any downstream `image_to_text` call — including the arbitrator's retry —
  runs with `Using base64 data: 0 chars` and fails on `invalid image: expected image mime
  type, got "text/plain"`. This converts a RECOVERABLE miss into a hard failure.
- **FIX (a) APPLIED (v1.0.0.245):** `prompt=user_prompt` forwarded into the
  forced-processing `execute()` call (`fastapi_server_complete.py`). `user_prompt` is
  never reassigned between its binding and this call, so it carries the user's real
  question. Verified end-to-end through the REAL `/v1` path.

  | | answers correctly |
  |---|---|
  | before | **0 / 6** (0/3 each arm of the A/B) |
  | after | **7 / 8** |

  **The 1 residual failure is recorded, not rounded away.** One run returned *"I'm
  unable to transcribe the text from this image"* while the digits appeared later in the
  same reply — a self-contradicting answer. It also exposed a SCORING bug: the first
  check was `'8317' in reply`, which passed that run. A user reading it sees a refusal.
  The check now requires the text AND the absence of a failure disclaimer.

- **FIX (b) NOT APPLIED — deliberately.** `image_exists = False` after forced processing
  is intentional and load-bearing: *"prevents re-triggering image processing on
  subsequent conversation turns"*. Removing it would trade a rare failure for unmeasured
  multi-turn behaviour. The residual intermittent above suggests it is still implicated,
  so the better-scoped change is: **do not attempt a retry that cannot possibly
  succeed** — when image data is unavailable, skip rather than run and surface
  `invalid image: got "text/plain"`. That lives in the arbitrator path and needs its own
  change and test.
- **Clear only when:** a vision request that the model CAN answer is reported as answered,
  asserted by a test that fails on current code — and ideally a second test proving a
  retry still has image data available.

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
- **UPDATE 2026-08-09 — two findings added after three live DR runs on the like-for-like config.**

  **(a) `engine.py:703` (900) is MODEL-INDEPENDENT — confirmed.** It truncated on
  `DeepSeek-V3.1` AND twice more on `DeepSeek-V4-Flash`, the exact model Ollama runs. So
  this is not a provider or model artifact; it would truncate on Ollama too. It is
  **volume-dependent**: it fired on the 3-round/24-item and 2-round/17-item runs, but not
  on the 2-round/15-item run. Larger evidence pool → longer gap JSON → truncation.

  **(b) NEW SITE — `research/synthesis.py:296-299`, claim verification, cap 12000.**
  ```python
  @property
  def _verify_max_tokens(self) -> int:
      # Output budget for the verification JSON. Long answers have many claims, so this
      # must be generous or claim extraction gets truncated (under-sampling the answer).
      return int(self._cfg.get("verification", {}).get("max_tokens", 12000))
  ```
  **The author anticipated this exact failure in the comment** and set 12000 as the
  default. `deep_research.engine.verification` is **ABSENT from `llm_config.yaml`**, so the
  default applies — and it truncated on the largest run (188K→246K-char synthesis prompts).
  Consequence: claim extraction under-samples the answer, so claims in the later part of a
  long report go **unverified** while citation grounding still reports coverage. This one
  is the *easiest* fix of the set — it needs a CONFIG entry, not a code change.

  **(c) What is NOT a defect — a correction.** `max_answer_tokens: 32000` truncated on 2/2
  runs and lost 12/16 then 4/24 chart markers, and was reported here as a capacity limit.
  **That was wrong.** Both runs had GLM-5.2 substituted as the DR heavy model instead of
  `deepseek-v4-pro`. Re-run with the correct model on a LARGER input (188,604 then 246,296
  chars vs 179,117): **no truncation, 20/20 chart markers placed, 0 repair passes.** The
  cap is correctly sized; the ceiling was an artifact of an unauthorised model swap. See
  [[provider-change-is-not-model-change]].

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

### SI-009 — `doctor --probe` probed UNAUTHENTICATED  →  **FIXED 2026-08-09 (v1.0.0.243)**
- **Root cause was broader than first logged.** The original entry blamed `_probe_model`'s
  guard (it skips the auth header when a key is still a literal `${VAR}`). That guard is
  fine. The real defect was one layer up in `_probe_endpoints`:
  ```python
  api_key = os.path.expandvars('${GEMINI_API_KEY}' if 'googleapis' in endpoint else '')
  ```
  **Hardcoded to a single provider** — every other endpoint was probed with an EMPTY key.
  DeepInfra/OpenAI/OpenRouter lanes all returned `401: missing API key` and were reported
  as `?` inconclusive, which reads as "cannot verify the model" when the truth is "we never
  authenticated". It silently disarmed the one command meant to gate a deploy.
- **Caught in use, not by inspection:** running the A/B pre-flight on 2026-08-09, all 6
  DeepInfra lanes came back `?`. Post-fix: 6/6 `✓`.
- **Fix:** resolve the credential per endpoint via the existing `_ENDPOINT_KEY_ENV`
  host→env map, expanded with `_expand_secret` (which reads `.env`). **Both helpers already
  existed; neither was wired in.**

### SI-009 (original entry, superseded above) — `${VAR}` aliases  [P2]
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

### SI-027 — Dataset charts described at a resolution they do not have  →  **FIXED (policy) 2026-08-11 (v1.0.0.252)**  [was P2, user-reported]
- **Reported:** a "past two years" chart of 30/20/10/5-year Treasury yields read as though the
  10y and 30y were **diverging**. They were not — the 30y-10y spread was **0.52 → 0.54 over 13
  months** (10y +0.39, 30y +0.41: a parallel shift, not a divergence).
- **The DATA was perfect.** All 12 annual averages matched FRED to the basis point, and all four
  series resolved correctly (DGS30/20/10/5). **Zero fabrication.** The defect was entirely in
  how the chart was DESCRIBED.
- **Three misrepresentations:** (1) three annual points per line narrated as a two-year *path*,
  which is what made a constant gap look like spreading; (2) the 2026 point labelled an "annual
  average" while covering **151 trading days** (Jan-Aug) — 30y shown as 4.93% against an actual
  latest of **5.19%**; (3) a "trend correlation of **+1.00**" reported from **three**
  observations, which carries no information however precise it looks.
- **Why POLICY and not code:** `shape: fred_observations` aggregates every FRED series to ANNUAL
  MEANS and exposes **no frequency parameter**. A directive telling the model to fetch daily data
  would be silently defeated by the code — the LLM-policy gate's exact trap. The directives
  therefore ask only for what the system CAN do: disclose granularity, label a partial year,
  refrain from statistics the sample cannot support.
- **Two surfaces:** the `compare_datasets` DESCRIPTION (read when choosing/using the tool, so
  expectations are set BEFORE writing) and the non-DR answer directive `_ARTIFACT_MARKER_RELAY`
  (read when composing). The parallel-rise-read-as-divergence error is named explicitly —
  *"Two lines rising together with an unchanged gap are NOT diverging; check the gap first."*
- **CORRECTION (2026-08-11, user challenge).** The original wording said the tool "cannot serve"
  daily data. **That is FALSE and is retracted.** FRED returns **497 daily observations** for
  DGS10 over 2 years; `datasources/shapes.py::fred_observations` sums them by year and emits 3
  `{year, value}` records — **494 of 497 discarded (99%)**. RAICA HAS the daily data and throws it
  away. The claim rested on a CONFIG COMMENT rather than the handler code — the same
  trust-the-description-over-the-mechanism error logged elsewhere today.
- **Why the aggregation exists, and where it stops being right:** `fred_observations` was built for
  the socioeconomic catalog (GDP, unemployment, debt-to-GDP, inequality), where an annual mean is
  the correct summary. Treasury yields are daily instruments whose PATH is the information, so the
  shape is right for its original purpose and wrong for this one.
- **Standing:** the SI-027 policy is a DISCLOSURE PATCH over a fixable data path, not a workaround
  for a hard limit. Deferred by the user 2026-08-11 ("the disclaimer is sufficient for now").
- **Tests:** `tests/unit/test_chart_granularity_policy.py` (8), incl. one asserting the policy
  never promises daily/weekly/monthly data the tool cannot serve.


### SI-026 — A missing market value silently killed technicals AND charts  →  **FIXED 2026-08-11 (v1.0.0.251)**  [was P1, user-reported from production]
- **Reported:** user replied to an @Ask post — *"Show the 2 years chart of GPIQ"* — and got
  prose with **no chart** (sabawi.net/post/6502).
- **Gate chain traced end-to-end; the first three PASSED:** tool ALLOWED (in the @Ask
  whitelist) ✓ · tool SELECTED (`Generated tool calls: ['comprehensive_stock_analyzer']`) ✓ ·
  tool INVOKED ✓ · **marker PRODUCED ✗** — and not even the `chart NOT emitted` diagnostic
  fired, proving the block was never reached.
- **CAUSE (reproduced on prod, then locally):** the analyzer fills missing market fields with
  the **STRING `"N/A"`** (`market_cap`, `volume`, `pe_ratio`, `analyst_target`). GPIQ is an
  **ETF**: `quoteType: ETF`, marketCap/sector/industry `None`, all three financial statements
  empty. `"N/A"` is **TRUTHY**, so every guard of the form `if market_cap and ...` passed and
  the arithmetic raised — `market_cap / current_price` (shares outstanding), then
  `market_cap + total_debt - cash` (enterprise value). Both sit inside one broad `except`, so
  the detailed block aborted **silently**, taking the TECHNICAL ANALYSIS and the `[[chart:]]`
  marker with it.
- **Control run (prod, same build):** NVDA 12,634 chars / **4 charts** vs GPIQ 3,040 chars /
  **0 charts** — proving charts were healthy and the defect was ETF-specific, not global.
  A second control killed a red herring: `charts.enabled: false` in the config is an unused
  key; `charts_enabled()` returns True.
- **Fix:** module-level `_num()` coercion applied at the **single entry point** where market
  values are read, so all five arithmetic sites are covered at once. Fixing only the first
  crash was NOT enough — a second sentinel bug (`+` not `/`) surfaced immediately behind it.
- **Verified:** GPIQ 0→**4 charts**, QQQI 0→**4 charts**, NVDA/KO/JPM unchanged at 4.
  Pre-fix raises `TypeError: unsupported operand type(s) for /: 'str' and 'float'`; post-fix
  returns cleanly.
- **Scope:** affects EVERY instrument without a market cap — all ETFs, some ADRs and
  thinly-traded names — not just this ticker.
- **Tests:** `tests/unit/test_etf_sentinel_coercion.py` (18) — incl. a test pinning that
  `"N/A"` is truthy (the root cause), that a real `0.0` still survives coercion, and that the
  coercion stays at the single entry point.


### SI-025 — Duplicate YAML key halved the synthesis budget; flat truncation then destroyed computed tool output  →  **FIXED 2026-08-10 (v1.0.0.250)**  [was P0 — the product's flagship feature, unusable above ~3 tickers]
- **Reported by the user:** an 8-stock `@Ask` query returned *"No technical chart markers were
  provided in the evidence"* for **all 8** stocks and **zero DCF values**, while the July prod
  run on 7 stocks delivered per-stock charts AND per-stock DCFs. **I initially and wrongly
  claimed prod had never been asked a multi-ticker question — the user refuted it with the
  prod output. That claim is retracted.**
- **THREE COMPOUNDING DEFECTS:**
  1. **Duplicate YAML key (pre-existing, prod too).** `verification:` sat at synthesis-child
     depth with its five children at the SAME depth, so YAML made them `synthesis` siblings
     and the verifier's `evidence_token_budget: 87000` silently overrode
     `synthesis.evidence_token_budget: 160000` (last key wins). The code reads verification
     at ENGINE level, so its settings were never read at all. Three values ran at ~half their
     intended size for the config's whole life: synthesis budget 87,000 (vs 160,000),
     verify budget 47,850 (vs 87,000), verify max_tokens 12,000 (vs 24,000).
  2. **My SI-021 fix removed an accidental safeguard.** Prod's gap assessor was broken by a
     900-token cap, so DR stopped at 2 rounds / ~34K tokens — under budget BY LUCK. Reviving
     it took gathering to 4 rounds / ~206K tokens, overflowing an already-undersized budget.
     Correct research behaviour; it is why the user hit this and prod did not.
  3. **Flat fair-share truncation cut the wrong content.** Web prose is redundant; a tool
     block is not — its DCF, ratios and rendered chart exist in ONE place. Being the largest
     blocks they were cut hardest, and `_tok_truncate` keeps the HEAD while the analyzer
     appends its `[[chart:…]]` marker LAST, so the irreplaceable tail died first.
- **Measured on the user's exact profile (78 items / ~206K tokens):**

  | allocator | analyzer block kept | DCF + chart |
  |---|---|---|
  | OLD flat-share @87k (what ran) | **9%** | LOST |
  | OLD flat-share @160k (config fix ALONE) | **52%** | **still LOST** |
  | NEW priority @160k | **100%** | **SURVIVE** |

  The middle row is why the config fix alone was insufficient and the allocator had to change.
- **Fix:** (a) MERGE the stranded settings into the ALREADY-EXISTING `engine.verification:`
  block, and delete them from `synthesis:`. **First attempt was wrong and the repo's own
  `test_no_duplicate_yaml_keys_under_engine` caught it:** simply dedenting the stranded block
  created a SECOND engine-level `verification:`, and YAML taking the last silently downgraded
  `max_tokens` 32000 -> 24000 — reproducing the exact bug class being fixed. The merge keeps
  32000 and leaves exactly one block;
  (b) priority-aware allocation — computed sources (`synthesis.priority_sources`) are served
  first up to `priority_budget_ceiling` (0.70), remainder shared fairly; (c) rescue
  `[[chart:|image:|file:]]` markers from a truncated block and re-attach them.
- **VERIFIED END-TO-END on the user's exact 8-stock prompt (v1.0.0.250):**
  `synth chart-markers — evidence=20 prompt=40 draft=20`, `charts_required=20
  charts_placed=20`, **8/8 tickers with DCF values, 8/8 with charts and technicals**, and the
  phrase *"no technical chart markers"* appears **0** times (was 8).
  **Now exceeds prod:** 110 evidence vs 23, 277 sources vs 88, 20 charts vs 7, 8 DCFs vs 7.
- **Tests:** `tests/unit/test_evidence_budget_priority.py` — 10 tests; **5 fail cleanly** when
  only the config is reverted, and the regression test asserts the 160k-alone case STILL fails.


### SI-022 — A constant standing in for evidence in BOTH growth models  →  **FIXED 2026-08-10 (v1.0.0.248)**  [was P1, distorted every valuation]
- **Origin:** user's independent review of a real NVDA/AAPL report: *"rigorous-looking
  model → biased assumptions → predetermined conclusion."* Accurate on both counts.
- **(1) DCF flat cap overrode the blend.** `dcf_calculator.py` median-blended three growth
  signals then applied a flat 20% cap AFTER the blend. NVDA (live 2026-08-10):
  trailing 100.0%, analyst forward 43.3%, anchor 5.0% → median 43.3% → **capped to 20.0%**,
  a rate NEITHER real signal supported. Intrinsic **$83.05** vs price $221.57 (−62.6%), and
  the synthesising LLM wrote a paragraph disclaiming its own tool.
  **After:** growth 43.3%, intrinsic **$179.44**, −19.0%.
- **(2) Projections had no forward signal at all.** `projection_engine.py` extrapolated a
  capped historical CAGR while the DCF beside it in the same report blended one. CROX
  printed 20.0% while stating the raw 32.6% CAGR was "likely inflated by the HEYDUDE
  acquisition" and analysts implied 7.1% — detected the distortion, said so, used it anyway.
  **After:** 7.1%, matching the scope doc's predicted target exactly; revenue unchanged at
  4.4%, also as predicted.
- **Fix:** shared `evidence_aware_growth_cap()` — the cap steps aside only when BOTH
  independent real signals clear it (agreement is evidence, not an outlier), can only ever
  be RAISED, and excludes the injected anchor from the vote. Shared at module level so the
  DCF and the projections cannot drift apart again. Projections now median-blend the
  analyst forward consensus (EPS proxy for FCF, labelled).
- **Deviation from the signed-off scope §4.2** ("keep the 20% cap") — documented in the
  scope doc with rationale; §4.2's intent is preserved and CROX/KO are byte-identical.
- **Found by adversarial audit BEFORE shipping:** raising the base case above the flat 25%
  best-case ceiling made NVDA's "best case" **25% against a 42.6% base** — an optimistic
  scenario more pessimistic than the base one. Fixed and pinned by a parametrised test.
- **Two stale strings the change made FALSE, caught by reading the real output:**
  the DCF line still said "capped at 20%" beside a 43.3% number, and all three projection
  blocks still said "NOT analyst consensus estimates" when they now blend exactly that.
- **Behavioural change, stated not buried:** a stock with NO analyst coverage now blends
  two signals, and a median of two is their mean — growth is pulled toward the 5% anchor.
  Accepted deliberately: `dcf_calculator` has behaved this way since v1.0.0.176 and the
  point of SI-022 is that the two must agree.
- **Known limitation, NOT fixed:** AAPL still shows −49.1%. Its cap never binds (only one
  signal clears it); the low value comes from ~$90B/yr of buybacks suppressing trailing FCF
  growth to −3.9%. DCF for buyback-heavy mega-caps is a separate problem.
- **Tests:** `tests/unit/test_growth_blend_and_cap.py` — 17 tests, incl. the anchor-cannot-
  vote guard, the raise-only guard, and the scenario-ordering invariant.


### SI-021 — The DR gap-assessment loop was DEAD for 7 builds  →  **FIXED 2026-08-10 (v1.0.0.247)**  [was P0, silently degraded every DR answer]
- **Observed:** the user's `@Ask` benchmark prompt produced 4 rounds / 44 evidence / 171
  sources on PROD (pre-fix code) but **2 rounds / 19 evidence** locally — *identically on
  BOTH providers*, which is what exposed it.
- **Cause (CONFIRMED, reproduced and falsified):** SI-015 (v1.0.0.240) defined
  `_assess_max_tokens` on `ResearchPlanner` (engine.py:272) but it is consumed in
  `DeepResearchEngine._assess` (engine.py:724) — a different class. Every assessment
  raised `AttributeError: 'DeepResearchEngine' object has no attribute
  '_assess_max_tokens'`. `_assess` wraps the call in a bare `except Exception` whose
  legitimate purpose is "never lose a round to a transient assess error", so it logged a
  warning and returned `{"status": "sufficient"}`. **DR never requested another round on
  any prompt, for any provider, from v1.0.0.240 to v1.0.0.246** — while reporting success.
- **Why it hid:** nothing failed, nothing 500'd, answers still looked good. The sibling
  property `_planner_max_tokens` works because its consumer is in the same class, so the
  commit looked symmetric. Same class as the swallowed `NameError` that killed
  `search_web` for 6 days — see [[fastapi_server_re_import_gotcha]].
- **Fix:** moved the property to `DeepResearchEngine`.
- **Verified through the real @Ask path (not a unit test):** v1.0.0.247 / Ollama →
  **4 rounds, 40 evidence, 161 sources, 595,254 chars, stop=max_rounds, 0 truncations**,
  vs prod's 4 / 44 / 171 / 502,264 / max_rounds. Claims checked 123 with **3 unverified
  vs prod's 12**.
- **Collateral:** `docs/PROVIDER_AB_TEST_RESULTS.md` is **INVALID** — its entire DR half
  measured this dead loop in both arms. Banner added; must be re-run.
- **Tests:** `tests/unit/test_dr_gap_assessment_alive.py` — 3 of 5 FAIL on pre-fix code,
  including a behavioural test that reproduces the exact production warning line.


### SI-018 — `convert` rewrote NON-LLM service endpoints  →  **FIXED 2026-08-10 (v1.0.0.246)**  [was P1, self-inflicted]
- **Observed (2026-08-10, live):** a flood of `❌ Embedding generation failed: 404` →
  `❌ Batch failure: task 0 returned None` → `❌ UNHEALTHY`, ~3s apart, during a user query.
- **Cause (verified by diff against HEAD, not by inspection):** `convert --to <provider>` guarded
  transport rewrites with a **DENYLIST** — `_INERT_SEGMENTS = {model_presets, fallback, providers}` —
  i.e. "any block that is not one of these is an LLM lane." False. The config also holds non-LLM
  services carrying `base_url`/`api_key`. A real conversion rewrote **10 lines across 5 services**:
  - `document_interrogator.embedding.service` → DeepInfra, while `model_name:` stayed
    `text-embedding-3-small`. Discovery matches `model`/`*_model`/`selected_model` — **not**
    `model_name` — so the model was left behind and every embedding call 404'd.
  - `flight_search.apis.{amadeus,skyscanner,serpapi,rapidapi_skyscanner}` → vendor API keys
    replaced with `${DEEPINFRA_API_KEY}`.
- **Root defect:** `_discover_lanes` and `_write_conversion` DISAGREED about what a lane is. The
  denylist had to be maintained in parallel with discovery, and was not.
- **Fix:** the transport allowlist is now derived from the conversion plan itself — a block is
  transport-converted only if a model *inside it* is being converted. Discovery and rewriting agree
  by construction, so a new non-LLM service can never be swept in.
- **Verified through the real command, not just unit tests:** `convert --revert` → byte-identical to
  HEAD; `convert --to deepinfra` → **10 LLM-lane transport lines converted, 0 non-LLM lines touched**;
  all 5 previously-corrupted services intact. Embedding endpoint re-invoked directly: HTTP 200,
  1536-dim vector. Test `test_non_llm_service_blocks_are_never_rewritten` FAILS on the pre-fix code.
- **Note:** the FRED/World-Bank `discovery.type` lines were *suspected* but proved **not** corrupted —
  the `_KNOWN_PROVIDERS` condition already excluded them. Confirmed by diff before claiming impact.

### SI-019 — Embedding recovery was an UNBOUNDED detect/compensate loop  →  **FIXED 2026-08-10 (v1.0.0.246)**  [was P1, pre-existing]
- **Observed:** **6,614 recovery cycles** and a **9.1 MB** log from one bad endpoint, still spinning
  when found, at `Progress: 0/5 embeddings processed` throughout.
- **Cause:** the `for restart_attempt in range(2)` budget lives **inside** the `while processed_count`
  batch loop it is meant to bound, so it restarts at 1 on every iteration and can never be exhausted.
  `_restart_embedding_service()` returns `True` **unconditionally** for any non-Ollama provider
  ("cloud-based, no restart needed") **without verifying anything**, so the code logged
  `✅ Embedding service recovered successfully` 6,614 times while the service was dead, then
  `continue`d. Classic control loop: it reacted to an actor that simply acted again, with no damper.
- **Fix:** `recovery_cycles` is scoped to the whole call (initialised *before* the `while`), checked
  *before* recovery is attempted, and `return`s rather than `continue`s. Bound is config-driven
  (`batch_processing.max_recovery_cycles: 3`). The false-success log line now reads
  `↩️ ready to retry (recovery reported OK — not yet verified)`, and the give-up message names the
  likely cause: a `base_url`/`model_name` mismatch.
- **Independent of SI-018.** That bug only supplied the trigger; this one fires on ANY persistent
  embedding failure (vendor outage, expired key, quota wall).
- **Tests:** `tests/unit/test_embedding_recovery_damper.py` — 6 of 7 FAIL on pre-fix code.

### SI-020 — The version-sync gate was a SILENT NO-OP under pytest  →  **FIXED 2026-08-10 (v1.0.0.246)**  [was P2]
- **Observed:** `pytest tests/integration/test_version_sync.py` reported **5 passed** while
  `README.md` was a build stale (`1.0.0.245` vs `1.0.0.246`) **and** `logging_config.json` had drifted.
  Run as a script the same file correctly printed 5 ✗ and exited 1.
- **Cause:** `check()` only prints and bumps a module counter — deliberately, so script mode reports
  EVERY drifted surface rather than stopping at the first. But nothing ever asserted, so each test
  function returned normally regardless. The gate written to stop version drift did not gate in the
  runner most likely to be used casually.
- **Fix:** a `@gates` decorator on all 5 test functions asserts the failure counter did not move.
  A decorator rather than an autouse fixture: a fixture asserts during TEARDOWN, which pytest reports
  as `5 passed, 1 error` — the same misreadable green. Script mode is unchanged (still collects all,
  exits 1). Falsified: breaking the README badge now yields `1 failed, 4 passed`.

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
