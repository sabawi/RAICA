# CHANGELOG v1.0.0.341 — 2026-10-23

## LLM admin API: `POST /admin/llm/test` — one real call on a leg — Phase 2b

### Added
- `utils/llm_admin.test_leg` + `POST /admin/llm/test` `{path, model?, provider?}`: ONE real call on a leg's current
  model, or on a proposed model/provider ("test before saving").
  - Chat legs: `admin_ui.test_prompt`, capped at `admin_ui.test_max_tokens`, through the provider built exactly as RAICA
    builds the leg → `{ok, kind: "chat", reply, ms}`.
  - Legs in `admin_ui.embedding_legs`: one word through RAICA's own `embed_texts`, which also checks the configured
    vector size (a model with another size fails — switching to it would break the document index).
  - A provider failure is the result (`ok: false`, the provider's own error), never reported as a success.
  - Only discovered legs and providers under `llm.providers` (404 otherwise); token-gated like every `/admin/llm/*`.
- Config (defaults, additions picked up by the migrator): `admin_ui.embedding_legs`, `admin_ui.test_prompt`,
  `admin_ui.test_max_tokens` — no prompt, cap or timeout fallback in code.

### Verified
- `tests/unit/test_llm_admin.py` 14 (+5; a real HTTP server plays Ollama and an OpenAI-compatible embeddings service);
  3 planted defects (proposed model ignored, a non-leg path testable, an error turned into a success) — red.
- **Through the real local server:** on-box embedding OK (384 dims, 52 ms); the answer leg `deepseek-v4-pro:cloud`
  replied "OK" in 464 ms (1 billed call); a made-up model → `ok:false` with Ollama's own 404 message; a catalogue path
  → 404; no token → 401.

### Docs
- `docs/LLM_ADMIN_API.md`, `README.md`.
