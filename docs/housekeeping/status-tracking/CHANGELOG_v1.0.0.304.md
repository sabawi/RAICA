# CHANGELOG v1.0.0.304 — the series arrives as a top-level argument, not inside `data`

**Date:** 2026-08-17 · **Against:** v1.0.0.303 · **Closes:** SI-069

## How this was found: my v303 verification was invalid

v1.0.0.303 fixed `compute` rejecting a `data` argument sent as a JSON string, and I verified it
"on live". The user re-ran the same USGS query and it **failed again** — 30 calls, same outcome.

My live check hand-built a tool call and invoked `_resolve_call_references` directly. That
bypassed the shape the model actually emits, so it passed while production stayed broken. This
is the "my test skipped the failing layer" trap, and it is the second time in this session that
a green isolated check masked a live failure.

## The real shape

From the live log, after v303 was deployed:

```
'arguments': {'expr': 'np.percentile(mags, 90)',
              'mags': '{"from": "lookup_website#1", "column": "mag"}'}
                       ^ the series, at the TOP LEVEL, named after itself
```

`data` is absent entirely, so the call dies on *"`data` must be a non-empty object mapping names
to arrays"* — reported to the user as "the data object was not properly formed".

It is a natural mistake: the model treats the **series name** as the parameter name, and the name
it chooses is exactly the one its own `expr` refers to. Everything needed is present and
unambiguous; only its position is wrong.

A second shape appeared in the same run: `len(mags)`. The evaluator permits only
`np.<function>(...)` calls and **already names this equivalence** in its own `_BUILTIN_TO_NUMPY`
table — it simply reported it as an error rather than applying it, costing a round-trip every
time the model wrote the natural spelling.

## Changes

1. **Stray series are adopted as `data`.** When `data` is absent, any top-level argument that is
   not a declared parameter (`expr`/`data`/`label`) and carries a numeric series becomes part of
   `data`. Structural, not interpretive: an explicit `data` always wins — this only fills a gap —
   and non-series strays (prose, numbers) are left alone.
2. **`len(x)` → `np.size(x)`, `sorted(x)` → `np.sort(x)`**, rewritten on the AST so it cannot
   touch a string literal or a name that merely contains "len" (`np.mean(length)` is untouched).
   The security fence still validates the rewritten expression — nothing is relaxed, and the
   rewrite is disclosed in the result so the cited expression matches what ran.

## Proof, on the exact production call

```
input : {'expr': 'np.sum(mags >= 7.0) / len(mags)',
         'mags': '{"from": "lookup_website#1", "column": "mag"}'}
resolved: {'expr': str, 'mags': list[225]}
result  : 0.0355556   computed as: np.sum(mags >= 7.0) / np.size(mags)   over n=225
```

`0.0355556 = 8/225` — matching the **8 M7.0+ events** the user's own answer listed by reading the
file directly.

## Verification

- **20 tests** in `test_compute_argument_shapes.py`; **7 of the 8 new ones fail on pre-fix code**.
- Controls: an explicit `data` overrides strays; a prose argument is never adopted; a name
  containing "len" is never rewritten; an unparseable expression is left for the evaluator to
  report rather than masked by the rewriter.
- **Tier-0 10/10.** **`make smoke` PASSED.** **Unit 667 passed**, same 4 pre-existing failures.
  Version sync 19/19.

## Method note

The fix came from one grep of the arguments the model actually sent — not from reproducing the
30-call run. What went wrong in v303 was the *verification*, not the diagnosis: the shape I tested
was one I invented, and inventing the input is indistinguishable from not testing at all.
