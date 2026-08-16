# CHANGELOG v1.0.0.293 — SI-052 output guard, SI-054 smoke resilience

**Date:** 2026-08-16 · **Against:** v1.0.0.292 · **Closes:** SI-052, SI-054

## SI-052 — a degenerate output run is now STOPPED, not merely survived

One synthesis run streamed **2,924,215 characters that were 99.8% whitespace** — 2,152 runs
of 200+ consecutive spaces, longest 2,862 — around 6,393 characters of real content. With no
chart marker available the model hand-drew an ASCII chart and the padding ran away.

**Nothing in RAICA stopped it.** The run ended only because the vendor's ceiling fired
(`finish_reason=length` at 32,768 tokens), so a *higher* cap would have produced a *larger*
runaway, and a different trigger would reproduce it. Fixing the cause (SI-051's missing
marker) removed that trigger but not the class.

`llm_providers/openai.py::generate_stream` now tracks two counters and `break`s on either —
those are the lines that make an unbounded run impossible:

- **consecutive-whitespace run** > 400
- **total emitted characters** > 400,000

Both are reported to the caller in-band (`_[output stopped: …]_`) and logged loudly, because
a silent truncation is its own defect.

### Thresholds derived from the corpus, not chosen

| | max chars | longest whitespace run |
|---|---|---|
| legitimate answers | 7,040 (72,147 in benchmark) | **18** |
| the runaway | 2,924,215 | **2,862** |

400 sits **22× above** the largest real run and **7× below** the runaway. 400,000 chars is
~5.5× the largest legitimate answer ever measured. Deliberately far from the legitimate side:
a guard that fires on real output would be worse than no guard. Overridable per deployment
(`stream_max_chars`, `stream_ws_run_limit`); the code default is protective on purpose,
because a safety limit that vanishes when a config key is missing is not a safety limit.

## SI-054 — the mandatory smoke gate no longer fails a deploy on a cold-start timeout

`make smoke` classified `asyncio.TimeoutError` as a CODE defect:

```
SMOKE FAILED — 1 CODE defect(s); a tool crashes on invocation:
   - get_news_summaries: RAISED TimeoutError
```

Re-run immediately, no code change: **PASSED**, 4,887 chars. Invoked directly with the gate's
exact arguments three times: **2.5s / 0.5s / 0.4s**. The first, uncached fetch is the slow one
against a 30s budget — not a crash, which is the only thing this gate claims to detect.

The cost runs both ways, and the second way is worse: a spurious CODE-FAIL blocks a good
deploy, and a gate people learn to dismiss as "just flaky" is a gate whose REAL failures get
waved through — exactly how `search_web` stayed dead for six days.

**Fix:** retry **exactly once**, on timeout only. A second timeout is still a failure, but is
reported as `TIMED OUT twice at 30s each` rather than `RAISED TimeoutError`, so nobody hunts
for a crash that does not exist. A pass that needed the retry is disclosed
(`passed only on RETRY after a timeout`), so a flaky tool never looks clean. The timeout was
**not** widened — widening until nothing fails is how a gate stops meaning anything.

## Verification

- `tests/unit/test_stream_output_guard.py` — 6 tests, **3 fail on pre-fix code**. Includes a
  guard-against-the-guard: a legitimate answer containing an 18-char whitespace run passes
  through byte-identical.
- `tests/unit/test_smoke_timeout_resilience.py` — 4 tests, **all 4 fail on pre-fix code**,
  including a behavioural check that one timeout recovers and two do not.
- `make smoke` **PASSED** 6/6. Tier-0 **10/10**. Unit **572 passed** (4 pre-existing
  unchanged). Version sync 5/5.

## Also corrected in this release

The Ollama A/B runbook cited GLM-5.2's reasoning tokens on DeepInfra as an OPEN risk. That was
wrong — it was fixed in v1.0.0.285. Verified by inspecting the actual wire payload:

```
lane config think: False
ON THE WIRE     -> {'max_tokens': 8192, 'chat_template_kwargs': {'enable_thinking': False}}
```

Reasoning is suppressed on DeepInfra exactly as `think: false` does on Ollama. What remains is
ordinary prudence about vendor differences, not a known defect.

## Still open

SI-053 (latent column-less reference form). Whether S4-at-1-rep brings a Tier-1 run under the
throttle threshold remains unproven — the per-scenario instrumentation answers it on the first
Ollama run.
