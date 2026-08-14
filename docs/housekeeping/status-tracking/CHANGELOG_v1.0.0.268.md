# CHANGELOG — v1.0.0.268

**Date:** 2026-08-14
**Type:** Usability fix — a rejection the caller can act on
**Issue:** SI-036, last known residual cause

---

## The finding

Mined from the argument-shape log added in v1.0.0.266, with no extra production runs needed:

```
"str[8]='len(mag)'"
```

The model reaches for `len(mag)` to count rows. The evaluator rejects every bare-name call — which
is correct and load-bearing, since that is how `open(...)`, `getattr(...)` and `__import__(...)`
would arrive — but the message said only what was forbidden:

```
only `np.<function>(...)` calls are permitted
```

Four such rejections occurred across the last four production runs. All four answers were still
correct, but only because the model issues 3–12 compute calls per run and something else covered
the gap. **The reliability was partly redundancy absorbing a defect**, which would not hold for a
question asking for a single derived figure.

## The change

The rule is unchanged; the refusal now names the form to use:

```
len(mag)             -> … — write `np.size(...)` instead of `len(...)`
sum(mag)             -> … — write `np.sum(...)` instead of `sum(...)`
open("/etc/passwd")  -> …; `open` is not available
```

Mostly generic: any builtin sharing a name with an allowed numpy function maps to itself.
`_BUILTIN_TO_NUMPY` holds the two whose numpy name differs (`len`→`size`, `sorted`→`sort`). It is
help text only — it changes no decision, and the call is rejected either way.

Same principle as the column-not-found error listing the available columns, which demonstrably lets
the model self-correct.

## Deliberately NOT done

Allowing bare builtins into the evaluator. That would put `len`, `sum` and `min` in the namespace
and weaken the single cleanest rule in the fence for no real gain.

## Verification

| check | result |
|---|---|
| new tests | 4, including one asserting the hint is not a loophole |
| escape vectors vs permissive build | **12/12 still discriminate** |
| unit suite | **432 passed**, 4 pre-existing failures unchanged |
