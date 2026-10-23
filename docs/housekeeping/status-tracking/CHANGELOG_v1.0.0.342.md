# CHANGELOG v1.0.0.342 — 2026-10-23

## LLM admin API: change a leg or a key — restart, self-test, automatic restore — Phase 2c

### Added
- `PUT /admin/llm/legs` `{path, model?, provider?, settings?}` and `PUT /admin/llm/secrets/{NAME}` `{value}` (202), and
  `GET /admin/llm/change` (the change being verified; the last outcome). Token-gated like every `/admin/llm/*`.
- **Rules (no list of legs or keys in code):** a discovered leg; only settings it already has, same type; never a
  `${SECRET}` reference through a leg change; a provider change only on a leg that names its own provider, to one under
  `llm.providers`; the proposed file must load through RAICA's own loader. A key: only a name the config refers to as
  `${NAME}`; only letters, digits and `._~:+/=@-` (8–512), written unquoted — python-dotenv and systemd's
  `EnvironmentFile` then read the same value. Values are never echoed (last 4 only).
- **The safety net lives inside RAICA** (a bad change can stop it from starting, and then nothing outside can ask it to
  restore): backup + atomic write + pending marker → restart → the first start records its attempt BEFORE the config is
  read and tests the changed leg once → confirmed, or previous files restored and restarted; a start that finds an
  attempt already recorded (crash before the self-test) restores first.
- **Restart only through a supervisor:** SIGTERM to itself only when this process is the `MainPID` of its `.service`
  unit with `Restart=always`; otherwise the answer says to restart by hand and RAICA never stops itself.
- `.gitignore`: `config/.llm_admin_pending.json`, `config/.llm_admin_last.json`.

### Found through the real server, fixed before commit
- **`INVOCATION_ID` is not evidence of systemd:** a shell started by systemd passes it to everything it launches; a
  hand-started RAICA sent itself SIGTERM and stayed down. Now: own cgroup unit + `MainPID` + `Restart=always`.
- **`uvicorn.run("fastapi_server_complete:app")` imports the server module twice**, so its top-level code runs twice in
  one start: the start check counted two attempts and restored a change that had not failed ("did not confirm" instead
  of "self-test failed"). Now once per process.

### Verified
- `tests/unit/test_llm_admin.py` 23 (+9); 11 planted defects (no crash-restore, failed self-test kept, unsafe key
  characters, any key name, new settings, a secret reference overwritten, no backup, two changes at once, restart
  without a supervisor, the old INVOCATION_ID check, no once-per-process guard) — each red.
- **Real server, hand-started (no supervisor):** a bad model → "restart RAICA yourself", RAICA stayed up; after the
  restart its self-test failed (Ollama's 404) → restored, file identical. A good change (on-box embeddings) → confirmed.
  A start killed with `-9` before its self-test → the next start restored before reading the config.
- **Real server under a user systemd unit configured like production** (`Restart=always`, `EnvironmentFile=.env`): a good
  change → RAICA restarted itself (new PID) and kept it; a bad change → restarted, self-test failed, restored, restarted
  again by itself; a key written through the API → the restarted process received exactly that value
  (`/proc/<pid>/environ`) and python-dotenv parses the same; `.env` restored byte-identical afterwards.
- Every value of this machine's site file equals its pre-session copy (only `config_version` and the m0002 additions).

### Tests adjusted (found by the full unit run before deploy)
- `test_config_migrate.py::test_the_server_migrates_before_anything_reads_the_config` pinned `ensure_site_config` as
  the server's FIRST statement. The LLM admin restore must run before it (the migration would otherwise crash on an
  unconfirmed bad file at every start, before the restore could run), so ONE step may precede it — and the new
  `test_the_step_before_the_migration_imports_no_project_code` keeps `utils/llm_admin.py`'s module-level imports to the
  standard library + yaml (a planted project import → red).
- `test_llm_admin.py`'s embedding test passed alone but failed in the full run: RAICA's HTTP pool keeps one session
  bound to the event loop that created it, and an earlier test's loop leaked in. The test now uses its own pool.
- Full unit suite: 1070 passed, 4 failed — the same 4 fail on the commit before 1.0.0.340 (`test_html_entities`,
  `test_phase5_integration` ×2, `test_title_escaping`): not from this release.

### Docs
- `docs/LLM_ADMIN_API.md` (calls + the safety net), `docs/production/ADMINISTRATOR_GUIDE.md`, `README.md` (also corrects
  the 1.0.0.341 README's version labels).
