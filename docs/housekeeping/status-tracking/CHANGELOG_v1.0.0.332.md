# CHANGELOG v1.0.0.332

**Date:** 2026-10-01
**Theme:** `POST /v1/embeddings` — RAICA serves embeddings to other services (NewX profiling P1)

## New: `POST /v1/embeddings` (OpenAI-compatible)

NewX's adaptive-profiling phase P1 turns each PUBLIC post (caption + vision tags) into a vector to match
content to members' tastes. RAICA already owns an embedding provider; NewX now reaches it through RAICA
instead of holding its own key and model choice. Owner approved the change and the routing (public
posts' text goes to OpenAI via RAICA; restricted posts are never sent).

- `utils/embeddings_api.py` — pure infrastructure: forwards text to the provider configured under
  `document_interrogator.embedding` (OpenAI `text-embedding-3-small`, 1024 dims; Ollama also supported)
  and returns vectors in order. No interpretation, lists or special cases.
- **Fail fast, no fallback model** (PROJECT_CONFIGURATION_DIRECTIVE): every value is read strictly; a
  missing one → 503 naming it. Unlike the document interrogator's loader, it never falls back to another
  model — vectors from a different model live in a different space and would silently corrupt every
  similarity a caller computes. The response names the model used.
- **Response checks:** a wrong vector count, a wrong dimension, a provider error or an unreadable body
  raise (502) — never returned as vectors.
- **Limits** (new config section `embeddings_api`): `max_inputs: 64`, `max_chars_per_input: 8000` →
  400 beyond them, so a misbehaving caller cannot run up the provider bill. Logs carry counts only, never
  the submitted text.
- Route in `fastapi_server_complete.py`, next to `/v1/models`.

## Configuration

New section in `config/llm_config.yaml`:
```yaml
embeddings_api:
  enabled: true
  max_inputs: 64
  max_chars_per_input: 8000
```
No `.env` change (uses the existing `OPENAI_API_KEY`).

## Exposure

Production binds RAICA to 127.0.0.1 only (not proxied by Apache; port 5000 unreachable from outside —
checked), so only local services can call it, like the existing endpoints. The local development server
binds 0.0.0.0 (LAN-reachable) — pre-existing for all endpoints; with this one a LAN client could also
spend OpenAI credit. Low risk on a home network; noted, not changed.

## Tests and verification

- `tests/unit/test_embeddings_api.py` (14) — strict config incl. unset env key, input bounds, ordering,
  count/dimension/HTTP/unreadable failures, Ollama path; no real provider calls. Three planted defects
  (fallback model, no dimension check, no count check) each turned it red.
- Real call through the restarted local server: 3 inputs → 3 × 1024-d vectors, 24 tokens; cosine
  music↔music 0.615 vs music↔graduation 0.200; bad inputs → 400.
- `tests/unit`: 4 failed / 1012 passed — the same 4 fail on 1.0.0.331 (logged SI-107).
- `make smoke`: PASSED. `tests/utilities/run_mu_e2e_verify.py`: rc 0, all five tickers.

## Breaking changes / migration

None. New endpoint and a new config section only.
