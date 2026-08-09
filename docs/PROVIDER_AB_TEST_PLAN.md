# Provider A/B Test Plan — Ollama-cloud vs DeepInfra

**Status:** PRE-REGISTERED, not yet run · **Blocked on:** the SI-010 Ollama weekly
quota reset · **Version at time of writing:** v1.0.0.241

**Pre-registration matters here.** Every metric, threshold and decision rule below is
fixed BEFORE any data is collected. Choosing them afterwards is how a migration gets
justified by whichever numbers happened to look good.

---

## 1. The question

> Ollama-cloud and DeepInfra serve the SAME models. Does routing RAICA through
> DeepInfra change **answer quality**, **cost**, or **latency** — and by how much?

Not "is DeepInfra good" but "is the transport swap neutral". Anything that changes
must be attributable to the transport, which is why §2 exists.

## 2. What A and B are — and the confounds that would destroy the result

| | **A (control)** | **B (treatment)** |
|---|---|---|
| transport | Ollama-cloud (`127.0.0.1:11434`) | DeepInfra (`api.deepinfra.com/v1/openai`) |
| primary | `deepseek-v4-pro:cloud` | `deepseek-ai/DeepSeek-V4-Pro` |
| tool_calling / arbitrator | `glm-5.2:cloud` | `zai-org/GLM-5.2` |
| vision (+fallback) | `minimax-m3` / `kimi-k2.6` | `MiniMax-M3` / `Kimi-K2.6` |
| DR light / heavy | `v4-flash` / `v4-pro` | `V4-Flash` / `V4-Pro` |
| **everything else** | **identical** | **identical** |

Switch between them with `./config_server_cli.py convert --to ollama|deepinfra`, then
restart. Same code (v1.0.0.241+), same prompts, same tool catalogue, same caps.

### Confounds, and what is done about each

| # | confound | why it would ruin the result | control |
|---|---|---|---|
| C1 | **Model substitution** | provider AND model both change → a difference cannot be attributed. This already happened once: swapping the DR heavy model manufactured a truncation ceiling that did not exist | `convert` refuses to substitute; §2 table is same-model throughout. **Verify with `doctor --probe` on both sides before starting.** |
| C2 | **Live web drift** | DR gathers from the live web. The same query 20 minutes apart returns different sources, so a quality delta may be the internet changing, not the provider | **INTERLEAVE**: A1,B1,A2,B2,A3,B3 — never AAA then BBB. Time-drift then hits both arms equally. Record the wall-clock of each run. |
| C3 | **Stochasticity** | one run of a stochastic system is not evidence | **n=3 per case per arm**, report pass RATE and spread, never a single value |
| C4 | **Same weights?** | `deepseek-v4-pro:cloud` and `DeepSeek-V4-Pro` are *assumed* to be the same weights/quantisation. **This is UNVERIFIED** | Treat as a stated assumption, not a fact. If quality differs beyond threshold, this is a candidate explanation and must be investigated before blaming transport. |
| C5 | **Prompt caching** | DeepInfra bills cached input at $0.14/M vs $0.75/M and caching depends on repetition. Repeated identical A/B runs inflate B's cache-hit rate above real traffic | Report cached vs uncached tokens SEPARATELY. Compute cost both with and without cache credit. |
| C6 | **Quota re-exhaustion** | if Ollama 429s mid-test, A-side runs silently degrade | Run `doctor --probe` between every A run. Abort and record if any 429 appears. |
| C7 | **Cost is not comparable in kind** | DeepInfra is per-token; Ollama-cloud is a subscription | Do NOT report a single "cost" number. Report **DeepInfra $ actual** and **tokens consumed on both**, then a $/query for DeepInfra and quota-consumption for Ollama. |

---

## 3. Test cases

Ten cases: 6 non-DR, 4 DR. Each run **3×** per arm, interleaved = **60 runs**.

### Non-DR (exercises primary + tool_calling + arbitrator + vision)

| id | prompt | what it tests | objective check |
|---|---|---|---|
| N1 | "What is the capital of Japan? One sentence." | primary, no tools | contains "Tokyo" |
| N2 | "What is NVDA trading at right now?" | single-tool selection + execution | `get_stock_and_company_data` called; a price appears; price within ±5% of a reference pulled at run time |
| N3 | "Give me a full financial analysis of Tesla — fundamentals, news, sentiment." | multi-tool + arg precision | ≥2 tools; includes `comprehensive_stock_analyzer` OR `get_stock_and_company_data` with `detailed=true` |
| N4 | "Hello! How are you today?" | **abstention** | **0 tool calls** (a tool call here is a false positive) |
| N5 | "Do NOT search the web. From your own knowledge, what does HTTP 404 mean?" | adversarial instruction | 0 tool calls; answer correct |
| N6 | *(image)* "Transcribe the text in this image exactly." | vision lane | exact string match on a generated fixture |

### DR (exercises the full pipeline: decompose → plan → gather → synthesise → verify → deliver)

| id | prompt | what it tests | notes |
|---|---|---|---|
| D1 | "Full research report on PLUG (Plug Power) — financials, analyst view, risks, peers, recent news." | the heavy path | **direct comparison to 2026-08-09 B-side baselines** (3 runs already captured) |
| D2 | "What is the current scientific consensus on CRISPR off-target effects? Cite peer-reviewed sources." | academic path, `published_papers_search` | stable topic → lower web drift than D1 |
| D3 | "Compare US and China GDP growth over the last 10 years and chart it." | data-charts + compare_datasets | chart markers are objectively countable |
| D4 | "Research the outlook for hydrogen fuel-cell companies and **email me the report as a PDF**." | **delivery actions** | tests `pipeline.py` decompose `actions` — the SI-015 site that silently drops delivery |

