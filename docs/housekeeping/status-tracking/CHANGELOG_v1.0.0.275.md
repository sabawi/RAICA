# CHANGELOG — v1.0.0.275

**Date:** 2026-08-14
**Type:** Bug fix — a bell curve could not be built because its x-axis was forbidden
**Issue:** SI-041(a)

---

## The bug

A production request — *"…plot the bell curve and show these values on the curve"* — produced
**47 `Expression rejected`** in a single request, ran the gather gate to its round cap without
reaching `sufficient`, and rendered **no chart**. The surviving expressions show why:

```
np.linspace(np.min(mag), …)
np.arange(5.0, …)
```

Both were excluded from the numpy allow-list as *"allocate BY SIZE"*. That is a real memory
concern — `np.arange(10**12)` is 8 TB — but a blanket ban was the wrong shape: building the x-axis
of a fitted distribution curve is precisely what these functions are for.

## The fix

Both are permitted, with the **size argument** bounded — which is where the danger actually lived:

1. **Static bound at validation.** Any argument that is constant-only arithmetic is folded and
   checked against `MAX_ELEMENTS_PER_ARRAY`.
2. **Post-evaluation bound.** A result exceeding the cap is rejected, covering sizes computed from
   data.

### Why folding was necessary, not gold-plating

A literal-only check missed `np.arange(0, 10**9)` — `10**9` is `BinOp(10, Pow, 9)`, not a
`Constant` — so it **allocated 8 GB** before the post-evaluation check rejected it: a denial of
service that reported itself politely. Constant arithmetic is now folded at validation time and all
four bomb shapes are refused in **0.000s**, before numpy is reached.

The folder handles only literals and arithmetic operators. A name or a call folds to `None` and
falls through to the runtime guards, so it never becomes an evaluator for anything the caller
controls.

## Verification

| check | result |
|---|---|
| `np.linspace(np.min(mag), np.max(mag), 5)` | works — the case that was blocked |
| `np.arange(5.0, 7.0, 0.5)` | works |
| 4 allocation bombs incl. `10**9`, `10**12` | refused at validation in 0.000s |
| computed size (`np.arange(np.max(n))`, n=300000) | caught post-evaluation |
| escape vectors vs permissive build | **12/12 still discriminate** |
| unit suite | **468 passed**, 4 pre-existing failures unchanged |

## Still open from the same request (SI-041)

- **(b)** the answer DESCRIBED a chart it never rendered — a new fabrication shape, distinct from
  SI-038's invented marker, and not covered by `plot_data`'s failure path because the tool was
  never called
- **(c)** the header row counted as an observation: **226** reported against **225** events, the
  same off-by-one that gave "250 daily observations" against 249 for Treasury data
- **the model-choice error, unaddressed:** the answer reported **P(M≥7.0) = 0.54%** from a normal
  fit for a dataset **containing 8 such events (3.56%)** — magnitudes are Gutenberg-Richter, so a
  normal fit understates the tail ~9×. Correct inputs, correct arithmetic, wrong MODEL. Nothing in
  RAICA checks that an assumed distribution matches the data, and this may not be fixable by
  tooling alone.
