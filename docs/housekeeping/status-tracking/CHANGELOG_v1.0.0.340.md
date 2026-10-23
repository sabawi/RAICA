# CHANGELOG v1.0.0.340 — 2026-10-23

## LLM admin API, read side (`/admin/llm/config`, `/admin/llm/providers/{p}/models`) — Phase 2a

**Why:** NewX 1.1.0.0's admin page (Admin → AI service) must look up, test and change RAICA's models without editing
files (NewX `docs/DESIGN_ai_service_admin.md`, approved 2026-10-19; owner "go with … 5", 2026-10-23).

### Added
- `utils/llm_admin.py` + endpoints in `fastapi_server_complete.py`:
  - `GET /admin/llm/config` — the site's legs, providers and offered models.
  - `GET /admin/llm/providers/{name}/models` — that provider's own model list, fetched with its configured key.
- **Access:** header `X-RAICA-Admin-Token` must equal `RAICA_ADMIN_TOKEN` (`.env`, ≥ 24 characters). No token
  configured → the API is off (403); missing/wrong → 401. Constant-time comparison.
- **Secrets** are reported only as `{name, set, last4}`; config values show the `${NAME}` reference, never a value.
- **Legs are discovered** from the config (every node with `model`/`model_name`), minus `admin_ui.leg_exclude`
  (config), labelled by `admin_ui.labels` (config) — no list of legs in code. On the release defaults: the design's
  10 legs.
- `LLMProvider.list_models()` (base: "cannot list" error; Ollama `/api/tags`, OpenAI-compatible `/models`, with the
  configured key). A provider error is raised with its status, never returned as an empty list.
- **Config migration `m0002`** (config_version 2): adds `admin_ui` (leg exclusions + labels) and `offered_models: []`.
  Additions only.

### Verified
- `tests/unit/test_llm_admin.py` (9; a real HTTP server records what reaches the provider); 7 planted defects
  (exclusions ignored, a secret value leaked, token not checked, no token = open, flat legs missed, provider error
  hidden, no key on the list call) — each red. `tests/unit/test_config_migrate.py` 13/13.
- **Through the real local server:** the migration ran on this machine's site file — `1 -> 2`, added `admin_ui`,
  `offered_models`, moved/removed nothing, every existing value identical (diffed), previous file kept as
  `llm_config.yaml.v1.bak`; no token / wrong token → 401; with the token: config_version 2, 10 legs, 5 providers, no
  `.env` value anywhere in the response; Ollama listed 42 models, OpenAI 135; an unknown provider → 404.

### Docs
- `docs/LLM_ADMIN_API.md` (new), `docs/production/ADMINISTRATOR_GUIDE.md` (token), `README.md`.

### Migration / upgrade
- Set `RAICA_ADMIN_TOKEN` in `.env` to use the API (the NewX installer will generate it; Phase 4). The config migration
  runs by itself at start.
