# RAICA — Source Provenance (Primary-vs-Secondary) for Deep Research — Solution Proposal

**Status:** PROPOSAL (for review → design → implementation). No code changed yet.
**Author:** drafted 2026-07-03. **Scope:** the credibility/citation spine of the Deep-Research pipeline
(`research/engine.py`, `research/synthesis.py`, `research/pipeline.py`).
**Risk class:** MEDIUM — touches the evidence→answer pipeline, but additive on top of the existing credibility
machinery. Designed to be **shadow-able, feature-flagged, reversible, and no-worse-than-today**.

---

## 1. Problem statement

Deep-Research answers are well-liked but tend to **settle for secondary/reference sources** (Wikipedia,
Britannica, general explainers) when a **primary source** (a journal article, book, original document, filing,
dataset, or the actual speech/letter — "from the horse's mouth") is what a careful researcher would cite.

Operator's example: *asked to attribute a saying to a famous person, RAICA digs through Wikipedia's article,
finds the quote, and cites **Wikipedia** — instead of following Wikipedia's own reference to the original
speech/letter/interview and verifying + citing **that**.*

This is not a bug and cannot be quantified as a failure — the citation is real and live. It is a **quality**
gap: the answer is weaker than it should be because its facts rest on second-hand reporting.

**Two guardrails from the operator (design constraints):**
- **Do NOT penalize secondary sources.** They are valuable — for background/context they are fine, and when a
  primary is inaccessible they are the best we have.
- **Independent corroboration elevates a claim.** If the primary is unreachable (e.g. an undigitized book in a
  library) but **≥2 *independent* secondaries** point to the same primary/fact, that is strong evidence —
  "multiple witnesses to a crime." Such a claim should be presented at elevated confidence.
- **Stay reasonable and transparent** about what is primary, what is corroborated-secondary, and what rests on
  a single secondary.

**Goal:** prefer primary sources; actively *reach* the origin when feasible; treat independent multi-secondary
agreement as strong corroboration; and make the provenance of every key claim visible to the reader — without
ever silently dropping a secondary-sourced point or overstating what we verified.

---

## 2. Current architecture (as-is) — grounded in the code

### 2.1 The credibility axis (exists, LLM-driven, works)
- `research/synthesis.py grade_sources()` (`:161`) — an LLM grades each **source domain** into ONE tier:
  `peer_reviewed | reputable | popular | low_credibility | unknown` (`VALID_TIERS`, `:35`). Explicitly **"No
  hardcoded lists"** (`:163`) — the classification is semantic. Low-credibility domains also get a specific
  reason for a footnote.
- **The smoking gun:** the `reputable` tier is defined (`:179-180`) as *"established institutions, governments
  (.gov), universities (.edu), major news organizations, **encyclopedias**."* So Wikipedia/Britannica grade
  **reputable** — the second-highest tier.
- `_evidence_document()` (`:263`) tags each evidence block header with its credibility tier (`:275`), which the
  synthesizer sees.

### 2.2 Synthesis is credibility-aware but primacy-blind
- `synthesize()` system prompt (`:408-491`):
  - *"USE ALL SUBSTANTIVE EVIDENCE REGARDLESS OF SOURCE TIER"* (`:462`) and *"Calibrate CONFIDENCE to source
    credibility, but never use credibility to EXCLUDE a substantive point"* (`:470`).
  - The rules govern **credibility/attribution** only. There is **no notion of primary-vs-secondary**, so a
    `reputable` encyclopedia is a perfectly good end-citation as written.

### 2.3 The gather loop already understands corroboration gaps — but not primacy
- `engine.py Planner._build_prompt()` (`:201-232`) decomposes a request into sub-questions + a source strategy
  (*"wikipedia for background, search_web for general/web coverage, published_papers for scholarly"* `:213`).
  Nothing steers it toward the **origin** of a specific fact.
- `engine.py DeepResearchEngine.run()` loops rounds; `_assess()` (`:428`) is the coverage assessor — it already
  reopens a round for *"a claim with too few independent sources"* (`:439`) and proposes `next_queries`. So the
  loop **can already chase corroboration** — it just has no concept that a claim resting on a *secondary* is a
  gap worth chasing to the *primary*.
- Evidence item shape (`_dispatch_round`, `:403-412`): `{content, urls, source, sub_question_id, question,
  query, round, chars}` — URLs are a flat regex extraction per block.

### 2.4 Verification + audit (where provenance can be surfaced)
- `verify()` (`:514`) extracts claims and checks them against the evidence; `min_corroborating_sources` (`:125`,
  config `verification.min_corroborating_sources: 2`) is the threshold for labeling a claim "supported."
- `pipeline.py`: `_credibility_tally()` (`:40`), a low-credibility footnote generator (`:123-146`), and the
  `🔎 Research Audit` footer (`:181-193`, `Source credibility:` line). This is the natural place to add a
  provenance line + a single-secondary footnote (same pattern as the low-cred footnote).

