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

### SI-003 — Vestigial MySQL pool: dead code + a boot footgun  [P3]  *(spun off from SI-001)*
- **Finding:** the MySQL `db_pool` (`init_db_pool`, `execute_query`, `get_db_connection`) is **unused** —
  `execute_query()` has **0 callers** anywhere; the only references are `health_check` (cosmetic report)
  and the dead helper itself. All real storage is SQLite + FAISS.
- **Two cleanup items:**
  1. `ServerConfig` (fastapi_server_complete.py:197–198) **hard-requires `DB_PASSWORD` or the server
     refuses to boot** — for a DB that is never queried. A fresh install fails to start without a
     meaningless secret. Relax (only require it if the DB is actually used) or remove the pool.
  2. `/health` reports `database: "unavailable"` (alarming for ops) for something intentionally unused —
     remove the MySQL pool entirely, or report `"not_configured"`.
- **Impact:** none functional today (nothing uses it); pure tech-debt + fresh-install footgun. Awaiting a
  decision on cleanup before any code change.

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
