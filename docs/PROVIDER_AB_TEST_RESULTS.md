# Provider A/B Results — Ollama-cloud vs DeepInfra

**Run:** 2026-08-09 → 2026-08-10 · **Against:** v1.0.0.243–245 · **Plan:**
`docs/PROVIDER_AB_TEST_PLAN.md` (pre-registered)

**Verdict: HOLD the migration.** Non-DR is quality-neutral. Deep Research is not, and
the mechanism — while located — is not explained.

---

## 1. What was actually run

The pre-registered plan specified 10 cases × 3 reps × 2 arms (60 runs). It was cut
twice, deliberately and with the reasons recorded:

| half | planned | run | why cut |
|---|---|---|---|
| non-DR | 6 cases × 3 × 2 = 36 | **3 cases × 3 × 2 = 18** | user request; kept the three with distinct LANE coverage |
| DR | 4 cases × 3 × 2 = 24 | **2 cases × 3 × 2 = 12** | ~4h at 5–12 min/run; kept the heaviest case and the lowest-drift case |
| planner diagnostic | — | **6** | added after the DR result, to locate the mechanism |

**n=3 was preserved throughout** — the pre-registered value, and the minimum that
distinguishes "always" from "sometimes".

**Cases dropped, and what that costs:** N1 (both arms trivially pass), N3
(MIS-CLASSIFIED — it trips the Deep-research gate, so it belongs in the DR half), N5
(a real loss: it tests obeying an explicit *"do NOT search"*, where N4 tests default
judgement), D3 (charts — D1 already emits markers), D4 (**delivery** — needs inbox
verification; the SI-015 `actions` path is untested by this A/B).

---

## 2. Non-DR — NEUTRAL

18 runs. Scored from the server log (`TOOLS EXECUTED:`), not from the prose.

| case | tests | Ollama | DeepInfra |
|---|---|---|---|
| **N2** "What is NVDA trading at?" | tool selection **+ execution + data accuracy** (±5% of a live reference) | **3/3** | **3/3** |
| **N4** "Hello! How are you today?" | **abstention** — any tool call is a false positive | **3/3** | **3/3** |
| **N6** *(image)* "Transcribe exactly" | vision lane | 0/3 | 0/3 |

**No false-positive tool calls on either arm** — the metric whose failure blocks
migration outright. Both arms selected the right tool and returned a price within
tolerance, every run.

**N6 is VOID, not a result.** It failed identically on both arms because of a RAICA
defect, not the provider — see §5.

**Latency:** Ollama median **16.8s**, DeepInfra **34.3s** → **2.05×**. Report-only
under the rules (threshold >2×), so marginally over. A flag, not a blocker.

---

## 3. Deep Research — NOT NEUTRAL

12 runs. Medians of 3.

| | metric | Ollama | DeepInfra | Δ |
|---|---|---|---|---|
| **D1** PLUG | evidence items | **21** | 11 | **−48%** |
| | unique URLs | **79** | 59 | −25% |
| | citations | 142 | 128 | −10% |
| | groundedness | **30.0%** | 17.6% | **−12.4pp** |
| | latency | 283s | 700s | **+147%** |
| **D2** CRISPR | evidence items | **7** | 5 | −29% |
| | unique URLs | **98** | 86 | −12% |
| | citations | 59 | 50 | −15% |
| | groundedness | 95.5% | **100%** | **+4.5pp** |
| | latency | 199s | 486s | **+145%** |

**Chart completeness: perfect on both** (12/12–14/14, zero repair passes). No failed
runs, no errors.

**Truncation: 1 on DeepInfra (32000-token cap), 0 on Ollama.** 1 of 3 D1 runs.

---

## 4. Mechanism — located, not explained

Two hypotheses were formed and **both died on measurement**:

1. **"Latency eats a time budget."** WRONG. Every run stopped `sufficient` with gather
   at 44–92s against a `wall_clock_seconds: 240` ceiling. Nothing was time-pressured.
2. **"Source fetches are failing."** WRONG. `dispatched N → gathered N` matched exactly
   in every run. Nothing failed to retrieve.

So the difference enters **before gathering**. A direct planner diagnostic
(`ResearchPlanner.plan`, same prompt, same model, n=3 per arm) found it:

| arm | sub-questions | sources per sub-question | total dispatch |
|---|---|---|---|
| Ollama | 6, 5, 6 | `[1,2,2,3,2,2]` | **12, 10, 12** |
| DeepInfra | **6, 5, 6** *(identical)* | `[1,1,1,1,2,1]` | **7, 6, 7** |

