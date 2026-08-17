# CHANGELOG v1.0.0.302 — one hung source can no longer freeze a research round

**Date:** 2026-08-17 · **Against:** v1.0.0.301 · **Addresses:** SI-064 (the amplifier)

## What was wrong

`_dispatch_round` awaited `asyncio.gather(...)` with no timeout, and the only log line in that
region came **after** the await. A single source that never returned therefore froze the whole
round in total silence.

Measured on production 2026-08-17 — a DR round went quiet for **41 minutes**:

| source | what it showed |
|---|---|
| RAICA log | last line `Web search completed`, then nothing |
| **Ollama journal** | last request 14:56:01, then nothing — so **not** an LLM hang |
| `sar` | ~98% idle CPU, ~0.03% iowait — blocked, not spinning |
| system journal | no OOM, no network failure, no service restart |

The client waited out its 1800s timeout and received 0 bytes.

## The part that matters most: a budget already existed and could never fire

`loop.wall_clock_seconds` (240s) was meant to cover exactly this. It is evaluated at the
**top** of the round loop:

```python
while ...:
    if time.monotonic() - start > self._wall_clock:   # ← checked ONLY here
        stop_reason = "wall_clock"; break
    ...
    await self._dispatch_round(...)                   # ← the check cannot reach inside
```

A hung round never returns to the check. **A limit that can only be tested between iterations
cannot bound the work inside one.** This is worth stating plainly, because the obvious reading
of the config is that DR was already protected — it was not.

## The fix: bound the TASK, never the round or the request

The constraint was explicit: *must not preempt a genuinely lengthy request.* So the bound goes
on the individual dispatch, in `_safe_dispatch`, which already had the right shape (it catches
and returns a placeholder rather than raising):

- a **stuck source** is abandoned and recorded — the round keeps every other result;
- a **lengthy request** is untouched: it may run as many rounds as its own budget allows, and
  each round may take as long as its sources legitimately need.

Bounding the gather itself, or charging it against the wall clock, **would** preempt long
legitimate research — the exact failure mode to avoid.

A timeout is reported distinctly from a generic failure, because "this source hung" and "this
source answered badly" need different diagnoses.

## The value is derived, not chosen

Round wall time ≈ the slowest task, since a round awaits its sources in parallel. Across every
archived run:

```
round durations    15s, 17s, 19s, 19s, 19s, 22s, 26s, 45s, 46s
widest round       48 sources in parallel -> 45s
```

so the slowest legitimate task is ~46s — itself an over-estimate, because the interval between
round markers also contains the inter-round assess LLM call. A realistic bounded worst case for
one source is ~60–90s (`search_web`: 6 engines × 5s + ~3 extractions × 10s).

**`dispatch_timeout_seconds: 180`** — ~4× the slowest measured round, ~2× that worst case.

### A contradiction in my own first draft

I initially set **300s against a 240s `wall_clock_seconds`** — a per-source budget *larger than
the loop budget it lives inside*, which would let one stuck source outlive the entire gather
phase. Caught by asking what the two numbers mean together, corrected to 180s, and pinned by
`test_the_per_source_budget_stays_INSIDE_the_loop_budget` so the two limits can never drift
into contradiction again.

## Visibility

`🔎 Round N: dispatching M source(s) (per-source limit 180s) ...` is now logged **before** the
await. Previously the region's only line came after it, which is why a frozen round left
nothing to diagnose.

## Verification

- **10 tests**, `tests/unit/test_dr_dispatch_timeout.py`; **6 fail on pre-fix code**.
- **Both halves pinned:** a hung source is abandoned in <5s and the round keeps its other
  results; a slow-but-legitimate source returns its content untouched; three concurrent
  slow sources all succeed (proving the bound is per-task, not per-round).
- **The pre-fix run HUNG** until outer bounds were added to the tests. A test that hangs is not
  a failing test — it is an unusable one. With bounds, pre-fix fails cleanly in 31.6s.
- Two tests pass both pre- and post-fix by design: they are *constraint* guards against the fix
  being too aggressive, not regression detectors.
- **Tier-0 10/10.** **Unit 647 passed**, the same 4 pre-existing failures. Version sync 19/19.

## Scope

This fixes the **amplifier** — why one stuck source produced 41 minutes of silence instead of
one lost source. It does **not** explain why that source stuck; SI-064 stays open for that.
