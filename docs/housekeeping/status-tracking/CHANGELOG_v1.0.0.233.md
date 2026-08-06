# CHANGELOG v1.0.0.233 — `doctor --probe` now INVOKES models instead of reading a listing

**Date:** 2026-08-05
**Type:** Bug fix (developer tooling) + correction of a false root cause recorded in config/docs
**Runtime impact:** NONE — no lane, model, prompt or server code path changed. `config_server_cli.py`
is an operator CLI; the `llm_config.yaml` edits are comments only.

---

## Why

`config_server_cli.py doctor --probe` decided model availability with `available = model in body`,
where `body` was the response from `/models` or `/api/tags`. **That check is wrong in both
directions**, because a registry listing is evidence in neither:

| Model | Old listing check | Reality (real invocation) |
|---|---|---|
| `gemma4:31b-cloud` | ✗ "does not list this model" | **WORKS** (also vision-capable) |
| `kimi-k2.7-code:cloud` | ✗ "does not list this model" | **WORKS** |
| `qwen3-vl:235b-cloud` | ✓ OK | **HTTP 410 — retired 2026-06-16** |
| `minimax-m3:cloud` | ✓ OK | WORKS |

`/api/tags` lists only models **pulled locally**, so a never-pulled cloud model is absent yet answers
fine; and a retired model stays listed while returning 410. The probe therefore gave a clean pass to
the one genuinely dead model — the exact failure it exists to catch — and flagged two healthy ones.

Consequence: two false "unserved" claims entered `config/llm_config.yaml` and were then cited as the
root cause of the 2026-07-31 vision-lane break (SI-005). That diagnosis is now retracted.

## Changed

### `config_server_cli.py`
- **New `_probe_model(base, model, api_key, timeout)`** — establishes availability by INVOKING the
  model with a 1-token generation. Tries the OpenAI-compatible shape (`/chat/completions`) then the
  Ollama native shape (`/api/generate`), reusing the existing "try both shapes" idiom rather than a
  host→path table.
- **`_probe_endpoints` and `_probe_aliases` rewired** to `_probe_model`; the listing reads are gone.
  `_probe_aliases` dedupes by `(base, model)` so two aliases on one model cost one generation.
- **Verdicts are now scoped to what was actually proven.** Only `404`/`410` (or a 200-with-`error`
  body) count as a dead model. Auth (`401`/`403`), billing (`402`), rate limits (`429`) and generic
  `400`s report as inconclusive `?` with the server's message — never as "dead model". A non-JSON
  error body means the endpoint shape isn't served there, so the next shape is tried.
- **Google OpenAI-compat array bodies handled** — that endpoint returns errors as a single-element
  JSON *array*, which crashed the first cut of this fix with `'list' object has no attribute 'get'`.
- `--probe` / `--aliases` help text now states that the check invokes and costs one request per model.

### `config/llm_config.yaml` (comments only)
- `vision.config.model` / `fallback_model`: the "Ollama does NOT serve `kimi-k2.7-code:cloud`" and
  "`gemma4:31b-cloud` (unserved)" claims are corrected in place, with the refutation and the rule that
  availability is established only by invocation.

### `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md`
- **SI-005 cause RETRACTED.** The vision lane is healthy and the replacement models remain
  image-verified, but the recorded cause was false, so the real cause of the 2026-07-31 break is
  **UNKNOWN** and may recur. Guard installed is documented on the entry.

## Documentation

Surfaced by the new global pre-commit docs/README review mandate, applied to this very release:

- **`README.md` version was 44 builds stale** — `1.0.0.189` in 4 places (title, badge, release link,
  About section, Version History) while `version.py` was at `1.0.0.233`. Corrected. Same failure class
  as the NewX badge that sat 60 builds behind.
- **`doctor` was never documented at all.** The command shipped in `243ac0c` and
  `docs/CLI_MODEL_MANAGEMENT.md` — the file the Administrator Guide calls "comprehensive CLI
  documentation" — had **zero** mentions of it. Added a full `doctor` reference there: the three
  invocation forms, the per-model request cost, why it invokes rather than reading a listing (with the
  wrong-in-both-directions table), and how to read `✓` / `✗` / `?`.
- **`docs/production/ADMINISTRATOR_GUIDE.md`**: added `doctor` to the CLI feature list and the Quick
  Start commands, flagged as a pre-deploy check that exits non-zero on a dead model.

RAICA has **no version-sync test** (NewX has `newx/test_version.py`, which would have caught this drift
years earlier). Worth adding — noted as a follow-up.

## Verification

- `_probe_model` classifies **6/6** correctly: `gemma4:31b-cloud` ok, `kimi-k2.7-code:cloud` ok,
  `minimax-m3:cloud` ok, `qwen3-vl:235b-cloud` dead (410), `deepseek-v3.1:671b-cloud` dead (410),
  `totally-made-up-model:cloud` dead (404). The same test **fails on the old code**, which marked the
  first two ✗ and passed the retired one ✓.
- Full `doctor --probe --aliases` run is clean and **caught a real dead alias the old check was blind
  to**: `deepseek_ollama_cloud` → `deepseek-v3.1:671b-cloud`, HTTP 410, retired 2026-07-15. It is
  listed in `/api/tags`, so the listing check passed it.
- Auth/billing cases correctly demoted to `?`: `gemini_flash_36` / `gemini_pro_25` (HTTP 400 bad API
  key), `openrouter_deepseek` (HTTP 402 no credits).
- `python -m py_compile config_server_cli.py` clean; `llm_config.yaml` parses; `doctor` (no probe)
  unchanged.

## Follow-ups (not in this release)

- `deepseek_ollama_cloud` alias points at a retired model — needs repointing or removal.
- `gemini_flash_36` / `gemini_pro_25` aliases declare `provider: openai` while pointing at Google's
  endpoint, so `API_KEY_ENV_VARS` resolves `OPENAI_API_KEY` and no valid key is sent.
- SI-005's real cause remains unidentified. If vision breaks again, capture the actual error from
  `user_tools/image_to_text.py` at failure time rather than inferring from a listing.

## Migration

None. No config values, models, or runtime behaviour changed.
