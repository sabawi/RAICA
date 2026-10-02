# CHANGELOG v1.0.0.333 — 2026-10-02

## On-box embeddings for `POST /v1/embeddings` (`"model": "local"`)

**Why:** NewX semantic search embeds members' search queries. Searches are member data that must not
leave the machine (NewX design C5), so the query cannot go to the default provider (OpenAI).

### Added
- `config/llm_config.yaml` → `embeddings_api.local`: provider `ollama`, model `all-minilm` (384 dims),
  base URL the machine's own Ollama daemon (`http://127.0.0.1:11434`), timeout. No key needed.
- `utils/embeddings_api.py`: `load_embeddings_api_config(profile)` (`None` = default provider, `'local'` =
  the on-box model; strict, no fallback) and `resolve_profile(model)` — absent → default; `"local"` or the
  local model's name → local; anything else → refused.
- `/v1/embeddings` accepts `"model"`; unknown model → HTTP 400; a missing `embeddings_api.local` → 503.
  Still logs counts and the model only — never the text, nothing identifying the caller's users.

### Measured
- Local: 50–60 ms per short text; production: 34 ms median (10 calls), ~1.5 GB RAM available unchanged.
- Separation (cosine): "puppy" vs "a dog playing in the park" 0.30 vs "stock market crash" 0.12;
  "concert" vs "live music on stage" 0.56 vs "cooking pasta" 0.04.

### Tests
- `tests/unit/test_embeddings_api.py`: 25 (local profile config, fail-fast without it, model selection,
  unknown model refused, the local call goes to the on-box daemon). Planted: unknown → default, and
  missing local → default provider (would send queries off the box) — each red.
- Real endpoint (local server): local 2×384, unknown model 400, default unchanged (1024d).

### Deployment
- The model must be present on the machine's Ollama daemon: `ollama pull all-minilm` (done on local and
  prod, 2026-10-02). No dependency changes.

### Breaking changes
- None: requests without `model` behave exactly as in v1.0.0.332.
