# CHANGELOG v1.0.0.63

**Date:** 2026-05-31
**Previous:** v1.0.0.62
**Trigger:** Deep Research enhancement — Stage 0 (foundations) + pre-commit security scrub

---

## Summary

First step of the staged Deep Research & Multi-Modal initiative (see `docs/DEEP_RESEARCH_MULTIMODAL_PLAN.md`). Stage 0 removes hardcoded web-search depth limits (config-driven now) and replaces the keyword-based research detector with an LLM-driven classifier. Verified end-to-end against a complex live research request. Also scrubs a hardcoded personal email out of the codebase.

---

## New Features

- **Config-driven research depth** — new `deep_research:` block in `config/llm_config.yaml` is the single source of truth for web-search breadth/depth:
  - `search.web_max_results` (default **8**, was hardcoded 3)
  - `search.per_page_char_budget` (default **6000**, was hardcoded 2000)
  - `search.per_page_max_blocks` (default **12**, was hardcoded 5 paragraphs)
  - `research_classifier.enabled` toggle
- **LLM-driven research classifier** — `_is_research_query()` now asks the Primary LLM (semantic verdict) instead of matching keyword/phrase lists. Cached per prompt; fails SAFE to `research=true` (max context preservation) if disabled or unreachable.

## Changes / Fixes

- **De-hardcoded `search_web()`** (`fastapi_server_complete.py`) — reads depth from `deep_research.search`; per-page extraction uses the configured budgets instead of truncating at 2000 chars / 5 paragraphs. Defaults mirror the old values so a missing config never regresses search.
- **Replaced keyword research-detector** — removed the `research_keywords` / `academic_phrases` lists (a standing violation of the project's anti-hardcoding directive) in favor of the LLM classifier. Call site updated to `await` the now-async function.
- **Config reflects active model selection** — this commit also captures the working model configuration already running on the server (primary `deepseek-v4-pro:cloud`, tool/arbitrator `qwen3-coder-next:cloud`, primary context window `131072`). These were uncommitted working-tree changes pre-dating Stage 0; committed here to keep the repo in sync with the live server.

### SECURITY (pre-commit scrub)
- **Removed hardcoded owner email PII** — `sabawi@gmail.com` was hardcoded as a priority pattern in the email-extraction logic. Now sourced from the existing `GMAIL_PRIMARY_EMAIL` env var (`.env`) via `re.escape()`, preserving owner-prioritization behavior without embedding PII in source. Example email in a nearby comment replaced with `user@example.com`.

---

## Verification (end-to-end, live server)

Complex request exercised: deep research on the "Sumerian Problem" (debunk pseudo-archaeology + Ubaid continuity via ancient DNA/linguistics).

- **Web depth confirmed:** a single `search_web` returned **8 distinct sources** (~32 KB) vs. the old cap of 3; 3 searches + `published_papers_search` produced **27 source blocks / 112 KB** of tool context, delivered **100% intact** to the Primary LLM (no truncation; fits the 131072 window).
- **Hallucination/grounding audit of the final answer:** **0 fabricated URLs** (all 16 citations traced to retrieved sources); arXiv papers, the Marsh-Arabs/J1-Page08 genetics claim, and the Carl Sagan quote all verified as grounded in retrieved source content (not model memory). No invented facts/dates/papers.
- **Classifier:** validated correct in isolation (research prompts → research; casual/trivial → general). Note it is currently **dormant at runtime** (see Known Issues).

### Three credibility caveats found (now tracked as Stage 1–2 acceptance criteria)
1. **"Coined" vs "posed"** — response upgraded a source's "Kramer *posed* the problem in 1956" to "*coined*"; historically the Sumerian Question predates Kramer (~1870s). Inherited a source oversimplification → motivates **Stage 2 cross-source reconciliation**.
2. **Padded/off-topic academic citations** — real but tangential arXiv papers (space archaeology, muon imaging) presented as relevant → motivates **Stage 1 source-relevance/credibility weighting**.
3. **Overclaimed sourcing** — closing disclaimer called all sources "academic/peer-reviewed" while several are popular/non-scholarly (loresandlegends, scienceinsights, armstronginstitute) → motivates **Stage 1 credibility grading + Stage 2 claim labeling**.

---

## Known Issues / Deferred

- **Optimization subsystem absent** — `archive/experimental/optimization_safety.py` was never committed; `OPTIMIZATION_AVAILABLE=False`, so `process_with_safe_optimization()` always uses the fallback and the research classifier's threshold is **not yet exercised in production**. No regression (this predates Stage 0). Rebuild fully scoped in `docs/OPTIMIZATION_SAFETY_REBUILD_SCOPE.md`; sequenced after research Stages 1–2.

## Dependencies

- None new — classifier uses stdlib (`re`, `hashlib`). `requirements.txt` unchanged.

## Migration

- None required. New config defaults are backward-compatible. To tune research depth, edit `config/llm_config.yaml → deep_research.search`.

## Files

- `fastapi_server_complete.py` — search_web depth, LLM classifier, email PII scrub
- `config/llm_config.yaml` — `deep_research` block (+ active model config)
- `version.py` — 1.0.0.62 → 1.0.0.63
- `README.md` — version sync to 1.0.0.63
- `docs/DEEP_RESEARCH_MULTIMODAL_PLAN.md` (new) — staged roadmap
- `docs/OPTIMIZATION_SAFETY_REBUILD_SCOPE.md` (new) — Option-B scoping
- `docs/housekeeping/status-tracking/CHANGELOG_v1.0.0.63.md` (new)
