# CHANGELOG v1.0.0.258 — revert the v1.0.0.257 synthesis directives (external-review regression)

**Date:** 2026-08-11 · **Reverts:** `f3824bc` (v1.0.0.257)

## Why

Two independent external reviewers (Grok-research, ChatGPT-research) assessed the v1.0.0.257
answer against the v1.0.0.256 answer on the same prompt and **both scored it LOWER**, with the
same headline complaint: **over-reliance on Wikipedia / secondary sources**. Verdict: "good
popular article, not research quality" — 8/10, and "closer to 7 for a specialist audience
expecting dense primary-source engagement."

That is a cleaner signal than the in-house metrics, which reported "noise."

## What actually happened, with the mechanism

The three directives worked as designed and their gains are real — external review credits the
Radner attribution (the name-dropping fix), the up-to-date Al-Jallad treatment, correct Greek
chronology, and the structure. **But they bought breadth and paid for it in sourcing grade.**

- **8 of 11 Wikipedia references (72%) support sections that did not exist in the graded
  answer** — Akkadian language/literature, Ancient North Arabian, Arabs, Semitic languages,
  Mycenaean Greece, Ancient Greece, pre-Islamic Arabia. The ANSWER-THE-AXIS and
  VARIATION-ACROSS-A-SPAN directives expanded coverage into Luwian, Urartian, Elamite, Median,
  Mannean and South Arabian; academic retrieval did not expand with it, so encyclopedias filled
  the gap. The Urartian section carries NO citation at all.
- **The ANSWER-THE-AXIS carve-out was too weak.** "Never pad the gap with speculation" did not
  hold against a directive pushing hard toward an axis (everyday speech) for which direct
  evidence barely exists. External review: the reconstructions "remain educated inference
  rather than documented fact … presented with slightly more certainty than the evidence
  strictly warrants."

## The process failure being recorded

`encyclopedic_share` moved **0.069 → 0.167** in the post-change measurement — a 2.4× move, and
the ONLY metric that moved against the change. It was reported as "on a very small base."

It mapped directly to the user's PRIMARY stated critique, and it was softened rather than
treated as the blocking result. The signal was present and discounted. **Never soften the one
metric that moves against your own change, least of all when it tracks the concern the user
actually raised.**

## Changed

- `research/synthesis.py` — the three v1.0.0.257 directives removed. No other behaviour change.
- Version surfaces → 1.0.0.258.

## RETAINED from v1.0.0.257 (not part of the regression)

- `tests/benchmark/lib/generic_quality.py` — topic-agnostic metrics
- `tests/benchmark/scenarios/s9_ancient_languages.py` — S9 scenario
- `tests/unit/test_generic_quality_metrics.py` — 16 cross-topic tests
- `docs/RESPONSE_QUALITY_BASELINE.md` §4 + rules 9–10
- `CHANGELOG_v1.0.0.257.md` and SI-031, for the audit trail

## Next

The user's standing requirement, restated: **research weight must rest on PRIMARY verifiable
sources that are READ AND DIGESTED IN CONTEXT — not headlines or abstracts. Wikipedia and other
secondary sources are permitted as a LAST RESORT when access is blocked.**

This makes encyclopedia-reliance and retrieval depth ONE defect, not two: a source that arrives
as a 2,000-char abstract has not been read, so it cannot anchor an analysis, and an encyclopedia
wins by default because it is the only source with a full body in context.

Design work must therefore start by tracing what per-source metadata (retrieval depth, source
class, credibility grade) actually REACHES the synthesis prompt. A directive telling the model
to prefer sources it has read is unenforceable if the prompt never tells it which those are.
