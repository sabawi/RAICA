# Changelog — v1.0.0.184

**Date:** 2026-07-16
**Scope:** Deep Research — **Adversarial Balance, Phase 1 (synthesis directive / P3)**. As DR extends beyond hard science into humanities/philosophy/religion, "consensus" stops being a truth-signal and sources form echo chambers. This makes the synthesis be the adversary the field lacks — calibrated to epistemic status, never manufacturing balance. Design: `docs/RAICA_DR_ADVERSARIAL_BALANCE.md`.

## Added — `ADVERSARIAL_BALANCE_DIRECTIVE` in DR synthesis (gated: `deep_research.synthesis.adversarial_balance.enabled`)
Policy language only — the LLM judges the domain, the epistemic status, the echo chamber, and steelmans; **no hardcoded topic lists** (LLM-Policy Gate). Calibrates by epistemic status:
- **Established empirical** (evolution, vaccines, heliocentrism): reported AS established — **no invented balance, no elevating fringe denial to a "side."**
- **Speculative/unsettled empirical** (string theory, rival cosmologies): labeled as **hypothesis/conjecture**, rivals represented **in proportion to actual support** (never forced 50/50), with an explanation of **why the field favors one** — not presented as settled.
- **Subjective** (humanities/philosophy/religion/normative): the full adversarial treatment — the **strongest case FOR a point AND the utmost-effort strongest case AGAINST**; **detect the source echo-chamber and break out** (represent the excluded/dissenting view even when the pool under-supplies it, and say when the pool is one-sided); separate what evidence CAN establish (facts) from what it CANNOT (the normative/theological claim); commit to characterizing the **debate**, not a verdict on the unfalsifiable.
- **Grounding:** do NOT backfill a thin/one-sided pool with confident parametric assertions dressed as sourced (the failure seen live where a DR answer's own verify footer flagged ~19 claims as not-in-evidence).

**No-Inconsistency:** the directive is placed immediately after — and explicitly **scopes** — the existing "surface controversial positions" rule (`synthesis.py:778`) so it cannot false-balance settled empirical science; `ONE COMMITTED ANSWER` is scoped (commit to the debate's shape on contested questions, to the finding on empirical ones).

## Motivation (live case)
Post 5767 "Is Jesus God? Prove it!": the opening DR answer (526) gave a one-sided "definitive yes" built partly on parametric backfill, and only became even-handed (530) after the operator forced it. This makes 530-quality the default from the first answer.

## Verification
Controlled A/B (same model, directive off vs on) across all three bands: **Subjective** → echo-chamber flagged + steelman both + no overclaim; **Established** (evolution) → reported settled, **no invented balance**; **Speculative** (string theory) → labeled conjecture + differential support explained, no forced balance. Imports clean; directive present in synthesis and gated.

## Next (per design doc)
Phase 2 — planner adversarial decomposition + assess-loop echo-chamber breakout (balance the evidence POOL, not just the synthesis). Phase 3 — grading/citation balance + audit-footer "balance" line.

## No dependency changes.
