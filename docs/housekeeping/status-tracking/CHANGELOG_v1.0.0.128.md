# CHANGELOG v1.0.0.128

**Date:** 2026-06-16
**Previous:** v1.0.0.127 (tool-calling + arbitrator → glm-5.2:cloud)
**Theme:** **Tool-calling resilience + generalized fallback.** Two follow-ups to the news-bot reliability
work: (#21) retry the tool-calling model on transient 5xx/timeout, and (#22) replace the brittle keyword
forced-fallback with an LLM re-prompt (CLAUDE.md policy-gate).

---

## #21 — Tool-calling 5xx/timeout retry (`llm_providers/openai.py`)

The cloud tool endpoint (e.g. `glm-5.2:cloud` / formerly `qwen3-coder-next:cloud` via the Ollama OpenAI
proxy) intermittently returns HTTP 500. `generate_tools` made a **single** POST — one blip silently
degraded to "no tool calls" → no evidence gathered → autonomous news posts discarded for missing
citations (the original symptom).

- `generate_tools` now retries on **5xx and timeout** with linear backoff (`retry_delay * attempt`),
  config-driven (`retry_attempts`, `retry_delay`). **4xx is never retried** (client errors won't fix).
  Logs `⚠️ … transient` per retry and `✅ recovered on attempt N` on success.
- Unit test `tests/integration/test_tool_calling_retry.py` (5 cases, mocked HTTP): 500→200 recovers,
  timeout→200 recovers, persistent-500 raises after exactly N attempts, 4xx not retried, clean-200
  no regression. All green.

## #22 — LLM re-prompt replaces the keyword forced-fallback (`fastapi_server_complete.py`)

When the tool model returned no tools, the old code classified the request by keywords and force-called a
tool. The `'stock'` branch matched the substring inside the tool name `get_stock_and_company_data`
(printed in the bot's own citation prompt), so **news/general requests were mis-routed to the ticker-only
`comprehensive_stock_analyzer`**, which errored ("TOOL MISUSE") → sourceless post. This is also a CLAUDE.md
LLM-Policy-Gate violation (keyword routing deciding meaning).

- Replaced the `aapl/stock/news` keyword→tool chain with a **single re-prompt** of the same tool model:
  *"You returned no tools — if the request needs current/external info you MUST call the appropriate
  tool(s); otherwise return none."* RAICA executes whatever it returns; it no longer guesses.
- The RAICA-internal **meta-task skip** (title/tag/summary generation) is kept — it matches RAICA's own
  fixed-template prompts (not user intent) and avoids adding an LLM round-trip to every post.
- Failure is non-fatal (logs `🔁 … skipped`, forces nothing).

### Verified end-to-end (local)
- **Greeting** (`@raicaNews hello`, tools enabled): re-prompt fired → returned no tools → *"trusting the
  model"*, **no crash, no stock-tool misuse**.
- **News post**: tools selected on the **first** call (`get_news_summaries`+`search_web`) → re-prompt did
  NOT fire → 6 cited URLs. No regression.
- Together with #21, a transient 500 is now retried (so reaching the re-prompt means a *genuine* no-tools).

## Behaviour notes / tradeoffs
- The re-prompt adds ~1 LLM round-trip (~2s) only when the first call returns no tools AND it isn't a
  meta-task (greetings / knowledge-answerable asks). Bots aren't latency-critical; acceptable.

## Files
- `llm_providers/openai.py` (#21 retry), `fastapi_server_complete.py` (#22 re-prompt),
  `tests/integration/test_tool_calling_retry.py` (new), `version.py` (→ 1.0.0.128), `README.md`, this changelog.
