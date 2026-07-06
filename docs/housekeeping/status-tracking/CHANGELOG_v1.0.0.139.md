# CHANGELOG v1.0.0.139

**Date:** 2026-07-06
**Previous:** v1.0.0.138 (headline↔URL consistency check)
**Theme:** **Content-quality gate for body-not-retrieved sources (shadow-first).** When a cited source's page
body could not be fetched (paywall/bot-block/error), tell the synthesizer it holds only the **title**, not the
article — so it won't attribute specific facts/quotes/stats to it. Shadow-first: ships log-only; flip one flag
to enforce.

---

## Motivation

A day of the shadow **retrieval-audit** baseline (8 DR runs, 278 citations) showed body-retrieval is healthy —
**94.2% real body**, `over_captured=0`, `absent=0` — but ~**2.2% `error`** blocks: paywall/bot-blocked sources
(NEJM, ScienceDirect, marktechpost, iea.org, britannica, …) where RAICA holds only the title + an
`"Error extracting content: 403"` page, yet the writer can still cite them and attribute unseen specifics to
them (a hallucination vector). This gate targets exactly that ~2% — the only real exposure the baseline found.
(over-capture / citability / big headline-mispairing work was **skipped** — 0% / negligible exposure.)

## Change (shadow-first)

- **`research/retrieval_quality.py`**: new `annotate_unretrieved_blocks(content)` — inserts a
  `⚠️ BODY-NOT-RETRIEVED` marker after the CITATION URL line of each source block whose body is an
  extraction-**error** (marks `error` ONLY — a short abstract/snippet `thin` is real content). PURE, offline,
  lossless when nothing is marked, handles both source-block formats (incl. the papers `───`-before-CONTENT).
- **`research/synthesis.py synthesize`**: reads `synthesis.retrieval_gate`. In **SHADOW** it counts + logs
  `🚧 retrieval-gate [SHADOW]: N source-block(s) body-not-retrieved` (evidence + prompt UNCHANGED). When
  **ACTIVE** it annotates the evidence AND adds one GROUNDING rule (policy language, one voice with the
  existing ATTRIBUTION-not-exclusion rules): *a `⚠️ BODY-NOT-RETRIEVED` source is title-only — do NOT
  attribute specific facts/quotes/stats/dates to it; reference it only for a topic's existence / as further
  reading; prefer sources with a retrieved body for concrete claims.* Fail-open (a gate error never breaks
  synthesis). Does not touch the verify path or the original evidence list (audit sees unmodified evidence).

## Config

`config/llm_config.yaml` → `deep_research.engine.synthesis.retrieval_gate: { enabled: true, shadow: true }`.
Flip `shadow: false` to ENFORCE. `enabled: false` disables it. LLM-Policy-Gate clean: error detection is
structural (RAICA's own `Error extracting content:` marker); the action is policy language to the LLM.

## Tests

`tests/integration/test_retrieval_quality.py`: +5 gate tests — marks error (search_web AND papers formats);
lossless on a real block; never marks `thin`; only the error block in a mixed pair. 14 pass.

## Dependencies / breaking changes / migration

None. Ships in SHADOW (no answer change). Deploy: `git pull` + restart; grep `🚧 retrieval-gate` to confirm it
identifies the right blocks on live evidence, then set `retrieval_gate.shadow: false` to enforce.
