# CHANGELOG v1.0.0.249 — synthesis integrity directives (SI-023)

**Date:** 2026-08-10 · **Previous:** v1.0.0.248 · **Type:** policy (prompt), no code logic

From a user review of a real NVDA/AAPL report. Three defects — **none about data
accuracy**. The report's figures were verified EXACT against live yfinance (NVDA TTM
$253.5B, FY2026 $215.94B, market cap $5.39T, trailing P/E 34.05); the review's claim that
they were fabricated was itself mistaken, reasoning from stale knowledge. What the review
got right was **how the analysis presented itself**.

| | defect | directive |
|---|---|---|
| (a) | low-credibility sources carried load-bearing numbers ($740B capex, KPMG survey percentages) as bare facts — RAICA graded them weak, disclosed the grade in a footer, then cited them as if solid | a weak source may never be the SOLE support for a number a reader will act on; use it, but name it in the prose where the number appears |
| (b) | "30%/50%/20%", "60% confidence" presented with the precision of a computed output — no calibration model exists | give them, but state they are judgement; keep precision honest (`~60%`, never `62.4%`); give the reasoning |
| (c) | DCF said −62.6% overvalued while the price target implied upside, side by side, unreconciled | reconcile in the text, naming the assumption that explains the gap; "the model is structurally conservative" is explicitly NOT a reconciliation |

## Design constraints observed

**LLM-policy gate (A) — policy, not pattern matching.** All three are stated as rules in
language. No keyword lists, no regex, no if/elif deciding meaning. Pinned by a test.

**LLM-policy gate (B) — no code gate contradicts them.** Checked before writing, not after:

- NewX's citation guard fires only on replies with **no URLs at all** (`_has_any_url`
  early-returns), so an attributed, cited report can never be discarded by it.
- RAICA's `link_liveness` strips only genuinely dead links.
- `research/pipeline.py` already classifies `attributed_to_low_credibility` as
  **"a feature (fair presentation), not a defect"**, filing it under "source notes"
  rather than "Claims to scrutinize". Directive (a) drives exactly the behaviour the
  verifier already rewards — prompt and code speak with one voice.

(a) deliberately **permits rather than bans**: blanket exclusion of weak sources would cut
real coverage, since a broker page can still carry a genuine analyst consensus. The rule is
attribution, not suppression. (b) likewise does not ban scenario weights — they are standard
analyst practice; the defect was false precision without a stated basis.

## Verification

`tests/unit/test_synthesis_integrity_directives.py` (6 tests) guards PRESENCE and FORM —
that the directives still ship to the model and have not decayed into pattern matching.
**Behavioural compliance is NOT asserted there**: it is stochastic and must be verified by
real end-to-end runs, repeated, which is done separately against the `@Ask` benchmark.

One test bug worth recording: the first version searched raw source for a phrase that
straddles a string-literal line break (`"…structurally " "conservative"`) and failed —
which would have read as a missing directive. The test now joins adjacent literals so it
asserts against the text the MODEL receives, not the source layout.

`tests/unit`: 221 passed, 4 failed — those 4 fail identically on the committed baseline.

## Files changed

| file | change |
|---|---|
| `research/synthesis.py` | three directives added to the synthesis system prompt |
| `tests/unit/test_synthesis_integrity_directives.py` | **new** — 6 tests |
| `version.py`, `README.md`, `config/logging_config.json` | 1.0.0.248 → 1.0.0.249 |

## Breaking changes

None. Prompt-only; no code path changes.
