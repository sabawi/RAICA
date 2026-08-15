# RAICA — Gating the non-DR answer on GATHERED DATA (porting the DR assessor) — Design

**Status:** PHASE 0 shipped v1.0.0.270 · **PHASE 1 (enforce) shipped v1.0.0.274**, off by default
(operator opt-in via `RAICA_GATHER_GATE_SHADOW=false`).
**Drafted:** 2026-08-14
**Scope:** the non-DR tool path in `fastapi_server_complete.py` (`llama_stream`). Deep Research is
untouched — it already does this correctly and is the model being copied.
**Risk class:** MEDIUM-HIGH — it changes when the answer is allowed to be written.

---

## 1. The flaw, named precisely

The non-DR path is a **fixed-length pipeline dressed as an agent loop**. Nothing asks whether the
data the answer requires is actually in hand before synthesis proceeds.

Production, 2026-08-14, the request *"what was the average 10-year yield in 2025, and nothing
else"*:

```
03:33:20  selection 1 : ['search_datasets']          (catalog metadata)
03:33:23  SECOND ROUND: ['search_web','search_datasets']   <- round budget spent HERE
03:33:33  selection   : ['lookup_website']            <- the CSV finally arrives
          (no further selection — the counter was already exhausted)
```

**No selector ever saw the CSV.** `compute` was not rejected and not overlooked — it was
unreachable. The answer quoted a figure from a web article: **4.24%** against a true **4.2932%**.

An earlier run of the same prompt failed differently: `compute` was reached, rejected 4/4, and the
answer asserted *"computed as the arithmetic mean"* anyway — right by luck at 4.30%.

Two failures, one root cause: **the loop terminates on a COUNT, not on a CONDITION.**

### Why it stayed hidden

The Treasury and USGS prompts fetch their data in phase 1, so the single extra round landed exactly
where it was useful and everything worked (404/404 rows, exact figures). The flaw only appears when
phase 1 returns something *other* than the data — a catalog lookup, a failed fetch, a search that
finds a landing page. That is not an edge case; it is a routine shape.

## 2. What the DR path already does, and the non-DR path does not

`research/engine.py` is a genuine condition-gated loop:

| | Deep Research | non-DR (today) |
|---|---|---|
| after tools run | `_assess()` (`:709`) returns `sufficient` / `needs_more` + `next_queries` | nothing |
| loop control | `while True` with `assessment` (`:832`) | `if max_extra_rounds > 0` — a counter (`:10693`) |
| premature stop | `min_rounds` floor **overrides** a "sufficient" verdict (`:440`) | n/a |
| termination | `stop_reason = sufficient / max_rounds / wall_clock / no_further_queries` | count exhausted |
| gate on synthesis | evidence adequacy | **none** |

**The correct pattern already exists in this repository, on a path traced in the same session.**
The second round shipped in v1.0.0.262 bolted a counter onto the ungated path instead of porting
the gate. This design corrects that.

## 3. Design — one new stage, reusing what exists

### 3.1 The gate

After each tool batch completes, ask the tool-calling model ONE question with a small structured
answer:

```
Given the user's request and WHAT HAS BEEN GATHERED SO FAR (schema previews, not contents),
can the request be answered accurately and completely now?

{"status": "sufficient" | "needs_more",
 "missing": "<one line: what is absent>",
 "next_tools": [ <tool calls, same shape as any other selection> ]}
```

`status: needs_more` → execute `next_tools`, loop. `sufficient` → proceed to phase 2 and synthesis.

This is deliberately the **same shape** as `_assess` (`engine.py:709`) so the two paths can be read
against each other, and so a future consolidation is a merge rather than a rewrite.

### 3.2 What it is shown

`_describe_round_results()` already produces exactly the right input: reference ids, column names,
row counts, a few sample rows — 579 chars for a 20,730-char CSV. The gate sees **what exists**, not
its contents, which is what "do I have what I need?" requires and keeps the prompt small.

### 3.3 Where it hooks

`fastapi_server_complete.py`, replacing the counter at `:10693`:

```
:10174  generate_tools            (selection 1)
:10534  PHASE 1 SEARCH            (execute)
        ┌─► GATHER GATE  ── needs_more ──► execute next_tools ──┐   (loop, bounded)
        └───────────────── sufficient ─────────────────────────►┘
:10734  PHASE 2 SMART             (delivery tools — unchanged, still last)
:11399  verifier → synthesis
```

Phase 2 stays after the loop: delivery must attach the finished content, not an intermediate.

### 3.4 Bounds — the damper, stated as lines of code