### 2.5 Existing citation grounding (substrate, already live)
- `research/citation_grounding.py ground_citations()` (`:145`) — Phase-1 URL grounding + a per-block **quorum**
  (drops/flags blocks left with 0 valid sources; config `deep_research.citation_grounding`). Establishes the
  corroboration/quorum machinery the provenance model plugs into.

---

## 3. Root-cause analysis

| # | Cause | Consequence |
|---|---|---|
| P1 | Credibility tier **conflates trustworthiness with primacy**; encyclopedias grade `reputable` (2.1) | A secondary scores high → is treated as a first-class end-citation |
| P2 | Synthesis has **no primary-vs-secondary preference** (2.2) | Given a Wikipedia block, the model cites it rather than the primary it references |
| P3 | Gather loop chases **corroboration gaps but not origin gaps** (2.3) | A claim backed only by secondaries is never a reason to go find the primary |
| P4 | No **provenance signal** on claims or in the audit footer (2.4) | Reader can't tell horse's-mouth from second-hand; no pressure to improve |

**Highest-leverage change:** P3 — actually *reach* the primary in the gather loop (re-ranking what's already
gathered, P1/P2, only helps if a primary was incidentally collected). P1/P2/P4 make the preference and the
transparency real.

---

## 4. Proposed architecture (to-be): a claim-provenance ladder

Primary-vs-secondary is an axis **orthogonal to credibility** (a source can be reputable AND secondary, e.g.
Wikipedia; or reputable AND primary, e.g. a .gov statute). We add that axis and a per-claim **provenance
ladder** the reader can see:

| | Provenance | Definition |
|---|---|---|
| 🏆 | **primary-verified** | cited to the origin of the claim (the actual paper / speech / letter / filing / dataset / original work) present in the evidence |
| 🤝 | **corroborated** | primary not in evidence, but **≥ N *independent* secondaries agree** on the same fact/attribution — elevated confidence (multiple witnesses) |
| ⚠️ | **single-secondary** | supported by exactly one secondary — reported transparently ("per X; primary not located") |

### 4.1 Two honesty constraints (per operator)
1. **Independence is required for corroboration.** Two outlets that reprint the same wire story, or that both
   cite only Wikipedia, are **one** witness — an echo, not corroboration. The LLM must judge that the
   secondaries are *independent lineages* converging on the same primary. Non-independent agreement does NOT
   elevate.
2. **"Corroborated" stays labeled corroborated — it is NOT promoted to "primary."** Multiple witnesses give high
   confidence but we did not see the origin; transparency means saying so. Same practical confidence, truthful
   provenance. *(Operator-confirmed 2026-07-03.)*

### 4.2 Non-goals (guardrails)
- **No secondary penalty.** Provenance governs *attribution and confidence*, never *exclusion* — background,
  context, and framing still draw freely on secondaries (mirrors the existing credibility rule at `:470`).
- **No hardcoded domain lists** (LLM-Policy Gate). "Encyclopedia = secondary" is judged **semantically** by the
  LLM per source/claim, never a `{wikipedia.org, britannica.com}` set (which a new encyclopedia would defeat and
  which the gate forbids).

---

## 5. Concrete changes (touch points, cost basis)

All model-facing changes are **policy language to the LLM**; RAICA only dispatches and renders.

