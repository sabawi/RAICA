# CHANGELOG v1.0.0.234 — version-sync acceptance test (Tier-0 gate)

**Date:** 2026-08-06
**Type:** New test + pre-commit gate wiring; documentation
**Runtime impact:** NONE — no server code path changed.

---

## Why

RAICA had **no version test**. NewX has `newx/test_version.py`, which asserts its README badge matches
`version.py`; RAICA had no equivalent, and both of its non-importing version surfaces had rotted:

| Surface | Was | Should have been |
|---|---|---|
| `README.md` | `1.0.0.189` (5 places) | `1.0.0.233` — **44 builds stale** |
| `config/logging_config.json` | `1.0.3.122` | `1.0.0.233` — a **different version series** |

`utils/version_sync.py::verify_version_consistency()` already existed and would have caught the
logging_config drift — but nothing ever ran it. The README it never checked at all.

## Added

### `tests/integration/test_version_sync.py` (19 assertions)
Standalone script, exits non-zero on drift, following the `newx/test_version.py` pattern.

- **`version.py` is well-formed** — `MAJOR.MINOR.PATCH.BUILD`; `__version__`, `get_version_info()`,
  `get_release_string()` and `VERSION_TUPLE` all agree with `VERSION`.
- **README agrees on every surface that claims the current version** — badge, `releases/tag/` link, and
  every `RAICA vX` mention (title, About heading, Version History). Checking only the badge is what let
  the other four rot as a group.
- **`config/logging_config.json` agrees** — it cannot import `version.py`, so it rots silently.
- **`utils/version_sync.py::verify_version_consistency()` reports consistent** — reusing the existing
  utility rather than duplicating its logic.
- **`/health` cannot drift by construction** — asserted *statically*: the server must import
  `__version__` and serve that symbol, with no hardcoded version literal anywhere in the API surface.
  Deliberately avoids importing `fastapi_server_complete`, which would boot the whole stack and make a
  pre-commit gate slow and flaky.

**Scope note:** the README check ignores version strings citing the **upstream** Agentic-RAG-System fork
(`Inherited from v1.0.3.123`, `v1.0.3.43 introduces …`). Those are historical facts and must not be
rewritten by a bump — a test that flagged them would be wrong, and would get silenced rather than fixed.

## Wired

- Registered in `TIER0_TESTS` (`tests/benchmark/run_benchmark.py`) — Tier 0 is now **9/9**.
- **`version.py`, `README.md` and `config/logging_config.json` added to `CORE_REGEX`**
  (`tools/benchmark_precommit.sh`). This is the part that makes the test matter: previously a version
  bump triggered **no gate at all**, so the test would have existed without ever running at the moment
  drift is introduced. Verified the regex now matches all three.
- `docs/RAICA_QUALITY_BENCHMARK.md` §2 and §7 updated to match (the trigger script says to keep §7 in
  sync).

## Fixed

- `config/logging_config.json` resynced `1.0.3.122` → current, via the existing
  `utils/version_sync.py::update_all_configs()` rather than a hand edit.
- `README.md` version references brought to current.

## Verification

- Test passes **19/19** on a synced tree.
- **Falsification:** bumping `version.py` without touching any surface produces **5 failures and exit
  1**, naming each drifted file. Confirmed twice — once on a simulated `1.0.0.999`, and again live on
  the real `.233 → .234` bump in this release, which the gate caught before the surfaces were updated.
- Full Tier 0: **9/9 PASS**.
- Trigger check: `version.py`, `README.md`, `config/logging_config.json` all match `CORE_REGEX`;
  a non-core path (`docs/some_doc.md`) correctly does not.

### Gotcha worth recording
While falsification-testing, `git checkout -- version.py` restored the file within the **same second**
and at the **identical byte length** (`1.0.0.999` and `1.0.0.233` are the same size). CPython's default
bytecode invalidation compares only source mtime-in-seconds and size, so the stale
`__pycache__/version.cpython-312.pyc` was treated as valid and the test read the *old* value — producing
a false FAIL under the Tier-0 runner. `python -B` does **not** help: it suppresses *writing* bytecode,
not reading it. If a revert-and-retest gives an inexplicable result, `rm` the `__pycache__` entry.

## Follow-ups

- `utils/version_sync.py` still only *writes* `config/logging_config.json`. If another non-importing
  file starts carrying the version, add it there and to the test together.

## Migration

None.