**Why D1 is first:** three B-side runs already exist from 2026-08-09 with full metrics
(evidence items, URLs, chart markers, truncations, timings). Any A-side result can be
sanity-checked against them immediately.

---

## 4. Metrics — all objective, none by eye

### Quality

| metric | how measured | source |
|---|---|---|
| tool-selection accuracy | expected tool called? | `TOOLS EXECUTED:` in log |
| false-positive tool calls | tools called on N4/N5 | log; **any >0 is a failure** |
| answer correctness | substring / numeric tolerance per case | response body |
| citation count | `[Title](URL)` occurrences | response body |
| **citation liveness** | HTTP status of each cited URL | `research/link_liveness.py` |
| **groundedness** | % cited URLs classed `real` | `📊 retrieval-audit` |
| chart completeness | `final_draft` vs `required` | `🖼️🔎 synth chart-markers (final)` |
| chart repair passes | count | `🖼️🩹 chart-completeness repair` |
| **truncation events** | count + which lane | `✂️ TRUNCATED` (v1.0.0.237) |
| DR evidence volume | items, unique URLs, chars | `🧭 Deep research complete` |
| DR rounds | count | `🔎 Round N` |
| arbitrator schema compliance | parses + `tasks[]` present | arbitrator response |
| delivery success (D4) | email actually sent | `📦 delivery` + inbox check |

### Cost

| metric | A (Ollama) | B (DeepInfra) |
|---|---|---|
| input tokens | from provider response `usage` | `usage.prompt_tokens` |
| cached input tokens | n/a | reported separately (C5) |
| output tokens | `usage` | `usage.completion_tokens` |
| **$ actual** | n/a (subscription) | `usage.estimated_cost`, reconciled against the usage page |
| quota consumption | tokens vs weekly limit | n/a |

> **Do not extrapolate cost from logged char counts.** RAICA's `~N tokens` log line is
> `chars ÷ 4`, not tokenisation. A cost estimate built on it came in **30% under**
> actual on 2026-08-09. Use provider `usage` only.

### Latency

Wall-clock per run, plus DR stage timings from `🧭 Deep research complete`
(plan / gather / total).

---

## 5. Decision rules — fixed in advance

| outcome | rule |
|---|---|
| **Quality regression — BLOCK migration** | any of: tool-selection accuracy drops >10pp; ANY false-positive tool call on N4/N5 where the other arm has none; citation liveness drops >10pp; chart completeness drops at all; a truncation appears on one arm only |
| **Quality neutral** | all quality metrics within ±10pp, no new truncations, no delivery failures |
| **Latency** | report only. A >2× slowdown is a flag, not a blocker |
| **Cost** | report only — it is a business decision, not a correctness one |
| **Inconclusive** | any C1/C4/C6 violation detected → discard the affected runs and re-run |

**A quality regression blocks migration regardless of cost saving.** Tool selection
and citation grounding are the two surfaces where a silent degradation does the most
damage, and both are measurable here.

---

## 6. Procedure

```
0. PRE-FLIGHT
   ./config_server_cli.py doctor --probe          # A-side must be 429-free (SI-010)
   record: date, RAICA version, git SHA, DeepInfra balance
   generate the N6 image fixture; pull the N2 reference price

1. For case in [N1..N6, D1..D4]:
     For rep in 1..3:
       - convert --to ollama;    restart; run case; capture   (A)
       - convert --to deepinfra; restart; run case; capture   (B)
     # INTERLEAVED per rep (C2), NOT blocked by arm

2. AFTER EVERY A RUN: doctor --probe -> abort on 429 (C6)

3. Capture per run: full response body, server log slice, provider usage,
   wall-clock, and the metric set in §4

4. Reconcile B-side $ against the DeepInfra usage page before reporting (it lags)
```

**Estimated B-side cost:** 6 non-DR × 3 ≈ $0.30 + 4 DR × 3 × ~$0.35 ≈ $4.20 →
**~$4.50**, against a $4.03 remaining balance. **Fund before starting, or cut DR to
2 reps (~$2.80).** A-side consumes Ollama quota only.

**Time:** ~30 restarts + 60 runs; DR runs are 5–12 min each → **4–6 hours**.

---

## 6b. Freeze window — do not change finance output during the A/B

`docs/PROJECTION_GROWTH_BLEND_SCOPE.md` is signed off but **deferred until this A/B
completes**. It changes the growth numbers the synthesising LLM reasons over (CROX
earnings 20.0% → 7.1%), so landing it mid-experiment would make a quality delta
attributable to either the provider or that change — inseparably. Nothing that alters
model inputs or finance calculations lands until the A/B is reported.

## 7. Known limitations — stated up front

1. **C4 is unresolved.** Whether the two providers serve identical weights/quantisation
   is unverified and probably unverifiable from outside. A quality delta may be a
   serving difference, not a transport one.
2. **Web drift is mitigated, not eliminated.** Interleaving equalises it in
   expectation; it still adds variance. D2 (stable academic topic) is the least
   affected case and should be weighted accordingly.
3. **n=3 is small.** It distinguishes "always/never" from "sometimes"; it does not
   support fine statistical claims. A 10pp threshold is deliberately coarse for this
   reason.
4. **Ollama quota may not survive the full run.** If it re-exhausts, the A arm
   truncates and the comparison is partial — record how far it got rather than
   filling gaps.
5. **The 2026-08-09 B-side baselines used one substituted model** (GLM-5.2 as DR
   heavy) for runs 1 and 2. Only **run 3** is like-for-like and comparable. Runs 1–2
   are useful for the truncation story, not for quality comparison.
