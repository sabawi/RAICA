# CHANGELOG v1.0.0.334 — 2026-10-02

## Ollama embeddings through `/api/embed` (batched, truncating)

**Why:** the first real NewX semantic-search index run failed every batch: RAICA called Ollama's legacy
`/api/embeddings`, which REFUSES text longer than the model's context (HTTP 500, "the input length exceeds
the context length"; all-minilm reads 256 tokens, and a long or Arabic post exceeds it at ~1,000 chars).

### Changed
- `utils/embeddings_api.py` (Ollama provider): one `POST /api/embed` per request with
  `{"model", "input": [...], "truncate": true}` instead of one legacy call per text. Long input is
  truncated to the model's context; token count from `prompt_eval_count`.
- Same vectors as before (measured: cosine 1.0000 between the two endpoints for the same text), so
  stored vectors stay valid. Works on Ollama 0.32.9 (local) and 0.30.8 (prod), checked on both.

### Measured
- 64 inputs including a 1,440-character Arabic text: one call, 618 ms (local).

### Tests
- `tests/unit/test_embeddings_api.py`: 26 — one batched call with `truncate: true`, count mismatch is an
  error, local profile uses `/api/embed`. Planted: `truncate` removed → 2 red.

### Breaking changes
- None. The OpenAI provider path is unchanged.