A loop that can request more tools is a control loop; an undamped one oscillates. Every bound below
must exist before this ships:

| bound | value | why |
|---|---|---|
| `max_gather_rounds` | 3 | hard ceiling; the loop cannot run longer whatever the verdict |
| `wall_clock_seconds` | 90 | mirrors DR's `wall_clock`; a slow tool cannot hold a reply forever |
| dedup by (tool, args) | reuse `_tool_call_key()` | a repeated verdict cannot re-run the same fetch |
| no-progress stop | if a round adds **no new reference id**, stop | the exact anti-oscillation rule the counter lacked |
| whitelist re-check | reuse existing filter | a gate round must never widen a bot's `allowed_tools` |
| fail-open | any error → today's behaviour | the gate must not be able to lose an answer |

`min_rounds` is deliberately **NOT** ported: DR needs a floor because breadth matters there; a
single-figure question is legitimately answerable after one round.

## 4. Observability — required at commit, not later

SI-021: the DR gap-assessment loop was **dead for seven builds** behind a catch-all, reporting
success while `_assess` raised `AttributeError` every time. That is the same class of code, so it
ships with its own evidence:

- `🚪 gather-gate: round=N verdict=<sufficient|needs_more> missing=<…> next=[tools] refs=<ids>`
  on **every** round, including the first `sufficient` — silence must never be the success signal.
- `🚪 gather-gate: STOPPED reason=<sufficient|max_rounds|wall_clock|no_progress|error>` once per
  request, so the stop reason is always attributable.
- A counter of rounds actually executed, so "the gate is live" is a fact in the log rather than an
  assumption.

**Acceptance:** a shadow run must show a `needs_more` verdict on the failing prompt above. If the
gate only ever says `sufficient`, it is inert and must not be enabled.

## 5. Rollout

1. **Phase 0 — shadow.** Gate runs, logs its verdict, and **changes nothing**. Measure on real
   traffic: how often `needs_more`, on what shapes, and would it have fixed the 4.24% run.
2. **Phase 1 — enforce**, config-gated, default off, after the shadow numbers are read.
3. **Phase 2 — retire the counter** (`max_extra_rounds`) once the gate supersedes it. Two
   overlapping mechanisms is worse than either.

```yaml
tool_calling:
  gather_gate:
    enabled: false
    shadow: true
    max_gather_rounds: 3
    wall_clock_seconds: 90
```

## 6. Risks, and what would falsify this design

- **The gate always says `sufficient`.** Most likely failure — an LLM asked "is this enough?" tends
  to agree. Falsified by the Phase-0 shadow: if it never says `needs_more` on the prompt that
  motivated it, the design is wrong, not the prompt.
- **Latency.** One extra model call per round, up to 3. Measure in shadow before enforcing;
  the current second round costs ~2–5s.
- **Oscillation.** Two tools that each make the other look necessary. The no-progress rule is the
  specific defence; name the line that makes round N+1 impossible.
- **It fixes the wrong layer.** If the model reliably picks web-article answers over computing even
  *with* the data in front of it, the gate will dutifully report `sufficient` and the real problem
  is tool selection. The shadow numbers distinguish these; nothing else does.
- **LLM-Policy Gate.** The verdict is a policy judgement in language, no keyword lists. But it must
  be checked against the directives the same model already receives — in particular the whitelist,
  which the gate must not appear to widen.

## 7. What this does NOT fix

- A model that has the data and still quotes a secondary source. That is tool selection.
- `compute` rejections (v1.0.0.267–269 addressed those separately).
- SI-038's fabricated-marker hole, which is output-side.

## 8. Open questions for sign-off

1. **Shadow first, or straight to enforce behind a flag?** Shadow costs a release; enforcing early
   risks a latency regression on every tool request.
2. **Which model runs the gate** — the tool-calling model (glm-5.2, already loaded, cheap) or the
   primary? The tool model chose search-over-compute in the failing run, which is an argument for
   the primary, and against it on cost.
3. **Should the gate be allowed to say "answer without it"?** A tool that keeps failing should end
   in an honest "could not retrieve", not an infinite `needs_more`. Probably a third verdict:
   `insufficient_and_unobtainable`.
4. **Does DR keep its own assessor, or do both paths converge on one?** Convergence is the right
   long-term shape; doing it now doubles the blast radius.


---

## 9. Phase 1 result (v1.0.0.274)

Authorised by production evidence: asked for the 2025 average 10-year yield, the gate returned
`needs_more`, was ignored because shadow was on, and the answer stated **4.33%** against a true
**4.2932%** with `compute` never called. The mechanism that would have caught it was already
deployed and deliberately muzzled.

