# Changelog — v1.0.0.188

**Date:** 2026-07-16
**Scope:** Deep Research veracity — **citability-requires-retrieval** (increment #2 of the paired Cluster-B/veracity increment). A specific empirical finding can no longer be attributed to an academic source whose body wasn't retrieved. Design: `docs/RAICA_DR_ADVERSARIAL_BALANCE.md`.

## Changed — `_gate_rule` in DR synthesis gains an ABSTRACT/METADATA-ONLY clause
`published_papers_search` returns a paper's **title + abstract + DOI**, and the retrieval-gate (v1.0.0.182) treats an abstract as real "content" (not `BODY-NOT-RETRIEVED`), so academic-metadata blocks are **not** gated. The writer then stated the paper's *full-text* findings from parametric memory. Observed live (Arab-origins run): the verify layer flagged **5 claims** attributing peer-reviewed papers' specific conclusions (Genome Research 2016, the Marsh-Arabs J1 study) to sources for which only the title/DOI/abstract was in evidence.

New clause (policy language, LLM-judged, one voice with the existing `BODY-NOT-RETRIEVED` rule; gated with the retrieval-gate): for an academic paper whose block gives only its **title / DOI / citation / abstract**, report **only what that abstract or metadata actually states**; do NOT assert the study's specific detailed findings, figures, sample sizes, dates, or conclusions as if the full paper were read. Knowledge beyond the block is **parametric memory** and must not be presented as sourced to it.

## Verification
Isolation A/B on a bare **title+DOI** academic block (the real failure mode): WITHOUT the clause the writer presented the **title as the study's finding**; WITH it, the writer recognized the source as *"metadata-only… no abstract, no body text, no specific findings… I cannot fabricate or infer specific findings not present in the evidence."* Import clean; clause present + gated with the retrieval-gate.

## Next (paired increment)
#1 — assess-loop QUALITY breakout (`engine.py _assess`): on a popular/low-cred-dominated round for a scholarly topic, spend a round pulling reputable/academic sources (Nicaea residual).

## No dependency changes.
