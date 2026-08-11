# Response Quality Baseline — the minimum bar for any AI response

**Status:** STANDARD, adopted 2026-08-10 · **Scope:** RAICA, NewX, Agentoo1 — any component
that produces a response for a human reader.

These seven dimensions are the **minimum** against which a response is judged. They are
**measured**, never asserted, and they are measured on a **baseline BEFORE a change** and
again after, with the delta reported. Apply them with judgement — a greeting does not need
a primary-source ratio — but never substitute an opinion for a measurement where one is
available.

Origin: a day of work on 2026-08-10 in which a flagship feature broke for a user, was
"verified" repeatedly without a baseline, and produced four separate false findings from
defective measurement. Every rule below is the residue of a specific mistake.

---

## 1. The seven dimensions

### D1 — Depth (primary sources)
Share of citations that are **primary**: filings, government/statistical data, earnings
transcripts, datasets, the entity's own disclosure — as opposed to commentary *about* them.

```
primary% = primary_citations / total_citations
```
**Measured 2026-08-10:** finance **80%**, open-web policy **14%**. The gap is structural:
depth is strong where a TOOL supplies primary data and collapses where the system must find
it on the open web.

### D2 — Breadth (coverage / blast radius)
`evidence_items`, `unique_sources`, `rounds`, `stop_reason`. Breadth without depth is noise;
depth without breadth is anecdote. Report both or neither.

### D3 — Quality (accuracy, correctness, reasoning)
- **Accuracy:** re-verify a sample of figures against the LIVE source. Not "does it look
  right" — fetch it. (8/8 tickers matched live yfinance to the decimal.)
- **Correctness:** claims checked / supported / **contradicted**. Contradicted is the serious
  verdict; unverified only means the verifier could not ground it.
- **Reasoning:** does a quantitative tool result that contradicts the conclusion get
  RECONCILED in the text, or presented alongside it and ignored?

### D4 — Presentation
Headings, tables, charts, figure density — **and every deliverable the prompt explicitly
named** (comparison table, as-of date, per-entity recommendation). A missing named
deliverable is a failure regardless of prose quality.

### D5 — Relevance of source extraction
Share of RETRIEVED sources judged off-topic.
```
off_topic% = off_topic_sources / retrieved_sources
```
**Measured:** **17.3%** (144/833). Worst on open-web policy topics (34.6%).
**Distinguish evidence-pool contamination from ANSWER contamination** — 23/23 off-topic
items were filtered by synthesis and reached no answer. Retrieval noise is a COST (budget,
latency), not a correctness failure.

### D6 — Hallucination
```
fabrication% = cited_urls_absent_from_evidence / cited_urls
```
Plus: fabricated-citation audit, dead-link rate on *measurable* domains, and figure accuracy.
**Measured: 0.0%** across 199 citations. Not a problem in RAICA today.

### D7 — Provenance
Share of citations that are **cited but were never actually retrieved** (`over_captured` —
the URL was harvested from another page's content).
```
over_captured% = cited_not_retrieved / cited
```
**Measured: 40.2%.** The single largest quality defect. Not hallucination — the link is real
— but it is **unverified attribution**.

---

## 2. Measurement rules

Each rule below exists because breaking it produced a false finding on 2026-08-10.

1. **Baseline FIRST.** Measure the incumbent on real queries before changing code. Re-measure
   after. Report the delta. *(A full day of fixes was "verified" self-referentially — each
   change tested against its own intent, never against the system's prior behaviour.)*
2. **Prefer ANSWER-derived metrics over LOG-derived.** The log can prove a tool ran while the
   answer proves nothing reached the reader. *(8 DCFs computed, 8 chart markers emitted, and
   the answer said none were provided. A log-only instrument scores that a PASS.)*
3. **A metric must be COMPARABLE across arms.** *(`claims_unsupported_ratio` moved 0.000 →
   0.107 and meant nothing: 129 vs 215 claims extracted — one arm simply examined more.)*
4. **Control group before any verdict.** *(A liveness check reported 50% dead links; the
   control showed Yahoo returns 404 for REAL pages and 200 for an INVENTED path. The
   instrument was anti-correlated with truth.)* Exclude domains where the instrument cannot
   discriminate, and say so.
5. **n ≥ 3 for anything stochastic.** *(Latency varied 1.7×, chart count 0–20, claim count
   63–142 at identical config.)* Single-run deltas under ~2× are noise.
6. **RETAIN the artifact.** Persist the answer and log window per run. *(A metric moved and
   the flagged claims could not be read, because the harness measured then discarded the
   answer.)*
7. **Check whether a detector ENFORCES.** *(The relevance judge flags 17% off-topic and drops
   none of it — the budget is still consumed.)* A SHADOW detector measures; it does not fix.
8. **Verify the instrument before the subject.** Five detector bugs in one day: an
   order-dependent claims parser, a substring filter that suppressed its own message, a
   too-narrow judgement regex, a raw-source search defeated by a line break, and a table
   detector that failed a valid table by one row. When a metric looks alarming, suspect the
   instrument first.

---

## 3. Where the harness lives (RAICA)

- `tests/benchmark/run_benchmark.py` — Tier 0 (deterministic gates), Tier 1 (golden scenarios
  vs `baseline.json`), Tier 2 (latency)
- `tests/benchmark/lib/spectrum.py` — the D1–D7 measurement helpers + `retain()`
- `tests/benchmark/scenarios/s4..s9` — the full-spectrum suite: 8-ticker finance, 7-ticker
  finance (prod-comparable), original commentary, simulation with charts/tables,
  evidence-only history, and a well-studied humanities question graded to an A+ bar
- `tests/benchmark/lib/generic_quality.py` — TOPIC-AGNOSTIC metrics usable by any scenario:
  citation mix by structural source class, citation reuse, unanchored-citation ratio,
  retrieval depth, and scope violations against bounds PARSED FROM THE PROMPT

---

## 4. Two biases this suite deliberately refuses to encode

Added 2026-08-11 after the first cut of the S9 instruments was found to be topic-locked (a
hardcoded 700-1000 BC window, a list of ancient Near East inscriptions, a speech-vs-writing
word list). Baselining on those and then "improving" would have tuned RAICA for one question
about one century and reported it as a quality gain.

1. **Disagreement is never scored.** A "does the answer show scholarly debate" metric marked
   higher-is-better rewards MANUFACTURING controversy, and the topics where that does the
   most damage — settled science, loaded political premises — are exactly the ones DR is
   already weakest on. `debate_markers` is DIAGNOSTIC, with no direction.
2. **Subdivision is never scored.** An answer covering a span that genuinely IS uniform
   should say so, not invent phases. `span_subdivisions` is likewise diagnostic. What IS
   scored is the falsifiable error: asserting out-of-bounds material as in-bounds.

**Rule 9 — a metric must not be gameable by paraphrase.** The first name-dropping detector
was a list of English phrases ("directly addresses", "explores these"); rewording to "sheds
light on" would have zeroed the metric with the defect untouched. It was replaced by a
structural test — does the citing sentence carry a figure, date, quotation or named entity —
which holds across wordings, subjects and languages.

**Rule 10 — measure a contrasting domain before shipping a shared-prompt change.** Anything
edited into the synthesis system prompt affects EVERY answer. A humanities-motivated change
must be measured on finance and on a second topic too, or a fix for one subject ships as an
unseen regression in another.

**Run Tier 1 before and after any change that can affect responses.** It exists; it was
sitting unused with a clean pre-change baseline while a day of unmeasured work went by.
