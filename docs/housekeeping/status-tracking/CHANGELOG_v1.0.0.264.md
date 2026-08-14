# CHANGELOG — v1.0.0.264

**Date:** 2026-08-14
**Type:** Bug fix (P1) — `compute` failed on the expressions a careful caller writes
**Issue:** SI-036 follow-up, found on production by the user re-running the Treasury request

---

## The bug

`compute` failed intermittently on production with:

```
Expression rejected: Invert is not permitted in a compute expression
```

`Invert` is `~`. Referenced real-world series contain gaps (a missing observation stays `None`),
and `np.min(s[~np.isnan(s)])` is THE numpy idiom for an extremum that skips them. The AST
allow-list rejected it, so `compute` failed on precisely the expressions a careful caller writes —
and the model then fell back to reading the table by eye.

The user's answer showed the consequence: **minimum spread reported as 0.10 beside quoted values
(4.89, 4.37) that give 0.52**, and a maximum of 0.62 against a true 0.69. The same self-refuting
signature as the original 2026-08-11 failure.

**Why it looked random:** simple expressions passed, gap-masking ones did not. A three-run
production check scored the maximum 2/3 and the observation count 2/3, with tool selection,
reference resolution and chart publishing all 3/3 — the plumbing was reliable, the arithmetic was
not.

## The fix

`~`, `&`, `|` and `^` are now permitted AST nodes. They are pure value operators: they grant no
attribute access, no calls and no names, so the fence is untouched — the attribute rule, name
binding, empty builtins and the numpy allow-list all still apply.

**Verified the fence still holds:** all 12 pre-registered escape vectors still FAIL against a
deliberately permissive plain-`eval` build. A named test covers the masking idioms and records the
production failure it prevents.

## Verification

| check | result |
|---|---|
| restricted-eval suite | 30 passed (3 new masking tests) |
| escape vectors vs permissive build | 12/12 still discriminate |
| unit suite | 418 passed, 4 pre-existing failures unchanged |
| the exact production expression | `np.min((y30-y10)[~np.isnan(y30-y10)])` now evaluates |

## Measurement note

The three-run harness scored `compute` as **selected**, not **succeeded** — it read the selection
log. Given the `Invert` rejections in the same window, `compute` was selected and then failed in
the runs that produced a wrong maximum. The harness now checks for rejection messages and for a
genuine `computed as …` claim in the answer, so the next pass rate measures the right thing.
