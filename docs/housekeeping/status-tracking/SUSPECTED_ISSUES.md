# Suspected Issues Log

Per the global directive *"NEVER dismiss a possible bug without evidence — if busy, log it with a priority
call; clear it only on evidence or a verified fix."* Open items are things NOTICED but not yet confirmed
as bug-or-not. **Do not delete an item on a hunch** — resolve it with evidence (real bug filed/fixed, or
proven not-a-bug) and move it to Resolved with that evidence.

Priority: **P1** act now · **P2** investigate soon · **P3** watch / low-impact.

---

## Open

### SI-062 — 59 integration tests fail under a full pytest run, and no report has ever covered them  [P3 — LOGGED, 2026-08-17]
- **Observed:** `pytest tests/unit tests/integration` gives **63 failed / 707 passed**. Verified
  identical (63, same test IDs) on a clean `HEAD` worktree, so this is pre-existing, not a regression.
- **Why it was never visible:** every changelog reports "**552 passed, 4 pre-existing failures**".
  That figure is `tests/unit` ONLY — and `tests/unit` does indeed fail exactly 4. The 59 integration
  failures have simply never been inside the reported scope, so the number looked healthy for months.
- **Not explained by a missing server:** a healthy server was running on :5000 during both runs.
- **Largest cluster:** `test_intent_classifier_characterization.py` (19), `test_tool_calling_retry.py`
  (5), `test_user_tools_integration.py` (3). Note `test_tool_calling_retry.py` and
  `test_dr_title_extraction.py` **pass** when run as standalone scripts in Tier-0 (10/10), so at
  least some of these are pytest-harness/async-collection artifacts rather than product defects —
  which is a hypothesis, not a finding.
- **Evidence needed to clear:** classify all 59 into (a) harness artifacts, (b) tests asserting
  behaviour that legitimately changed, (c) real product defects. Only (c) is a bug; (a) and (b) are
  test debt that is currently hiding (c).
- **Priority rationale:** P3 because it is long-standing and stable, but it is exactly the shape of
  the swallowed-error class this log exists for — a broad green headline over an unexamined red.

### SI-064 — a Deep Research request on LIVE went silent mid-flight and never completed  [P1 — OPEN, 2026-08-17]
- **Observed on live (`2f5a2e6`, v1.0.0.284), not local.** Sent the S2 benchmark prompt
  ("Deep research the history of jazz music in America … Save the result as a PDF file and an
  HTML file") to `localhost:5000/v1` ON the live host. Client waited **1800s and received 0
  bytes**. The server log's LAST line was at **14:56:05** ("Web search completed") and it wrote
  **nothing for the next ~30 minutes** — no `Deep research complete`, no `Stage 2 timings`, no
  error, no traceback.
- **Not a client-disconnect artifact:** the log went silent at 14:56:05 while the client stayed
  connected until 15:17. Twenty-one minutes of in-flight silence BEFORE the client gave up.
- **The server did not crash:** `/health` answered normally throughout, the process stayed up
  (48h uptime) and is now idle at 0.2% CPU. One request went nowhere; the server is fine.
- **Intermittent, not universal:** an earlier DR on the same live host completed normally —
  `Deep research complete: 4 rounds, 42 evidence items, 271 unique URLs, 91.7s` /
  `pipeline complete in 289.8s`. The user separately ran a DR on live the same day and judged
  the output good.
- **NOT caused by any change of ours.** Live is v1.0.0.284 and was not modified; it was only
  sent a request.
- **SUSPECTED (explicitly not confirmed):** an upstream call hung and RAICA's timeouts are long
  enough to mask it — the code logs `PRIMARY LLM: Starting with 45 minute timeout`, so a stalled
  provider or search call would look exactly like this: total silence, no error, healthy process.
  29 throttle events were recorded in the slice, and live's datacenter IP is already documented
  as more bot-blocked than a residential one (see the search_web egress action item).
- **Discriminator NOT yet tested:** this prompt requests PDF+HTML delivery; the successful runs
  did not. That is a hypothesis, not a finding.
- **Evidence needed to clear:** re-run the identical prompt on live 3x and record the completion
  rate; add a heartbeat/watchdog log inside gather so a stalled upstream call is visible instead
  of silent; capture which call is outstanding when it stalls (thread dump / py-spy).
- **Why P1:** a user-facing request that hangs for 30+ minutes with no error is worse than a
  failure — the caller has no signal at all. Frequency is unknown.

### SI-063 — S2 `dr_latency_s` exceeds tolerance, localized to GATHER, and throttle does NOT explain it  [P2 — OPEN, 2026-08-17]
- **Observed (v1.0.0.299 Tier-1):** `S2_dr_delivery.dr_latency_s` **354.5s** vs baseline
  **140.7s** (tolerance 120, so the bar is 260.7). Sole non-PASS row in the run; every CODE
  metric passed and `citation_count` was an IMPROVEMENT (16 vs 13).
- **ATTRIBUTION CORRECTED 2026-08-17 — the first one was an arithmetic artifact.** I computed
  `total − synthesize − verify`, labelled the remainder "gather+other", and then reported it as
  gather (+84%). But the server METERS plan and gather explicitly
  (`🧭 Deep research complete: … (plan Xs + gather Ys)`), and measured gather barely moved:
  **75.0s → 87.1s**. The residual was mostly phases I had not accounted for. Never infer a
  phase by subtraction when the phase is instrumented.
- **Real decomposition of the 354.5s (v299 S2), from the log:**
  plan 22.0 (6%) · gather 87.1 (25%) · grade 8.2 (2%) · synthesize 82.0 (23%) · verify 53.8 (15%)
  · **unmetered inside the pipeline 62.7 (18%)** · **delivery + streaming 38.7 (11%)**.
  Metered stages sum to 253.1s against a pipeline total of 315.8s and a client-observed 354.5s,
  so **~101s (29%) of wall time sits in gaps nothing measures.**
- **What the volumes rule out:** v299 gathered LESS than the faster v297 run — 25 evidence items
  / 89 URLs / 129,579 chars vs 31 / 66 / 129,077 — and every run stops at `max_rounds` (4), so
  extra rounds, source count and ingest volume are all refuted as the cause.
- **The volatile phases are LLM calls, not retrieval:** synthesize across runs 77.3 / 202.8 /
  82.0 / 133.7; verify 124.7 / 133.1 / 53.8 / 188.4. DR latency is dominated by generation plus
  unmetered overhead.
- **What REFUTES the easy explanation:** throttle in that scenario was **59** events this run
  versus **76** in the previous one — *lower* throttle with *higher* gather latency. A simple
  "more rate-limiting = slower" story is contradicted by the data, so it is not recorded as
  the cause. Plausible but UNVERIFIED alternatives: 429 backoff duration (not event count) is
  the real cost driver; slow-but-successful responses add latency without incrementing the
  counter at all; DR plans queries dynamically so two runs do not issue the same work.
- **Baseline is provider-comparable** — measured 2026-07-23, Ollama era, so this is not a
  DeepInfra-vs-Ollama artifact. That was checked, not assumed.
- **n=1.** S2 declares `MAX_REPEATS=1` (DR is expensive), so there is no within-run spread.
  Observed history: 140.7 (baseline), 232.7, 700.1 (client timeout, see v299), 354.5. The
  spread straddles the tolerance, which may mean the tolerance is too tight for this metric —
  but widening a tolerance because a run failed it is the "soften the metric that moved
  against you" trap, so nothing has been changed.
- **Evidence needed to clear:** accrue 3–5 more S2 measurements now that runs are archived
  with per-repeat samples (v1.0.0.297), and instrument gather with the 429 *backoff seconds*
  rather than the event count. If the centre really has moved, rebaseline with a stated
  reason; if it is variance, widen the tolerance with the distribution as justification.
- **Not a deploy blocker:** PERF only, single sample, all quality metrics intact.

### SI-055 threshold half — the guard over-fired and called four healthy runs unmeasurable  [RESOLVED v1.0.0.298, 2026-08-17]
- **Observed:** a single throttle threshold (150) marked a run INCONCLUSIVE regardless of what
  the metrics said. Four runs were falsely invalidated; the clearest had **33/33 rows PASS** and
  `citation_count` samples `[14, 14, 14]` against a baseline of 13 — zero within-arm variance.
- **Refuted premise:** the guard asserted "an empty result is indistinguishable from a real
  regression". Nothing was empty. The run's own data killed the premise.
- **Why it mattered:** a false INCONCLUSIVE blocks a good deploy AND trains the reader to
  discount the suite — the same harm the guard was written to prevent, from the other side.
- **Fix:** degradation is now CONJUNCTIVE — ceiling exceeded, OR elevated throttle AND a real
  retrieval collapse (`scoring.retrieval_collapsed`, derived from the 2,806-event run's
  signature: a higher-better CODE metric hitting zero against a non-zero baseline; no metric
  name list). Two levels: ELEVATED_AT=150 (report only), CEILING=800 (geometric mean of the
  measured good/bad boundary, 226 vs 2,806 — honest about a wide unknown).
- **Also made STRICTER where it was too lenient:** a collapse with NORMAL traffic is now a
  REGRESSION, not INCONCLUSIVE. The old rule could not express that case and excused real bugs.
- **Verified:** the real v297 archive re-scores INCONCLUSIVE → PASS; truth table exercised in
  all four corners; identical input returns INCONCLUSIVE at HEAD and PASS now; 13 new tests.

### SI-060 — A `git pull` deploy silently migrates the LIVE provider, and would have 401'd every lane  [P1 — CONFIRMED + FIXED, 2026-08-17]
- **Observed:** live (`2f5a2e6`) runs every lane on Ollama at `127.0.0.1:11434`. `HEAD` pointed every
  lane at `https://api.deepinfra.com` — residue of a LOCAL trial that got committed. Live's `.env`
  has **no `DEEPINFRA_API_KEY`** (measured, not inferred: `grep -c` returned 0).
- **Impact if deployed:** 401 on every LLM call — primary, tool-calling, arbitrator, DR, convergence,
  codegen, vision. A total outage, from a change nobody asked for. "Deploy the fixes" reads as a code
  deploy; the pull carries `config/llm_config.yaml` too.
- **Why nothing caught it:** every existing check validates the config against the machine it is ON
  (`doctor`, the lane suite, the Tier-0 transport gate) — where the key exists. None asked whether the
  config that is about to LAND works on the host it is landing on. The secret that decides it lives
  outside the repo, so no diff review could see it either.
- **How it surfaced:** the user disputed a claim that live was broken, having just run a real DR query
  on live with a good result. Checking live's actual config refuted my claim (SI-056/057 were
  LOCAL-ONLY) and exposed this instead. Two false production claims in one session, same disposition:
  reasoning about production from local state instead of measuring it.
- **Fix:** `tools/deploy_preflight.py` — compares the incoming config against the target's CURRENT
  config and env. Reports (1) any lane whose endpoint host changes, (2) any `${VAR}` an incoming
  active lane needs that is absent on the target. Exit 0 GO / 1 NO-GO / 2 GO-WITH-DECISION.
  Secrets are read by NAME only; no value is ever transferred or printed.
- **Falsified:** NO-GO (exit 1) on `HEAD`→live naming `DEEPINFRA_API_KEY` × 11 lanes; GO (exit 0) on
  live's own config → live. Tests in `tests/integration/test_deploy_preflight.py`.
- **Status:** repo config converted back to Ollama via the configurator; preflight against live now
  **GO — no provider migration, no missing credentials**.

### SI-061 — `convert` to a keyless provider strands the previous provider's credential  [P2 — CONFIRMED + FIXED, 2026-08-17]
- **Observed:** after `convert --to ollama`, three lanes read `api_key: ${DEEPINFRA_API_KEY}` while
  sitting on `http://127.0.0.1:11434` (`llm.primary`, `vision.model`, `vision.fallback_model`).
- **Cause:** `API_KEY_ENV_VARS['ollama'] is None`, so `_target_transport` returned `api_key: None`,
  and the writer's rewrite branch (`if ... tgt_block.get('api_key')`) never fired. The stale line
  simply survived.
- **Exact mirror of SI-017**, which fixed keyless→keyed (INSERT a key). The keyed→keyless direction
  (NEUTRALISE a key) was never fixed.
- **Why it matters beyond cosmetics:** Ollama ignores the key, so this looked harmless — but the same
  branch strands `DEEPINFRA_API_KEY` on an **OpenRouter** endpoint, which is a 401, and it silently
  drifted the repo config away from the deployed one.
- **Fix:** for a target needing no credential, `_target_transport` now yields the provider name as a
  literal (`"ollama"`) rather than `None`. Not deletable: lanes declared `type: openai` against a
  local Ollama endpoint go through an OpenAI-compatible client that requires a non-empty token — and
  this reproduces exactly what the deployed config already carries.
- **Falsified:** 8/8 in `test_deploy_preflight.py`; the repo-wide `test_the_shipped_config_has_no_stranded_credential`
  FAILED naming all three lanes before the re-conversion and passes after.

### SI-059 — On Ollama, a lane's configured `max_tokens` is ignored; `num_predict` falls back to 16384  [P2 — CONFIRMED, 2026-08-16]
- **Observed:** `llm.tool_calling.config.max_tokens: 8192`, but the effective Ollama budget is
  **num_predict=16384**. `ollama.py::_wire_params` falls through to `self.get_num_predict()`, which
  reads `config['num_predict']` — a key the lane does not set — and defaults to 16384. The lane's
  `max_tokens` is never consulted when no caller kwarg is present.