**The decomposition is identical. The source assignment is not.** Ollama assigns 2–3
sources per sub-question; DeepInfra assigns mostly 1. A **~42% dispatch reduction**,
which propagates cleanly to the observed evidence gap — same direction, same magnitude,
clean separation across 3 reps with no overlap.

### What this says about confound C4

The plan flagged C4 as unresolvable: *whether the two providers serve identical weights
or quantisation is UNVERIFIED*. This result bears on it directly. Same model, same
prompt, same config, differing consistently on **one specific output field** is more
consistent with a **serving difference** (quantisation, sampling defaults, decoding
parameters) than with a transport difference.

**That is a hypothesis, not a finding.** It cannot be proven from outside. But C4 is now
a narrow, testable question rather than a vague caveat: run the same model on both
providers with sampling parameters pinned identically, and diff raw outputs.

---

## 5. Bugs this A/B found (all logged, most fixed)

The A/B's largest yield was not the comparison — it was five defects, none
provider-specific:

| id | what | status |
|---|---|---|
| **SI-016** | The user's prompt never reached FORCED IMAGE PROCESSING; the vision model was asked to *describe* the image, never to answer the question. Verified by falsification: **0/3 without the user prompt, 3/3 with it**. Voided N6 on both arms. | **FIXED** v1.0.0.245 (0/6 → 7/8) |
| **SI-017** | `convert` could rewrite an `api_key` but never INSERT one, so a lane moving from a keyless provider (Ollama) to a credentialed one lost its credentials → `401` on every vision call. | **FIXED** v1.0.0.244 |
| **SI-009** | `doctor --probe` authenticated for Gemini ONLY; every other endpoint was probed unauthenticated and reported `?` inconclusive — silently disarming the command meant to gate a deploy. Caught by running the A/B pre-flight. | **FIXED** v1.0.0.243 |
| **SI-015** | Hardcoded `max_tokens` on JSON-returning DR calls truncating into silent fallbacks. A **2048-token** truncation (tool lane) was observed during these runs — a fifth site. | partially fixed v1.0.0.240 |
| **SI-010** | Entire Ollama-cloud stack 429 weekly-limited. Dashboard showed the cause: **glm-5.2, 3,206 requests** — the tool lane consumed 100% of the weekly cap. | resolved (quota reset 20:01) |

---

## 6. Decision, against the pre-registered rules

| rule | result |
|---|---|
| tool-selection accuracy drop >10pp | **no** — 3/3 both arms |
| ANY one-armed false-positive tool call | **no** — 0 on both |
| chart completeness drop | **no** — complete on both |
| **a truncation on one arm only** | **YES** — 32000-cap, DeepInfra only → **BLOCKS** |
| citation liveness drop >10pp | **NOT MEASURED** — see §7 |

**HOLD.** Two reasons, in order of weight:

1. **A same-model, same-prompt configuration producing consistently thinner research
   plans is an unexplained behavioural difference.** Migrating through one means
   inheriting a problem that can no longer be attributed.
2. The one-armed truncation trips a rule fixed in advance. It is 1 of 3 — a thin
   signal — but pre-registration exists precisely so a thin signal is not argued away
   after the fact.

**This is not "DeepInfra is worse."** Answers were well-formed on both arms; D2's
groundedness was *better* on DeepInfra (100% vs 95.5%); non-DR was indistinguishable.
DeepInfra also served RAICA correctly for a full day while the Ollama quota was
exhausted — it is a viable failover today.

---

## 7. What was NOT measured — stated so it is not assumed

- **Citation liveness** (HTTP status of cited URLs via `research/link_liveness.py`).
  The decision rule names it; **groundedness** was measured instead. The D1 groundedness
  drop of 12.4pp therefore does NOT strictly trip that rule.
- **Delivery (D4)** — the SI-015 `actions` path, where truncation silently drops a
  user's PDF. Untested here.
- **Cost.** RAICA does not surface DeepInfra's `usage.estimated_cost`, and a figure
  derived from logged char counts came in **30% under** actual earlier in this work.
  The dashboard is authoritative. Ollama's cost is quota consumption, not dollars, and
  the two are not comparable in kind (confound C7).
- **N1 / N3 / N5** — dropped in the cut.
- **Prompt-cache attribution (C5)** — cached vs uncached tokens were not separated.

---

## 8. Next, in order

1. **Settle C4.** Same model, both providers, sampling parameters pinned identically,
   diff raw outputs. This is the question the whole result now hangs on.
2. **Measure citation liveness** on both arms — the rule that was named but not measured.
3. **Test D4 (delivery)** — the untested path with the most user-visible failure mode.
4. **Then** implement `docs/PROJECTION_GROWTH_BLEND_SCOPE.md`, which was frozen until
   this A/B reported.
