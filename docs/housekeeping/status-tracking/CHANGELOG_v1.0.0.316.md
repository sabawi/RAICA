# CHANGELOG v1.0.0.316 — an empty evidence block is an ERROR, not "no tools executed"

**Date:** 2026-08-21 · **Against:** v1.0.0.315 · **Closes (partially):** SI-093 · **Confirms:** SI-086

Shipped in response to a live production incident, not a test finding.

---

## What happened

On **2026-08-21 at 04:41 UTC** the `@raicaMiddleEast` bot published **eight fabricated news items**
to the live NewX feed — named towns (Kfar Tibnit, Haret Hreik), specific casualty figures, named
officials — dated **2025-07-09/11**, thirteen months stale, tagged `#BreakingNews`, with **no
sources**. `"Kfar Tibnit"` appears **zero** times in any `get_news_summaries` result: the specifics
were invented, not retrieved.

Three hours later, replying to a user, the same bot on the same tools produced genuinely current,
well-sourced Aug 20–21 2026 reporting. Two paths, one job, opposite outcomes — the controlled
experiment that located the defect.

## The proximate cause was SI-086 — and this release CONFIRMS that fix

`logs/archive/server_complete_20260821_102123.log`, 04:41:09:

```
BEFORE applying corrected results - tools_results length: 21396
Corrected results length: 1510
preview: ARBITRATOR_ERROR_CORRECTION_FAILED: ... {5: {'error_pattern': 'empty_response', ...
PARSED RESULTS: Generated 0 tool entries
Context: 0 | System: 14728
```

21,396 characters of real news discarded for a 1,510-char failure sentinel. `STARTS WITH SENTINEL:
True`, so the v1.0.0.313 fix — which APPENDS the notice instead of substituting it — would have
preserved the evidence. That fix reached production at 10:21 UTC, **5h40m after this post**.

**This is the first production observation of that failure branch**, which the v1.0.0.313 changelog
recorded as "never verified end-to-end — the guard's log line has never fired." It has now fired,
on real traffic, with exactly the signature the unit tests model. That caveat is closed.

## But fixing SI-086 does not close SI-093

SI-086 preserves results that **exist** when the arbitrator fails. It is one route to an empty
context, not the only one — the trigger here was a tool returning `empty_response`, which is the
rate-limit / timeout / block shape. **If retrieval itself returns nothing, there is nothing to
preserve and the outcome is identical.**

The real defect is what happened next:

```python
if context_block.strip():
    ...
else:
    # If no tools executed, use original context only      <- WRONG for half the cases
    in_prompt = f"PROMPT: {transformed_prompt}"            <- sent anyway, silently
```

Two different situations reached that branch and the code could not tell them apart:

| | |
|---|---|
| (a) no tools were asked for | nothing is missing — normal |
| (b) tools ran and their evidence vanished | an ERROR, handled silently |

The model then received its full mandate — *"You are a Middle East news correspondent. Report hard
news: what happened, where, when, who is involved"* — with zero evidence, and filled the vacuum from
training data. That is why every fabricated item clusters near the model's knowledge horizon, and
why the post truthfully admitted "Specific article URLs were not available."

`Context: 0` was logged at `:12274` and **read by nothing** — the system measured the failure and
discarded the measurement.

Same class as **SI-078 / SI-084**: an explicit instruction to produce X, no tool output that can
supply X, so the model invents X. There it minted a fake chart marker; here, war reporting.

## The fix

1. **Distinguish the two cases.** `_evidence_loss_lead(context_block, tools_called)` — a pure, total
   helper, so the condition that published fabricated reporting is testable without standing up the
   streaming path it lives in.
2. **Tell the model the truth.** When tools ran and produced nothing, `_EVIDENCE_UNAVAILABLE_NOTICE`
   is prepended to the context. It states the FACT of the loss and does not classify the request —
   no keyword list, no request-type branching, no per-bot special casing, per the project's
   LLM-policy directive. It explicitly forecloses the disclaimer-and-proceed loophole the failing
   post used:

   > …do not soften this into a caveat attached to content you generated anyway.

3. **Give `Context: 0` a reader.** The condition now logs
   `🚨 EVIDENCE LOST: N tool(s) executed (…) but the context block is EMPTY`.

## Tests

`tests/unit/test_evidence_loss_notice.py` — **8 tests**, including the exact six-tool set from the
04:41 run, whitespace/`None` contexts, and two controls that must stay silent (no tools asked for; a
populated context, as in the 04:36 run that worked). One test asserts the notice contains no
`news`/`chart`/`stock`/`bot` special-casing. The helper and the notice do not exist in the pre-fix
file at all, so the guard is unambiguously new.

## What this does NOT do — read this before relying on it

- **This is a prompt directive, not a guarantee.** The model is told it has no sources and must not
  assert facts. It remains free to ignore that. The layer that holds regardless of model behaviour
  is a **NewX-side refuse-to-post floor** for citation bots carrying zero sources — tracked in
  SI-093 item 3, **not in this release**.
- **Not verified end-to-end.** Unit tests only. Forcing an empty context through the real path needs
  a deliberate harness; the next production rate-limit will be the first real test. Watch for
  `🚨 EVIDENCE LOST` in `logs/server_complete.log`.

## Files changed

| file | change |
|---|---|
| `fastapi_server_complete.py` | `_EVIDENCE_UNAVAILABLE_NOTICE`, `_evidence_loss_lead`, the branch split, the EVIDENCE LOST error log |
| `tests/unit/test_evidence_loss_notice.py` | **NEW** — 8 tests |
| `README.md`, `config/logging_config.json`, `version.py` | version → 1.0.0.316 |
| `SUSPECTED_ISSUES.md` | **SI-093 logged** (P1, CONFIRMED) with the production evidence |

## Breaking changes

None. The notice fires only when tools ran AND the context is empty — a state that previously
produced silent fabrication.

## Dependencies

Unchanged.
