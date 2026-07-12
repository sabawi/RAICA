# Changelog — v1.0.0.181

**Date:** 2026-07-12
**Scope:** Housekeeping — a persistent suspected-issues tracker + the evidence-based resolution of SI-001, plus a self-caught hardening fix to the tool smoke gate. Docs + test-tooling; no server behavior change (running servers need no restart).

## Added — `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md`
A standing log for possible-but-unconfirmed bugs, per the global directive *"never dismiss a possible bug without evidence — log it with a priority call; clear it only on evidence or a verified fix."* An item is cleared only with proof (real bug fixed, or proven not-a-bug), never on a hunch.

## Investigated & Resolved — SI-001: `database: unavailable` is NOT a functional bug
- **Concern:** `/health` reports `database: "unavailable"` on local AND prod (silent memory-cache fallback, `Access denied for 'root'@'localhost'` at startup) — could a DB-backed feature be silently degraded everywhere?
- **Proof it's benign:** the MySQL pool's only functional consumer, `execute_query()`, has **0 callers** across the codebase; the pool is referenced only by `health_check` (cosmetic) and its own dead helper. All persistence runs on SQLite (`document_interrogator` metadata DB) + FAISS, both healthy. MySQL is running on live; the pool merely fails auth and fails soft. → **cosmetic only, nothing degraded.**

## Logged for later — SI-003 [P3]: vestigial MySQL pool (tech-debt, not urgent)
The investigation surfaced real low-priority cleanup: (1) the MySQL pool is dead code (+ an unused `aiomysql` dependency); (2) `DB_PASSWORD` is hard-required to BOOT (`fastapi_server_complete.py:197-198`) for a DB nothing queries — a fresh-install footgun — and `/health` shows an alarming `database: unavailable` for something intentionally unused. Tracked in the log; awaiting a decision before any code change (touches the startup lifecycle).

## Hardened — tool smoke gate (a flaw it caught in itself)
Running `make smoke` before this deploy exposed two flaws in the smoke test: it passed `{"ticker":…}` to `get_stock_and_company_data`, which reads the `symbol` key (`fastapi_server_complete.py:952`), so the tool fell back to the raw JSON as the symbol and returned a "no data" message — and the gate SCORED THAT AS PASS on length alone (a false pass). Fixed the arg key (→ `symbol`; now returns real data) and added result-level FAILURE-phrase detection ("no data found", "possibly delisted", …) that downgrades such results to WARN. Not a product bug (the tool works; production passes the right key) — a guardrail-quality fix so the gate can't rubber-stamp a broken tool.

## Note
- **v1.0.0.179 `search_web` fix is user-confirmed** working end-to-end (Lindsey Graham + Bear `@Ask` prompts return real sources; 0 `DuckDuckGo Error` since restart).

## No dependency changes.
