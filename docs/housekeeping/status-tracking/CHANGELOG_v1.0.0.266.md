# CHANGELOG — v1.0.0.266

**Date:** 2026-08-14
**Type:** DIAGNOSIS ROUND — instrumentation only, no behaviour change
**Issue:** SI-036 — `compute` receives data references UNRESOLVED

---

## Why instrumentation and not a fix

On production, `compute` fails repeatedly with:

```
Expression rejected: data['mag'] is not numeric: float() argument must be … not 'dict'
```

A reference is reaching the tool unresolved — while the SAME round resolves `plot_data` correctly
(`resolved data references for 'plot_data' → {'x': 225, 'series': 1}`). The resolver recognises a
reference as a dict carrying both `from` and `column`, so the model must be emitting a different
shape for `compute`, and **nothing recorded what that shape is**.

Guessing at it would be the sixth consecutive unmeasured fix in this line of work. The previous
diagnosis round found the real cause of a four-attempt dead end in one log line; this is the same
move.

## What was added

`_arg_shape()` describes an argument's SHAPE rather than its contents — after resolution the
arguments hold hundreds of numbers, so raw logging is not an option. It prints a reference's KEYS,
which is precisely what distinguishes a recognised form from an unrecognised one:

```
correct   : {'data': {'mag': "dict['column', 'from']"}}
variant   : {'data': {'mag': "dict['col', 'from']"}}
variant   : {'data': {'mag': "dict['column', 'ref']"}}
resolved  : {'data': {'mag': "list[3]['float']"}}
```

Two log lines per second-round call:

- `🔬 second-round-args: tool=… available=[…] shapes=…` — before resolution
- `🔗 … resolved …` **or** `🔬 second-round-args: NOTHING RESOLVED for '…' — no argument matched
  the reference form`

The old resolution log only fired when a **top-level list** changed length, which is why `compute`
— whose references sit nested inside `data` — never appeared in it at all. That blind spot is why
this took two rounds to see.

## Verification

Instrumentation only; no code path changes behaviour. `tests/unit/test_si036_second_tool_round.py`
18 passed.
