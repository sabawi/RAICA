# CHANGELOG v1.0.0.66

**Date:** 2026-06-01
**Previous:** v1.0.0.65
**Trigger:** Deep Research — source-credibility transparency + research-completeness tuning

---

## Summary

Two targeted improvements to the Deep Research audit and synthesis, driven by live testing:
(1) the audit footer now footnotes each low-credibility source the answer actually cited, with a specific reason; (2) the synthesis prompt was recalibrated so it surfaces substantive contested/minority points (properly attributed) instead of retreating to safe-consensus generalities. Validated on a religiously-sensitive comparative-religion query against external frontier-model baselines.

---

## New Features

- **Low-credibility source footnotes (cited-only):** the `🔎 Research Audit` footer now lists the low-credibility domains the answer ACTUALLY CITED (cross-referencing the answer body's URLs against the graded sources), each with a SPECIFIC credibility concern, e.g.:
  - `equip.org — partisan Christian apologetics site`
  - `someblog.com — self-published, no sourcing`
  - Sources that were gathered but not cited are not listed (no noise); when none are cited the section is omitted.
  - Implemented via: credibility grading now returns `{tier, reason}` per domain (reason captured for low-credibility); a new `_low_cred_cited_section()` in `pipeline.py` matches answer URLs to low-cred domains. Resolves the prior gap where the footer showed a bare `low_credibility: N` count with no indication of which sources were used or why.

## Changes / Tuning

- **Research-completeness synthesis directive:** the synthesis system prompt now states explicitly:
  - **"USE ALL SUBSTANTIVE EVIDENCE REGARDLESS OF SOURCE TIER"** — a point's importance is its substance/relevance, not its source's tier; do not silently drop a point because its source isn't peer-reviewed.
  - **"THIS IS RESEARCH, NOT A CONSENSUS SUMMARY"** — surface contested, minority, heterodox, and controversial positions present in the evidence (controversial ≠ wrong; the prevailing narrative is itself open to challenge); omitting a substantive controversial point is a failure.
  - Credibility rules reframed from gatekeeping to **attribution** ("these govern ATTRIBUTION, never EXCLUSION"): calibrate confidence to source quality and attribute contested/low-credibility claims as positions ("X argues…") with context — reserve outright debunking for claims the evidence actually refutes.
  - Fixes an over-correction observed in v1.0.0.65 where, on a low-tier-heavy evidence pool, synthesis shrank (~15K chars) and stuck to safe generalities. Post-fix the same topic produced richer output (~23K) that engaged the contested material while keeping the conclusion anchored to the peer-reviewed/reputable consensus.

## Verification (live)

- Comparative-religion query (origins of the three monotheistic faiths; the prompt intentionally used the loaded word "corruption"): synthesis engaged the contested Sumerian/Canaanite-influence material (previously omitted), attributed it to its sources, and disclosed 5 cited low-credibility sources in the footnote with accurate per-source reasons. The conclusion tracked the evidenced transformation narrative (polytheism → henotheism → monotheism) rather than endorsing the loaded framing — matching the behavior of external frontier models on the identical prompt. Depth recovered (33% of cap vs 20% pre-fix); 31/31 claims supported.

## Architecture note

The three layers now work together: synthesis **includes** contested points (attributed) → verification **audits** them (low-cred attributions go to the benign `ℹ️` bucket, not `⚠️`) → the footer **discloses** which low-credibility sources were cited and why. Coverage is broadened without the conclusion being driven by weak sources.

## Dependencies

- None new. (`urllib.parse`, `re` — stdlib — used in `pipeline.py` for URL/domain matching.)

## Migration

- None required. No config changes; behavior change is in synthesis output and the audit footer.

## Files

- `research/synthesis.py` — `{tier, reason}` grading + research-completeness synthesis prompt
- `research/pipeline.py` — `_low_cred_cited_section()` footnote + footer wiring (`answer_text` passthrough)
- `version.py` (→ 1.0.0.66), `README.md`, this changelog
