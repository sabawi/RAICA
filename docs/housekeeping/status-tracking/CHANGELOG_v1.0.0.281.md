# CHANGELOG v1.0.0.281

**Date:** 2026-08-15
**Focus:** SI-003 — remove the vestigial MySQL connection pool.

## What was removed and why

`fastapi_server_complete.py` carried a complete aiomysql connection pool that nothing used:
`execute_query()` had **0 callers**. All RAICA storage is SQLite + FAISS. (The SQLite→Postgres
production stack belongs to the separate NewX repo.)

It was not merely dead weight — it cost two real things:

1. **A fresh-install footgun.** `ServerConfig` raised at *import* time unless `DB_PASSWORD` was set,
   so a new installation refused to boot without a secret for a database that does not exist. This
   was verified rather than assumed: the removal test fails on pre-fix code with the actual
   `RuntimeError: DB_PASSWORD environment variable is required.`
2. **A permanent false alarm.** `/health` reported `"database": "unavailable"` forever, which reads
   as an outage to anyone monitoring it.

## Changes

Removed from `fastapi_server_complete.py`:
- `import aiomysql` / `from aiomysql.pool import Pool`
- the `ServerConfig` DB block and its `DB_PASSWORD` fail-fast raise
- the `db_pool` global
- `init_db_pool()`, `close_db_pool()`, `get_db_connection()`, `execute_query()`
- the lifespan startup/shutdown calls
- the `/health` database probe — `services` is now `{"cache", "ollama"}` with no database key
- `/metrics` `db_stats` **and its dangling `"database_pool": db_stats` usage**, which would have
  been a `NameError` on the first `/metrics` request had only the definition been cut

Elsewhere:
- `.env.example` — the whole `DB_*` block, including the phantom `DB_MAX_OVERFLOW` the code never read
- `requirements.txt` — `aiomysql` dropped (nothing in the shipped tree imports it any more)
- `tests/utilities/test_tools_available.py` — aiomysql entry removed
- `tools/migrate_data.py` → `archive/experimental/` (unreferenced; targeted an "old Flask server")

Docs corrected, because they promised a MySQL that no longer exists:
- ADMINISTRATOR_GUIDE — component list, requirements list, "MySQL security" section, `DATABASE_URL`
  env sample, and the `DATABASE_URL` row in the environment-variable table
- DEVELOPER_GUIDE — stale `export DATABASE_URL="mysql://..."`

## Deliberately out of scope

- `agents/website_deployer/*.sh` — these provision MySQL for **generated PHP sites** via the `mysql`
  CLI; unrelated to RAICA's own storage.
- `agents/coding_agent/.../_execute_query_step` — a different symbol; name collision only.

## Tests

`tests/unit/test_no_mysql_pool.py` (new, 4 tests), all failing on pre-removal code:

| Test | Pre-fix result |
|---|---|
| server imports without `DB_PASSWORD` | **FAILS** — `RuntimeError: DB_PASSWORD ... is required` |
| no MySQL symbols remain in the server | **FAILS** — `aiomysql still referenced` |
| `/health` no longer reports a phantom database | **FAILS** |
| requirements/.env.example no longer advertise MySQL | **FAILS** |

The first test needed a second attempt to be honest: clearing `os.environ` was not enough, because
`load_dotenv()` runs at import and repopulated `DB_PASSWORD` from the developer's local `.env` — it
passed on the *unfixed* code. It now injects every `.env` value **except** the `DB_*` keys and stubs
dotenv, which reproduces a fresh install precisely.

Suite: **488 passed**, 4 pre-existing failures unchanged.

## Verified locally through the real path

```
/health  → {"status":"healthy","services":{"cache":"memory","ollama":"healthy"}}   (no database key)
/metrics → {...,"cache":{...},"ollama":{...},"tools":{...}}                        (no database_pool)
```

## Upgrade note

`DB_*` variables in an existing `.env` are now simply ignored; no action required. A fresh install
no longer needs `DB_PASSWORD` at all.
