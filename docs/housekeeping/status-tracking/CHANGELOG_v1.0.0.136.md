# CHANGELOG v1.0.0.136

**Date:** 2026-07-05
**Previous:** v1.0.0.135 (EuropePMC soft-404 citation fix)
**Theme:** **DR citation liveness — Phase 1 (ENFORCE) + re-verify refinement.** The output-side liveness
check now actually **strips verified-dead citation links** (keeping the headline text) instead of only
logging them, and confirms a dead verdict with a second fetch so a transient flap never removes a good link.

---

## Background

v1.0.0.134 shipped Phase 0 (shadow): every DR answer's cited URLs are fetched and the dead ones logged
(`🩺 citation-liveness [SHADOW]: dead=X/N cited`), answer unchanged. Baseline over live traffic + a
content-level audit of a real academic run (30 citations) confirmed: the lenient check is accurate, keeps
bot-blocked (401/403) and transiently-flapping articles, and the only "dead" hit in the audit was a site
(`bioengineer.org`) that momentarily 404'd then served the real article on re-probe. See
`docs/RAICA_DR_CITATION_LIVENESS.md`.

## Change (Phase 1)

- **Enforce the strip.** `research/pipeline.py`: when `verify_live.shadow: false`, the verified-dead set is
  fed to `ground_citations` and grounding runs **ACTIVE** (`_effective_shadow = shadow AND NOT enforcing`),
  so a dead cited link is removed as **ROTTED** — the visible headline text is preserved, only the broken
  link is dropped (lossless for substance). Enforcing also activates fabricated-link stripping (URLs no tool
  returned); both are link-only removals. On a clean run (dead=0) enforce is a **no-op** — zero answer change,
  zero added latency beyond the fetch already done in shadow.
- **Re-verify before stripping.** `research/link_liveness.py verify_url_live(..., reverify=True)`: a DEAD
  verdict (hard 404/410 or homepage-redirect) is **confirmed with one more fetch after a short pause**; a URL
  is declared dead only if it fails **both** checks. A valid article can momentarily 404 (CDN/rate-limit
  flaps) — this guarantees a citation is never stripped on a transient blip. Live URLs still cost one fetch;
  only the rare dead-looking URL pays the second.

## Config

`config/llm_config.yaml` → `deep_research.engine.citation_grounding.verify_live.shadow: false` (was `true`).
Set back to `true` to return to shadow; `enabled: false` to disable the liveness step entirely. Fail-open.

## Tests

- `tests/integration/test_dr_citation_liveness.py`: +3 re-verify tests (transient 404→200 kept; dead-twice
  dropped; live URL costs one fetch). Existing enforce/strip + grounding + link-verify tests still pass.
- **27 pass** (liveness 14 + grounding 8 + link-verify 5).

## Scope note (what this does NOT do)

Liveness answers "does the URL resolve." It does **not** verify that RAICA actually *retrieved the real page
body* (a 200 can be a soft-404 / JS shell / cookie-wall / paywall stub / bot-block error page) or that the
cited claim is *grounded* in that body. That deeper "citation groundedness / retrieval-integrity" gap
(hallucination risk on live-but-not-actually-read pages) is tracked as follow-on work, separate from this
liveness layer. Soft-404s (HTTP 200) are still fixed at the source (e.g. EuropePMC in v1.0.0.135).

## Dependencies / breaking changes / migration

None. Deploy: `git pull` on live + restart. Behavior change: dead citation links are now removed (text kept)
instead of shown.
