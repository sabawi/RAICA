# CHANGELOG v1.0.0.127

**Date:** 2026-06-16
**Previous:** v1.0.0.126 (citation grounding Phase 0 — shadow)
**Theme:** **Tool-calling + arbitrator model swap → `glm-5.2:cloud`.** Replaces `qwen3-coder-next:cloud`,
which was throwing intermittent HTTP 500s from Ollama cloud — the real root cause of autonomous news/finance
bots silently failing to post (no tools selected → no evidence URLs → NewX's citation guard discards the post).

---

## Root cause (investigated from live logs)

Operator report: "since the v1.0.0.126 deploy, scheduled NewX bots stopped posting." Investigation
**exonerated the .126 deploy** and found the true cause:

- The tool-selection model **`qwen3-coder-next:cloud` intermittently returns HTTP 500** from Ollama cloud
  (`❌ OpenAI tool API error 500: Internal Server Error`, e.g. 14:26 and 17:18 UTC on 2026-06-16) — the same
  family of transient cloud 5xx we hit in Deep Research (.74–.79).
- On a 500, no tools are chosen → the bot produces a post with **no source URLs** → NewX's
  *"has no URLs but plugin requires citations"* guard correctly **discards** it.
- A pre-existing brittle forced-fallback (keyword chain at `fastapi_server_complete.py:10419`) then misroutes
  news/general bots to `comprehensive_stock_analyzer` (a ticker-only tool that errors), guaranteeing the
  discard. (Tracked separately — see "Follow-ups".)
- The "no-URL discard" is **chronic**: logged multiple times daily for 10+ days, including 6× on 2026-06-16
  *before* the .126 restart. `.126`'s only code change is DR-path shadow grounding, which never runs for these
  bots (`deep_research:False`). Live config was byte-identical to the pre-deploy backup except the additive
  `citation_grounding` block.

## Change

- `config/llm_config.yaml`:
  - `llm.tool_calling.config.model`: `qwen3-coder-next:cloud` → **`glm-5.2:cloud`** (line ~84).
  - `arbitrator.config.model`: `qwen3-coder-next:cloud` → **`glm-5.2:cloud`** (line ~163) — so no path depends
    on the flaky qwen cloud model.

No code change. **No NewX change needed**: NewX never sends `tools_calling_model` (verified — payload builder
`newx/app/ai_connector/responder.py:403-454`, and the scheduler reuses `call_raica`), so RAICA's config
default governs the tool model for *all* bot requests (mentions + autonomous).

## Verification (local, end-to-end)

- `glm-5.2:cloud` present on Ollama; OpenAI tool-calling works (`finish_reason: tool_calls`), **3/3 consistent**
  picking `get_news_summaries` for a news prompt (vs qwen's fallback misrouting to the stock tool).
- Full raicaNews-style request through local RAICA `/v1`: glm-5.2 generated
  `[get_news_summaries×2, search_web×2]` → tools ran → **19 specific article URLs** (BBC/Al Jazeera/DW/
  ProPublica article pages) in a properly-cited Markdown briefing (headline-as-link-text). Layer-1 filtering
  correctly skipped generic homepages.

## Tradeoff

- glm-5.2 is a **reasoning model**: the tool-selection step took ~9s in the full run (vs qwen ~1s when healthy).
  Acceptable for autonomous bots; adds a few seconds to interactive @Ask replies. Reliability >> latency here.

## Follow-ups (not in this release)
- Add 5xx retry/resilience to the tool-calling path (mirror DR transient-5xx retry) so any model's brief blip
  doesn't nuke evidence gathering.
- Replace the brittle forced-fallback keyword chain (`:10419`) with policy-driven fallback to general web
  evidence tools (CLAUDE.md policy-gate compliance) — never a ticker-only stock tool for news/general bots.

## Files
- `config/llm_config.yaml`, `version.py` (→ 1.0.0.127), `README.md`, this changelog.
