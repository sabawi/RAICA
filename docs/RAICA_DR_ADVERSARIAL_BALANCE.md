# RAICA — Adversarial Balance & Echo-Chamber Breakout for Deep Research

**Status:** PROPOSAL (for review → design → implementation). No code changed yet.
**Author:** drafted 2026-07-12. **Scope:** the DR reasoning spine — `research/engine.py` (planner + assess/gather
loop), `research/synthesis.py` (synthesize + grading), and the audit footer in `research/pipeline.py`.
**Risk class:** MEDIUM — touches the evidence→answer path, but additive and shadow-able; all model-facing
changes are **policy language** (the LLM judges), never hardcoded topic/domain lists (LLM-Policy Gate).

---

## 1. Problem statement (operator-framed, reproduced)

DR was built and hardened on **hard-science and reliable-news** questions, where truth has external checks:
the empirical method, replicable evidence, and a **peer-reviewed adversarial process** that forces claims to
survive their critics. As DR extends into **humanities, philosophy, and religion**, those checks **do not fully
apply**: subjectivity dominates, and sources routinely form an **echo chamber** — they quote each other, exclude
outsiders, and disparage dissent, so a literal web/scholar search returns a self-reinforcing one-sided pool.

**Reproduced (live, 2026-07-12, post 5767 "Is Jesus God? Prove it!"):**
- The opening DR answer (reply 526) gathered a **thin, one-sided pool** (20 results / 86 sources, apologetics-
  dominated) and then **backfilled it with confident specifics from the model's parametric memory** — its OWN
  verify footer flagged **~19 load-bearing claims as *not in the gathered evidence*** (scripture quotes, Greek
  analysis, archaeological finds). It read as authoritative but was one-sided and under-grounded.
- Only after the operator forced the issue (rebuttals) did the follow-ups (528/530) gather a richer, balanced
  pool (29 results / 185 sources) and reason even-handedly — steelmanning both sides, distinguishing what
  history can and cannot establish, and staying grounded. **The quality we want in 530 had to be dragged out of
  it; it must be the DEFAULT from the first answer.**

## 2. The requirement (operator's words, made testable)

For any significant point, the model must:
1. **Steelman both ways.** Make the STRONGEST argument it can for the point — AND make its utmost effort to
   present the STRONGEST counter-argument. A token nod to "some disagree" is a failure; the counter-case must be
   as strong as the model can honestly make it.
2. **Break the echo chamber — immediately.** Recognize when the gathered sources are self-referential / one
   lineage / exclude the other side, and actively go get the excluded, adversarial, outsider view — in the
   **gather**, not just the prose.
3. **Know the domain.** Distinguish a **hard-science/empirical** question (where peer-reviewed consensus is a
   genuine truth-signal) from a **humanities/philosophical/normative/religious** one (where "consensus" may be an
   echo chamber and subjectivity dominates), and calibrate how much weight "consensus" earns accordingly.
4. **Counter-balance the SOURCES and CITATIONS**, not only the prose. The evidence pool and the cited references
   must represent the strongest opposing sources, not just the dominant side's.
5. **Stay grounded** — do not pad a thin/one-sided pool with confident parametric assertions dressed as sourced
   (the 526 failure). If the evidence is thin or one-sided, say so.

## 3. Root cause (grounded in the code)

| # | Cause | Where |
|---|---|---|
| A1 | **Planner never seeks the counter-side.** The decompose prompt plans sub-questions + source strategy but has no directive to steelman/seek the opposing or critical view — so the pool starts skewed by whatever SEO/consensus dominates. | `engine.py` planner `_build_prompt` |
| A2 | **No mid-gather echo-chamber breakout.** `_assess` reopens a round for "a claim with too few sources," but has no concept of "this round's sources are one-sided/self-citing → go get the other side." | `engine.py _assess` |
| A3 | **Synthesis balance is bounded by what was gathered.** The "surface contested/minority/heterodox positions" rule (`synthesis.py:778`) can only surface positions *present in the evidence*; it cannot manufacture a counter-view the gather never collected. | `synthesis.py` synthesize prompt |
| A4 | **Credibility grading is echo-chamber-blind.** The tier grader (peer_reviewed/reputable/…) rewards the mainstream/consensus sources; a marginalized-but-substantive dissenting source can be graded low precisely *because* the echo chamber excluded it — reinforcing the skew. | `synthesis.py grade_sources` |
| A5 | **No domain awareness.** Nothing tells the model to weigh "consensus" differently for physics vs theology. | planner + synthesize |
| A6 | **Parametric over-reach.** "Use ONLY the evidence" is weak on familiar topics; the model backfills from training and verify only flags it post-hoc. | synthesize + verify |

## 4. Proposed architecture (policy-language; LLM judges everything)

Four coordinated touch points, stated in **one voice** across the stages that see them (No-Inconsistency):

