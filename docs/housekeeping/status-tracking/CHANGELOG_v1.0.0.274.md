# CHANGELOG — v1.0.0.274

**Date:** 2026-08-14
**Type:** PHASE 1 — the gather gate now acts on its verdict (opt-in), and a keyword classifier is removed
**Design:** `docs/RAICA_NONDR_GATHER_GATE.md` §9

---

## Why now

Production, asked *"what was the average 10-year U.S. Treasury yield in 2025"*:

```
gather-gate: round=1 verdict=needs_more        <- correct, and ignored (shadow)
compute calls: none
answer: "4.33% ... calculated from the complete set of 250 daily observations"
truth : 4.2932% over 249 observations
```

The gate produced the right verdict and shadow mode discarded it. The mechanism that would have
caught the error was already deployed and deliberately muzzled.

## Phase 1

The loop now stops on a CONDITION rather than a count. On the identical request:

```
round=1  needs_more  "10-year Treasury yield data for 2025"          -> executing ['lookup_website']
round=2  needs_more  "the average must be calculated from the ..."   -> executing ['compute']
round=3  sufficient                                                   -> STOPPED reason=sufficient
```

Answer: **"4.29%, computed as the arithmetic mean over 249 daily observations"** — correct value,
correct count.

**Round 2 is the round a counter can never reach:** the data was already in hand and the
CALCULATION was what was missing. That state produced 4.24%, 4.33%, and a "computed as" claim with
no computation behind it.

Division of labour: the gate decides WHETHER more is needed, the existing second-round selector
decides WHAT to call — so whitelist filtering, dedup and reference resolution are reused, not
duplicated.

### Dampers

`max_gather_rounds` 3 (used all three above and stopped on `sufficient`, not the cap) ·
`wall_clock_seconds` 90 · dedup by name+arguments · whitelist re-checked every round ·
**no-progress stop** (a round adding no new reference id ends the loop — the line that makes
oscillation impossible) · fail-open.

**Off by default.** The committed config keeps `shadow: true`; enforcement is a per-deployment
operator choice via `RAICA_GATHER_GATE_SHADOW=false`, and a test asserts the shipped default.

## Removed: a keyword classifier

`audit_uncomputed_claim` matched the ANSWER against `computed as|over n=` to decide whether a
calculation had been claimed. That is a regex deciding MEANING, which the Cardinal Rule forbids,
and it had already failed in the way that guarantees: production wrote *"is calculated from the
complete set of 250 daily observations"* and the audit stayed silent.

Whether a derived figure is missing is a STRUCTURAL fact — a quantity was requested, no compute
result exists — and the gate already judges it in language. A test pins the regex out of the
codebase so it cannot return as a convenience.

## Verification

| check | result |
|---|---|
| enforced run on the failing request | 4.29% / 249 obs — **correct**, was 4.33% / 250 |
| loop terminated on `sufficient`, not the cap | ✓ rounds=3 |
| unit suite | **460 passed**, 4 pre-existing failures unchanged |
| shipped default still shadow | ✓ asserted |

## Cost

1–3 extra model calls on requests that need them; none on requests the gate finds sufficient at
round 1.