- **Same class as SI-057:** a value declared in config is silently ignored at the transport. The
  openai path honours it (`get_max_tokens()` → 8192); the ollama path does not. The two transports
  disagree about the SAME lane config, which is exactly what `param_map` exists to prevent.
- **Not fixed immediately, on purpose:** discovered mid-A/B (GLM-5.2 vs DeepSeek-V4-Flash on Ollama).
  BOTH arms run at 16384, so the comparison is unaffected — changing the budget between arms would
  confound the very experiment it was found during. Fix after the A/B completes.
- **Fix:** `_wire_params` should fall back to `config['num_predict']` THEN `config['max_tokens']`
  before the 16384 default, so a lane that declares only `max_tokens` is honoured on both transports.
- **To clear:** effective num_predict equals the lane's configured max_tokens on Ollama, with a test
  that fails on the current fallback order.


### ~~SI-058~~ — The provider converter was SINGLE-USE: a converted line could never convert again  [RESOLVED v1.0.0.290, 2026-08-16]
- **Found by a user-requested full-circle test** (Ollama → DeepInfra → OpenRouter → Ollama). A single
  forward conversion always looked perfect; only a round trip exposed it.
- **Mechanism:** `_write_conversion` did `if self._CONVERT_TAG in line: continue`, so every line it had
  ever tagged was skipped by all later switches. Lanes converted per arm decayed **9 → 2 → 4 → 0 → 0**,
  leaving the config permanently half on each provider — `primary` on Ollama while `deep_research`,
  `convergence` and `code_generation` kept DeepInfra slugs and inherited the Ollama endpoint.
  **The tool built to prevent SI-057 was re-creating it.**
- **Also fixed:** the Ollama catalog was unreachable (`{base}/models` 404s; the OpenAI-compatible
  listing is `{base}/v1/models`), so `convert --to ollama` failed outright and every Ollama model
  would have looked UNSERVED to the invocation check.
- **Also added:** `_MODEL_MAP` for explicit cross-provider substitutions where no exact equivalent
  exists, printed as `MAPPED — model CHANGES` so a deliberate change is never mistaken for identity.
- **Verified:** circle re-run with **0 consistency problems on every arm**; DeepInfra **ALL 11 LANES
  LIVE** twice. Remaining live-lane failures are external and expected: Ollama `429 weekly usage
  limit`, OpenRouter `402 Insufficient credits`.
- **KNOWN LIMITATION (open):** round-trips through a MAPPED lane are LOSSY — A→B→A does not restore
  A's model (primary lost its `-0813` pin; vision came back as MiniMax-M3/Kimi-K2.6). The original is
  preserved in each line's `(was ...)` tag, so `convert --revert` recovers it. Config was restored to
  the intended baseline after the test.


### ~~SI-057~~ — `doctor` gave a clean bill of health to SIX 404-ing lanes  [RESOLVED v1.0.0.289, 2026-08-16]

> **SCOPE CORRECTION (2026-08-16, verified against the live server): LOCAL ONLY.**
> These lane mismatches were created by the LOCAL DeepInfra trial and never reached production.
> Verified by reading sabawi.net's actual `config/llm_config.yaml` over SSH, not by inference:
> every live lane is an Ollama `name:cloud` slug at an Ollama endpoint
> (`primary: deepseek-v4-pro:cloud`, `tool_calling`/`arbitrator: glm-5.2:cloud` at
> `127.0.0.1:11434/v1`, `api_key: "ollama"`), which is CONSISTENT — no 404s, no dead lanes.
> The `api.deepinfra.com` line in the live file sits inside the dormant `providers:` block.
> The config's own comments say "LOCAL DEEPINFRA TRIAL" and "LOCAL trial first".
>
> The "178 attempts / 1 success" measurement is real but is a LOCAL measurement.
>
> **How the error happened:** I reasoned from my local config's history and asserted it about
> production without reading live's file — and then used that false premise to argue for an
> urgent deploy. The user caught it by running a real Deep Research prompt on live and getting
> a well-researched answer. A claim about production requires reading production.

- **Found because the user asked why the provider switch had not been done with the configurator.**
  It had not been used at all — the migration was hand-edited, so lanes were converted piecemeal.
- **Six ACTIVE lanes were dead:** `deep_research.engine.model` / `.heavy_model`,
  `convergence.shadow_classifier`, `convergence.intent_classifier`, `code_generation.selected_model`
  / `.classification_model` — all Ollama `name:cloud` slugs INHERITING the DeepInfra endpoint.
  Verified: `deepseek-v4-flash:cloud` → HTTP 404. Deep Research, the authoritative intent
  classifier and code generation were all non-functional.
- **Why nothing saw it:** `_ENDPOINT_MODEL_PREFIXES` had no `api.deepinfra.com` row, so a DeepInfra
  endpoint matched no rule, fell past the Ollama-only branch and returned "fine". `doctor` printed
  **"✓ Every active lane's model matches its endpoint."** A false clean bill of health is worse than
  no check: it is the reason a paid 40-minute benchmark was run against a broken config.
- **Fixed:** provider-agnostic invariant (Ollama `name:tag` vs remote `vendor/model`) so a NEW
  provider is covered on the day it is added; `convert` now INVOKES on a catalog miss instead of
  trusting a `/models` listing; a single-file live lane suite calls EVERY lane with a real prompt;
  and that suite plus a consistency check now run MANDATORILY after every `convert` and `--revert`.
- **Verified:** real conversion → 14 lanes converted, **ALL 11 LANES LIVE** in ~11s. Falsified by
  injecting a left-behind lane: reports `✗ MODEL/ENDPOINT MISMATCH` + `LANE SUITE FAILED — 1/11` →
  `FAILURE`, exit 1; exit 0 when healthy. Tier-0 10/10, unit 552 passed.
- **Standing rule:** provider changes are made with
  `./config_server_cli.py convert --to <provider> --yes` — never by editing llm_config.yaml.


### ~~SI-056~~ — Ollama→DeepInfra migration left two lanes behind  [RESOLVED v1.0.0.288, 2026-08-16]

> **SCOPE CORRECTION (2026-08-16, verified against the live server): LOCAL ONLY.**
> These lane mismatches were created by the LOCAL DeepInfra trial and never reached production.
> Verified by reading sabawi.net's actual `config/llm_config.yaml` over SSH, not by inference:
> every live lane is an Ollama `name:cloud` slug at an Ollama endpoint
> (`primary: deepseek-v4-pro:cloud`, `tool_calling`/`arbitrator: glm-5.2:cloud` at
> `127.0.0.1:11434/v1`, `api_key: "ollama"`), which is CONSISTENT — no 404s, no dead lanes.
> The `api.deepinfra.com` line in the live file sits inside the dormant `providers:` block.
> The config's own comments say "LOCAL DEEPINFRA TRIAL" and "LOCAL trial first".
>
> The "178 attempts / 1 success" measurement is real but is a LOCAL measurement.
>
> **How the error happened:** I reasoned from my local config's history and asserted it about
> production without reading live's file — and then used that false premise to argue for an
> urgent deploy. The user caught it by running a real Deep Research prompt on live and getting
> a well-researched answer. A claim about production requires reading production.

- **Fixed:** arbitrator repointed to DeepInfra; vision moved to `Qwen/Qwen3-VL-235B-A22B-Instruct` +
  `meta-llama/Llama-3.2-90B-Vision-Instruct` (both verified BY INVOCATION on a real test image);
  new Tier-0 gate `test_lane_transport_consistency.py` makes the class impossible to commit again.
- **Verified:** arbitrator **3 attempts / 3 validated / 0 regenerations** (was 178/1/34); vision 3/3
  runs naming red, blue, SEVEN, circle, square; answers 3/3 statistically exact with 0 fabrications
  and 3/3 chart markers serving HTTP 200 image/jpeg; latency 300s+ → 27-33s. Tier-0 10/10, smoke 6/6,
  unit 552 passed. Gate falsified by reverting the config.
- **Also fixed:** three `image_to_text` unit tests were coupled to the production config (patched the
  Ollama path, passed by accident); they now pin their transport explicitly.
- ~~Original entry below~~ [P0 — CONFIRMED by invocation, 2026-08-16]
- **Found by the user asking whether the provider switch accounted for the vision models.** It did not,
  and the arbitrator is worse.

| lane | type | model | base_url | state |
|---|---|---|---|---|
| primary | openai | deepseek-ai/DeepSeek-V4-Pro-0813 | api.deepinfra.com | OK |
| tool_calling | openai | zai-org/GLM-5.2 | api.deepinfra.com | OK |
| **arbitrator** | openai | **zai-org/GLM-5.2** | **127.0.0.1:11434/v1** | **404 on every call** |
| **vision** | **ollama** | minimax-m3:cloud + kimi-k2.6:cloud | 127.0.0.1:11434 | **quota 429, primary AND fallback** |

- **Arbitrator (P0):** a DeepInfra model slug is pointed at the LOCAL OLLAMA proxy. Verified by
  invoking it: `HTTP 404 {"message":"model 'zai-org/GLM-5.2' not found"}`. Tonight's log:
  **178 attempts, 1 successful validation, 34 exhausted-all-5 failures.**
- **This is the CAUSE of the trigger behind SI-048/051/052.** A failing arbitrator regenerates tools up
  to 5x per request; the regeneration path then discarded every prior result. v1.0.0.287 made the
  system RESILIENT to that loop — it did not stop the loop. Both halves are needed.
- **Vision (P1):** the only lane still on Ollama, and both its models now return
  `status code: 429 ... you have reached your ...`. DeepInfra equivalents verified BY INVOCATION
  (they described a test image, not merely returned 200):
  `Qwen/Qwen3-VL-235B-A22B-Instruct` and `meta-llama/Llama-3.2-90B-Vision-Instruct` (different family,
  preserving the existing fallback-diversity rationale).
- **Why nothing caught this:** the parity work (v1.0.0.285) audited PARAMETERS across providers and the
  contract test asserts a provider CONSUMES what callers pass. Nothing asserts that a lane's MODEL is
  actually SERVED BY that lane's BASE_URL. That is a reachability check, and it belongs in Tier-0.
- **Caveat on recent verification:** every E2E run in v1.0.0.285-287 executed with a dead arbitrator.
  The fixes verified there stand on their own evidence, but system behaviour with a WORKING arbitrator
  is UNMEASURED.
- **To clear:** repoint arbitrator base_url to DeepInfra; repoint vision to the two verified DeepInfra
  models; add a Tier-0 lane-reachability gate that INVOKES each configured lane; then re-verify.
  Repointing a lane is a behaviour change — measure it, do not assume it (PARITY plan §7.1).


### ~~SI-055~~ — Tier-1 self-throttled its search egress and reported false CODE REGRESSIONs  [RESOLVED v1.0.0.291, 2026-08-16]
- **Fixed:** `tests/benchmark/lib/throttle.py` counts 429/captcha responses in the run's own log
  slice; a degraded run reports the new **INCONCLUSIVE** verdict (exit 2) instead of PASS or
  REGRESSION, keeps the raw per-metric observations (flagged `unreliable`), shows the evidence, and
  is REFUSED as a baseline. Threshold 150 derived from the measured distribution (normal 2-17,
  heavy-but-usable 55-99, the failed run 2,806).
- **Verified without paid runs:** 6 tests, 3 fail on pre-fix code; the detector flags the real
  2,806-event archived log and clears every healthy one. A healthy run with the same collapsed
  metric still reports REGRESSION — the guard is not a blanket excuse.
- ~~Original entry below~~ [P1 — CONFIRMED, 2026-08-16]
- **Observed (v1.0.0.287, 00:35-01:15):** `make benchmark-full` returned **SUITE: REGRESSION** with
  `S1 citation_count 0` (base 13), `S1 specific_url_ratio 0` (base 1), `S2 dr_completed False`,
  `attachment_count 0`, `pdf_valid False`, `S3 vision_ran False`, `S4 answer_chars/evidence_items/
  unique_sources 0`. The harness tagged nearly all of these **CODE**, not ENV.
- **They are NOT code.** Rate-limit events per 30-min bucket on the SAME build:

  | window | 429 / captcha | what ran |
  |---|---|---|
  | 23:00-23:30 | **0** | 6 E2E runs — correct stats, tables, 4/4 charts delivered |
  | 00:00-00:30 | **1,015** | benchmark |
  | 00:30-01:00 | **976** | benchmark |
  | 01:00-01:30 | 622 | benchmark tail |

  Total tonight: **2,922 HTTP 429 + 1,249 Google captcha pages**. Tool SELECTION was healthy
  throughout (`TOOLS EXECUTED: search_web, get_news_summaries, ...`) — the searches simply returned
  nothing. S3 vision has an explicit, separate cause: Ollama cloud quota, primary AND fallback,
  `status code: 429 ... you have reached your ...`.
- **Mechanism:** the suite runs S1 x3, S3 x3, S4 x3 over 8 tickers across several engines. That volume
  trips the engines' rate limiters, and the resulting empty results are then scored as code
  regressions. **The benchmark fails itself**, and its ENV-vs-CODE classifier does not catch it.
- **Why P1:** this is a measurement-integrity defect. It produces false CODE-REGRESSION verdicts that
  would block a good deploy, and — worse — it trains the reader to discount the suite, which is
  exactly how a REAL regression gets waved through. It also means **no valid baseline can be captured
  while it persists.**
- **Do NOT rebaseline from a throttled run.** Baking these numbers in would make every future
  comparison meaningless.
