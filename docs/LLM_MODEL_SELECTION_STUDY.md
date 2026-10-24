# LLM Model Selection — Why RAICA Runs on deepseek-v4-pro

**Written:** 2026-10-10 · **Against:** v1.0.0.334 (local and live on the same commit, `f6773b5`)
**Updated:** 2026-10-24 — arbitrator and vision moved to deepseek-v4.1-flash, vision fallback to minimax-m3.1-flash (§4.6)
**Purpose:** one place to cite when the question "is there a cheaper model?" comes back. Every number
below is taken from a dated RAICA record (changelog or `SUSPECTED_ISSUES.md`) or from Ollama's
published price list, and is marked with its source. Anything that is NOT in a record is labelled as such.

---

## 1. The decision, in one paragraph

RAICA's heavy lanes — `llm.primary` (answers and synthesis) and `llm.tool_calling` (tool selection and
orchestration) — run on **deepseek-v4-pro:cloud**. Cheaper models were measured on RAICA's real request
paths and fell short on accuracy: deepseek-v4.1-flash got calculations wrong, glm-5.3-flash failed its
first calculator call every time, gpt-oss-120b selected the right tool less than a third as often. The one
model that **matched** deepseek-v4-pro — glm-5.3 — produced about **13× the output tokens** per tool
request and was slower, so it costs more at nearly the same per-token price. The owner's broader trials
(MiniMax, Kimi) reached the same conclusion; those are not in the written record (§5).

The light lanes are a different question. On 2026-10-24 the arbitrator and vision moved from glm-5.3-flash to
**deepseek-v4.1-flash** (the build Ollama upgraded on 2026-10-17), and the vision fallback from minimax-m3 to
**minimax-m3.1-flash** — same or better accuracy, several times faster, at a small cost difference (§4.6).

## 2. What runs where today

Read from `config/llm_config.yaml` on 2026-10-24 (local == live, every selected model compared):

| Lane (config path) | Model |
|---|---|
| `llm.primary` | `deepseek-v4-pro:cloud` |
| `llm.tool_calling` | `deepseek-v4-pro:cloud` |
| `code_generation.providers.ollama` | `deepseek-v4-pro:cloud` |
| `arbitrator` | `deepseek-v4.1-flash:cloud` (was glm-5.3-flash until 2026-10-24, §4.6) |
| `vision` | `deepseek-v4.1-flash:cloud`, fallback `minimax-m3.1-flash:cloud` (were glm-5.3-flash / minimax-m3 until 2026-10-24, §4.6) |
| `deep_research.engine.model` | `deepseek-v4.1-flash:cloud` (heavy synthesis/verify routed to pro, §4.4) |
| `convergence.shadow_classifier`, `convergence.intent_classifier` | `deepseek-v4.1-flash:cloud` |