- **P1 — Planner: domain read + adversarial decomposition.** The planner first judges the question's domain
  (empirical/hard-science vs humanities/philosophical/normative/religious — LLM-judged, no topic list). For a
  contested/subjective one, it MUST plan sub-questions that deliberately seek the **strongest opposing and
  critical/outsider** sources (e.g., the best case *against* the claim, the dissenting scholars the mainstream
  marginalizes), not only the surface framing.
- **P2 — Assess: echo-chamber detection + breakout.** After a gather round, the assessor judges whether the
  evidence is **self-referential / one-sided** (sources citing each other, one ideological lineage, the counter-
  view absent). If so it opens a round whose explicit goal is to **fetch the excluded counter-position** —
  breaking the chamber *during* gather, bounded by the existing round/wall-clock ceilings, degrade-gracefully.
- **P3 — Synthesis: domain-aware, steelman-both, calibrated, grounded.** Recognize the domain; make the
  strongest case for each major position AND the strongest counter-case; **flag the echo-chamber effect** when
  the sources exhibit it; distinguish **what the evidence can establish (fact) from what it cannot (normative/
  theological/interpretive)**; **calibrate confidence** — on a genuinely contested question, do NOT declare a
  verdict on the unfalsifiable claim; and do **not backfill thin evidence with parametric assertions**.
- **P4 — Grading/citation balance:** ensure a substantive dissenting/outsider source is **not dismissed merely
  because the echo chamber marginalized it** (provenance/credibility govern attribution + confidence, never
  exclusion — reuse the existing rule), and that the final **citations include the counter-side's best sources**.

### 4.1 Treatment by epistemic status — balance is PROPORTIONAL, never invented (operator-decided 2026-07-16)
The domain read sorts each claim by epistemic status and picks the treatment; "balance" is the tool for the
SUBJECTIVE band, NOT a symmetry imposed everywhere:
- **Established empirical** (evidence/observation has settled it — evolution, vaccines, heliocentrism): report
  it as established. **Do NOT invent balance or manufacture dissent.** Note only genuine, live scientific disputes.
- **Speculative / unsettled empirical** (a live hypothesis — string theory, a competing cosmological model):
  label it plainly as **conjecture/hypothesis**, represent genuine rival hypotheses **in proportion to their
  actual evidential support** (not 50/50), and **explain WHY the community favors it over the alternatives** (the
  evidence/reasons that make it catch on) — without forcing artificial balance and without presenting it as settled.
- **Subjective** (humanities / philosophy / religion / normative / aesthetic — no empirical arbiter,
  echo-chamber-prone): the full adversarial treatment — steelman the point AND its strongest counter, break the
  echo chamber, calibrate to "contested," commit to the shape of the debate not a verdict.

**Unifying rule: balance tracks genuine uncertainty — never manufacture controversy where evidence has settled
the matter; never present as settled what is genuinely speculative or subjective.** This also SCOPES the existing
"surface controversial/heterodox positions" rule (`synthesis.py:778`): it applies to genuinely contested/subjective
questions and does NOT license surfacing fringe dissent against established empirical findings.

### 4.2 Methodological reflexivity — separate EVIDENCE from INTERPRETATION (Cluster A, operator feedback 2026-07-16)
Live testing (the Jewish-origins query) showed the synthesis reasoning well on *which side* but still letting
INTERPRETIVE MODELS and CATEGORIES pose as the evidence. The directive now also requires (P3, same flag):
- **Evidence vs interpretation** — pin each claim to its level; state what a class of evidence CAN/CANNOT show.
- **Material culture ≠ identity** — a house-form / pottery / diet / burial marker may be environmental,
  economic, regional, or fashion, not a "people" ("pots are not people"); weigh the mundane alternatives before
  treating it as an ethnic signature. *(Concrete instance from operator: absence-of-pig-bones was used as an
  Israelite ethnic marker, but low pig husbandry was a REGIONAL Levantine pattern — environment/economy, not a
  distinct people's diet. The directive encodes the PRINCIPLE, never the example — no-hardcoding gate.)*
- **A dominant reconstruction is a MODEL, not the endpoint** — present it as a model with assumptions + critics.
- **Flag retrojection / anachronism** — reading a later identity/category back onto earlier evidence; make the
  continuity itself an object of scrutiny.
- **Neutral framing** — don't let the prose assume the contested conclusion ("interpreted as", not asserted).

Validated (isolation A/B): without the block the model called the four-room house "a diagnostic marker of
Israelite ethnicity" and asserted a "continuous biological lineage"; with it, it split raw-evidence from model,
applied "pots are not people," critiqued the pig-bone-as-identity claim, flagged the retrojection, and concluded
the markers "do not, by themselves, prove this culture called itself 'Israelite' or 'Jewish'."

### Remaining clusters (roadmap)
- **Cluster B — primary-source depth.** *Planner gather-quality SHIPPED v1.0.0.186* (route load-bearing
  scholarly claims to `published_papers_search`, seek competing models + historiography, adversarial
  decomposition). Validated on the archaeology case (low_cred 24→10, peer_reviewed pool, 12 journal DOIs).
  Validated on the archaeology + Arab-origins cases (peer-reviewed pool, journal/epigraphic sources).
  **NEXT — a paired Cluster-B / veracity increment:**
  - **(1) Assess-loop QUALITY breakout (P2):** when a gather round comes back dominated by POPULAR /
    low-credibility sources — typical of *narrative* "what happened" history where journal coverage is thin
    (live Nicaea run: peer_reviewed **3**, popular 15, low_cred 9, leaning on explainer blogs/advocacy) — spend
    a round pulling REPUTABLE reference / university-press scholarship (period encyclopedias, academic histories,
    primary-text editions) instead of settling. `engine.py _assess`. Pairs with primary-first provenance.
  - **(2) Citability-requires-retrieval:** a SPECIFIC empirical finding may be attributed to a source ONLY if
    that source's BODY was actually retrieved — not just its title / DOI / abstract. Observed live (Arab-origins
    run): the writer stated the specific conclusions of peer-reviewed papers (Genome Research 2016, the Marsh-
    Arabs J1 study) from memory because it knew the paper existed, though the gathered evidence held only the
    metadata; verify caught all 5. Tightens the retrieval-gate (v1.0.0.182) + the synthesis attribution rule so a
    paper's results can't be asserted from its metadata alone. The veracity increment that most directly serves
    "the cited evidence genuinely supports the claim."
