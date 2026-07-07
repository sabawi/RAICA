# CHANGELOG — RAICA v1.0.0.147

**Date:** 2026-07-07
**Type:** Feature — Deep Research PRIMARY-FIRST, QUALITY-FIRST sourcing directive + citation-diversity shadow

## Summary
After layer A routed the Byzantine DR to real primary sources, it over-cited ONE of them: al-Ṭabarī's
*Conquest of Arabia* was cited **68 of 74 times** (92%), with only 5 distinct sources. Per operator guidance,
the fix is NOT to strip the primary (you can't beat a genuine primary source) but to **weight primaries in the
coverage AND diversify by adding MORE quality sources** — additional primaries first, then reputable secondary
scholarship — never by padding with weak sources.

## Changes
- **`research/synthesis.py`** — added a **PRIMARY-FIRST, QUALITY-FIRST SOURCING** rule to the synthesis
  GROUNDING block: anchor on primary sources so they dominate both citations AND coverage/space; seek MORE
  distinct primaries; diversify ONLY by adding equal-or-higher-quality sources (never a weak/off-topic source
  for variety — it can't substitute for or dilute a primary); do NOT restate the same citation across many
  claims (cite where it best supports; corroborate distinct points with distinct sources). Policy language
  (LLM-Policy Gate) — no hardcoded source lists.
- **`research/pipeline.py`** — NEW `📚 citation-diversity [SHADOW]` metric on the final answer: cited /
  distinct / max_reuse / % one source, flagging over-reliance (≥5 reuse & >40% one source) as a "drive MORE
  primaries" signal (quality-aware — NOT a strip target; reuse of a genuine primary means find more primaries,
  per the source-provenance ladder). Log-only.

## Verification (local, e2e — the Byzantine DR)
- Before: 74 citations, 5 distinct, al-Ṭabarī ×68 (92%). After: **10 distinct sources, top source ×4 (18%)**,
  `📚 citation-diversity [SHADOW]: cited=10 distinct=10`. Still all high-quality academic DOIs (Brill/JSTOR) —
  diversified by ADDING quality, not lowering the bar.

## Relationship to the provenance ladder
This is `prefer_primary` expressed as policy (weight primaries in coverage) + a diversity/over-citation
measurement. The structural `chase_primary` gather loop (extra rounds to find MORE distinct primaries) and the
B-enforce phase remain the next steps; the provenance shadow already logs "sub-questions with NO primary".

## Risk / rollback
- Directive is prompt-only (guidance); diversity metric is log-only. Version → 1.0.0.147.
