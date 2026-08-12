# CHANGELOG v1.0.0.257 — synthesis scope/axis/span directives + topic-agnostic quality metrics

**Date:** 2026-08-11
**Status:** deployed to local and live. **The behavioural change is UNPROVEN — see "What the
measurement actually showed" before drawing any conclusion from it.**

---

## Why

A production `@Ask` answer on the linguistic landscape of the ancient Near East was graded
8.5–9.0/10 (B+/A−) by the user, who asked what would take it to A+ on a question with a large
established body of research. Two critiques were given:

1. "use of wikipedia and secondary sources while there are accessible academic and peer
   reviewed sources available"
2. "some sources are mentioned but not cited"

---

## A diagnosis that was recorded, then refuted

The first diagnosis was that the scholarship had never been READ. It rested on a control test
showing Brill returns HTTP 200 with 208 chars of body and De Gruyter 202/220, against
Wikipedia's 10,164 — using URLs constructed by hand, and drawn WITHOUT checking the audit for
the actual production run. That audit refutes it:

```
retrieval-audit: real=23 thin=1 error=0 over_captured=0 absent=0 / 24 cited
```

24 cited matches the answer's reference count exactly; 23 came back with a body. The sources
WERE fetched. This is recorded because the refuted version was briefly reported to the user as
confirmed. An explanation that merely FITS is not a cause that has been VERIFIED.

**What is actually wrong is retrieval DEPTH**, and unlike everything else measured here it is
stable: 2,016 / 2,405 / 2,253 / 2,661 / 2,618 / 1,982 chars per source across six local runs,
and 2,216 on the production answer — ±15% over seven measurements. That is roughly one
abstract per source. `deep_research.engine.retrieval_audit.min_body_chars` is **200**, so a
single paragraph grades as `real`, and a clean provenance line sits above an answer that never
engaged its sources. An abstract tells you what a work is ABOUT and often not what it ARGUES,
which is exactly the observed prose ("Radner directly addresses this phenomenon").

Two further defects are pure reasoning failures, provable from the answer's OWN dates:

- **Scope** — the TL;DR names the Neo-Babylonian Empire as dominating 1000–700 BC while the
  answer dates it 626–539 BC, beginning 74 years AFTER the window closes.
- **Uniform span** — Aramaic becomes a lingua franca in the 8th c., the final third of a
  300-year window, and the answer never says the picture changes across it.

---

## Changed

### `research/synthesis.py` — three directives in the DR synthesis system prompt

Each carries an explicit carve-out, because the naive form of each rule makes answers WORSE.

- **SCOPE INTEGRITY** — bounds set by the request govern what may be asserted as
  *characterising* the subject; out-of-bounds material stays legitimate as background but must
  be MARKED and must never appear in a summary or TL;DR as though it belonged.
  *Carve-out:* explicitly protects out-of-bounds context so it is labelled, not dropped, and
  preserves correcting a mistaken premise.
- **ANSWER THE AXIS THAT WAS ASKED** — make the asked axis the spine, not the
  better-documented adjacent topic; state plainly where evidence is thin.
  *Carve-out:* "never pad the gap with speculation."
- **VARIATION ACROSS A SPAN** — say where the picture changes across a range; where it is
  genuinely uniform, say that explicitly.
  *Carve-out:* "NEVER manufacture phases … an invented subdivision is a worse error than an
  honest flat answer."

**Deliberately NOT added:** a "show the disagreement" directive. The prompt already carries
*"Where sources CONFLICT, explicitly say so"* and an adversarial-balance clause calling a token
"some disagree" a failure. Adding more pressure toward debate language risks false balance on
settled questions. Refine over proliferate.

**Conflict audit (LLM-Policy Gate clause B):** checked against every directive already in the
prompt — no contradiction; two reinforce existing "include but label" and "say when thin"
patterns. No code gate (whitelist, validator, guard) rejects what these permit; the relevance
judge is shadow-only and nothing filters by date.

### `tests/benchmark/lib/generic_quality.py` — NEW, topic-agnostic metrics

The first cut of the S9 instruments was topic-locked and would have tuned RAICA for one
question about one century. Replaced with metrics that derive their parameters from the PROMPT
and the ANSWER: `citation_mix` (structural source classes), `citation_reuse`,
`unanchored_citation_ratio`, `retrieval_depth`, `declared_span`, `span_violations`.

Two quantities are DIAGNOSTIC with no direction, deliberately — see
`docs/RESPONSE_QUALITY_BASELINE.md` §4.

### `tests/benchmark/scenarios/s9_ancient_languages.py` — NEW scenario
### `tests/unit/test_generic_quality_metrics.py` — NEW, 16 tests across four subjects

Ancient history, equity research, public policy and clinical science, both eras, plus the two
refused biases.

### Docs
- `docs/RESPONSE_QUALITY_BASELINE.md` — §4 (refused biases), rule 9 (no paraphrase-gameable
  metric), rule 10 (measure a contrasting domain before a shared-prompt change).
- README + `config/logging_config.json` version surfaces → 1.0.0.257.

---

## What the measurement actually showed

**S9, n=3, before vs after: no measurable improvement.** Every metric sits inside noise; the
variance swamps the effect (`answer_chars` 15,498–50,037; `claims_unsupported_ratio`
0.049–0.562). `encyclopedic_share` moved the WRONG way, 0.069 → 0.167, on a very small base.
The retained POST artifact marks out-of-bounds material LESS than the pre-change one.

The directive text was verified present in the live `synthesize()` path (called at
`synthesis.py:1374/1387`), so this is not a dead variable. Whether the effect is real but below
the noise floor, or diluted in a 31,162-character prompt carrying ~40 directives, is
**not established**. No further prompt text was added to chase it.

**Cross-domain control (rule 10).** S5 finance held every functional deliverable — 7/7 tickers
with DCF, 7/7 with a call, 23 chart markers, comparison table and as-of date present — and
`claims_unsupported_ratio` improved 0.0085 → 0.0015. S8 history: all noise. **No cross-domain
regression in the deliverables.**

---

## Known / open

- **SI-031** — S5 `evidence_items` PRE [65, 89] → POST [41, 24], non-overlapping ranges. A
  synthesis-prompt change cannot plausibly affect UPSTREAM gathering, so this is suspected
  variance rather than a confirmed regression, but it is logged rather than dismissed. Needs
  n≥3 to resolve.
- **Retrieval depth (~2,250 chars/source)** is the measured A+ blocker and is untouched by this
  release. It is a code change, not prose, and it has a stable number to move.
- `min_body_chars = 200` makes the retrieval audit call an abstract "real"; the metric is
  lenient enough to hide the defect above.

## Rollback

`git revert` this commit and restart. The change is confined to the DR synthesis system prompt
plus additive test/benchmark files; no schema, config or API surface changed.