- **Cluster C — deeper domain balance** (genetics: shared ancestry ≠ descent ≠ a people; fringe: critique WHY it
  fails, not just a credibility tag) → emerges from A+B plus a small directive sharpening.

### Reconciliation with `ONE COMMITTED ANSWER` (No-Inconsistency)
The reasoning directive's "commit to one answer" is preserved but **scoped**: on a contested/subjective
question the committed answer is a committed characterization of **the state of the debate** — what is
established, what is genuinely disputed, and the strongest case on each side — NOT a false "proven." On an
empirical question, commit to the well-supported conclusion as before.

## 5. LLM-Policy-Gate & consistency compliance
- **No-Hardcoding:** domain classification, echo-chamber detection, "who is the counter-side," and steelman
  quality are ALL the LLM's judgment from the content — never a hardcoded list of "controversial topics,"
  "echo-chamber domains," or "dissenting sources." Applies to every stage.
- **No-Inconsistency:** the adversarial-balance policy is stated once and echoed in one voice across planner
  (seek the counter-side), assess (break the chamber), synthesize (steelman both + calibrate), and grading
  (don't exclude marginalized dissent). It complements — never contradicts — the existing prefer-primary,
  surface-controversial, use-only-evidence, and reasoning directives.

## 6. Rollout (shadow-first where feasible, phased, no-worse-than-today)
1. **Phase 1 — synthesis (P3).** The domain-aware, steelman-both, calibrated, grounded directive. Lowest-risk,
   no new gather cost, and directly makes the *opening answer* behave like 530. Validate on the exact
   "Is Jesus God? Prove it!" prompt (and an empirical control, e.g. a physics question, to confirm science
   answers are unaffected).
2. **Phase 2 — planner + assess (P1/P2).** Adversarial decomposition + echo-chamber breakout, so the *pool*
   itself is balanced (the deeper fix). Measure added rounds/latency; keep the ceilings.
3. **Phase 3 — grading/citation balance (P4)** + audit-footer surfacing (e.g., a "balance" line: how one-sided
   the pool was, whether the counter-side was reached).

Each phase behind a `deep_research.synthesis.adversarial_balance` flag block, fail-open, gated on
"no-worse-than-today" (an empirical-question control must not regress).

## 7. Open questions for review
1. **Domain granularity:** a binary science-vs-humanities read, or a spectrum (empirical / social-science /
   historical / philosophical / theological) with per-band calibration?
2. **Breakout aggressiveness (P2):** always attempt a counter-side round on a contested question, or only when
   echo-chamber is detected? (Latency vs balance.)
3. **Confidence rendering:** how to phrase "the debate's state" verdict so it still feels decisive, not wishy-
   washy — commit to the *shape of the disagreement*, not a shrug.
4. **Empirical control:** which fixed science prompt guards against over-correction (false "both sides" on
   settled science — e.g., evolution, vaccines)? This is the critical guardrail: adversarial balance must NOT
   manufacture false controversy where the empirical adversarial process HAS settled the matter.

> Bottom line: outside hard science, DR must be its own adversary — steelman every point AND its strongest
> counter, detect and break the echo chamber in the gather, weigh "consensus" by domain, and balance the
> sources and citations — without manufacturing false controversy where empirical evidence has genuinely settled
> the question.
