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

| `PUT /admin/llm/legs` `{path, model?, provider?, settings?}` (1.0.0.342) | **202** `{changed, restarting, note}`. Rules: a discovered leg; only settings the leg ALREADY has, keeping their type; never a `${SECRET}` reference (keys go through the next call); the provider only on a leg that names its own, and only one under `llm.providers`. The proposed file must load through RAICA's own loader. 400 with the reason; 409 while another change is being verified |
| `PUT /admin/llm/secrets/{NAME}` `{value}` (1.0.0.342) | **202**. Only a name the config refers to as `${NAME}`. The value may contain only letters, digits and `._~:+/=@-` (8–512 characters) and is written unquoted, so **python-dotenv and systemd's `EnvironmentFile` read the same value** (both checked on a real restart). The value is never echoed (last 4 only) |
| `GET /admin/llm/change` (1.0.0.342) | `{pending, last}` — the change being verified, and the last outcome: `confirmed`, or `restored` with why and the self-test result |

The provider used for a list or a test is built exactly as RAICA builds a leg: the named block under
`llm.providers`, overlaid with the leg's own settings, then `${VAR}`-expanded (`utils/config_loader.get_llm_config`).

## Changing a leg or a key: restart, self-test, automatic restore
A bad change can stop RAICA from starting — and then nothing outside can ask it to restore. So RAICA protects itself:
1. **PUT:** the live file (and `.env` for a key) is backed up (`llm_config.yaml.admin-<time>.bak`, mode 400;
   `.env.admin-<time>.bak`, mode 600), the new file is written atomically (mode 444), and a pending-change marker is
   recorded (`config/.llm_admin_pending.json`).
2. **Restart:** only when systemd will start RAICA again — this process is the `MainPID` of the `.service` unit it runs
   in, with `Restart=always` — RAICA sends itself SIGTERM (the path `scripts/deploy.sh` uses). `INVOCATION_ID` is not
   evidence (a shell started by systemd passes it to everything). **Without a supervisor RAICA never stops itself:** the
   answer says to restart it (`./stop_complete.sh && ./start_complete.sh`); the change is verified at that start.
3. **The first start with the change** records its attempt before anything reads the config, then tests the changed
   leg ONCE (a key: the first leg that uses it): **pass → confirmed; fail → previous files restored and a restart.**
4. **A start that finds an attempt already recorded** (the first start crashed or stopped before its self-test)
   restores the previous files BEFORE the config is read.
   The check counts once per process: `uvicorn.run("fastapi_server_complete:app")` imports the server module twice.

Verified through the real server (2026-10-23), by hand-start and under a user systemd unit configured like production
(`Restart=always`, `EnvironmentFile=.env`): a good change kept after RAICA restarted itself; a bad model restored after
its failed self-test with a second restart; a start killed with `-9` before its self-test → the next start restored;
a key written and read back identically by systemd (`/proc/<pid>/environ`) and python-dotenv.

## Next (Phase 2d)
`offered_models` honoured for a bot's answer: a bot naming an offered model gets that model (on its provider) for the
ANSWER only; a name not on the list is refused with a clear error (owner, 2026-10-23).
