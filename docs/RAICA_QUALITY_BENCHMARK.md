# RAICA Quality & Performance Benchmark — Design (for review)

**Status:** PROPOSAL — awaiting sign-off on the metric definitions before any code is written.
**Author:** Claude (with Al Sabawi)
**Date:** 2026-06-17

---

## 1. Purpose

Lock in the quality/accuracy/completeness/performance baseline we just established, so that whenever we
touch a **core workflow** we get an objective answer to one question:

> *Did this change degrade any locked-in behavior — and ideally, did it improve a metric?*

It is THREE things at once:
1. a **regression gate** (block "the wiring looked right but the behavior degraded" defects),
2. an **improvement detector** (a metric beating baseline is surfaced, not just pass/fail),
3. a **versioned benchmark** of RAICA's intricate behaviors for future comparison.

It is NOT a correctness proof and NOT a replacement for the user end-to-end test that CLAUDE.md mandates —
it's the standing floor those tests sit on.

---

## 2. Design pillars (what makes an LLM benchmark trustworthy vs flaky)

**P1 — Assert on INVARIANTS, never exact text.** LLM output varies every run. We measure *structural,
countable* properties: which tool was selected, citation count, % of citations that are specific article
URLs, whether URLs resolve, attachment count, whether the doc title is a section heading, stage latency.
Never "the answer equals X". (CLAUDE.md-compliant: we score the LLM's structured output; we never hardcode
meaning.)

