# CHANGELOG — v1.0.0.270

**Date:** 2026-08-14
**Type:** Phase 0 SHADOW — the non-DR gather gate. Logs a verdict; acts on nothing.
**Design:** `docs/RAICA_NONDR_GATHER_GATE.md`
**Also:** the uncomputed-claim audit hole (v1.0.0.269 follow-up)

---

## The flaw being addressed

The non-DR path terminates gathering on a **count**, not a **condition**. Production, on
"the average 10-year yield in 2025, and nothing else":

```
03:33:20  selection : ['search_datasets']                  (catalog metadata)
03:33:23  SECOND ROUND: ['search_web','search_datasets']   <- budget spent here
03:33:33  selection : ['lookup_website']                   <- the CSV finally arrives
          (no further selection — the counter was exhausted)
```

No selector ever saw the CSV. `compute` was not rejected and not overlooked — it was
**unreachable**. The answer quoted **4.24%** from a web article against a true **4.2932%**.

Deep Research has had the correct shape since it was written: `_assess`
(`research/engine.py:709`) returns `sufficient`/`needs_more` and the loop stops on an evaluated
condition, with a `min_rounds` floor that overrides a premature "sufficient". The second round
shipped in v1.0.0.262 bolted a **counter** onto the ungated path instead of porting that gate.
This is the port, in shadow.

**Why it stayed hidden:** the Treasury and USGS prompts fetch their data in phase 1, so the single
extra round landed where it was useful and both produced exact figures. The flaw only shows when
phase 1 returns something other than the data — a catalog lookup, a failed fetch, a search hit.

## What ships

- `_gather_gate_assess()` — one structured question after phase 1: *can this be answered
  accurately with what has been gathered?* → `{status, missing, next_tools}`.
- It is shown the **schema preview** (`_describe_round_results`), not file contents — 579 chars for
  a 20,730-char CSV. "Do I have what I need?" is answerable from what exists.
- The prompt states the rule that matters: a figure that must be DERIVED is **not** in hand merely
  because the data is.
- `next_tools` is filtered to the offered set, so a verdict can never read as a recommendation to
  widen a bot's `allowed_tools`.
- **Every round is logged, including the first `sufficient`.** SI-021 had this class of assessor
  dead for seven builds behind a catch-all while reporting success; silence must never be the
  success signal. An unparseable verdict logs `UNAVAILABLE` rather than defaulting to an agreeable
  `sufficient`.

Config: `tool_calling.gather_gate` — **`enabled: false`, `shadow: true`**. Phase 0 cannot change
behaviour.

## Acceptance test (design §4) — met

Enabled locally against the prompt that motivated it:

```
🚪 gather-gate: round=1 verdict=needs_more
   missing='Dataset search failed to return usable data for the 10-year U.S. Treasury yield in 2025.'
   next=['search_datasets','lookup_website']  [SHADOW — not acted on]
```

Correct verdict, correct reason, after a phase 1 that returned only catalog metadata.

## A bug the first shadow run caught immediately

The first run returned `missing='No user prompt was provided; the request is empty…'`.
`user_message` is **constructed** (`:10135-10164`) — a directive preamble first, with the real
request appended **last** as `User Prompt: …`. Truncating from the front kept the preamble and cut
the question; with NewX's ~7,000-char system prompt merged in, the gate judged a request it had
never seen. It would have produced plausible-looking verdicts on every run and made the whole
shadow measurement worthless. Now takes the tail, with a named test.

## Also in this release

`audit_uncomputed_claim` (v1.0.0.269) only flagged a computation claim when compute was **attempted
and failed**. The very next production run called no compute at all, so `failed` was False and a
claim would have gone unrecorded. It now reports `unsupported_after_failure` (high confidence) and
`unsupported_no_compute` (lower — a source's own methodology can legitimately be described as
"computed as…") separately.

## Verification

| check | result |
|---|---|
| acceptance: `needs_more` on the motivating prompt | ✓ |
| shipped config disabled + shadow | ✓ asserted by test |
| unit suite | **454 passed**, 4 pre-existing failures unchanged |

## Next

Read the shadow numbers on real traffic before enforcing. The design's stated risk is that the gate
always says `sufficient` — an LLM asked "is this enough?" tends to agree. One `needs_more` on one
prompt is not that measurement.
