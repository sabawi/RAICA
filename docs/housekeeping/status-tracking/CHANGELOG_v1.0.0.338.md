# CHANGELOG v1.0.0.338 — 2026-10-19

## Ollama cloud: a configured `api_key` reaches every Ollama-native route

**Why:** NewX's AI service admin (NewX `docs/DESIGN_ai_service_admin.md`) lets a new site use Ollama's cloud models
with an API key.
- Measured 2026-10-19: Ollama 0.40.6's local daemon does NOT use a key for cloud models (401 with the key in its
  process environment), while `https://ollama.com` accepts it directly.
- So a cloud leg is that leg with `base_url: https://ollama.com` and `api_key: ${OLLAMA_API_KEY}`; RAICA's config
  already supports both per leg. No new provider type.
- What was missing: the key was never SENT.

### Fixed
- `llm_providers/ollama.py`: a configured `api_key` is sent as `Authorization: Bearer …` on `/api/generate`,
  `/api/chat` and `/api/tags`.
  - The local daemon ignores the header; its config carries the placeholder `ollama`.
  - This covers primary, tool calling and arbitrator, plus deep research and the intent/shadow classifiers, which
    call through the manager with a model override.
- `user_tools/image_to_text.py` (vision): it called the module-level `ollama.chat()`, i.e. the library's DEFAULT
  host with no key, IGNORING `vision.config.base_url`. A cloud vision leg would silently have stayed local. It now
  uses `ollama.Client(host=<configured>, headers=<bearer>)`.
- `user_tools/analytical_visualizer.py` (chart tool): sends the configured key.

### Known, unchanged
- The primary leg's emergency fallback (when the LLM manager raises) still posts to the local daemon
  (`ServerConfig.OLLAMA_URL`). With a cloud leg, that fallback reaches an unauthenticated daemon and fails loudly.
  The log line "Sending request to Ollama at OLLAMA_URL" describes only that fallback.

### Tests
- `tests/unit/test_ollama_auth_header.py` (3): a real local HTTP server records what RAICA sends.
  - The provider sends the key on `/api/chat` and `/api/tags`.
  - No key means no header.
  - Vision uses the configured host AND key.
- Planted: the provider's header line removed → red; vision back on `ollama.chat` → red; restored (cmp) → green.
- `tests/integration/test_vision_fallback.py` (Tier 0): the first commit attempt was BLOCKED by Tier 0. Its
  reply-parsing tests mocked the module-level `ollama.chat`, which vision no longer calls, so they recorded nothing.
  The mock moved to `ollama.Client` (it also records the host and headers each call was made with). Every
  assertion is unchanged: the fallback order and the parsed replies. Tier 0: 10/10 after.
- Tier 0 also caught a stale README release link (`releases/tag/v1.0.0.337`); fixed.