- **To clear:** detect throttling as a first-class ENV signal (count 429/captcha responses per run and
  mark affected metrics ENV, not CODE), and/or stagger + cache search across repetitions. Then a clean
  Tier-1 with 0 throttle events, and only then `--update-baseline --reason`.


### ~~SI-054~~ — Smoke gate failed a deploy on a cold-start timeout  [RESOLVED v1.0.0.293, 2026-08-16]
- **Fixed:** retry exactly once, on TIMEOUT only. A second timeout is still a failure but reads
  `TIMED OUT twice at 30s each`, not `RAISED TimeoutError`. A pass needing the retry is disclosed,
  so a flaky tool never looks clean. The timeout was NOT widened.
- **Verified:** 4 tests, all 4 fail on pre-fix code; `make smoke` PASSED 6/6.
- ~~Original entry below~~ [P2, 2026-08-15]
- **Observed:** `make smoke` failed with `get_news_summaries: RAISED TimeoutError`, blocking the deploy
  per protocol. Re-run immediately after: **PASSED**, `get_news_summaries 4847 chars`.
- **Not a tool defect (measured):** invoked directly with the smoke's exact args 3x — **2.5s / 0.5s /
  0.4s**, 4847 chars each. The tool is healthy; the first (uncached) call is the slow one, and
  `tests/smoke/tool_smoke.py:65` sets `PER_CALL_TIMEOUT = 30`.
- **Why it matters in BOTH directions:** a spurious CODE-FAIL blocks a good deploy, and — far worse —
  a gate known to "just be flaky" is a gate whose real failures get waved through. That is precisely
  how search_web stayed dead for 6 days.
- **To clear:** either warm the feed cache before timing, or give this one tool a longer budget with
  the reason stated inline; then 3 consecutive clean `make smoke` runs from cold.


### ~~SI-051~~ — A published chart never reached the user  [RESOLVED v1.0.0.287, 2026-08-15]
- **Same root cause as SI-048:** regeneration discarded plot_data's result, so the marker never
  entered the synthesis context. Proof it was PLUMBING not policy: every `[[chart:` occurrence
  in the synthesis prompt came from the INSTRUCTION text — no real marker was ever present.
- **Verified 6 E2E runs, 2 datasets:** charts published == markers delivered, **4/4, zero loss**.
  All four delivered URLs serve real images (HTTP 200, 51-67 KB, image/jpeg). The 2 runs
  without a marker published **0** charts — tool SELECTION variance, not delivery.
- ~~Original entry below~~ [P1 — CONFIRMED e2e, v1.0.0.285]
- **Observed (3/3 E2E runs, 2026-08-15, NewX live):** `plot_data` published a real chart in every run —
  `📊 plot_data: 1 series x 225 points → /static/images/media/9e6e348….jpg` — and all three URLs serve
  **HTTP 200, image/jpeg, 42–66 KB**. The RAICA→NewX bridge is fully working.
- **But the answer contained ZERO `[[chart:…]]` markers in all 3 runs.** The user sees no chart.
- **Mechanism (suspected):** the synthesis model, seeing the compute failures of SI-050 in the same
  context, wrote a refusal ("I cannot complete this request", 2/3) instead of reproducing the marker it
  had been handed. The marker survives to the tool result; it dies at synthesis.
- **Why this is P1:** every layer below works and the deliverable still does not arrive. This is the
  last link of the chart chain (ALLOWED → SELECTED → INVOKED → PRODUCED → **SURVIVES SYNTHESIS** →
  RENDERS) and it is the one now failing.
- **To clear:** an E2E run where the answer carries a marker whose URL returns an image. Do NOT clear on
  a server-side "chart published" log line — that is what looked like success here.

### ~~SI-053~~ — Column-less reference not recognised  [RESOLVED v1.0.0.294, 2026-08-16]
- **Fixed with the index-aware rule this entry itself prescribed** — NOT by widening the predicate.
  A column-less dict is a reference only when its `from` names an id present in the batch index:
  `{"from": "compute#1"}` resolves; `{"from": "2026-01-01", "to": "2026-06-30"}` is left alone.
- **Verified:** 14 tests; the resolution test fails on pre-fix code, and the date-range guard passes
  both ways by design (it is the over-widening check). Resolver suites unaffected: 45 passed.
- ~~Original entry below~~ [P3, 2026-08-15]
- **Found by:** the SI-050 generalization matrix (`tests/unit/test_corrected_tools_generalization.py`),
  not by an E2E run — three runs of one prompt could never have surfaced it.
- **Mechanism (confirmed by test):** `utils/tool_output_reference.py:349` —
  `_is_reference` requires **both** `from` and `column`. A compute output genuinely has no columns
  (SI-047), so `{"from": "compute#1"}` is a plausible shape; it is not recognised, passes through raw,
  and numpy renders it as `array(['from'])` — the same failure class as SI-050.
- **Why it is P3, not P1:** the contract per SI-047 is that the model supplies a `column` out of habit
  and it is IGNORED for computed series, and **I have no evidence the model omits it.** The production
  `plot_data` failures I checked were a different cause entirely (the model INLINED
  `x: list[24]['float']` instead of referencing). Recorded as suspected, not asserted.
- **Do NOT fix by widening the predicate.** Treating a bare `from` as a reference would also capture
  legitimate arguments such as `{"from": "2026-01-01", "to": "2026-06-30"}`. The safe rule is
  index-aware: it is a reference if `from` names an id present in the reference index.
- **Current behaviour is pinned** by `test_a_column_less_reference_is_not_silently_executed_as_key_names`
  so a partial change cannot land unnoticed.

### ~~SI-052~~ — No output-size guard on synthesis  [RESOLVED v1.0.0.293, 2026-08-16]
- **Fixed:** `openai.py::generate_stream` tracks a consecutive-whitespace run (>400) and total
  emitted chars (>400,000) and BREAKS on either — the lines that make an unbounded run impossible.
  Reported in-band and logged loudly. Thresholds derived from the corpus: legitimate answers peak
  at 72,147 chars / 18-char whitespace run; the runaway was 2,924,215 / 2,862.
- **Verified:** 6 tests, 3 fail on pre-fix code, including that a legitimate answer with an 18-char
  whitespace run passes through byte-identical.
- ~~Original entry below~~ [P2, 2026-08-15]
- **Downgraded, NOT closed.** The trigger is gone: with SI-051 fixed the model receives a real
  marker and no longer hand-draws ASCII charts. **0 synthesis truncations across 6 E2E runs**,
  all answers 3.0-5.9 KB at 14-17% whitespace (was 2,924,215 chars at 99.8%).
- **Why it stays open:** nothing in RAICA stopped the runaway — only the vendor's 32,768-token
  ceiling did. A different trigger would produce the same result. Needs an explicit
  output-size / degenerate-repetition guard; name the line that makes cycle 2 impossible.
- ~~Original entry below~~ [P1 — CONFIRMED e2e, v1.0.0.286]
- **Observed (1 of 3 E2E runs, 2026-08-15):** a single answer streamed **2,924,215 characters** —
  **99.8% whitespace** (2,917,822 space/newline chars around 6,393 chars of real content), including
  **2,152 runs of 200+ consecutive spaces**, longest **2,862**. The tail is `*` and `|`: the model was
  drawing an ASCII scatter/axis by padding with spaces.
- **Trigger:** no `[[chart:…]]` marker was available (**SI-051**), so the model improvised a text chart
  and the padding degenerated. The two issues are causally linked — fixing SI-051 likely removes the
  trigger, but the absence of any output-size guard is a defect in its own right.
- **Impact if it reaches production:** a ~3 MB reply per request — bandwidth, NewX render cost, and
  DB/post storage — for 6 KB of information. On a phone this is a hang.
- **What actually stopped it:** nothing in RAICA. The run ends with
  `✂️ TRUNCATED by max_tokens: model=deepseek-ai/DeepSeek-V4-Pro-0813 in generate_stream hit the
  32768-token output cap (finish_reason=length)` — the vendor ceiling was the only brake. Had the cap
  been higher, the answer would have been larger still. (The detector that surfaced this is the
  v1.0.0.237 truncation guard, which is now earning its keep a second time.)
- **To clear:** an output-size/degenerate-repetition guard on the synthesis stream — name the line that
  makes an unbounded padding run impossible — plus 3 E2E runs with no answer above a sane ceiling. Do
  NOT clear merely because SI-051 is fixed: the trigger would be gone, the class would not.

### ~~SI-050~~ — Reference dicts reached `compute` unresolved on the arbitrator retry path  [RESOLVED v1.0.0.286, 2026-08-15]
- **Observed:** **58 `UFuncTypeError`** across 3 E2E runs (control: the preceding 3 runs on the same
  build had **0** — `logs/archive/server_complete_20260815_201107.log`).
  `ufunc 'greater_equal' … (StrDType, _PyFloatDType)`, `ufunc 'subtract' … (dtype('<U4'), dtype('<U6'))`.
- **First hypothesis — REFUTED by measurement.** I suspected the silent text fallback at
  `utils/tool_output_reference.py:344-346` (a column whose cells fail to parse is returned as text).
  Reproduced through the real path instead: `lookup_website` → `build_reference_index` →
  `extract_column('mag')` returned **225 floats at a 100% parse rate**. The fallback never fired.
- **Actual root cause (CONFIRMED, exact reproduction):** `<U4` and `<U6` are precisely `len('from')`
  and `len('column')`. `_execute_corrected_tools` (`fastapi_server_complete.py:5237`) — the
  arbitrator's regeneration path — called `tool_manager.safe_function_call()` **directly, without
  `_resolve_call_references()`**, which every other path uses. The raw
  `{"from": "lookup_website#1", "column": "mag"}` reached the tool, and numpy converted the dict to an
  array of its KEYS. Verified: `np.asarray(list({'from':…,'column':…}))` → `['from' 'column'] <U6`,
  and `arr >= 5.5` reproduces the production error **byte-for-byte**, as does the `<U4`/`<U6` subtract.
- **Fix:** resolve references before executing regenerated calls, reusing the existing resolver, and
  pass `prior_results=list(zip(tools_called, tools_results_list))` from the caller. Accept `arguments`
  as either a dict (resolved) or a JSON string (unresolved).
- **Verified:** `tests/unit/test_corrected_tools_resolve_references.py` — 3 tests, **2 fail on pre-fix
  code** (verified by reverting the hunks). E2E 3 runs: **UFuncTypeError 58 → 0**, refusals **2/3 → 0/3**,
  n=225 in 3/3, tables in 3/3, real statistics reported (5.87 / 5.80 / 0.42 / 7.80).
- **Note:** SI-048 (2nd-decimal drift) is NOT explained by this and remains open.

### SI-049 — Workstation froze during a local E2E run; the memory consumer was never identified  [P2 — SUSPECTED, 2026-08-15]
- **What happened:** during a local E2E test the machine exhausted 15 GB RAM, livelocked in swap and had
  to be hard power-cycled. Freeze onset **18:40:32** (Discord logged a 6,209 ms stall); journald reported
  *"Under memory pressure, flushing caches"* at 18:43:59 and 18:46:57, then silence; reboot 18:50:30.
- **What is ESTABLISHED:** memory exhaustion, not disk (56% full) and not a fork storm (PID churn steady
  at 700–850/min through 18:40, no spike). Transition was a **cliff**, not a decay.
- **What is NOT established — the consumer.** The hard power-off destroyed the evidence that would name
  it: the kernel OOM ring buffer is in RAM, `sysstat`'s `sa15` was never flushed, and the session
  transcript is truncated at 18:39:21. Three candidates were **refuted**: the suspect `grep` (reproduced
  against the identical surviving log — 3.4 MB RSS, instant), the gather-gate loop (bounded at
  `fastapi_server_complete.py:10869/10872/10910`) and `utils/restricted_numpy_eval.py` (200k-element cap).
- **Why it took the machine down (VERIFIED):** Bash commands run in a scope with `MemoryMax=infinity`;
  `systemd-oomd`'s only live policy is 50% pressure on `user@.service` while the root slice ships
  `ManagedOOMSwap=auto`, so **swap exhaustion never triggers a kill**; no `earlyoom`, no zram;
  `vm.overcommit_memory=0` + `vm.swappiness=60` + an 8 GB swapfile turn exhaustion into minutes of thrash.
- **Mitigation in use:** run local E2E inside `systemd-run --user --scope -p MemoryMax=8G -p
  MemorySwapMax=0` (verified: a runaway dies at the cap, system availability unchanged). Recommended:
  `sudo apt install earlyoom` (needs operator).
- **To clear:** reproduce under the cap with per-process sampling and name the consumer, or establish it
  was not RAICA. 3 capped E2E runs on v1.0.0.285 peaked at **1,525 MB** — did not reproduce.

### ~~SI-048~~ — Synthesis misreported numbers the tool computed correctly  [RESOLVED v1.0.0.287, 2026-08-15]
- **ROOT CAUSE (shared with SI-051/052): arbitrator regeneration REPLACED the results list.**
  `fastapi_server_complete.py` did `tools_results_list = regenerated_tools_results` and
  `tools_called = [...]`, discarding phase-1 fetches, all gather-gate compute outputs and
  plot_data's marker. Synthesis then received ONE entry (the raw CSV) and eyeballed the stats.
  Evidence: `PARSED RESULTS: Generated 1 tool entries` while the gate had run 10 computes.
- **Fix:** `_merge_regenerated_results()` keeps every non-regenerated entry and derives names
  FROM the entries, so the two lists are parallel by construction (`arbitrator_validate_tasks`
  pairs them with `zip()`, which truncates silently); plus a loud skew warning at that zip.
