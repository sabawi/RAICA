# LLM admin API — `/admin/llm/*`

The API the NewX admin page (Admin → AI service) uses to look up, test and change RAICA's models without editing
files. Design and owner decisions: NewX `docs/DESIGN_ai_service_admin.md` (§5 API, §6 discovery). Code:
`utils/llm_admin.py`, endpoints in `fastapi_server_complete.py` (section "LLM ADMIN API").

## Access
- RAICA listens on 127.0.0.1 only; on top of that **every call needs the header `X-RAICA-Admin-Token`** equal to
  `RAICA_ADMIN_TOKEN` in RAICA's `.env` (at least 24 characters; the NewX installer generates it into both `.env`
  files).
- **No token configured → the API is off** (403 on every call). A missing or wrong token → 401.
- **Secrets never leave RAICA through this API:** a key is reported only as `{name, set, last4}`; a value shorter than
  8 characters shows no characters at all. Config values that refer to a secret are shown as the reference
  (`${OPENAI_API_KEY}`), never expanded.

## Legs are discovered, not listed in code
A leg is every node of the site's `config/llm_config.yaml` with a `model` or `model_name`, except the paths under
`admin_ui.leg_exclude` (config — today `code_generation` and `llm.providers`, which are catalogues). Its provider is the
node's own `provider`/`type`, else its parent's `type`, else (a flat leg such as `deep_research.engine`) the primary
leg's provider. Labels come from `admin_ui.labels`. A leg added by a future release appears with no code change.
`admin_ui` and `offered_models` were added by config migration `m0002` (config_version 2).

## Calls
| Call | Answer |
|---|---|
| `GET /admin/llm/config` | `{config_version, legs: [{path, label, provider, provider_from, model, model_key, settings, secrets}], providers: [{name, settings, secrets}], offered_models}` |
| `GET /admin/llm/providers/{name}/models` | `{provider, listed: [...], count}` — the provider's OWN list (Ollama `/api/tags`, OpenAI-compatible `/models`), fetched with the configured key. "Listed" is not proof a model works. 404 for an unknown provider; 502 with the provider's own error |
| `POST /admin/llm/test` `{path, model?, provider?}` (1.0.0.341) | **ONE real call** (it costs one model call) on the leg's current model, or on a proposed one: chat legs get `admin_ui.test_prompt` capped at `admin_ui.test_max_tokens` → `{ok, kind: chat, reply, ms}`; legs in `admin_ui.embedding_legs` embed one word through RAICA's embeddings code, which checks the configured vector size → `{ok, kind: embedding, dims, tokens, ms}`. A provider failure is the result (`ok: false`, the provider's own error), not an HTTP error. Only discovered legs and providers under `llm.providers`; anything else → 404 |

The provider used for a list (and, later, a test) is built exactly as RAICA builds a leg: the named block under
`llm.providers`, overlaid with the leg's own settings, then `${VAR}`-expanded (`utils/config_loader.get_llm_config`).

## Next (Phase 2 c–d)
`PUT /admin/llm/legs/{path}` and `PUT /admin/llm/secrets/{NAME}` (validate,
atomic write with backup, restart, verify, automatic restore), and `offered_models` honoured for a bot's answer.
