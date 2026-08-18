# CHANGELOG v1.0.0.308 — an impossible figure is caught and recomputed *before* the answer

**Date:** 2026-08-18 · **Against:** v1.0.0.307 · **Closes:** SI-073 · **Opens:** SI-074

## The gap this fills

v1.0.0.307 documented that a difference between two columns is arithmetic in `expr`, not a name
in `data`. That is guidance to the tool-calling model. It did nothing about the two questions the
user asked next:

> *"Why did the model NOT check its own calculation, find the error and correct it? Does it have
> the ability to do that?"*

Traced through every checking mechanism on that path:

| mechanism | what it checks | fired here? |
|---|---|---|
| gather-gate | is there *enough data* | shadow-only (`enabled: false`) |
| POST-LLM verifier | were required **delivery** tools run | yes, found nothing missing |
| claims audit | claim-to-source grounding | **Deep Research only** — not this path |
| arbitrator | **error STRINGS** in tool output | yes, result was clean → `GOOD` |
| primary prompt | 78 lines | **no** plausibility rule at all |

**Answer: it had the perception but no ability and no instruction.** It noticed — *"appears to be
expressed in the same units as the mean … suggesting the spread values were multiplied by 100"* —
and, with no way to act and nothing telling it to stop, rationalised instead.

## (1) Directive — primary model

`primary_model_system_prompt.txt` gains an explicit rule: a figure that **cannot be true** is an
error. A difference cannot exceed the numbers it is drawn from; a share cannot exceed 100%; a
count cannot exceed the sample size; a standard deviation cannot exceed the range. Report the
contradiction and omit the figure.

And the prohibition that matters most:

> You are FORBIDDEN to invent a unit conversion, a scaling factor, a "×100", or any other story
> that makes an impossible number admissible. If you find yourself explaining why a figure only
> LOOKS wrong, stop: that is the moment you are about to publish a false result.

## (2) Mechanism — correction *before* generation, not after

`_second_round_tool_calls` runs at **line 11145**; the primary LLM call is at **line 12114**. The
correction round happens ~1,000 lines earlier in the request flow, so this is better than
regenerating a bad answer: **the wrong figure never reaches the answer at all.**

That prompt previously asked only *"what is missing?"*. It now also asks whether what has already
been computed is **possible**, names the specific failure shape — a series NAMED for a quantity
but BOUND to a single raw column, so the arithmetic never happened — and instructs the model to
re-issue the corrected call with every column the calculation needs and the arithmetic in the
expression.

## Verified on the exact failing case

Testcase #2 (Treasury), the prompt that produced the wrong spreads, run twice:

| figure | before | run A | run B | truth |
|---|---|---|---|---|
| 10Y−2Y mean | 4.37752 ✗ | **0.509** | **0.5086** | 0.50860 |
| 10Y−2Y min | 3.97 ✗ | **0.27** | **0.27** | 0.2700 |
| 30Y−3Mo mean | 4.94293 ✗ | **1.197** | **1.1975** | 1.19745 |
| 30Y−3Mo min | 4.64 ✗ | **0.97** | **0.97** | 0.9700 |

No trace of the raw-series values; 0 rejections; charts rendered in both.

## Safety — no over-flagging

The risk of a plausibility rule is that it flags CORRECT figures. Measured on the two testcases
whose answers were already right:

| run | compute calls | rejections | false "impossible" flags | figures |
|---|---|---|---|---|
| USGS | 24 | 0 | **0** | 225 / 5.88 / 0.42 ✓ |
| Phillips | 30 | 0 | **0** | — |

The directive fires on the wrong case and stays silent on the right ones.

Tier-0 **10/10**, unit **671 passed** (same 4 pre-existing), `make smoke` **PASSED**, sync 19/19.

## SI-074 (opened, not done) — the arbitrator should be a semantic judge

The user identified the architecturally correct home for this check, and inspection confirmed why
it did not fire: `arbitrator_validate_tasks` marks a result BAD only when it matches a **hardcoded
error-string list** (`FileNotFoundError`, `TypeError`, `Command failed with code`, …). The
Treasury result was `4.37752 | computed as: np.mean(spread_10y_2y) | over n=157` — clean,
well-formed, no error string → `GOOD`.

It is a **crash detector, not a correctness checker**, and it inspects RESULTS, never the
ARGUMENTS that produced them. Written up as a future line item; see SUSPECTED_ISSUES SI-074.

## Limits, stated plainly

- **n=2** on the failing case. Not a reliability claim; the failure is silent-and-plausible.
- **Prompt work, not a hard gate.** Nothing in code enforces arithmetic plausibility.
- **gather_gate remains `enabled: false, shadow: true`** on live and local — a fuller version of
  this check exists there, built and never switched on. Separate decision.