- **Verified 3/3 Treasury runs:** every reported statistic matches ground truth —
  4.293/3.97/4.79 and 4.777/4.41/5.08. The previously fabricated **4.62** and **4.27** appear
  in NONE of the three answers. Live log: `REGENERATION MERGE: kept 161 prior result(s)`.
- **Residual (minor):** one USGS answer rendered std as "≈ 0.43" where compute returned 0.42.
  Mean and median were exact. Tracked here, not re-opened as P1.
- ~~Original entry below~~ [P1 — CONFIRMED, mechanism proven, 2026-08-15]
- **Upgraded from P2/SUSPECTED ("2nd-decimal drift, probably rounding"). It is not rounding, and it is
  not a compute bug — `compute` is correct and the ANSWER changes the values.**
- **Proof (Treasury 2025 daily yields, v1.0.0.286, a DIFFERENT dataset from the one that first showed
  the drift — so this generalises):**

  | | `compute` returned | answer reported | ground truth |
  |---|---|---|---|
  | 10 Yr mean | **4.29321** | 4.27 | 4.2932 |
  | 10 Yr max | **4.79** | **4.62** | 4.79 |
  | 10 Yr min | 3.97 | 3.97 | 3.97 |
  | 30 Yr mean | **4.77731** | 4.76 | 4.7773 |
  | 30 Yr max / min | 5.08 / 4.41 | 5.08 / 4.41 | 5.08 / 4.41 |

- **The data was complete:** `🔗 SECOND ROUND: resolved data references for 'compute' → {'data':
  {'y10': 249}}` — all 249 rows, and `compute` logged `computed as: np.max(y10)` returning 4.79.
- **4.79 → 4.62 is not a rounding error.** No Treasury column has max 4.62 (5 Yr = 4.61, 7 Yr = 4.71),
  so the reported triple (4.27 / 3.97 / 4.62) is internally inconsistent with ANY real column — it is
  partly transcribed, partly invented.
- **Pattern across both datasets:** minima transcribe exactly, means are systematically LOW, one
  maximum badly wrong. Exact extremes are precisely what stops a reader noticing the rest.
- **Impact:** RAICA reports authoritative-looking statistics that differ from what its own verified
  tool computed. This defeats the entire point of computing rather than eyeballing, and it is invisible
  without an independent recomputation.
- **Note:** the USGS instance (5.87 vs 5.8828) is the same defect, not a separate one.
- **To clear:** an answer whose every cited statistic matches the `computed as:` value in the log,
  on ≥3 runs across ≥2 datasets. Prompt-level fixes must be measured, not assumed — see the
  `{{PRIMARY_LLM_RESPONSE}}` precedent in the parity plan §6 D3.

### SI-047 — A computed series cannot be charted: plot_data references require a TABLE  [P1 — CONFIRMED on prod, v1.0.0.284]
**Every `plot_data` call in the 2026-08-15 07:26 run failed with the same error:**
```
plot_data: could not use the referenced data — referenced output does not contain a table
           with a header and rows
```

**Cause (`utils/tool_output_reference.py:138-146`).** `extract_column` resolves a reference through
`_parse_table`, which requires a header plus at least two rows. A `compute` result is not a table —
it is a labelled array:
```
25th, 75th, 90th, 95th, 99th percentiles of earthquake magnitudes: [5.6  , 6.   , 6.4  , 6.68 , 7.476]
```
So `{"from": "compute#N", "column": ...}` can NEVER resolve, and **anything the model calculates —
a histogram, a fitted curve, a transformed axis — is unchartable by construction.**

**Why it only became fatal now.** The defect predates the SI-046 directive. Earlier runs charted a
RAW FETCHED COLUMN (`lookup_website#1`), which is a table and resolves fine — the one successful
chart (06:49) did exactly that. The directive correctly pushes the model to plot computed things
(observed histogram + a justified fit), and every such reference hits this wall. It also explains
the `plot_data#1 failed` in the run before, which was noted as a "rough edge" and not chased.

**Fix direction:** `extract_column` must accept a reference whose output is a numeric SERIES rather
than a table — parse the array `compute` emits and return those values, keeping the existing table
path for tabular sources. One function, deterministically testable from the exact output format
above, with NO LLM call required to verify.

**FIXED in v1.0.0.284.** `extract_column` now decides by SHAPE before demanding a column: JSON
records and tables take the existing paths unchanged, and anything else is offered to a new
`computed_series()`, which parses the labelled scalar/array `compute` emits. A column name passed
out of habit is ignored rather than rejected, and the `[TRUNCATED: …]` note is excluded so its
square brackets are not mistaken for data.

**CLEAR-CONDITION MET — verified end-to-end through the real path, no LLM required:**
```
🔗 SECOND ROUND: resolved data references for 'plot_data' → {'x': 5, 'series': 2}
   x                     -> [5.6, 5.9, 6.2, 6.5, 6.8]        (from compute#1)
   Observed count        -> [74.0, 62.0, 17.0, 32.0, 11.0]   (from compute#2)
   Gutenberg-Richter fit -> [1.88, 0.98, 0.51, 0.27, 0.14]   (from compute#3)
   plot_data success: True
   [[chart:/static/images/media/3ab6194….jpg|align=center|caption="Earthquake magnitude
    distribution (H1 2026, M>=5.5)"]]
```
The rendered image was opened and inspected: both series drawn, axes and source line correct.

**Tests:** `tests/unit/test_computed_series_reference.py` (11). On pre-fix code **7 fail** with the
production error verbatim (`a reference needs a 'column' naming which values to take`); the 4
"existing paths unchanged" tests pass both ways by design.

**Still open — the full-request confirmation.** The chain is proven at the tool boundary, but no
real @Ask request has produced a chart of a computed series since the fix. That needs the Ollama
quota reset, and it is the same run that confirms SI-046 at n>=3.

### SI-046 — The distribution family is chosen by the TOOL-CALLING model before the data's shape is known  [P2 — CONFIRMED on prod, v1.0.0.283]
**User report:** "I said in this prompt to pick the *appropriate* probability distribution and did
not mention Normal anywhere." The rendered chart overlaid a **Normal PDF (μ=5.88, σ=0.42)** on
manifestly exponential data — first bin 74 observed vs ~25 predicted.

**Not a hardcoded default.** `plot_data` contains no distribution fitting of any kind; it plots the
series it is handed. The Gaussian was computed by the model and passed in, legend text included.

**The mechanism — two models, and the wrong one decides.** This run:
```
glm-5.2:cloud          x9  — tool selection + gate verdicts (chose the normal fit, 06:49:08)
deepseek-v4-pro:cloud  x1  — synthesis (wrote the answer)
```
The choice of distribution is a STATISTICAL judgement, but it is made by the tool-calling model at
GATHER time, before anything has examined the data's shape. The stronger synthesis model runs
afterwards, and it got it right — its own answer says the first bin holds "far more than the ~25
events a normal distribution would predict" and that "a normal distribution is a poor fit for the
tail", while displaying exactly that fit. **The answer contradicting its own chart is structural,
not a lapse:** by synthesis time the chart is already rendered and immutable.

**Why the previous run looked better:** v1.0.0.281 produced NO chart, so only the synthesis model's
(correct) Gutenberg-Richter reasoning was visible. Fixing the plumbing exposed the judgement gap
that was always there.

