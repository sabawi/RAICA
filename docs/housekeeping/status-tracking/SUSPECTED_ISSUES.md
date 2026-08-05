# Suspected Issues Log

Per the global directive *"NEVER dismiss a possible bug without evidence — if busy, log it with a priority
call; clear it only on evidence or a verified fix."* Open items are things NOTICED but not yet confirmed
as bug-or-not. **Do not delete an item on a hunch** — resolve it with evidence (real bug filed/fixed, or
proven not-a-bug) and move it to Resolved with that evidence.

Priority: **P1** act now · **P2** investigate soon · **P3** watch / low-impact.

---

## Open

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
