# Changelog — v1.0.0.185

**Date:** 2026-07-16
**Scope:** Deep Research — **Adversarial Balance, methodological reflexivity (Cluster A)**. Extends the Phase-1 synthesis directive so an *interpretive model or category* can no longer pose as the *evidence*. Design: `docs/RAICA_DR_ADVERSARIAL_BALANCE.md` §4.2.

## Added — `🔬 EVIDENCE vs INTERPRETATION` block in `ADVERSARIAL_BALANCE_DIRECTIVE`
Same gate (`deep_research.synthesis.adversarial_balance.enabled`), policy language only (LLM-judged, no hardcoded examples). Requires the synthesis to:
- **Separate raw evidence** (inscription/artifact/bone/genome/document) **from the interpretive model/category** built on it, and state what each class of evidence CAN and CANNOT show.
- **Material culture ≠ identity** — a house-form/pottery/diet/burial marker may be environmental, economic, regional, or fashion, not a distinct people ("pots are not people"); weigh mundane alternatives before treating it as an ethnic signature.
- Treat **a dominant reconstruction as a MODEL, not the endpoint** — with its assumptions and serious critics, alongside competing models.
- **Flag retrojection/anachronism** — reading a later identity/boundary/category backward onto earlier evidence; make the continuity itself an object of scrutiny, not a premise.
- **Neutral framing** — don't let the prose assume the contested conclusion ("interpreted as…", not asserted).

## Motivation (operator feedback on the live Jewish-origins DR run)
The v1.0.0.184 answer reasoned well on *which side* but let interpretation masquerade as finding: it called the four-room house "a diagnostic marker of Israelite ethnicity," used absence-of-pig-bones as an ethnic identity marker (a **regional** Levantine pattern — environment/economy, not a people's "diet"), and asserted a "continuous lineage spanning three millennia" (presupposing the contested continuity). The block encodes the *principle* (weigh mundane/regional explanations; distinguish evidence from model; flag retrojection) — never the example.

## Verification
Isolation A/B (directive WITHOUT vs WITH the block, on the exact ethnic-marker/continuity claims): without → "diagnostic marker of Israelite ethnicity," "continuous biological lineage." With → split raw-evidence from model, applied "pots are not people," critiqued the pig-bone-as-identity claim, **flagged the retrojection** ("relies on connecting these findings to a group named in a much later religious text… which the question explicitly excludes"), and concluded the markers "do not, by themselves, prove this culture called itself 'Israelite' or 'Jewish'." Every reflexivity signal appeared only in the WITH version. E2E DR confirmation on the live prompt.

## No-Inconsistency
Complements the epistemic-status calibration and `ONE COMMITTED ANSWER` (commit to a clear characterization *including* "the continuity is itself contested").

## Next
Cluster B (Phase 2): primary-source-depth gather (avoid tertiary wikis; develop the competing ethnogenesis models + historiography). Cluster C: deeper genetics/fringe balance.

## No dependency changes.