**MEASURED 2026-08-15 — the sequencing hypothesis is REFUTED.** The natural fix ("compute the
shape first, feed it back, then let the model pick the family") is what ALREADY HAPPENS. Every one
of these was computed in gather round 1 and was in `available=[compute#1 … compute#13]` when the
`plot_data` call chose a Gaussian:
```
np.size(mag)=225 · np.mean=5.88 · np.median=5.80   <- mean > median, skew visible
np.min=5.5 · np.max=7.8                            <- long right tail, visible
np.percentile(mag,5) · np.percentile(mag,95)
np.histogram(mag, bins=15)[0] = [74,62,17,32,11,8,5,6,0,2,1,2,2,2,1]   <- monotone decay
np.mean(mag >= 6.5 / 7.0 / 7.5)                    <- empirical tail probabilities
```
**glm-5.2 had the shape in front of it and chose normal anyway.** Any fix built on "give it the
diagnostics first" would therefore have changed nothing — this was recorded before the measurement
was taken, and is corrected here rather than shipped.

**Two remaining candidate causes, requiring DIFFERENT fixes — distinguish before building:**
1. It was never TOLD the family must follow from the shape (no directive links those numbers to the
   choice) → a policy directive suffices.
2. glm-5.2 will not make this judgement regardless — it is selected for tool-call throughput, not
   statistical reasoning → no prompt fixes it; the decision must move to a stage/model that reasons
   about the data (V4-Pro already gets it right at synthesis, merely too late).

**The experiment:** same request, directive added, run >=3x (selection is stochastic). If it still
picks normal WITH the shape and an explicit instruction, the answer is (2) — relocate the decision
instead of tuning words further.

**DIRECTIVE SHIPPED v1.0.0.284 — the experiment is now the deciding step, NOT the fix.** Added to
BOTH surfaces the tool-calling model reads: Section J of `pre_tool_model_system_prompt.txt` ("A
FITTED CURVE IS A CLAIM ABOUT THE DATA, NOT DECORATION" — measure the shape before fitting; let the
measurements rule out families; say which family and why; plot observed data alone if none is
defensible) and a compressed clause in the per-round selector prompt, which is the one that was live
when `plot_data` was chosen on prod.
- **No lookup table:** no subject is mapped to any distribution. The rules are stated as
  CONTRADICTIONS between a measurement and a kind of family (mode at the boundary, mean displaced
  from median, monotone decay, extremes a family gives no mass to) — criteria that hold for
  lognormal, Poisson or power-law data equally. Pinned by a test that FAILS if any family name
  (gaussian/gutenberg/lognormal/poisson/weibull/pareto) appears in the prompt.
- **Conflict audit passed:** `_ARTIFACT_MARKER_RELAY` governs DESCRIBING a chart, this governs
  CHOOSING one; `Ask.yaml` DERIVED FIGURES reinforces "measure the shape first"; Section J's
  provenance rules untouched.
- **Code-gate reconciliation:** every diagnostic the directive asks for was RUN through the real
  `compute` evaluator — mean-median gap, hand-rolled skewness (numpy has no `skew`), modal bin,
  tail decay, extremes vs 95th percentile. All pass, so no gate silently defeats the policy.
- **RESULT (re-run on v1.0.0.284, prod 2026-08-15 07:26) — CANDIDATE (1) CONFIRMED, directive works.**
Same prompt, first behavioural change in four runs. The model measured the shape and then chose an
exponential family — no Gaussian anywhere:
```
np.mean((mag - np.mean(mag))**3) / (np.std(mag, ddof=1)**3)   <- skewness, computed explicitly
np.log(10) / (np.mean(mag) - np.min(mag))                      <- Gutenberg-Richter b-value
np.histogram(mag, bins=np.arange(5.5, 7.85, ...))              <- observed histogram
label: 'observed histogram counts per 0.1-magnitude bin'
```
So glm-5.2 CAN make this judgement; it had simply never been told to. Candidate (2) — "the model
will not do it regardless" — is REFUTED, and the decision does not need to move to V4-Pro.
**Caveat, stated plainly: n=1.** Selection is stochastic and the >=3x confirmation is deferred to
the quota reset, as is the non-earthquake generalisation check. Do not treat this as settled.

**NOT closed — blocked on the next defect (SI-047).** No chart was produced: every `plot_data` call
failed because a COMPUTED series cannot be charted at all. The directive is correct and now exposes
the next defect in the chain.

**Previously recorded as undecided:** It tests candidate (1) only. If a re-run
  still fits a Gaussian while holding both the shape AND this instruction, the answer is candidate
  (2) and the decision must move to a model that reasons about the data, not a fourth draft of the
  words. Run >=3x; verify on a NON-earthquake dataset before believing it generalises.

**Original fix direction — policy, not a rule table.** Hardcoding "magnitudes → Gutenberg-Richter" is exactly
what the LLM-Policy Gate forbids; the next dataset would be lognormal, Poisson or power-law and the
table would be wrong again. The directive belongs where the CHOICE is made (the tool-selection
prompt), in substance: *a distribution family must follow from the data's measured shape — compare
mean against median, look at skew and the tail — and if that shape has not been measured yet,
measure it BEFORE plotting a fitted curve.* The gather-gate loop already sequences this naturally:
`needs_more` → compute the shape diagnostic → then plot.
- **Check for conflicts before shipping** (no-inconsistency clause): this new directive must be
  reconciled with `_ARTIFACT_MARKER_RELAY` and the NewX `Ask.yaml` DERIVED FIGURES / STOCK & DATA
  CHARTS blocks, all of which already instruct the same models about charts.
- **Open question worth measuring first:** whether glm-5.2 can make this judgement at all with the
  context it has at selection time, or whether the choice must move to a stage that sees the data.
  Do not assume the directive works — verify through a real run, and on a NON-earthquake dataset so
  the fix is not tuned to one case.

### SI-045 — The numpy allow-list contained 97 names and NOT ONE constant  [RESOLVED v1.0.0.283]
**Found in the second live SI-041 re-test (prod, v1.0.0.282).** The chart failed again, for a
THIRD, unrelated reason — and this time the answer disclosed it, which is the SI-041(b) relay
directive finally working:
> "the normal-PDF curve values (which required `np.pi` in the density formula) were rejected by
> the compute tool's allowed-function list"

Log: `Expression rejected: np.pi is not in the allowed function list` ×5.

**Cause.** `np.pi` parses as an `ast.Attribute`, and the attribute check tested a single set that
held FUNCTIONS only. An audit of the 97 allowed names found **zero** constants. Blocking a constant
was never a safety property — it allocates nothing, executes nothing and takes no argument.

**Why the restriction exists at all** (the user asked, and it is worth stating): `compute`
evaluates expressions AUTHORED BY THE LLM. That is `eval` over untrusted input, so the fence is an
ALLOW-list, never a deny-list — `np.load` alone executes pickles. The fence is correct. The list
behind it was simply incomplete.

**Fixed:**
- `ALLOWED_NUMPY_CONSTANTS = {pi, e, inf, nan, euler_gamma}`, accepted for attribute access and
  REJECTED when called (`np.pi(3)` → "is a constant, not a function"), which beats numpy's opaque
  "'float' object is not callable" surfacing inside a tool result.
- Added `histogram` and `polyfit` — the two a distribution question actually needs. Without
  `histogram` the model hand-rolled every bin as `np.sum((mag >= 5.5) & (mag < 5.75))`, ten times.
  Both are in `_SIZE_TAKING`, so `bins`/`deg` are bounded exactly like `linspace`'s `num`.
- Removed the dead `flatten` entry: `np.flatten` does not exist (it is an ndarray method).
- Error wording: "not in the allowed function list" → "not an allowed numpy name", since the set
  is no longer functions only.

**Fence verified unchanged:** `np.load(...)`, `np.zeros(10**9)`, `np.vectorize`, `__import__`,
`np.histogram(bins=10**9)` and `np.polyfit(deg=10**8)` all still rejected.

**Same class as SI-041(a)** (`linspace`/`arange` blocked, cost a request 47 rejections and its
chart). Two occurrences make it a pattern: **the allow-list is audited against the WORK, not just
against the threat.** Before adding a numeric capability, run the expression a real analysis would
write.

### SI-044 — A tool cannot reference another tool's output from the SAME batch; gate then ends on a self-contradictory verdict  [P1 — CONFIRMED on prod, v1.0.0.281]
**Found in the live SI-041 re-test (prod, 2026-08-15 02:59).** Everything else in that request
worked; the chart still did not appear, for two defects that are BOTH in my own code.

**(1) Intra-batch dependency cannot resolve.** The selector chose, in ONE gather-gate round:
```
round=1 executing ['compute' ×14, 'plot_data', 'plot_data']
```
`plot_data` referenced `compute#9` / `compute#6` — outputs of computes in that same batch.
`_resolve_call_references` runs ONCE before the batch, and the batch executes in parallel via
`asyncio.gather`, so those references could not exist yet:
```
🔬 second-round-args: tool=plot_data available=['lookup_website#1']
   → Tool 'plot_data' error: unknown output reference(s) ['compute#9']
```
The very next round proves the data was fine, just late:
`available=['compute#1' … 'compute#14', 'lookup_website#1']`.

**(2) The gate ended the loop while reporting the opposite.** One round later:
```
🚪 gather-gate: round=2 verdict=sufficient
   missing='The plot_data tool failed ... could not reference the compute outputs.
            A valid plot_data call is needed to produce the [[chart:...'
   next=['plot_data']
```
`status=sufficient` with a NON-EMPTY `missing` and a NON-EMPTY `next_tools` is incoherent, and it
stopped the loop exactly when one more round would have worked. `_gather_gate_assess` takes the
model's `status` at face value (`needs_more` only on an exact match, else `sufficient`) and never
cross-checks it against the other two fields it just parsed.

**FIXED in v1.0.0.282 — NOT yet validated end-to-end (needs a real re-run of the USGS prompt).**
- (1) `_split_calls_awaiting_batch_output` holds back a call whose reference names a tool scheduled
  in the SAME batch; the gate loop flushes those deferred calls at the TOP of the next round,
  BEFORE assessing — assessing first could return `sufficient` and exit while the chart sat unmade.
  Deferral was chosen over topological ordering because it keeps parallel execution, reuses the
  existing loop, and per-tool ids stay stable (`asyncio.gather` preserves order, so `compute#9`
  still means the 9th compute). A reference to a tool NOT in the batch is left to fail loudly as
  before — deferral must not become a way to swallow a bad reference and run a tool on missing data.
- (2) Coherence guard in `_gather_gate_assess`: `sufficient` + non-empty `missing` + non-empty
  `next_tools` is treated as `needs_more`. It reads two fields the model already returns —
  structural, not keyword matching. BOTH signals are required; escalating on `next_tools` alone
  would loop to `max_rounds` on every request.
- Tests: `tests/unit/test_intra_batch_references.py` (7). The coherence test exercises the existing
  `_gather_gate_assess` and fails on pre-fix code by assertion; the deferral tests cover a new
  helper, so they fail on missing-attribute rather than behaviour — stated plainly rather than
  dressed up as behavioural proof.

**Original fix directions (for the record):**
- (1) Defer, don't fail: when a call references an output produced by a tool scheduled in the SAME
  batch, hold that call back for the next round instead of erroring. The loop already re-runs, and
  round 2 demonstrably had the references. (Alternative — order the batch topologically — is more
  work and loses parallelism.)
- (2) A coherence guard on the verdict: if the model names `missing` AND `next_tools`, that is
  `needs_more` regardless of the status string. This is a STRUCTURAL check on fields the model
  already returns — not keyword matching on meaning.

**Consequence today:** requests that need a chart OF A COMPUTED SERIES (as opposed to a fetched
column) silently produce no chart. `plot_data` charting a raw fetched column is unaffected.

**Also note — the answer did not disclose the failure.** `_ARTIFACT_MARKER_RELAY` tells the model to
"note briefly that a chart wasn't available"; it substituted tables and said nothing. Better than
SI-041(b)'s fabricated "the plot below shows…", but the disclosure half of the directive did not
fire. Track with SI-041(b) residue.

### SI-042 — DEGRADED never triggers the auto-rebuild; the recommendation has no consumer  [P2 — CONFIRMED by code + prod logs]
**Correction to the first version of this entry (2026-08-15).** I originally recorded that the
orphan-count swing "suggests the CHECK is sampling/threshold-sensitive, not that the index is
actually oscillating." **That was wrong, and the prod logs refute it** — the index really does
oscillate, because orphans really do accumulate and the auto-rebuild really does reset them
(see SI-043). The hypothesis fit the numbers; I recorded it without testing it.

**The auto-rebuild EXISTS and WORKS — for CORRUPTED only.** Prod, verbatim:
```
08/15 00:41:15  Status: CORRUPTED (COUNT_MISMATCH, orphaned_in_faiss 556)
08/15 00:41:15  🚨 CORRUPTION DETECTED - Starting automatic rebuild
08/15 00:43:06  ✅ Automatic rebuild completed successfully      (1m51s)
```

**The gap is the DEGRADED branch** (`tools/faiss_integrity_monitor.py`):
```python
if result['corruption_detected']:
    result['rebuild_required'] = True                                    # CORRUPTED → repairs
elif result['status'] == 'DEGRADED':
    result['recommendations'].append('SCHEDULED_REBUILD_RECOMMENDED')    # ← flag never set
```
Three independent things then make DEGRADED a dead branch:
1. `check_and_repair_faiss_integrity` (:411) gates repair on `rebuild_required`, which DEGRADED
   never sets — so `automatic_rebuild_if_needed` is not even called (no "No rebuild required"
   line appears in any prod log, confirming the inner function never runs on this path).
2. Its final line is `return integrity_result['status'] in ['HEALTHY', 'DEGRADED']` — DEGRADED is
   explicitly reported as **healthy** to the caller.
3. **Nothing consumes `SCHEDULED_REBUILD_RECOMMENDED`.** Grepped the codebase: the string is
   written at :92 and read nowhere. The word "SCHEDULED" implies a scheduler that does not exist.

**Consequence:** `EMBEDDING_INCONSISTENCY` — vectors possibly written by a different embedding
model/dimension than the one now querying — is detected on every boot and actioned never. It
degrades ANSWER QUALITY silently; it cannot surface as an error.

**RESOLVED in v1.0.0.280 — and NOT by making DEGRADED trigger a rebuild.**

The caution above turned out to be the whole story. Measuring first showed that
`_check_embedding_consistency` **never consults the index at all**: it embeds 5 sample chunks
TWICE through the LIVE API and compares the two results. A FAISS rebuild re-embeds through that
same API, so **by construction it cannot change the verdict** — wiring DEGRADED to a rebuild would
have rebuilt ~2 minutes on every boot, forever.

Worse, the verdict was a near-certain FALSE POSITIVE. The old test was
`np.allclose(rtol=1e-10)` — far tighter than float32 carries. Measured on real prod content
(`text-embedding-3-small`):

| sample | max abs diff | cosine |
|---|---|---|
| 0, 2, 3 | 0.0 | 1.00000000 |
| 1 | 1.2e-04 | 0.99999961 |
| 4 | 3.4e-04 | 0.99999426 |

Ordinary batched-inference jitter between replicas; semantically identical for retrieval.

**Three changes:**
1. **Consistency judged by COSINE** against a configured floor (`0.999`) instead of element-wise
   equality. Still catches what matters — a changed model, wrong dimension or mismatched text
   collapses cosine far below the floor (pinned by a test).
2. **DEGRADED is surfaced, not swallowed.** `check_and_repair` no longer returns
   `status in ['HEALTHY','DEGRADED']`; DEGRADED logs an explicit operator WARNING naming the
   issue and metrics, and the startup line no longer claims "system is healthy".
3. **A DAMPER on every automatic rebuild** (not just this path): attempts are recorded in a new
   `integrity_rebuilds` table and capped at `max_per_window` per `window_hours` (config:
   `document_interrogator.integrity.auto_rebuild`). **The line that makes cycle N+1 impossible**
   is the `recent >= limit` check in `automatic_rebuild_if_needed`, which returns before the
   rebuild whatever the detector says. The attempt is recorded BEFORE the rebuild runs, so a
   rebuild that CRASHES still counts — otherwise the error path would reintroduce the loop.
   `corruption_threshold` also moved out of code into config.

**Verified on a copy of the REAL production index:** `status: HEALTHY`, `issues: []`,
`recommendations: ['NO_ACTION_REQUIRED']`, `embedding_consistency: consistent=True,
min_cosine=1.0`. Tests: 6 new; the damper test executes 5 rebuilds against a limit of 2 on
pre-fix code and fails with that count.

### SI-043 — Re-indexing orphans FAISS vectors; the watcher re-ingests unchanged files  [P2 — ROOT CAUSE CONFIRMED, reproduced]
**Mechanism (reproduced in isolation, `document_interrogator.py:766-795`).** `add_chunks` appends
vectors unconditionally, then reconciles SQLite by PRIMARY KEY:
```python
self.faiss_index.add(embeddings_array)            # ALWAYS appends N new vectors
...
except sqlite3.IntegrityError:                    # chunk_id TEXT PRIMARY KEY
    cursor.execute('UPDATE chunks SET faiss_index = ? ... WHERE chunk_id = ?')
```
`chunk_id` is `_generate_chunk_id(document_path, chunk_index)` — path+index, NOT content — so
re-indexing a changed file produces the SAME ids. The row is repointed to the new vector and **the
old vector is never removed**: FAISS `IndexFlat` has no removal. Every chunk row still points at a
valid vector, which is exactly why `missing_in_faiss` is always 0.

**Reproduction** (same chunk_ids, three ingests): rows stay 10, vectors go 10 → 20 → 30,
`orphaned_in_faiss = 20`.

**What triggers it on prod — the RAICA repo indexes its own docs.** Directory 1 watches 170 files
under `~/RAICA/docs/`. Verbatim, at the v1.0.0.277 restart:
```
01:50:07  ✅ Added 284 chunks to document store
01:50:07  ✅ Auto-processed: /home/ubuntu/RAICA/docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md
01:50:07  📊 Directory 1: scanned 170 files
```
**This file.** Every deploy that edits SUSPECTED_ISSUES.md re-ingests ~284 chunks and orphans ~284
vectors. The corruption threshold is 5% (≈413 vectors at 8.2k chunks), so roughly every other
SI-log deploy trips CORRUPTED and fires the rebuild — which is precisely the observed cadence of
three rebuilds in three days during heavy session work. **Writing up these issues is the single
biggest contributor to the leak they describe.**

**TWO distinct defects, do not conflate them:**
1. **Structural (by design, not a bug per se).** Re-indexing genuinely-changed content must orphan
   its old vectors while the index is a plain `IndexFlat`. The auto-rebuild is the de-facto
   compactor. A real fix means `IndexIDMap2` + `remove_ids`, i.e. an index-type migration.
2. **PARITY DEFECT (a real bug, cheap to fix).** The startup scan guards with
   `if await self._file_needs_reindexing(...)` (hash + mtime, `:1534`) — the watcher does NOT
   (`:1224` `on_created`, `:1229` `on_modified` call `_process_single_file` directly). So a
   byte-identical rewrite — `git pull`/`git checkout`, an editor save, `touch` — re-embeds and
   orphans the whole file for no benefit, and `on_modified` can fire several times per save. Two
   paths doing one job, one guarded and one not.

**Also costs money.** The embedding provider is OpenAI `text-embedding-3-small`; every needless
re-ingest is a paid API call for content that did not change.

**CORRECTION (2026-08-15) — I recommended fixing (2) first because it "removes the avoidable
share of the leak". That was wrong, twice over, and measurement refuted it both times:**
- **The watchdog path never runs.** `📝 File modified` and `📄 New file detected` appear **0**
  times across every retained prod log, and no observers are ever started. The path that DID
  re-index (`:1925`, periodic scan) already guards with `_file_needs_reindexing`.
- **The mtime-only branch never fires either.** Prod counts: `Change detected (hash)` = **14**,
  `Change detected (mtime)` = **0**. Every observed re-index was a genuine content change.

**So the observed leak is 100% STRUCTURAL — defect (1).** Files I really edited were really
re-indexed, and their old vectors could not be removed. No guard would have prevented any of it.
The only real fixes are an index migration (`IndexIDMap2` + `remove_ids`) or treating compaction as
scheduled maintenance. **Do not raise `corruption_threshold`** — that hides the leak rather than
fixing it.

**Fixed in v1.0.0.278 — LATENT hardening only, does NOT reduce the observed leak.** Both defects
are real but currently unreachable; they are closed so that enabling the watcher (there is a
`start_watching` endpoint at `fastapi_server_complete.py:14204`) does not immediately start
orphaning vectors on every editor save:
- watchdog `on_created`/`on_modified` now route through `_process_file_if_changed`, which applies
  the same `_file_needs_reindexing` guard every scan caller already used;
- `_file_needs_reindexing` no longer re-indexes on an mtime bump when the content hash is
  IDENTICAL — it refreshes the stored mtime and skips.
Pinned by `tests/unit/test_watcher_reindex_guard.py`, which fails on pre-fix code
(`vectors 1 -> 2`) and carries its own control: step 3 requires a genuine change to still be
indexed, because "no vectors added" is also what a dead embedding pipeline produces.

**STRUCTURAL CAUSE FIXED in v1.0.0.279 — `IndexIDMap2` + `remove_ids`.** The store now uses an
id-mapped index; each chunk keeps a stable id (its `chunks.faiss_index`), and `add_chunks` removes
the superseded vector BEFORE adding its replacement, so re-indexing replaces rather than
accumulates. Legacy positional indexes migrate on load by `reconstruct`-ing the existing vectors —
**no re-embedding, so no API spend** — carrying only positions still referenced by a row, which
compacts the accrued orphans in the same pass.

**Rehearsed against a copy of the REAL production index before deploying:**
```
BEFORE  IndexFlatIP   8614 vectors / 8330 rows -> 284 ORPHANED
AFTER   IndexIDMap2   8330 vectors / 8330 rows ->   0 orphaned   (0.3s, ids all unique)
        count_sync synchronized=True · lookup_integrity HEALTHY 0/100 · range_validity valid
        search verified on the migrated index: relevant hits, ntotal unchanged
```
**A second defect surfaced during that rehearsal and is fixed too:** the monitor's
`_check_index_range_validity` asserted `faiss_index < ntotal`, which is meaningless once ids are
ids — after removals they are deliberately non-contiguous. On the migrated real index
`max_index=8613` against `ntotal=8330` would have been reported INVALID/CORRUPTED **on every
boot**. It now checks membership in the live id set. `_perform_full_rebuild` and
`tools/rebuild_faiss_index.py` likewise preserve ids instead of renumbering by position.

**Remaining:** the migrated index still reports `DEGRADED` for `EMBEDDING_INCONSISTENCY` — a
separate concern tracked in SI-042, untouched by this fix. Orphaning is resolved.

**Do not clear** until: the watcher path is guarded, and a byte-identical rewrite is shown NOT to
change `faiss_index.ntotal`.

### SI-041 — Three defects surfaced by a statistics+chart request  [P2 — CONFIRMED by measurement]
**Request (prod, v1.0.0.274):** USGS M5.5+ catalogue, first half 2026 — "sample size, mean, median,
std-dev … plot the bell curve … probabilities for tail events and most likely next magnitude".

- **(a) `linspace` / `arange` are blocked, so a fitted curve cannot be built.** 47 `Expression
  rejected` in one request; the surviving expressions were `np.linspace(np.min(mag)…)` and
  `np.arange(5.0…)`. They were excluded from the numpy allow-list as "allocate BY SIZE" — correct
  as a memory-safety concern, wrong as a blanket ban, because building x-axis points for a
  distribution curve is exactly what they are for. The gate consequently ran to `max_rounds`
  without reaching `sufficient`, and no chart was produced.
- **(b) A chart was DESCRIBED but never rendered.** The answer says "The plot below shows the
  frequency of events by magnitude" and there is no `plot_data` call and no `[[chart:…]]` marker in
  the log. This is a NEW fabrication shape: not an invented marker (SI-038), but prose narrating a
  visual that does not exist. `plot_data`'s failure path cannot cover it because the tool was never
  called.
- **(c) The header row counted as an observation — again.** Reported **226 events**; the file has
  226 LINES = 1 header + **225** events. The same off-by-one produced "250 daily observations"
  against 249 for the Treasury data. Two occurrences make it a pattern, not a slip.
- **Also wrong, but downstream of the above:** std-dev **0.44** against a true **0.4218**;
  "mean and median are very close, suggesting the distribution is nearly symmetric" against a
  measured **skewness of 1.97**.
- **The most damaging error is not arithmetic.** The answer reports **P(M≥7.0) = 0.54%**, "roughly
  once in every 185 events", **in a dataset containing 8 such events (3.56%)** — a normal-model
  tail estimate contradicted by its own data, stated in the conclusion without a hedge. Magnitudes
  follow Gutenberg-Richter (exponential), so a normal fit understates the tail ~9x. The answer even
  cites Gutenberg-Richter in its "most likely next magnitude" section and does not connect it to
  the tail probabilities it just reported. **This class — correct inputs, correct arithmetic, wrong
  MODEL — is invisible to every check RAICA has**, because nothing verifies that the distribution
  assumed matches the data.
- **Fixed in v1.0.0.275:** (a). **Fixed in v1.0.0.276:** (c) — the note now states DATA
  ROWS; the model was reading our own "N lines" label as the observation count.
- **(b) addressed in v1.0.0.277 — PARTIAL, and NOT yet validated through the real path.**
  Trace result: availability was never the problem. `plot_data` is registered, exposed to the LLM
  (35 tools) and whitelisted in `Ask.yaml`; the chain broke at SELECTION. Two things had to be
  true for the answer to narrate a chart that did not exist, and both were:
  1. `_ARTIFACT_MARKER_RELAY` already forbids it ("You CANNOT create a chart, plot, graph or image
     yourself") and tells the model to describe the data in prose when no marker is present. **The
     directive was simply ignored** — the same shape as the "computed as" fabrication.
  2. **The gather gate had no basis to object.** It judged only whether DATA and DERIVED FIGURES
     were in hand, so `sufficient` was an HONEST verdict with no chart made. Nothing in the loop
     held out for the artifact.
  The fix extends the gate's judgement to anything the request asks the system to PRODUCE: such a
  thing is not in hand unless a tool produced it and its marker appears in the gathered output.
  A directive can be ignored; a gate that withholds `sufficient` cannot. Stated as POLICY, LLM-
  judged — no phrase list, per the standing no-keyword-hardcoding directive (pinned by
  `test_the_artifact_rule_is_POLICY_not_a_keyword_matcher`).
  **Damper** (this fix creates a control loop — it demands an artifact): `describe_reference`
  renders `plot_data`'s short output in full, so the `[[chart:…]]` marker is VISIBLE to the next
  assessment and cycle 2 cannot re-demand it. Verified empirically, pinned by
  `test_a_produced_chart_marker_is_VISIBLE_to_the_next_assessment`. `no_progress` backstops it.
  **Consistency (no-inconsistency clause):** gate and relay sequence rather than conflict — the
  gate says "go make it" during gathering; the relay says "if it still does not exist, say so" at
  synthesis.
  **RESIDUE, still open:** this makes the chart EXIST when one can be made. It does NOT stop the
  model narrating a visual when the gate exhausts its rounds and no chart could be produced — that
  case rests on the relay directive alone, which is exactly what failed here. A post-answer
  LLM-judged fabrication check (alongside the `nondr-citation` shadow audit) is the right home for
  it; not built.
  **NOT VALIDATED END-TO-END.** Unit tests only (stubbed LLM); the discriminating test fails on
  pre-fix code. No real chart request has been run through the server since the change.
- The model-choice problem in the last bullet is unaddressed and may not be fixable by tooling
  alone.
- **Do not clear** without: a request of this shape producing a real chart, and a tail estimate
  that either uses an appropriate distribution or states that the normal fit understates it.

### SI-039 — Deep Research synthesis latency 8.7x the baseline  [P2 — CONFIRMED by measurement, cause UNATTRIBUTED]
- **Observed (2026-08-14, first Tier-1 run against v1.0.0.272):**
  ```
  REGRESSION  PERF  dr_synthesize_s   368   (base 42.4, lower_better)   8.7x
  REGRESSION  PERF  dr_latency_s      621   (base 141,  lower_better)   4.4x
  PASS        PERF  dr_verify_s        80   (base 53.8)
  ```
  Concentrated in SYNTHESIS — verify passed. Consistent with a 426 KB synthesis prompt observed
  in the log during the run, which routes to the heavy `pro` model
  (`deep_research.engine.heavy_threshold_chars`).
- **Every CODE metric PASSED** in all three baselined scenarios (S1 citation_count 12/base 13 and
  specific_url_ratio 1.0; S3 vision_ran + keyword hits; S2 dr_completed, attachment_count 2,
  pdf_valid, html_self_contained, doc_title_is_section). So this is a performance regression, not a
  correctness one.
- **Cause NOT established — two candidates, deliberately not chosen between:**
  1. Something in the v1.0.0.259-272 work. The second round and gather gate add model calls, but
     both sit on the **non-DR** path and should not touch DR synthesis at all. If they are
     implicated, that is a scope leak worth finding.
  2. **Baseline staleness.** `baseline.json` predates this session and the DR scenarios run
     `repeats=1` — a single sample of a stochastic multi-minute pipeline against a possibly-old
     baseline is weak evidence in either direction.
- **To attribute it:** run S2 alone against the pre-session commit (`cda77be`) and compare. ~10
  minutes. That either exonerates this work or finds a real problem. **Do not record a cause before
  that runs.**
- **Do not clear** without a like-for-like S2 comparison, n>=2 per arm given the variance.

### SI-040 — The Tier-1 benchmark takes 30-45 min, so it is never run  [P3 — CONFIRMED]
- **Observed:** `make benchmark-full` advertises ~15 min and took **30+ min** to complete, with the
  two DR scenarios accounting for nearly all of it (7-10 min per request).
- **Why it matters:** the pre-commit hook asks for this suite on every core-workflow change. It went
  **unrun across thirteen consecutive releases** (v1.0.0.259-272) partly for this reason. A gate
  that costs 30-45 minutes will not be run before a deploy, so in practice it gates nothing.
- **Also found:** `S4_multi_ticker_8` has **no baseline entries at all** — every metric printed as
  `INFO (base —)`, so the suite cannot fail on it however bad the numbers get. Its values looked
  healthy (249 claims checked, 0.024 unsupported ratio, 212 unique sources, 0 truncated) but
  `chart_markers_in_answer: 0` on an 8-ticker stock scenario is worth a separate look.
- **Direction (not started):** a fast lane that runs S1+S3 (~1 min, both baselined) on every commit,
  with the DR scenarios promoted to a nightly or pre-deploy-only job.

### SI-038 — A FABRICATED `[[chart:...]]` marker can launder an ungrounded answer past NewX's citation guard  [P1 — CONFIRMED by invocation]
- **Observed (2026-08-14, local, the Treasury request, 3 runs of 3):** EVERY run emitted an invalid
  marker, in three different shapes:
  ```
  run 1  [[chart:eyJuYW1lIjoiVVMgVHJlYXN1cnkgRGFpbHkgWWll...   (base64 of a chart JSON)
  run 2  [[chart:6a2e2a6b-1e0e-4e0e-8e0e-6e0e-6e0e-6e0e-6e0e]] (UUID-shaped)
  run 3  [[chart:ea2e5e6e-5e5e-4e5e-8e5e-5e5e5e5e5e5e]]        (UUID-shaped)
  ```
  **The real format is a PUBLISHED IMAGE URL**, and only the acquire→store→render→publish chain can
  mint one — `datasources/data_chart_builder.py`:
  ```python
  return f'[[chart:{url}|align={align}|caption="{cap}"]]'
  ```
  So none of the three is a chart, including the base64 one. (An earlier note in this session called
  that run's marker genuine; it is not — base64 JSON is no more a published URL than a UUID is.
  Correcting it here so the record is not wrong.)
- **Why the model invents them:** the request asked for a chart over a FETCHED CSV, and no tool can
  produce that — SI-028 **P2a (`plot_data`) is not built**. `search_datasets`/`compare_datasets`
  chart only from the dataset catalog. Faced with an explicit chart instruction and no capability,
  the model emits the marker it has seen in its instructions. This is the LLM-Policy Gate's
  no-inconsistency clause biting: @Ask's prompt tells it to "reproduce every [[chart:...]] marker
  EXACTLY as returned" and never to redirect the user elsewhere, while it holds no tool that can
  chart a fetched file.
- **Why this is P1 and not a broken image.** NewX treats the marker as PROOF of tool-sourcing.
  `newx/app/ai_connector/responder.py` (`_ARTIFACT_MARKER_RE` / `_has_tool_artifact`) states it
  outright: markers "are emitted ONLY when a RAICA data tool actually produced a real, rendered
  asset ... Their presence is therefore proof the reply is TOOL-SOURCED, not hallucinated", and the
  citation guard accepts them **in place of a source URL**. That premise is now false. A reply with
  no valid citation and one invented marker passes a guard designed to stop exactly that.
- **Cause (SUSPECTED — not yet traced):** nothing validates a marker's payload before the reply is
  accepted. The renderer presumably fails or draws nothing, but the GUARD has already been
  satisfied by the marker's mere presence. **To confirm or refute:** post a reply containing a
  syntactically valid but meaningless marker and no URL, and see whether the citation guard admits
  it. Do not record the cause until that is run.
- **Fix direction (not started), two independent halves:**
  1. **Validate the marker where the guard reads it.** A real marker's payload is a URL on our own
     publisher host; a UUID or a base64 blob is not. Validation belongs at the guard — the place
     that treats the marker as evidence — not only at the renderer, which merely draws nothing.
  2. **Remove the reason to invent one:** build SI-028 P2a (`plot_data`) so a fetched CSV can
     actually be charted. Until then the honest behaviour is to say a chart cannot be produced,
     which the @Ask prompt currently discourages.
- **Do not clear** without a test showing a fabricated marker is rejected while a real one passes.

### SI-036 — `compute` cannot be selected for FETCH-then-CALCULATE: the non-DR path runs ONE tool round, decided before any data exists  [P1 — CONFIRMED on production by the user's own test]
- **Observed (2026-08-14, live prod, the user's Treasury request, run TWICE):** `compute` was
  loaded, whitelisted and offered — `Available tools: [... 'compute']` — and was **never called**:
  ```
  tool calls: ['lookup_website', 'lookup_website']
  ```
  Run 1 without the Ask system prompt, run 2 with the `DERIVED FIGURES MUST BE CALCULATED`
  directive verifiably present in the merged prompt (assertion in the harness, 7,378 chars). Same
  result both times. **The directive did not change tool selection.**
- **CAUSE — CONFIRMED from the request's own log, and it is architectural, not a prompt problem.**
  The non-DR path performs exactly **one** tool-calling round:
  ```
  About to call LLM Manager for tool calling
  tool calls: ['lookup_website', 'lookup_website']   <- chosen ONCE, before any data exists
  LLM Manager tool calling response received  -> synthesis -> POST-LLM
  ```
  Every tool is chosen **up front**, before the CSVs are fetched. `compute` is inherently a
  SECOND-round tool — what to calculate is unknowable until the data is in hand — so on this path
  it can essentially never be selected for the fetch-then-calculate pattern. No prompt wording can
  fix this; the round structure is the gate. `compute` is also **absent from the DR path's
  `sources.allowed`**, so the multi-round path cannot reach it either.
- **Consequence:** the answer degraded in exactly the way the user's prompt forbade — the minimum
  spread was **estimated** ("narrowed to around 20-22 basis points", "approximately"), for a number
  sitting in a CSV it had already fetched, against an explicit "do not fill gaps with estimates —
  say so plainly instead". Run 1 was arithmetically self-refuting (minimum +0.52 reported beside a
  start value of +0.23). It also claimed the 5Y "rose from approximately 4.35% to 4.32%".
- **This was a DESIGN miss, and the process guard that should have caught it did not fire.** The
  architecture-first gate was applied to tool REGISTRATION and WHITELIST reachability (both traced,
  both correct) but never asked *"can a tool be invoked AFTER another tool's output exists?"* — the
  stage that actually defeats the feature. Worse, the pre-ship validation used a prompt with the
  data **inline**, which makes `compute` a legitimate FIRST-round call — so the isolated test
  passed and hid the real-path failure. That is the textbook bypass the gate exists to prevent.
- **Options (NOT started, need sign-off):** (a) a second tool-calling round on the non-DR path when
  the first round returned data — the general fix, and it would help any compute-like tool;
  (b) add `compute` to the DR `sources.allowed` so at least the multi-round path can reach it;
  (c) fold computation into the data-fetch tool's own return. **Do not clear** until `compute` is
  observed in `tool calls:` on a real fetch-then-calculate request.

### SI-035 — Two files register the SAME tool name; which implementation is live depends on filesystem order  [P2 — CONFIRMED by invocation]
- **Observed (2026-08-13, while verifying SI-028 P2b tool discovery):** `discover_user_tools()`
  returns `analytical_visualizer` **twice**:
  ```
  ['analytical_visualizer', 'analytical_visualizer', 'calculator', 'compare_datasets', ...]
  ```
  Two files define it — `user_tools/analytical_visualizer.py` (name from `self._name`) and
  `user_tools/analytical_visualizer_tool.py` (returns the literal `"analytical_visualizer"`).
- **Why it matters:** registration is `self.available_functions[tool.name] = wrapper`
  (`fastapi_server_complete.py:552`), so the second load **silently overwrites** the first. The
  winner is decided by `os.listdir()` order in `tool_discovery.py:40` — filesystem order, which is
  not guaranteed stable across machines or after a re-checkout. Local and production can therefore
  run DIFFERENT implementations of the same tool name with no log line saying so.
- **Sharper because of the design decision:** `docs/RAICA_GENERALIZED_EXTRACT_CHART.md` explicitly
  REJECTS wiring `analytical_visualizer` (it generates and EXECUTES chart code, emits no
  `[[chart:]]` marker, writes to a sandbox path). Two copies of a deliberately-rejected tool, one
  shadowing the other, is worse than either.
- **To resolve:** determine which file is the live one on prod, delete or rename the other, and add
  a duplicate-name guard to `discover_user_tools()` that logs loudly rather than overwriting.
  **Do not clear** without confirming which implementation prod was actually running.

### SI-033 — OpenAlex rate limit is the NEXT binding constraint now that SI-032 unblocked the calls; RAICA is not in the polite pool  [P2 — CONFIRMED by counts, cause SUSPECTED]
- **Observed (2026-08-13, S9 benchmark, 3 consecutive DR runs):** `OpenAlex search error: 429`
  **103 times across 103 papers searches** — every single OpenAlex call in the arm. The preceding
  arm on the same machine saw 17 × 429 starting only 8 minutes in, so the budget is consumed
  quickly and does not recover between back-to-back runs. Crossref 66 × 429 and Semantic Scholar
  96 × 429 in the same window.
- **Why this appeared only now:** before SI-032, most OpenAlex calls died at HTTP 400 before they
  could count against a quota. Making the query valid converted silent failures into real traffic,
  and the quota became the limit. This is a consequence of the fix working, not a defect in it —
  but it caps the benefit.
- **Cause (SUSPECTED — not yet tested):** OpenAlex and Crossref both grant a much higher-rate
  "polite pool" to callers that identify themselves with a **`mailto`**, either as a URL parameter
  or inside the User-Agent. `_fetch_json_content` sends a UA whose comment claims the polite pool
  (`"RAICA-research/1.0 (academic literature search)"`, tool line ~1076) but carries **no mailto**,
  and `_search_openalex` (line ~937) adds no `mailto=` parameter — so RAICA is almost certainly in
  the COMMON pool. **To confirm or refute:** issue the same burst with `mailto=` present and
  compare the 429 rate. Do not record this as the cause until that is run.
- **Impact if real:** OpenAlex is the largest all-discipline corpus (250M+ works) and the main
  humanities channel after Layer A routing. Losing it to 429s returns DR to the general-web
  sourcing SI-032 was meant to fix. Needs an operator-supplied contact address (.env, secrets only).

### SI-034 — Higher retrieval volume overruns the synthesis budget; sources_truncated 0 → 17  [P2 — SUSPECTED, confounded]
- **Observed (2026-08-13, S9, n=3 per arm):** `sources_truncated` **0 → 17** (runs [0,0,0] →
  [17,12,23]; ranges do not overlap), with log lines of the form `truncated (~90892 tokens)`.
  Alongside it `evidence_items` 34 → 56 and `unique_sources` 98 → 160, and `answer_chars`
  44,735 → 27,641.
- **Reading:** the SI-032 fix genuinely increases how much evidence DR gathers. That is the point —
  but the extra evidence appears to exceed what synthesis can absorb, and the answer got SHORTER
  while the evidence pool grew, which is the wrong direction and suggests material is being dropped
  at the synthesis boundary rather than used.
- **Why only SUSPECTED:** the same run was confounded by SI-033 (OpenAlex 429 on 103/103 calls in
  that arm), so the shorter answer may reflect the lost corpus rather than truncation. **Do not
  attribute either way** until the arms are re-run with the order reversed or a cooldown between
  them. See the SI-032 benchmark note.

### SI-032 — Academic search is substantially BROKEN in production; the whole raw sub-question is sent as the API query  [P1 — cause CONFIRMED by falsification · fix shipped v1.0.0.260 · AWAITING prod re-measure before clearing]
- **Observed (2026-08-12, across the retained prod logs, 12 DR runs):** 158 academic-source
  failures. Two of them are OUR bug, not rate limiting:
  ```
  OpenAlex search error: 400, message='Bad Request',
    url='https://api.openalex.org/works?search=What%20do%20independent%20analyses%20and%20
         comparisons%20conclude%20about%20the%20suitability%20of%20GPIQ,%20QQQI,%20and%20TDAQ...'
  DOAJ search error: 400, message='Bad Request',
    url='https://doaj.org/api/v2/search/articles/What%20do%20independent%20analyses%20and%20...'
  ```
  **Success vs failure, measured:** OpenAlex **11 ok / 47 × 400 (81% failing)**; DOAJ
  **4 ok / 51 × 400 (93% failing)**.
- **Cause (CONFIRMED 2026-08-13 by falsification through the real code path, and CORRECTED —
  the mechanism first recorded here was wrong in its details):** the planner's natural-language
  SUB-QUESTION is passed verbatim as the bibliographic query, and these catalogues parse the
  argument as a **query EXPRESSION, not as free text**. The killer is not length — it is that
  every planner sub-question ends in `?`, which both APIs read as an OPERATOR. Each server names
  its own rule in the 400 body:
  ```
  OpenAlex -> {"error":"Invalid query parameters error.",
               "message":"Wildcards (* or ?) require exact (no-stem) search..."}
  DOAJ     -> {"status":"bad_request","error":"Query contains disallowed Lucene features"}
  ```
  The named falsification test was run — same code path, short keyword query:
  ```
  source     arm    n_results  chars
  openalex   LONG      0        243   <- the exact string from this log
  openalex   SHORT     5         34
  doaj       LONG      0        215
  doaj       SHORT     3         33
  ```
  **A competing cause was REFUTED, not merely unconsidered:** re-issuing the identical query with
  strict yarl/aiohttp encoding returned the same 400 from both APIs, so this is NOT a URL-encoding
  bug on our side; removing the `?` alone returned 200. **Two claims originally recorded here are
  withdrawn:** (a) *"DOAJ puts the query in the URL PATH, which a long sentence breaks outright"* —
  a 131-char punctuation-free query returns HTTP **200** with 0 matches, so the path is fine and
  length is a RELEVANCE problem, not a transport one; (b) *"arXiv/PubMed tolerate it"* — arXiv
  does, **PubMed does not**: it returns an EMPTY SET (0 vs 5), which is worse than a 400 because
  nothing errors.
- **Scope, measured across all 11 corpora (WIDER than the 2 first logged):**
  | effect | sources | mechanism |
  |---|---|---|
  | hard HTTP 400 | `openalex`, `doaj` | query-DSL operators |
  | silent 0 results | `pubmed`, `core`, `doab`; `europe_pmc` 5→1 | over-long AND-ed term lists |
  | unaffected | `arxiv`, `crossref` | — |
- **Other channels failing in the same window:** `Semantic Scholar` 73 × 429 and `CORE` 26 ×
  "likely needs API key" (both SI-006, awaiting free registration), plus **`Crossref` 23 × 429**,
  which was NOT previously tracked.
- **Why this is P1 and not housekeeping.** It is the most likely CAUSE of the user's standing
  complaint that DR answers lean on Wikipedia. With five academic channels degraded, general web
  search is what remains, and the encyclopedia is what general web search returns. **Two
  consecutive policy-only attempts to fix the sourcing mix failed under measurement
  (v1.0.0.257 reverted after external review; the v1.0.0.259 attempt dropped before shipping)
  — because no directive can cite scholarship the retrieval layer never fetched.**
- **Fix shipped v1.0.0.260** — two layers, because neither alone is sufficient (the first gate
  produces a well-formed query; the second guarantees it stays valid on the wire):
  - **Fix A — planner policy** (`research/engine.py`): `published_papers_search` was listed among
    the sources for which the planner should OMIT a per-source query and let the sub-question
    sentence be used. It is now told to send bibliographic keywords via the existing
    `per_source_queries` mechanism, and the assessor's `next_queries` prompt says the same, so
    rounds 2+ match round 1. Policy language, LLM-judged — no keyword lists.
  - **Fix B — transport** (`user_tools/published_papers_search_tool.py`): the query is rendered
    valid in each source's own query syntax at a single chokepoint (`_prepare_search_tasks`), so
    every caller — DR or not — is covered even if `per_source_queries` is turned off. Protocol
    constants, measured per API; nothing here interprets meaning.
  - **Parity defect found by the adversarial audit and also fixed:** the below-`min_rounds`
    re-issue rebuilt the plan's tasks INLINE without consulting `queries`, so on that path
    published_papers_search silently received the raw sub-question again — re-opening the bug for
    exactly the runs that gather hardest. Both callers now share `DeepResearchEngine._plan_tasks`.
- **Evidence of recovery (real tool entry point, `execute()`, 3 scholarly topics):**
  | arm | papers retrieved | HTTP 400s |
  |---|---|---|
  | PRE (pre-fix code, raw sub-question) | 42 | 6 |
  | POST (fixed code, planner's keyword query) | **104** | **0** |

  The planner half was verified on the REAL planner with the REAL model, n=3 (non-deterministic
  decision): **3/3 runs** emitted bibliographic queries for every `published_papers_search` task.
  Regression: `tests/unit/test_si032_academic_query_syntax.py`, 30 tests, all failing on pre-fix
  code (the real-entry-path case fails on a genuine assertion, not a missing-attribute crash).
- **S9 partial benchmark, 2026-08-13, n=3 per arm — the mechanical claim held, the QUALITY claim is
  UNRESOLVED because the experiment was confounded.** Recorded in full because the confound is the
  finding:
  | metric | PRE (v1.0.0.259) | POST (v1.0.0.260) | note |
  |---|---|---|---|
  | OpenAlex 400 / DOAJ 400 | 14 / 17 | **0 / 0** | the fix, confirmed again |
  | evidence_items | 34 | **56** | ranges do not overlap |
  | unique_sources | 98 | **160** | ranges do not overlap |
  | retrieval_depth_chars | 1,966 | **2,750** | ranges do not overlap |
  | scope_violations | 5 | **0** | ranges do not overlap |
  | academic_share | 0.739 | **0.429** | moved AGAINST the change |
  | encyclopedic_share | 0.000 | **0.238** | moved AGAINST the change |
  | answer_chars | 44,735 | 27,641 | moved against |
  | sources_truncated | 0 | 17 | see SI-034 |

  **The confound:** arm ORDER is entangled with rate-limit state. The PRE arm ran first and drew
  down the shared OpenAlex quota (its own 429s begin 8 min in); the POST arm then 429'd on **103 of
  103** papers searches, starting 56 seconds after it began. OpenAlex — the largest all-discipline
  corpus and the main humanities channel after Layer A routing — contributed **nothing** to the POST
  arm. That is sufficient on its own to explain academic_share falling and encyclopedic_share
  rising, so those two numbers say nothing about the fix. See SI-033.
  **Corrected experiment before any quality verdict:** re-run with the order REVERSED (or a cooldown
  between arms, or interleaved). If the sourcing-mix delta FLIPS with order, it was the quota; if it
  persists, it is the fix.
- **Do not clear** until the post-fix OpenAlex/DOAJ 400-rates are confirmed on **real production
  DR traffic** (the measurements above are local), and `encyclopedic_share` / `academic_share` are
  re-measured on an UNCONFOUNDED run. The retrieval layer is fixed; the SOURCING-MIX claim it was
  meant to explain is still unproven — and note S9's incumbent already sat at encyclopedic_share
  0.000, so S9 may have too little encyclopedic share to displace to test that claim at all.

### SI-031 — Finance evidence_items halved after a SYNTHESIS-only prompt change  [P3 — SUSPECTED, needs n>=3]
- **Observed (2026-08-11, v1.0.0.256 -> v1.0.0.257):** the S5 7-ticker finance scenario returned
  `evidence_items` PRE **[65, 89]** -> POST **[41, 24]**. The ranges do NOT overlap, which is why this is
  logged rather than waved through as variance.
- **Why it is only SUSPECTED:** the only change in v1.0.0.257 is three directives added to the DEEP RESEARCH
  SYNTHESIS system prompt. Evidence gathering runs UPSTREAM of synthesis, so there is no plausible causal
  path from the change to the count. Either the metric reads something synthesis-side, or this is run-to-run
  variance at n=2 — and n=2 cannot distinguish them.
- **Why it may not matter even if real:** every functional deliverable held in the same comparison — 7/7
  tickers with a DCF, 7/7 with a recommendation, 23 chart markers, comparison table and as-of date present —
  and `claims_unsupported_ratio` IMPROVED 0.0085 -> 0.0015. Fewer evidence items with equal or better output
  is not obviously a regression.
- **Evidence to gather:** re-run S5 at n>=3 on both versions; confirm whether `evidence_items` is derived
  from the GATHER stage or from what synthesis retained. If it is gather-side, the cause is elsewhere and
  this release is exonerated; if synthesis-side, check whether the longer prompt is displacing evidence.
- **Do not clear** without one of: a reproduced n>=3 separation, or proof the metric is synthesis-side and
  the drop is benign.

### SI-030 — Citing a download URL silently downloads files when the reader clicks  [P2 — CONFIRMED by the user, caused by SI-028 P1]
- **Reported 2026-08-11:** the user clicked the Treasury citations in a RAICA answer and got
  **six files downloaded with no browser message and no notification.** *"was not expecting the
  silence."*
- **Not a broken link — a working one behaving as designed.** Verified with full browser headers:
  the cited URL returns `200 text/csv` with
  `Content-Disposition: attachment; filename="daily-treasury-rates.csv"`. The server instructs the
  browser to DOWNLOAD rather than display, so a click renders nothing and silently writes a file.
- **CAUSED BY SI-028 P1 (mine, v1.0.0.253-255).** Making machine-readable files fetchable was
  correct; what I did not anticipate is that their URLs then appear as CITATIONS. A citation is a
  promise the reader can SEE the evidence, and an attachment URL cannot satisfy it.
- **A human-viewable equivalent usually exists** and should be preferred for the citation, with the
  data file named as what was actually parsed. For this source, verified `200 text/html`:
  `.../interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value=2025`
- **Fix shape (NOT implemented):** `_extract_data_content` already holds the response headers —
  capture `Content-Disposition` and surface an `is_attachment` label in the tool result, then a
  policy line: cite a human-viewable page where one exists; if only the download URL is available,
  mark it plainly as a file download so a click is never a surprise. Policy alone is weaker here —
  the model cannot know a URL is an attachment without being told.
- **Generalises beyond Treasury:** every CSV/XLSX/ZIP endpoint P1 unlocked has the same property.
- **Clear only when:** a cited data-file URL is either replaced by a viewable page or explicitly
  labelled as a download, asserted by a test that fails on current behaviour.


### SI-028 — Generalized search → extract → chart fallback  [P1 **DONE** v1.0.0.253; **P2b DONE v1.0.0.261**; P2a/P3/P4 outstanding]
- **P2b SHIPPED 2026-08-13 (v1.0.0.261)**, on the user's sign-off. `utils/restricted_numpy_eval.py`
  + `user_tools/compute_tool.py` + 27 tests. Reproduces the motivating failure exactly:
  `np.min(y30-y10)` = **0.18**, `np.max` = **0.69** (the production answer said +0.19 and +0.53).
  The 12 pre-registered escape vectors were shown to DISCRIMINATE against a permissive plain-`eval`
  build — 27/27 pass on the real evaluator, all 12 fail on the permissive one. Two of them
  (V2, V12) initially passed on the permissive build by ERRORING rather than being blocked, and
  were rewritten into attacks that genuinely succeed when unguarded.
- **⚠️ P2b is NOT yet reachable from the failure it was built for.** `@Ask` sends an
  `allowed_tools` whitelist and the server filters to it (`fastapi_server_complete.py:9808`), so
  `compute` is invisible there until P3 adds one line to
  `../NewX/newx/ai_plugins/Ask.yaml`. Verified: that whitelist currently lists the same 8 tools the
  prod log showed, and `calculator` is absent from it for exactly this reason.
- **P1 SHIPPED 2026-08-11 (v1.0.0.253):** `lookup_website` now dispatches on the SERVER-declared
  `Content-Type` (`_probe_content_type` → `_extract_data_content`), passing CSV/TSV/JSON/XML through
  verbatim with the line count stated and truncation DISCLOSED. Unknown types are returned labelled
  rather than rejected. HTML/PDF paths unchanged. Verified against the exact file that failed:
  **153 lines, complete, `text/csv`**. Plus routing guards (policy, not ticker regex) sending listed
  securities to the specialized analyzer, and a requirement to name the fetched source/rows/columns.
- **P2a-P4 still NOT started** (generic `plot_data` tool, whitelist, fallback-ordering policy).
- **P2b ADDED 2026-08-11 — restricted numpy expression evaluator**, replacing a proposed
  `series_stats` tool. Trigger: the Treasury answer fetched 401 real daily rows and every value it
  QUOTED was exact, while values it DERIVED were wrong — minimum 30Y-10Y spread reported as +0.19
  beside two yields that give +0.67, and a maximum of +0.53 when the true max is +0.69 a year
  earlier. The model was eyeballing extrema over a 401-row table.
  **`calculator` could not have helped and was not even visible:** it is absent from the @Ask
  whitelist (prod log confirms 8 tools offered, not including it), and `user_tools/
  example_calculator.py` takes two scalars and one of add/subtract/multiply/divide.
  **User's call:** expose numpy and let the LLM pick the function rather than write a new
  calculator per statistic. Verified on the real failure — `np.min(y30-y10)`=0.18,
  `np.max(y30-y10)`=0.69 — with `__import__`, `open()` and dunder traversal all blocked by an
  AST allow-list. `sandboxed_executor` explicitly REJECTED as substrate (command whitelist over
  subprocess, not a Python sandbox). Fence + 12-vector adversarial checklist in the design doc;
  numpy allow-list must be an ALLOW-list because numpy ships `np.load` (executes pickles),
  `np.vectorize` (takes a callable), `np.frombuffer`, `np.memmap`.
- **NEW D3 SUBTYPE for the quality baseline:** *unverified derived statistics* — real retrieved
  data, correct quoted values, wrong COMPUTED ones. Invisible to liveness, provenance and
  absent-from-evidence checks; only arithmetic over the retrieved series catches it.
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

### SI-003 — Vestigial MySQL pool  [RESOLVED v1.0.0.281 — removed]
- **Was:** `init_db_pool` / `close_db_pool` / `get_db_connection` / `execute_query` (aiomysql) in
  `fastapi_server_complete.py`, with **0 callers** for `execute_query()`. All RAICA storage is
  SQLite + FAISS.
- **Two real costs, both gone:**
  1. `ServerConfig` raised at IMPORT time unless `DB_PASSWORD` was set — a fresh install refused to
     boot for a database that does not exist. Verified as a REAL footgun, not a theoretical one:
     the removal test fails on pre-fix code with the actual
     `RuntimeError: DB_PASSWORD environment variable is required`.
  2. `/health` reported `"database": "unavailable"` forever, which reads as an outage. The key is
     gone entirely — `services` is now `{"cache", "ollama"}`.
- **Removed:** aiomysql imports · `ServerConfig` DB block + fail-fast · `db_pool` global · the four
  pool functions · lifespan init/close calls · `/health` DB check · `/metrics` `db_stats` (and its
  dangling `"database_pool"` usage, which would have been a `NameError` on the first `/metrics`
  request had only the definition been cut) · `.env.example` DB_* block (incl. the phantom
  `DB_MAX_OVERFLOW` the code never read) · `aiomysql` from requirements.txt · the aiomysql entry in
  `tests/utilities/test_tools_available.py`. `tools/migrate_data.py` (unreferenced, targeted an
  "old Flask server") moved to `archive/experimental/` per the directory convention.
- **Docs corrected** (they promised a MySQL that no longer exists): ADMINISTRATOR_GUIDE component
  list, requirements list, MySQL-security section, `DATABASE_URL` env sample and config-table row;
  DEVELOPER_GUIDE `DATABASE_URL` export.
- **Out of scope, deliberately left alone:** `agents/website_deployer/*.sh` (deploy generated PHP
  sites with their own MySQL via the `mysql` CLI) and `agents/coding_agent`'s `_execute_query_step`
  (unrelated symbol, name collision only).
- **Verified:** 488 unit tests pass; local `/health` returns `{"cache","ollama"}` with no database
  key; `/metrics` returns cleanly with no `database_pool`.
### SI-029 — Feature flag returned FALSE on its first call in any process  →  **FIXED 2026-08-11 (v1.0.0.256)**  [was P1, production]
- **Observed on PROD**, same process, no arguments: `call 1: False · call 2: True · call 3: True ·
  call 4: True`.
- **CAUSE (third diagnosis — the first two were WRONG and are recorded so the method is visible):**
  an ORDERING error inside `datasources.data_charts_enabled()`. It read the
  `RAICA_DATA_CHARTS_ENABLED` override BEFORE calling `data_charts_cfg()` — but it is
  `config_loader.load_config()`, invoked inside that helper, which POPULATES `os.environ` from
  `.env`. Proven by watching the variable across the call:
  `before: None · after importing loader: None · after load_config(): 'true'`.
  So the first caller saw `None`, fell through to the config file's `false`, and every later caller
  got `true`.
- **Two refuted diagnoses:** (1) "lazy config cache" — refuted, `load_config()` returned a stable
  `enabled: False` on every call; (2) "`load_dotenv` timing" — refuted, the variable was still
  `None` immediately after `load_dotenv()`. Only the third was verified by observation.
- **Impact:** `DeepResearchEngine._allowed_sources` adds `search_datasets`/`compare_datasets` only
  `if _data_charts_enabled()`, so whether Deep Research could reach the dataset tools depended on
  whether that property was the FIRST caller in the process — **feature availability decided by
  import order**. After the fix DR's runtime source set is **10** with both tools present.
- **Fix:** load the config first, then read the override. One line moved; precedence unchanged.
- **Tests:** `tests/unit/test_data_charts_flag_first_call.py` (3) — the regression test runs in a
  FRESH interpreter, because the defect exists only on the first call and any in-process test that
  has already touched the config cannot see it. 2 of 3 FAIL on pre-fix code; the third pins that
  the env override still wins, which the fix preserves.


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