**P2 — Separate "our regression" from "the world changed."** This is the lesson of the qwen3-vl retirement,
the live-IP bot-blocking, and daily news churn. EVERY metric is tagged:
- **CODE** — under our control. A CODE regression = **FAIL** (red).
- **ENV** — depends on the outside world (cloud model availability/5xx, a news site returning 403/406, a
  URL that 404s because the article moved, today's headlines). An ENV miss = **WARN + alert**, never a red
  bar. (A model 410 is an *operations* signal — "go pick a new model" — not a code regression.)
A suite that fails on ENV noise gets ignored. This tagging is the single most important rule here.

**P3 — Baseline-as-data + deltas.** A versioned `baseline.json` holds the known-good metric values. The
suite reports the **delta** for each metric and a verdict: `IMPROVEMENT | PASS | REGRESSION | WARN(env)`.
"No degradation" = within `baseline − tolerance`. Baseline is updated only by an explicit, reviewed action
(never silently), with a note on what changed and why.

**P4 — Tiered cadence.** Cheap deterministic checks run constantly; expensive real-LLM scenarios run on
demand. You cannot run a 15-minute real-LLM suite on every commit.

---

## 3. Tiers

| Tier | What | Determinism | When | Cost |
|---|---|---|---|---|
| **0 — Gates** | The existing offline unit/contract tests, consolidated under one runner | deterministic (mocked/offline) | **every commit touching core** (pre-commit hook, BLOCKS) | seconds |
| **1 — Golden scenarios** | 5–6 real end-to-end runs vs `baseline.json` scorecard | non-deterministic (real LLM) | **before deploy/checkpoint** + nightly (manual/cron) | ~10–20 min |
| **2 — Latency budgets** | Per-stage timings parsed from `server_complete.log`, vs baseline | measured | piggybacks on Tier 1 | free |

**Tier 0** already mostly exists (7 files): `test_citation_grounding`, `test_tool_calling_retry`,
`test_dr_title_extraction`, `test_html_single_workflow_styling`, `test_vision_fallback`,
`test_delivery_failure_reporting`, `test_citation_source_filtering` + `test_citation_link_verification`.
Step 1 is just to wire them into one runner + the hook. They are the fast "did the logic break" floor.

**Tier 1/2 run against LOCAL RAICA by default** (cheaper, residential IP avoids datacenter bot-blocking),
with `--live` as an explicit opt-in.

---

## 4. Scorecard schema

Each scenario emits metrics; the runner compares to baseline and writes `scorecard.json` + a human summary.

```jsonc
{
  "metric": "specific_url_ratio",        // stable id
  "scenario": "news_mention",
  "class": "CODE",                        // CODE | ENV | PERF
  "value": 0.93,
  "unit": "ratio",                        // ratio | count | bool | seconds
  "direction": "higher_better",           // higher_better | lower_better | must_equal
  "baseline": 0.90,
  "tolerance": 0.10,                      // allowed slack before REGRESSION
  "verdict": "PASS"                       // IMPROVEMENT | PASS | REGRESSION | WARN
}
```
- **Scenario verdict** = worst CODE/PERF metric (ENV WARNs never fail a scenario).
- **Suite verdict** = `REGRESSION` if ANY CODE metric regressed beyond tolerance; else `PASS` (with an
  `IMPROVEMENTS` list and an `ENV_WARNINGS` list surfaced separately).
- **Noise control:** each Tier-1 scenario runs **N=3** times; the metric value is the **median** (cost vs
  confidence trade — configurable).

---

## 5. Scenario catalog (maps 1:1 to what we hardened)

Each lists the **metrics** and their class. (Exact baseline numbers captured in §6 from a verified-good run.)

### S1 — News mention citation quality
Prompt: a real-time news ask (e.g. "latest world news") via `/v1`, `deep_research:false`.
- `tool_selected_web` — did the tool model pick search_web/get_news_summaries — **CODE/bool/must=true**
- `citation_count` — # cited URLs — **CODE/count/higher_better**
- `specific_url_ratio` — fraction that are deep article URLs (not homepage/section) — **CODE/ratio**
- `fabricated_url_count` — cited URLs NOT in gathered evidence — **CODE/count/must=0**
- `url_resolve_ratio` — fraction returning 2xx — **ENV/ratio** (sites bot-block; informational)
- `latency_s` — **PERF/seconds/lower_better**

### S2 — Deep Research + email delivery (PDF + HTML)
Prompt: "deep research X, email as PDF and HTML" (recipient = test mailbox; or file-only on local).
- `dr_completed` — pipeline produced an answer — **CODE/bool**
- `doc_title_is_section` — title looks like "1. …"/"Part 2" — **CODE/bool/must=false**
- `source_count` — evidence sources — **CODE/count/higher_better**
- `attachment_count` — **CODE/count/must=2**
- `pdf_valid` — opens + non-trivial size — **CODE/bool**
- `html_self_contained` — has `<style>` + `@media screen` + markdown rendered — **CODE/bool**
- `subject_is_topic` — subject reflects the research topic, not a section — **CODE/bool**
- `dr_latency_s`, per-phase timings — **PERF**

### S3 — Vision (image recognition)
Prompt: `/v1` with a fixed local test image of a known object + "what is this?".
- `vision_ran` — vision model invoked, no exception — **CODE/bool**
- `description_keyword_hits` — known-object keywords present (e.g. for a labeled product) — **CODE/ratio**
- `vision_model_available` — primary model not 410/404 — **ENV/bool** (the retirement signal)
- `vision_latency_s` — **PERF/seconds** (the kimi vs minimax experiment lands here)

### S4 — Citation guard (NewX) behavior
Deterministic where possible (mock the judge); a thin live check otherwise.
- `greeting_posts` — a greeting reply is allowed — **CODE/bool**
- `sourceless_news_discarded` — a url-less news reply is rejected — **CODE/bool**
- `image_description_posts_attempt1` — image reply bypasses the guard — **CODE/bool**
- `has_image_detected` — RAICA-multimodal + Ollama formats both detected — **CODE/bool** (the f43b3e2 bug)

### S5 — Citation grounding (output guard)
Pure/offline (already Tier 0) — promoted into the scorecard for visibility.
- `fabricated_stripped`, `rotted_distinguished`, `valid_kept`, `lossless_when_clean` — **CODE/bool**

### S6 — Resilience (injected-failure)
- `tool_call_5xx_recovers` — 500→200 retry works (mocked HTTP) — **CODE/bool**
- `vision_fallback_runs` — primary fails → backup runs (mocked) — **CODE/bool**

---

## 6. Baseline management

- `tests/benchmark/baseline.json` — versioned, committed. Each metric records value + the
  commit/version it was measured at + a one-line note.
- **Capture:** run the suite on the CURRENT verified-good build (today's `v1.0.0.131` / NewX `f43b3e2`)
  and write the baseline.
- **Update protocol:** baseline changes ONLY via `--update-baseline` with a mandatory `--reason`, and the
  diff is shown + committed. A baseline bump for an *improvement* is good; a bump that hides a regression
  is forbidden (review gate).

---

## 7. Execution & automation

### One command
`python tests/benchmark/run_benchmark.py --tier 0|1|2|all [--live] [--update-baseline --reason "…"]`
plus a `make benchmark` (Tier 0) / `make benchmark-full` (Tier 1, local) convenience target.
Output: `scorecard.json` + a readable table (`IMPROVEMENT`/`PASS`/`REGRESSION`/`WARN` with deltas).

### Pre-commit trigger (the "when core code is touched" automation)
A repo pre-commit hook (alongside the existing CLAUDE.md compliance check):
1. Detect whether any **CORE FILE** is staged (list below).
2. If yes → run **Tier 0** (fast, blocks the commit on a CODE `REGRESSION`).
3. Also print a **reminder** (does NOT block): *"Core workflow touched — run `make benchmark-full` (Tier 1,
   local, ~15 min) before deploy/checkpoint."* Tier 1 is too slow to block every commit, so it's a
   **pre-deploy** gate folded into the Checkpoint Protocol, not a pre-commit gate.

**CORE FILE list (triggers Tier 0 + the Tier-1 reminder):**
`fastapi_server_complete.py`, `research/**`, `llm_providers/**`, `orchestration/**`,
`user_tools/image_to_text.py`, `user_tools/sandboxed_executor.py`, `user_tools/pdf_generator_tool.py`,
`services/pdf_service.py`, `utils/html_generator.py`, `config/llm_config.yaml`, `config/pdf_styles.css`,
`primary_model_system_prompt.txt`, `pre_tool_model_system_prompt.txt`.
(NewX core: `newx/app/ai_connector/responder.py`, `scheduler.py` — NewX has its own hook.)

This policy is also recorded in project memory so it survives across sessions.

---

## 8. Directory layout
```
tests/benchmark/
  run_benchmark.py          # CLI: tiers, scorecard, baseline-delta, CODE/ENV verdicts
  baseline.json             # versioned known-good metrics
  scorecard.json            # last run (gitignored)
  scenarios/
    s1_news_citation.py  s2_dr_email_delivery.py  s3_vision.py
    s4_citation_guard.py s5_grounding.py          s6_resilience.py
  fixtures/
    test_image_known_object.jpg   # fixed image for S3
  lib/
    scoring.py    # metric/verdict/baseline-delta engine + CODE/ENV classification
    raica_client.py  # POST /v1, parse stream, extract URLs/attachments/timings
```

---

## 9. Caveats & non-goals
- **Noise is real:** even with N=3 medians + tolerances, a Tier-1 run can occasionally WARN by luck. The
  CODE/ENV split + tolerances keep that from being a red bar; treat a single REGRESSION as "re-run, then
  investigate."
- **Maintenance cost:** model names, budgets, and known-good numbers drift; the suite needs upkeep. We keep
  it lean (6 scenarios) and resist gold-plating.
- **Not a security/auth test:** delivery recipient-lock, privilege gates, etc. stay in their own targeted
  tests; the benchmark covers quality/accuracy/completeness/performance.
- **Cost:** Tier 1 burns cloud tokens (DR especially). Local-by-default + on-demand cadence keeps it sane.

---

## 10. Rollout plan
1. **Phase A — DONE (bb43fdf, 2026-06-17):** Tier-0 runner + `make benchmark` + pre-commit hook (blocks on
   a Tier-0 CODE regression when a CORE file is staged). Floor in place.
2. **Phase B — DONE (74001f0):** scoring engine (`scoring.py`) + scorecard/baseline-delta + `/v1` client +
   S1/S2/S3. Baseline captured at RAICA v1.0.0.131 / NewX f43b3e2 (SUITE PASS): S1 specific_url_ratio 0.909
   / citation_count 11; S3 keyword_hits 1.0; S2 attachments 2, pdf_valid + html_self_contained True,
   doc_title_is_section False, DR latency 237s.
3. **Phase C — DONE:** Tier-2 per-stage latency added to the scorecard (`vision_model_s` — the
   kimi/minimax dial; `dr_synthesize_s`, `dr_verify_s` — parsed from the server log) + nightly automation
   (`make benchmark-nightly` / `tools/benchmark_nightly.sh`, cron line documented). Baseline re-captured =
   16 metrics, SUITE PASS (vision_model_s 7.9s; dr_synthesize 71.6s; dr_verify 82.6s). **Design refinement:**
   S5 (grounding) + S6 (resilience) are kept as **Tier-0 deterministic gates** (correct home — always-on
   commit gate; not duplicated into the costly real-LLM scorecard). S4 (NewX citation guard) is folded into
   the NewX work (it's NewX behavior).
4. Maintain: baseline updates are explicit + reviewed (`--update-baseline --reason`).

---

## Decisions (signed off 2026-06-17)
1. **Metric definitions / CODE-vs-ENV tagging / tolerances (§5)** — APPROVED as written. `url_resolve_ratio`
   stays **ENV** (the live/datacenter IP gets bot-blocked; a 403/406/404 there is not our regression).
2. **S2 email on local** — **FILE-ONLY locally**: render + assert the PDF/HTML artifacts; do NOT send mail
   on every benchmark run. (Email transport stays covered by its own targeted test + the `--live` opt-in.)
3. **N (repeats)** for Tier-1 noise control — **3** (median). Configurable.
4. **Baseline bump approval** — Claude MAY approve a bump for a clear improvement (must show the diff +
   `--reason`); the user can **overrule** when an improvement looks suspect. Never silent.
