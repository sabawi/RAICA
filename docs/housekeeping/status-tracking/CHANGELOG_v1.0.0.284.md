# CHANGELOG v1.0.0.284

**Date:** 2026-08-15
**Focus:** SI-046 — the distribution family must be chosen from the measured shape.

## The problem

A request for "the appropriate probability distribution curve" produced a **Normal PDF overlaid on
manifestly exponential data**. The user never mentioned Normal.

`plot_data` has no distribution fitting — it plots what it is handed, so the Gaussian was the
model's choice. Which model matters: **glm-5.2** (tool-calling) chose it at gather time, while
**deepseek-v4-pro** (synthesis) wrote an answer that correctly identified Gutenberg-Richter and
called the normal fit poor. The answer contradicting its own chart is structural — by synthesis
time the chart is already rendered.

## What was measured first

The obvious fix — compute the shape, feed it back, then choose — **is what already happened**. At
the moment of choice the selector held:

```
np.size=225 · np.mean=5.88 · np.median=5.80        <- skew visible
np.min=5.5 · np.max=7.8                            <- long tail visible
np.percentile(5) · np.percentile(95)
np.histogram(mag, bins=15)[0] = [74,62,17,32,11,8,5,6,0,2,1,2,2,2,1]   <- monotone decay
np.mean(mag >= 6.5 / 7.0 / 7.5)
```

It had the shape and chose a bell curve anyway, because **nothing in any prompt layer connected
those numbers to the choice**. All chart guidance answered provenance — *where do the numbers come
from* — and never modelling.

## The directive

Added to both surfaces the tool-calling model reads:

1. **Section J of `pre_tool_model_system_prompt.txt`** — "A FITTED CURVE IS A CLAIM ABOUT THE DATA,
   NOT DECORATION": measure the shape before fitting one; let the measurements rule out families;
   say which family and why in the title or series label; if no family is defensible, plot the
   observed data alone.
2. **The per-round selector prompt** (built in code) — a compressed clause. This is the prompt that
   was actually live when `plot_data` was chosen on production; the system prompt alone would have
   missed that round.

### No lookup table

No subject is mapped to any distribution. The rules are stated as **contradictions between a
measurement and a kind of family** — a mode at the edge of the range, a mean displaced from the
median, counts decaying monotonically from the first bin, extremes a family would give almost no
mass to. Those criteria hold for lognormal, Poisson or power-law data equally, and the model names
the family, not the prompt.

A test **fails** if any family name (gaussian, gutenberg, lognormal, poisson, weibull, pareto)
appears in the tool-selection prompt — once "earthquakes → Gutenberg-Richter" exists, the next
dataset is wrong and nobody notices.

## Audits

| Check | Result |
|---|---|
| `_ARTIFACT_MARKER_RELAY` | No conflict — governs *describing* a chart; this governs *choosing* one |
| `Ask.yaml` DERIVED FIGURES | Reinforces — "measure the shape first" is an instance of it |
| Section J provenance rules | Intact, untouched |
| **Code gates** | Every diagnostic RUN through the real `compute` evaluator: mean−median gap, hand-rolled skewness (numpy has no `skew`), modal bin, tail decay, extremes vs p95 — all pass |

Tool *descriptions* were deliberately not touched: `CRITICAL MULTI-TOOL CALLING PROTECTION` warns
that editing them breaks multi-tool calling.

## This does not close SI-046

It tests **candidate cause (1)** only — *it was never told*. Candidate **(2)** — glm-5.2 will not
make this judgement regardless — remains live.

**The experiment:** re-run the same prompt **≥3×** (selection is stochastic). If it still fits a
Gaussian while holding both the shape *and* this instruction, the answer is (2), and the decision
must move to a model that reasons about the data — not a fourth draft of the wording. Verify on a
**non-earthquake** dataset before believing it generalises.

## Tests

`tests/unit/test_distribution_choice_directive.py` (5): directive present in both surfaces, stated
as evidence criteria rather than a recipe, no family names introduced, and every diagnostic it asks
for is computable through the restricted evaluator.

Suite: **506 passed**, 4 pre-existing failures unchanged. Smoke 6/6.

## Files

- `pre_tool_model_system_prompt.txt` — Section J directive
- `fastapi_server_complete.py` — per-round selector clause
- `tests/unit/test_distribution_choice_directive.py` — new
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-046
- `version.py`, `config/logging_config.json`, `README.md` — 1.0.0.284