Enforcing, on the identical request:

```
round=1  needs_more  "10-year Treasury yield data for 2025"          -> executing ['lookup_website']
round=2  needs_more  "the average must be calculated from the ..."   -> executing ['compute']
round=3  sufficient                                                   -> STOPPED reason=sufficient
```

Answer: **"4.29%, computed as the arithmetic mean over 249 daily observations"** — correct on both
the value and the count.

**Round 2 is the round a counter can never reach.** The data was already in hand; what was missing
was the CALCULATION. That is the precise state that produced 4.24%, 4.33%, and a "computed as the
arithmetic mean" claim with no computation behind it.

### Division of labour

The gate decides WHETHER more is needed; the existing second-round selector decides WHAT to call.
Whitelist filtering, dedup and reference resolution are therefore reused rather than duplicated.

### Dampers, all live

| bound | behaviour |
|---|---|
| `max_gather_rounds` | 3 — used all three above and stopped on `sufficient`, not the cap |
| `wall_clock_seconds` | 90 |
| dedup | by name + canonicalised arguments |
| whitelist | re-checked every round — a gate round can never widen a bot's `allowed_tools` |
| **no-progress** | a round adding no new reference id ends the loop — the line that makes oscillation impossible |
| fail-open | any error returns to prior behaviour |

### What was removed

`audit_uncomputed_claim` and its `computed as|over n=` regex. It matched the ANSWER to decide
whether a calculation had been claimed — a pattern deciding MEANING, which the Cardinal Rule
forbids — and it had already failed: production wrote "is calculated from the complete set of 250
daily observations" and the audit stayed silent. Whether a derived figure is missing is structural,
and the gate judges it in language. A test pins the regex out of the codebase.


## 10. SI-041(b) — the gate also judges requested ARTIFACTS (v1.0.0.277)

§1-§9 framed the gate around DATA and DERIVED FIGURES: is the data here, and has the figure the
user asked for actually been calculated? A production request exposed a third thing the same test
applies to.

**The failure.** A USGS statistics request asked for a plot. The answer said *"The plot below shows
the frequency of events by magnitude"*. There was no `plot_data` call and no `[[chart:…]]` marker
anywhere in the run. Not an invented marker (SI-038) — prose narrating a visual that does not
exist.

**The trace.** Availability was never the issue: `plot_data` is registered, exposed to the LLM
among 35 tools, callable, and whitelisted in NewX `Ask.yaml`. The chain broke at SELECTION, and it
took two independent failures:

| Link | State | Why it did not stop the answer |
|---|---|---|
| Directive | present | `_ARTIFACT_MARKER_RELAY` already forbids inventing a visual. It was **ignored** — same shape as the "computed as" fabrication that motivated §1. |
| Gate | present, silent | It judged only data and derived figures, so `sufficient` was an **honest** verdict with no chart in hand. |

**The fix.** Extend the gate's judgement to anything the request asks the system to PRODUCE — a
chart, plot, graph or rendered file is not in hand unless a tool produced it and its marker appears
in the gathered output. This is the §1 argument applied to artifacts: *a directive can be ignored;
a gate that withholds `sufficient` cannot.* The loop then does the rest, unchanged — `needs_more`
re-runs the existing selector, which can pick `plot_data`.

**Damper (this is a control loop).** The gate now DEMANDS an artifact, so it must be able to SEE
one, or it would re-demand every round and re-render the same chart to `max_gather_rounds`. It can:
`plot_data` returns short prose, so `describe_reference` renders it in full and the `[[chart:…]]`
marker reaches the next prompt. Verified empirically and pinned by a named test; `no_progress`
backstops it.

**No keywords.** Detecting "the answer described a chart" by phrase-matching would fail on "the
graphic above", on another language, and on the next phrasing — and is exactly what the standing
directive forbids. The gate states the rule; the LLM applies it. A test scans the gate's executable
lines and fails if a phrase matcher or meaning-detecting regex appears.

**Consistency with the relay.** They sequence rather than conflict: the gate says *go make it*
during gathering; the relay says *if it still does not exist, describe the data and say a chart
was not available* at synthesis.

**Residue (open).** This makes the chart EXIST when one can be made. It does NOT cover the model
narrating a visual after the gate exhausts its rounds — that still rests on the relay directive
alone, which is what failed here. The right home is a post-answer LLM-judged fabrication check
beside the `nondr-citation` shadow audit. Not built.
