# CHANGELOG — v1.0.0.262

**Date:** 2026-08-14
**Type:** Bug fix (P1) + feature enablement
**Issues:** SI-037 (data-file truncation), SI-036 (second tool round), SI-038 (logged, not fixed)

---

## SI-037 — a data file was cut by a limit written for prose  [FIXED]

**The bug, from the tool's own log:**

```
Content too large (20198 chars), truncating to 10000
2025: tool returned 10,698 chars, 142 lines      <- 2025 has 249 trading days
```

Two truncation layers collided. `_extract_data_content` (SI-028 P1) bounds a data file by BYTES
and discloses the outcome honestly. The call site then ran `_safe_truncate` on the result
**unconditionally** — a 10,000-character prose limit that cuts at a **sentence boundary**, applied
to a CSV.

**Why it mattered.** The true maximum 30Y-10Y spread over 2025-2026 is **0.69, on 09/04/2025** —
inside the discarded rows. Production reported **0.67**, the maximum of what survived. The minimum
(0.18) was in the retained half and came out right, which is what made this look like a rounding
quibble rather than a truncated series. Observation count was reported as 406 against a true 404.

No error, no crash, a confident figure computed over half a table — and nothing downstream could
detect it. Liveness, provenance and citation checks all pass on a partial table.

**Fix:** data-file results (identified by RAICA's own `data_label` marker) bypass the prose
truncator entirely. Both limits moved from hardcoded constants into `llm_config.yaml`
(`lookup_website.max_article_chars` / `max_data_bytes`) per the configuration directive.

**Verified:** the 2025 CSV now arrives at **263 lines / 20,730 chars, marked `(complete)`**, up
from 142 lines. Tests: `tests/unit/test_si037_data_file_truncation.py` (5), failing on pre-fix code
with *"the final row was discarded — an extremum over this is wrong"*.

## SI-036 — second tool-selection round  [MECHANISM SHIPPED, ENABLED]

The non-DR path selected every tool in ONE call made **before any tool ran**
(`fastapi_server_complete.py:9834`, prompt = the user message alone), so a tool whose arguments
depend on another tool's OUTPUT was unreachable by construction. That is why `compute` was never
called on the Treasury request: what to calculate is unknowable until the CSV is fetched.

A second selection round now runs after phase-1 tools return. Guarantees:

- returned names are re-checked against the offered set, so the round **cannot become a bypass** of
  a bot's `allowed_tools` hard gate
- calls already run are dropped (dedup by name + canonicalised arguments)
- **hard cap of exactly one extra round** — the damper; a round that can request more tools is a
  control loop, and an undamped one oscillates
- fail-open: any error returns to today's behaviour
- no selector call at all when there is no prior output

`tool_calling.second_round.enabled: true` (operator decision, 2026-08-14). Selector budgets sized
from measured data — 100,000 chars/tool, since 20,000 would have re-truncated the very 20,730-char
CSV that SI-037 just repaired.

Tests: `tests/unit/test_si036_second_tool_round.py` (18).

## ⚠️ What this release does NOT fix

**`compute` is still not being selected, and derived figures are still wrong.** Measured after both
fixes, with the round enabled and the complete table in view:

| figure | answer | truth |
|---|---|---|
| observations | 406 | **404** |
| min spread | 0.10 (self-refuting: quotes 4.89/4.37, which give 0.52) | **0.18** on 01/13/2025 |
| max spread | 0.67 | **0.69** on 09/04/2025 |

`🔁 SECOND ROUND: no further tools requested` — the selector declines to call `compute` even with
complete data and an explicit instruction. **This is the third consecutive attempt at this problem
to fail under measurement** (prompt directive → architectural round → truncation fix). Per the
differential-diagnosis gate, the next step is INSTRUMENTATION of why the selector declines, not a
fourth fix.

## Also in this release

- **NewX v1.0.0.177 companion fix (separate repo):** the `DERIVED FIGURES` directive told the model
  to write "computed as …" unconditionally, so it began claiming calculations no tool performed —
  an estimate dressed as verified. Now reserved for figures quoted back from an actual `compute`
  result. **Verified: zero false claims** in the post-fix answer.
- **SI-038 logged (P1, not fixed):** a **fabricated** `[[chart:...]]` marker was emitted
  (`6a2e2a6b-1e0e-...` where a real marker carries base64 chart data). NewX's citation guard treats
  marker presence as *proof* of tool-sourcing and accepts it in place of a source URL, so an
  invented one can launder an ungrounded answer past it.
- **Test-quality fixes:** two of the new suites passed alone and failed in the full run
  (`asyncio.get_event_loop()` on a loop an earlier test had closed; a stub class replacing
  `AsyncToolManager` during execution). Both fixed. The SI-028 shim in
  `test_data_file_content_type.py` was updated to mirror the class's new limits contract —
  assertions unchanged.

## Verification

| check | result |
|---|---|
| unit suite | **383 passed**, 4 pre-existing failures (unchanged, unrelated) |
| version sync | 5 passed |
| SI-037 CSV completeness | 142 → **263 lines**, `(complete)` |
| derived-figure accuracy | **still wrong** — see above |

## Migration / breaking changes

None to APIs. Behavioural: `second_round` adds one tool-model call per request that gathered data.
Set `tool_calling.second_round.enabled: false` to revert.