Note the split: the cheap models are not absent — they hold the lanes where they measured well enough
(arbitration, vision, classification, Deep Research's small mechanical calls). Only the lanes where they
lost on accuracy run on pro.

## 3. Prices

Source: <https://ollama.com/pricing>, read 2026-10-10. "Usage is measured in tokens at each model's
rates." US$ per million tokens.

| Model | Input | Cached input | Output |
|---|---|---|---|
| **deepseek-v4-pro** | 1.32 | 0.044 | 3.96 |
| glm-5.3 | 1.40 | 0.26 | 4.40 |
| glm-5.2 | 1.40 | 0.26 | 4.40 |
| kimi-k3 | 3.00 | 0.30 | 15.00 |
| kimi-k2.6 | 0.95 | 0.16 | 4.00 |
| minimax-m3 | 0.60 | 0.12 | 2.40 |
| minimax-m2.7 | 0.30 | 0.06 | 1.20 |
| deepseek-v4.1-flash | 0.30 | 0.006 | 1.20 |
| gpt-oss:120b | 0.15 | 0.014 | 0.60 |
| glm-5.3-flash | 0.15 | 0.03 | 0.50 |
| minimax-m3.1-flash | 0.15 | not recorded | 0.60 |

minimax-m3.1-flash: from <https://ollama.com/library/minimax-m3.1-flash>, read 2026-10-23 (published 2026-10-19).

Off-peak (outside 12:00–18:00 UTC on weekdays, and all weekend) is discounted for **deepseek-v4.1-flash
and deepseek-v4-pro** only (same source).

**Caveat on older records.** Records from before per-token pricing (e.g. SI-099) talk about a weekly quota
and request counts, not dollars. A third-party write-up dates Ollama's move to credit-based pricing to
2026-08-31, with legacy plans keeping weekly limits (<https://dev.to/amareswer/ollama-cloud-free-vs-pro-usage-limits-pricing-what-you-actually-get-2026-3ieo>
— not confirmed on ollama.com); the production account still reported a "weekly usage limit" on 2026-10-09.
The token counts those records measured are still valid; the dollar figures in §4 apply today's prices to them.

## 4. The evidence, by lane

### 4.1 Tool calling — glm-5.3 vs deepseek-v4-pro vs deepseek-v4.1-flash (2026-09-25)

Source: `docs/housekeeping/status-tracking/CHANGELOG_v1.0.0.326.md`; `SUSPECTED_ISSUES.md` SI-099.
Harness: `tests/integration/run_tool_model_eval_live.py` — 14 real requests through `/v1` with the full
tool catalogue, per-request `tools_calling_model`, scored on required tools, precision, and answer
completeness (numbers checked against independently computed ground truth). Raw rows were not saved to a
file (`--out` defaults to empty); the changelog is the record.

| Model | Result |
|---|---|
| glm-5.3 | answers **37/42** (14 cases × 3) |
| deepseek-v4.1-flash (the build before Ollama's 2026-10-17 upgrade) | answers 37/42 — **REJECTED**: skipped the calculator and got compound interest wrong in **2/3** runs ($6,804.22 vs the true $6,847.26) |
| deepseek-v4-pro (4 discriminating cases × 3, against glm-5.3's rows on the same cases) | answers **9/12** and tools **9/12** — the same as glm-5.3; compound interest **3/3** (glm-5.3 2/3) |

Speed and volume, same 4 cases: deepseek-v4-pro median **38 s** vs glm-5.3 **96 s**; about **620** vs
**8,300** output tokens per request.

**Cost per tool request, at today's prices (output only, measured tokens):** glm-5.3 8,300 × $4.40/M ≈
**$0.037**; deepseek-v4-pro 620 × $3.96/M ≈ **$0.0025** — about **15× less** on output. Input prices are
nearly equal (1.40 vs 1.32), and input tokens for deepseek-v4-pro were not recorded, so no total ratio is
claimed. This is the "matched the quality, but more expensive" result: same accuracy, far more output.

Owner decision (v1.0.0.326): every glm-5.3 use (tool_calling, the code-generation preset,
code_generation's Ollama default) moved to deepseek-v4-pro.

### 4.2 Tool calling — cost of the three cheaper candidates (2026-09-25, before 4.1)

Source: `SUSPECTED_ISSUES.md` SI-099 "three-way cost A/B"; `CHANGELOG_v1.0.0.325.md`. S1 news-citation
prompt, only the tool model varied, arms rotated, 3 runs each; tokens from the tool model's own
`prompt_eval_count`/`eval_count`.

| Tool model | Latency (median) | Requests | Input tokens | Output tokens | Citations |
|---|---|---|---|---|---|
| glm-5.3 | 59 s | 3/2/3 | 50k/33k/50k | 3,246/1,552/2,390 | 15/16/16 |
| glm-5.2 | 55 s | 2/2/2 | 33k | 110–134 | 15/16/15 |
| deepseek-v4.1-flash | 35 s | 2/2/2 | 34k | 177–192 | 14/11/12 |

Per request at today's prices (mean input × input price + mean output × output price): glm-5.3 ≈ **$0.073**,
glm-5.2 ≈ **$0.047**, deepseek-v4.1-flash ≈ **$0.010**. deepseek-v4.1-flash was the cheapest and fastest —
and then failed the accuracy test in 4.1 (wrong compound interest 2/3) and gave fewer citations here
(median 12 vs 15–16).

### 4.3 Tool calling — glm-5.3-flash (2026-09-24)

Source: `SUSPECTED_ISSUES.md` SI-096. Combo prompt (image "Ticker: KO" → price → shares):
glm-5.3-flash produced compute errors on **3/3** runs; glm-5.2 on the same input **1/3**. The final answer
was correct 3/3 in both arms — the cost was an extra tool round every time. Owner decision: tool lane to
glm-5.3 (non-flash), which then lost to deepseek-v4-pro in 4.1. glm-5.3-flash stays where it measured
well: arbitration and vision.

### 4.4 Tool calling and arbitration — gpt-oss-120b vs GLM-5.2 (2026-08-09)

Source: `CHANGELOG_v1.0.0.236.md` §3c; `docs/LLM_PROVIDER_PARITY_REMEDIATION_PLAN.md` §2.4 and §6.
Run on DeepInfra against RAICA's **real** 33-tool payload (37,981 chars) and real tool system prompt,
16 cases × 3, scored on selection accuracy and stability.

| Lane | gpt-oss-120b | GLM-5.2 | Outcome |
|---|---|---|---|
| tool_calling | **29.2%** | **89.6%** | keep GLM-5.2 — "not close" |
| arbitrator | 100% | 100% | deferred |

gpt-oss-120b returned a date/time tool for a weather query and scored 0% on four near-duplicate
disambiguations. On arbitration it reached parity on verdicts, but with `reasoning_effort=xhigh` it used
1,711–2,354 tokens in 4 runs plus one run that consumed 8,000 and was cut off.

### 4.5 Deep Research — flash vs pro (2026-06-02 and 2026-07-11)

- `CHANGELOG_v1.0.0.68.md` (2026-06-02, deepseek-v4-flash — since retired): across planner, roster,
  verify and synthesis, flash was equal-or-better and 2–3× faster; a 15-civilisation run checked 161
  claims, 156 supported (97% grounded). **Pro was kept for normal chat** because flash failed a hard
  multi-step reasoning puzzle that pro solved.
- `CHANGELOG_v1.0.0.174.md` (2026-07-11): after a further flash-vs-pro comparison,
  `heavy_threshold_chars` 250000 → 20000 routes every real DR synthesis (~30K+ prompt) and verify (100K+)
  to **deepseek-v4-pro** "for more professional, persuasive output"; small mechanical calls (plan, grade,
  relevance, under ~8K) stay on flash. The numbers for that second comparison are not in the changelog.

### 4.6 Arbitrator and vision — glm-5.3-flash vs deepseek-v4.1-flash, and the vision fallback (2026-10-23)

Source: this run; harness `tests/integration/run_vision_arbitrator_eval_live.py` (v1.0.0.344). Owner question: is the
deepseek-v4.1-flash build Ollama shipped on 2026-10-17 better than glm-5.3-flash for the arbitrator and vision, and is
the new minimax-m3.1-flash a better vision fallback than minimax-m3? **240 real calls, 0 errors, 0 rate limits**,
3 runs per case, arms alternated inside each case.

**Method — RAICA's own code, nothing re-implemented.** Vision: `ImageToTextTool.get_image_processing_results` with
RAICA's system prompt, JSON contract and reply check, fallback OFF so each model stands alone; 12 generated images with
known answers (receipt, table, bar and line chart, count, small text, rotated text, diagram, memo, pie chart,
calendar, and a BLANK image that must be reported as blank). Arbitrator: the exact `arbitrator_system_prompt`, the
same prompt layout (request[:200], each result[:500]), `OllamaProvider.generate_stream` with the arbitrator's kwargs,
and RAICA's parse steps; 16 hand-built cases of 1–6 tool results, mixed good and bad (114 task verdicts per arm).

**Vision** (51 facts per arm = 17 per run × 3; cost = measured tokens × §3 prices):

| Model | Facts right | Followed RAICA's JSON contract | Time median / p90 / max | Output tokens (median) | $ per 1,000 images |
|---|---|---|---|---|---|
| glm-5.3-flash | 51/51 | 36/36 | 3.1 / 5.2 / 7.5 s | 346 | 0.26 |
| **deepseek-v4.1-flash** | 51/51 | 36/36 | **0.8 / 1.1 / 1.3 s** | 185 | 0.40 |
| minimax-m3 | 50/51 (read a serial "48-AXQ-209" as "…-2009") | 36/36 | 3.5 / 12.8 / 24.3 s | 179 | 1.02 |
| **minimax-m3.1-flash** | 51/51 | 36/36 | 2.3 / 3.8 / 4.8 s | 186 | **0.23** |

All four reported the blank image as blank and invented nothing. These images did not separate the models on
accuracy; speed and steadiness did.

**Arbitrator** (16 cases × 3 runs = 48 per arm; reasoning off on both, as RAICA runs it):

| | glm-5.3-flash | **deepseek-v4.1-flash** |
|---|---|---|
| Replies RAICA's parser could read | 45/48 | **48/48** |
| Task verdicts right | 108/114 | **111/114** |
| Cases fully right — original key / revised key (below) | 42/48 / 42/48 | 45/48 / **48/48** |
| Retry instructions given for every BAD verdict | yes | yes |
| Time median / p90 | 4.1 / 6.0 s | **0.7 / 1.0 s** |

The two cases where they differ, each the same in all 3 runs:
- **stale_news** (asked for the latest news, got 2021 articles): glm said GOOD; deepseek said BAD, stale data.
- **partial_cities** (weather asked for 3 cities, 1 returned): both saw the missing cities, but RAICA could not parse
  glm's reply (3.4–4.4k characters) in any run, so the verdict would be lost. deepseek's parsed every time, marking the
  call that worked GOOD and listing the two missing cities as missing tools. The case was keyed BAD before the run;
  that is how RAICA's arbitrator is designed to report a partial result, so the key was revised after reading the
  replies — both scores are shown.

**Cost — an ESTIMATE, tokens not recorded for this lane.** Live made 51 arbitrator calls on 2026-10-21..23 (11–28 a
day). The prompt is ~14k characters (≈4–5k tokens) at 0.30 vs 0.15 $/M input; deepseek's replies were about a third of
glm's length (median 715 vs 2,147 characters) at 1.20 vs 0.50 $/M output. That is under a tenth of a cent more per
call — well under a dollar a month at live's volume.

**Decision (owner, 2026-10-24, RAICA v1.0.0.343):** arbitrator and vision → deepseek-v4.1-flash; vision fallback →
minimax-m3.1-flash (a different model family from the primary, which is what a fallback is for). glm-5.3-flash is no
longer selected for any lane. **Checked on live after the switch:** the arbitrator answered a real Ask request in
0.81 s and RAICA parsed it.

**Limits.** Synthetic images and hand-built arbitrator cases, not real traffic; 3 runs per case; one day, so nothing
about busy hours. The first scoring had two scorer bugs, both fixed in the committed harness and checked by hand: the
date in RAICA's report wrapper failed the "blank" case for every model, and an order check read only first mentions.
An earlier run made 0 model calls (the vision tool needs the main thread) and was discarded.

## 5. Not in the written record

- **MiniMax and Kimi as tool/synthesis models.** The owner reports trialling minimax-* and kimi-* for
  quality vs savings during RAICA development, with the same conclusion as above. RAICA's records hold
  measured results for these models only in **vision** lanes (e.g. minimax-m3 vision fallback 9/9 and 3/3,
  v1.0.0.324; kimi-k2.5 retired 2026-07-31, SI-095) — not for tool calling or synthesis.
- **deepseek-v4-pro's input tokens** in the 4.1 comparison (only output was recorded).

## 6. Open caveat — the tool comparisons predate SI-102

`CHANGELOG_v1.0.0.328.md` / SI-102 (2026-09-25): from v1.0.0.1 until v1.0.0.328 the Ollama provider
double-wrapped every tool definition, so **every Ollama-served tool model saw no tool schemas** and worked
only from tool names mentioned in the system prompt. §4.1–4.3 were measured under that condition (§4.4 ran
on DeepInfra, which received the schemas correctly). With schemas visible, tool-call input rose from
~17k to ~26–29k tokens per call.

The re-run recommended in SI-102 — `tests/integration/run_tool_model_eval_live.py --arms
deepseek-v4-pro:cloud --runs 1`, compared with the 2026-09-25 rows — **has not been run** (no record of it
through v1.0.0.334). Until it is, the ranking in §4.1–4.3 stands on measurements taken with that defect
present. It applied to every arm equally, so the comparison was fair, but absolute accuracy and token
figures may differ today.

## 7. When to revisit

- Ollama changes a price in §3, or a new model appears in a lane's price band.
- A cheaper candidate is proposed: run it through `run_tool_model_eval_live.py` (tool lane),
  `run_vision_arbitrator_eval_live.py` (arbitrator, vision) and the
  `tests/benchmark` suite (DR, citations, vision), against deepseek-v4-pro **on the same cases**, and compare
  accuracy before cost. Write the estimated token spend down first — the account is shared with production.
- The SI-102 re-run (§6) is done.

### Pencilled in (owner, 2026-10-10)

A **level-field re-run**: the same RAICA code (current version, with SI-102's schema fix and the v1.0.0.327
`compute` fixes in place) for every candidate, scored on the same cases, costed at the day's prices — to be
scheduled when there are tokens to spare before a weekly reset. It is warranted: since the §4 measurements
the tool model sees the full tool schemas (input ~17k → ~26–29k tokens per call) and `compute` accepts plain
arithmetic, so both accuracy and token volume can have moved for every model. Write the token estimate down
and agree it with the owner before starting; the account is shared with production.
