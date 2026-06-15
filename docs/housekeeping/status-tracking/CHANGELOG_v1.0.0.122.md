# CHANGELOG v1.0.0.122

**Date:** 2026-06-15
**Previous:** v1.0.0.121 (non-DR citation accuracy — source filtering + prompt rules + live verify)
**Theme:** **Extend citation specificity to the Deep Research path** — DR citations now use the specific
article HEADLINE as link text, not a bare outlet name.

---

## Why

v1.0.0.121 fixed citations on the non-DR path (news bots / `search_web`), including the prompt rules in
`primary_model_system_prompt.txt`. But **Deep Research synthesizes via `research/synthesis.py`, not that
prompt** — so the new rules didn't reach it. On a live DR retest, the URLs were now correct (Layer 1/3
source filtering applies to DR's evidence gathering — it skipped `cbsnews.com/`, `nytimes.com/`,
`reuters.com/`, `apnews.com/world-news`, …), but the citation **link text** came out as the bare outlet
name + date, e.g. `NPR, June 15, 2026` / `BBC, June 15, 2026`, because the synthesis prompt said to cite
`[Title](URL)` without defining "Title".

## Fix

`research/synthesis.py` — three spots now require the link text to be the **specific article headline**
(which is present in each evidence block: `engine.py` stores the tool's `📄 SOURCE: <headline>` line as the
evidence `content`), never a bare outlet/publisher name or `outlet, date`:
- the per-evidence-block citation instruction (`_evidence_document`),
- the synthesis "CITATIONS ARE MANDATORY" rules, and
- the `## References` instruction.

Example baked into the prompt: `[NPR: US and Iran reach preliminary deal to end the war](https://www.npr.org/2026/06/15/...)`
— never `[NPR]`, `[BBC]`, `[New York Times]`, or `[NPR, June 15, 2026]`; outlet name + date go in the prose,
not the link text; the URL must be that block's specific article URL (never a homepage/section/feed). This
keeps DR consistent with the primary-prompt citation rules (no-inconsistency).

No code-logic change — prompt text only; additive (existing grounding/credibility rules unchanged).

## Verification

- DR retest on local (1.0.0.122): Layer 1/3 skipped all homepage/section URLs (logs); user confirmed the
  rendered citations now match the specific article headline + URL ("remarkable progress in link and title
  match and accuracy").
- `research/synthesis.py` imports clean; deterministic citation tests from .121 still green.

## Files
- `research/synthesis.py` — DR synthesis citation link-text = specific article headline (3 instructions).
- `version.py` (→ 1.0.0.122), this changelog.
