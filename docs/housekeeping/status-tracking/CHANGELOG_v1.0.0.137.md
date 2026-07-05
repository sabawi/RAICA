# CHANGELOG v1.0.0.137

**Date:** 2026-07-05
**Previous:** v1.0.0.136 (DR citation liveness — Phase 1 enforce + re-verify)
**Theme:** **Retrieval-quality audit (shadow instrumentation).** Quantify *body-retrieval exposure* — how
often a cited URL was backed by real retrieved page content vs a snippet/error/never-fetched. This is the
measurement step for the deeper "citation groundedness" (hallucination-risk) question. **Measures only; no
answer change.**

---

## Motivation

Liveness (v1.0.0.134–136) proves a cited URL *resolves*. It does **not** prove RAICA retrieved the real page
**body**, nor that the claim is *grounded* in it. A 200 can be a 403 error page, a paywall/JS-shell stub, or a
cross-reference URL that was never fetched (the `engine.py:410` over-capture). When RAICA holds only a title +
bogus/empty body, a fact attributed to that URL is coming from the model's prior — a real-looking citation on
an ungrounded claim. Before designing a fix, measure the exposure.

## Change (measurement only)

- **`research/retrieval_quality.py` (NEW, pure/offline):** `assess_retrieval(answer, evidence, min_body_chars)`
  classifies every URL the (post-grounding) answer cites by what RAICA actually held, using RAICA's own
  source-block markers (`🔗 CITATION URL:` / `CONTENT:` / `Extracted Content:`) + a length threshold — **structural
  signals, not semantic keyword lists** (LLM-Policy-Gate compliant):
  - `real` — fetched source block with a substantial body (≥ `min_body_chars`)
  - `thin` — fetched source block, but snippet-only / sparse body
  - `error` — body is RAICA's own `Error extracting content:` marker (403/paywall/5xx/exception)
  - `over_captured` — cited but never a fetched source (entered the evidence URL set only via another page's text)
  - `absent` — cited but not in the gathered evidence at all
- **`research/pipeline.py`:** after grounding, logs one line per run:
  `📊 retrieval-audit: real=… thin=… error=… over_captured=… absent=… / N cited | flagged=[…]`. Own try/except,
  fail-open — a measurement error never affects the answer.

## Config

`config/llm_config.yaml` → `deep_research.engine.retrieval_audit: { enabled: true, min_body_chars: 200 }`.
Pure shadow; `enabled: false` disables it.

## Known blind spot

Soft-404s that return a real-looking 200 body (the EuropePMC class) are **not** flagged here — they look like
`real` content. Those are addressed at the source (e.g. EuropePMC, v1.0.0.135). This audit targets the
measurable structural classes (error / thin / over_captured / absent).

## Tests

`tests/integration/test_retrieval_quality.py` (NEW, 4): each class counted; all-real when bodies substantial;
HTML + dedupe; no-citations. Pass.

## Dependencies / breaking changes / migration

None. Shadow measurement only — no behavior change. Deploy: `git pull` + restart; then grep
`📊 retrieval-audit` over a few days of real DR traffic to quantify exposure → informs the groundedness fix.
