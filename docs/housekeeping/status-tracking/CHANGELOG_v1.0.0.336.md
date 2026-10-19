# CHANGELOG v1.0.0.336 — 2026-10-19

## `llm_config.yaml` becomes site-owned: release defaults + structure migrations

**Why:** NewX 1.1 adds an admin page where each installation's admin sets RAICA's providers and the model for every
workflow leg (NewX `docs/DESIGN_ai_service_admin.md`). Owner decisions (2026-10-18/19):
- the installation's values are invariant: an update never changes them;
- updates may only migrate the STRUCTURE (add, move);
- a key is removed only by the release whose code no longer reads it, as with a database column;
- the live file is ignored by git and read-only after install.

### Changed
- `config/llm_config.yaml` → renamed (git) to **`config/llm_config.defaults.yaml`**, the release defaults, now
  starting with `config_version: 1`. The live `config/llm_config.yaml` is **no longer tracked** (`.gitignore`, with its
  `*.bak` backups).
- **New `utils/config_migrate.py`** (stdlib + PyYAML only). `ensure_site_config()`:
  - creates a missing live file as a **verbatim** copy of the defaults (comments kept), mode 444;
  - adds keys the defaults have and the site lacks;
  - applies `config/migrations/mNNNN_*.py` (`VERSION`, `MOVES`, `REMOVES`);
  - **refuses any undeclared value change**, leaving the file untouched;
  - keeps `llm_config.yaml.v<N>.bak` before every rewrite;
  - on older code (a rollback) restores the newest backup it understands, or refuses to start;
  - writes atomically (temp + rename), so a read-only target is fine.
- **Called FIRST in `fastapi_server_complete.py`,** before any project import, and in `ConfigLoader.__init__`, so
  CLIs, tests and scripts get it too. A release that stops tracking a file makes `git pull` DELETE it on existing
  clones; this recreates it, identical, before the first read.
- `config/migrations/m0001_baseline.py`: version 1, no structural change.
- `tools/llm_config_tool.py` (4 writers) and `config_server_cli.py` write through `atomic_write` (read-only file).
- Directive wording (owner-approved 2026-10-19), in `CLAUDE.md` rule 5 and `docs/PROJECT_CONFIGURATION_DIRECTIVE.md`:
  *Single source of truth: each installation's `config/llm_config.yaml` (site-owned, untracked, read-only). The
  repository ships `config/llm_config.defaults.yaml` and structure migrations; developers change defaults there.*

### Transition (existing installations)
Production (`f6773b5`) and the development machine both ran an UNMODIFIED copy of the tracked file, and no config
change landed after `f6773b5`. So the recreated live file has exactly the same values. Measured on the dev machine:
values identical, plus the new `config_version` key; RAICA's own loader reads it. A site with LOCAL edits to the
tracked file would make `git pull` refuse, loudly, instead of losing them.

**How development changes:** a model or tuning change for every installation edits the DEFAULTS. Running
installations see it as a recommendation (`differs_from_defaults()`, shown on the NewX admin page) and keep their
own value.

### Tests
- `tests/unit/test_config_migrate.py` (13):
  - verbatim install, mode 444;
  - no rewrite when current;
  - addition kept / admin value kept;
  - a move carries the value;
  - only declared removals;
  - an overwrite refused with the file untouched;
  - a 200-case property test (no value ever changes);
  - rollback restore or refuse;
  - atomic write onto 444;
  - numbering gaps refused;
  - the defaults' version = the latest migration;
  - the live file untracked and ignored;
  - the server migrates before any project import.
- **Planted defects, each restored from disk and compared with `cmp`:**
  - install re-dumps instead of copying → red;
  - an addition overwrites → 5 red;
  - the "target exists" check removed → still GREEN (the invariant refuses: layered);
  - both safeguards removed → red;
  - rollback restore removed → red;
  - the server hook removed → red.

### Breaking changes / migration
- Developers: edit `config/llm_config.defaults.yaml`. Your own `config/llm_config.yaml` is now yours and is
  read-only; change it with `tools/llm_config_tool.py` (or `chmod u+w` deliberately).
