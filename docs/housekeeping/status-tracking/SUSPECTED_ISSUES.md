# Suspected Issues Log

Per the global directive *"NEVER dismiss a possible bug without evidence — if busy, log it with a priority
call; clear it only on evidence or a verified fix."* Open items are things NOTICED but not yet confirmed
as bug-or-not. **Do not delete an item on a hunch** — resolve it with evidence (real bug filed/fixed, or
proven not-a-bug) and move it to Resolved with that evidence.

Priority: **P1** act now · **P2** investigate soon · **P3** watch / low-impact.

---

## Open

### SI-004 — data-charts `fbi_cde` source endpoint is dead (404) — configured FBI CDE API path moved  [P2]
- **Observed (2026-07-20):** with a valid `DATA_GOV_API_KEY` (40 chars) loaded, the catalog's configured
  endpoint `https://api.usa.gov/crime/fbi/cde/estimate/national/{measure}` returns **HTTP 404** (HTML
  `<title>CDE</title> Not Found`) for every offense. Probed alternates: `crime/fbi/sapi/api/estimates/
  national/{from}/{to}` and `crime/fbi/cde/summarized/national/{offense}/{from}/{to}` also 404 (they
  returned 403 API_KEY_MISSING only when the `?` separator was malformed — i.e. path exists at proxy
  layer but the resource shape has changed).
- **Impact:** the `fbi_cde` data source (US crime charts, e.g. the original post/5955 request) cannot
  fetch — no chart renders for FBI measures. **World Bank source is unaffected and fully working.** The
  fail-closed policy (v1.0.0.210) prevents hallucination when fbi_cde fails, so this degrades safely
  (honest prose, no fabricated chart) rather than emitting bad data.
- **Evidence:** curl probes above; `EN.ATM.CO2E.PC` archival (WB) is a SEPARATE, already-FIXED issue.
- **Next step to resolve:** rediscover the current FBI Crime Data Explorer national-estimate endpoint +
  response shape (the CDE API was reorganized), update the `fbi_cde` block (`endpoint`, `records_path`,
  `x`/`value` field paths, `params`) in `config/llm_config.yaml`, and re-validate wire-shape with the key.
- **Priority rationale:** P2 — the headline crime-chart use case depends on it, but WB covers the
  acceptance tests and nothing crashes; safe to fix in a follow-up.

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

## Resolved (kept for the audit trail)

### SI-001 — `database: unavailable` on local AND prod  →  NOT a functional bug  (resolved 2026-07-12)
- **Concern was:** silent memory-cache fallback might be degrading a DB-backed feature everywhere.
- **Evidence / proof:** the MySQL pool's only functional consumer, `execute_query()`, has **0 callers**
  across the whole codebase; the pool is referenced only by `health_check` (cosmetic) and its own dead
  helper. RAG/persistence run on SQLite (`document_interrogator` metadata_db) + FAISS, both healthy. MySQL
  is running on live; the pool just fails auth (`root@localhost` — the `DB_USER`/`DB_HOST` defaults) and
  **fails soft**. So `database: unavailable` is cosmetic — **no feature is degraded.**
- **Outcome:** not a functional bug. The real (low-priority) tech-debt it exposed is tracked as **SI-003**.