| # | File / function (line) | Change | LOC | Risk |
|---|---|---|---|---|
| A | `synthesis.py grade_sources` (`:174`) | LLM also returns a `role: primary\|secondary\|unknown` per domain (semantic prior; "origin of a claim" vs "reports a primary; encyclopedias/aggregators/explainers are secondary") | ~15 | Low |
| B | `synthesis.py _evidence_document` (`:275`) | add the role to each block header tag: `[sq \| source \| reputable \| secondary]` | ~8 | Low |
| C | `synthesis.py synthesize` prompt (`:458`) | **PROVENANCE block** (one voice with the credibility rules): prefer the primary in evidence for facts/quotes/attributions/stats; encyclopedias are pointers, not the citation of record when a primary is present; primary absent → ≥N independent secondaries = present as well-corroborated (cite all), one secondary = present transparently ("per X, primary not located"); never present a secondary's report as origin-verified; governs attribution, never exclusion | ~25 | **High** (LLM behavior) |
| D | `engine.py Planner._build_prompt` (`:205`) | for sub-questions needing a specific fact/quote/attribution, plan one that seeks the **origin** directly (`published_papers_search` / `get_sec_filings` / a `search_web` for the original document/transcript) — not only `wikipedia` | ~12 | Med |
| E | `engine.py _assess` (`:433`) | extend the gap policy — a **key claim backed only by secondaries** is a gap; propose a `next_query` to fetch the primary (follow the secondary's own reference, or search the original). Bounded by existing `max_rounds`/`wall_clock`; **degrade gracefully** — chase failure keeps the corroborated secondaries | ~15 | **High** (behavior + latency) |
| F | `synthesis.py verify` (`:514`) + `_min_corroborating` (`:125`) | tag each supported claim `primary` / `corroborated` / `single_secondary` (reuse `min_corroborating_sources`; require *independent* secondaries for `corroborated`) | ~25 | Med |
| G | `pipeline.py` footer (`:181`) + footnote (`:123`) | audit **Provenance** line ("N primary · M corroborated · K single-secondary") + a single-secondary footnote (same pattern as low-cred) | ~30 | Low |
| H | `config/llm_config.yaml` `deep_research.synthesis` | `source_provenance` block (§7) | ~10 | Low |
| I | tests | grader-role unit; synthesis-prefers-primary golden; independence (echo ≠ corroboration) unit; footer provenance unit; chase-query shadow | ~150 | Low |

**Estimated effort:** ~2–4 focused days incl. shadow validation. No new dependency; reuses the grader,
`min_corroborating_sources`, the assess loop, and the audit-footer machinery. Highest behavioral risks are **C**
(does synthesis reliably prefer primary?) and **E** (does the chase pay off within the round budget?) —
de-risked by shadow mode (§8).

---

## 6. LLM-Policy-Gate & consistency compliance
- **No-Hardcoding:** every primary/secondary/independence judgment is made by the LLM from source content — no
  keyword/domain lists, no regex, no `if domain in SECONDARY`.
- **No-Inconsistency:** the provenance policy is stated **once, coherently**, and echoed in one voice across the
  four stages that see it — planner (seek origin), assess (chase origin), synthesize (prefer/attribute), verify
  (label). No stage may tell the model "secondary is fine as-is" while another says "prefer primary."

---

## 7. Config (fail-open, reversible)
```yaml
deep_research:
  synthesis:
    source_provenance:
      enabled: true
      prefer_primary: true            # C: synthesis prefers primary for facts/quotes/attributions
      chase_primary: true             # D/E: gather loop seeks the origin for key secondary-only claims
      corroboration_elevates: true    # F: >= N independent secondaries -> "corroborated"
      min_independent_secondaries: 2  # the "multiple witnesses" threshold
      flag_single_secondary: true     # G: transparency footnote when a key claim rests on one secondary
      shadow: false                   # true = compute+log provenance/chase, change nothing
```
Any failure (grader role parse, chase call, verify tag) → today's behavior for that step.

---

## 8. Rollout (no-fail discipline, mirrors citation-grounding)
1. **Phase 0 — shadow.** A/B/F compute the role prior + per-claim provenance labels and E computes *would-be*
   chase queries; all logged, **answer unchanged**. Gives a real baseline: how often claims are single-secondary,
   how often a primary was actually available, how often "corroborated" is truly independent.
2. **Phase 1 — synthesis preference (C, B, A).** Prefer primary + transparent attribution. No new gather cost.
   Lowest-risk quality win.
3. **Phase 2 — chase the primary (D, E).** Enable origin-seeking planning + assess gap. Measure added latency
   and primary-hit rate; keep the round/wall-clock ceilings.
4. **Phase 3 — surface provenance (F, G).** Audit footer line + single-secondary footnote.

Each phase behind the `source_provenance` flags, fail-open, gated on "no-worse-than-today."

---

## 9. Test strategy
- **Grader role unit:** an encyclopedia domain → `secondary`; a journal/DOI/.gov statute → `primary`; ambiguous
  news → `unknown`/best-effort (semantic, mocked LLM).
- **Independence unit (the crux):** two secondaries that both cite only source X, or reprint one wire story →
  treated as **one** witness (NOT elevated); two independent lineages → `corroborated`.
- **Synthesis-prefers-primary golden:** evidence containing both a Wikipedia block and the primary it references
  → the answer cites the primary (Wikipedia at most as corroboration), with a mocked/replayed evidence set.
- **Graceful degradation:** primary absent, ≥2 independent secondaries → `corroborated` (not dropped, not
  overstated); one secondary → `single_secondary` + footnote.
- **Footer provenance unit:** counts render correctly; single-secondary footnote lists the right claims.
- **No-regression:** existing `test_citation_*` and DR benchmark scenarios (`S1`/`S2`) stay green.

---

## 10. Open questions for review
1. **Chase aggressiveness:** always chase key claims, or only attribution/quote/statistic types? (Latency vs
   thoroughness.)
2. **`min_independent_secondaries`:** 2 (proposed) vs 3 for elevation to `corroborated`.
3. **Paywalled primary:** cite the DOI/abstract as `primary (paywalled)` (proposed) vs treat as unreachable →
   `corroborated`.
4. **Footer verbosity:** always show the Provenance line, or only when there are single-secondary claims to flag?
5. **Non-DR path:** apply the same provenance policy to the non-DR primary-synthesis path later, or keep DR-only?

> Bottom line: add a provenance axis orthogonal to credibility, teach the gather loop to reach the origin, treat
> *independent* multi-secondary agreement as strong corroboration, and show the reader the provenance of every
> key claim — preferring the horse's mouth without ever penalizing or hiding a secondary.
