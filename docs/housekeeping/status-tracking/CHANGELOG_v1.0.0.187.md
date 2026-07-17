# Changelog — v1.0.0.187

**Date:** 2026-07-16
**Scope:** Docs — record the next paired **Cluster-B / veracity increment** in the Deep Research adversarial-balance roadmap, from three live historical-research validations (Jewish origins, Nicaea, Arab origins). Docs only; no code/behavior change (no server restart).

## Changed — `docs/RAICA_DR_ADVERSARIAL_BALANCE.md` roadmap
The adversarial-balance initiative validated across the epistemic spectrum in live testing — contested/subjective (Jewish origins) → steelman + reflexive; settled history (Nicaea) → report + debunk with no manufactured balance; politically charged (Arab origins) → bias-watch + reflexive + well-sourced. Two residuals from that testing are now logged as the paired next increment:

- **(1) Assess-loop QUALITY breakout** (`engine.py _assess`): when a gather round returns POPULAR/low-credibility-dominated evidence — typical of *narrative* "what happened" history where journal coverage is thin (Nicaea run: peer_reviewed 3, popular 15, low_cred 9) — spend a round pulling REPUTABLE reference / university-press scholarship instead of settling for explainer blogs/advocacy.
- **(2) Citability-requires-retrieval** (retrieval-gate + synthesis attribution): a SPECIFIC empirical finding may be attributed to a source ONLY if its BODY was actually retrieved — not just its title/DOI/abstract. Observed in the Arab-origins run (the writer stated peer-reviewed papers' specific conclusions from memory while the gathered evidence held only metadata; verify caught all 5). The veracity increment most directly serving "the cited evidence genuinely supports the claim."

## Status recap (shipped this arc)
- v1.0.0.184 — adversarial balance Phase 1 (epistemic-status calibration + steelman + echo-chamber flag + no parametric backfill)
- v1.0.0.185 — Cluster A (methodological reflexivity: evidence vs interpretation)
- v1.0.0.186 — Phase 2 / Cluster B (planner reaches primary peer-reviewed scholarship, not tertiary wikis)

## No code / dependency changes.
