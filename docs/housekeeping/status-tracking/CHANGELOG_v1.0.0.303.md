# CHANGELOG v1.0.0.303 — `compute` accepts the call shapes models actually emit

**Date:** 2026-08-17 · **Against:** v1.0.0.302 · **Closes:** SI-067 · **Logs:** SI-068

## The report

A USGS earthquake request — *"sample size, mean, median and std-dev of the magnitudes, and plot
the appropriate probability distribution curve"* — produced an answer containing **no statistics
at all**:

> "the compute tool calls ... all failed to execute due to expression errors ... I am therefore
> unable to report the mean, median, standard deviation"

28 attempts, every one rejected. The model behaved correctly throughout: it refused to invent
figures and said so plainly.

## The cause: a correct call rejected at the door

From the live log, what the model actually sent:

```
'data': '{"mag": {"from": "lookup_website#1", "column": "mag"}}'
         ^ a STRING containing JSON, not an object
```

**That reference is correct** — right output id, right column name, right shape. But
`_prepare_data` does `isinstance(data, dict)`, which is `False` for a string, so the call died
with *"`data` must be a non-empty object mapping names to arrays"*.

`_resolve_call_references` already `json.loads`es the top-level `arguments` blob. **Nested
values were not decoded**, so the resolver walked a string, matched nothing, and reported
`NOTHING RESOLVED`. Tool-calling models routinely serialise object-valued arguments.

Reproduced in five seconds once located:

| `data` | result |
|---|---|
| `'{"mag": [5.5, 5.8, 6.1]}'` (string, as sent) | **REJECTED** |
| `{"mag": [5.5, 5.8, 6.1]}` (dict) | **5.8** |

### What was NOT broken

Established by inspection before changing anything: `extract_column` returns all **225**
magnitudes; the reference block shown to the model lists `lookup_website#1`, all 22 column
names, sample rows and the reference syntax; the tool schema documents the reference form and
says "PREFER THE REFERENCE"; and both prompt paths genuinely include it. Every layer worked. The
model used the affordance correctly.

## Two further shapes from the same run

**A bare reference where a mapping belongs** — `'data': '{"from": ..., "column": "mag"}'`, with
`expr` then referring to a name that did not exist.

**A script instead of an expression** — the model tried to satisfy the whole request at once:

```
'expr': 'n = len(mag); mean_mag = np.mean(mag); median_mag = np.median(mag); std_mag = np.std(mag, ddof=1); ...'
```

which fails `ast.parse(mode="eval")` *and* blows the 500-character cap. Four figures, one
expression slot — that interface mismatch is what generated 28 attempts.

## Changes

1. **`_decode_json_valued_args`** decodes nested JSON-string arguments before resolution.
   Conservative by construction: only a string whose first non-space char is `{` or `[`, that
   parses as JSON, into a dict or list. Prose, URLs and quoted numbers are untouched.
   `compute` also decodes defensively, since it is reachable on paths that skip the resolver.
2. **A bare reference gets an actionable error** naming the exact shape to send, echoing the
   reference back. Deliberately an error, not a guess: inventing a series name would bind the
   data to a name `expr` does not use, and the model would then chase "name not defined"
   instead of the real problem.
3. **`expr` may be a LIST** (≤12), each evaluated independently. One bad expression reports its
   own error and the rest still return values; a wholly failed batch is a failure and carries
   the fail-closed notice; a partial batch warns that the missing figures must not be stated.
   Script-shaped `expr` now gets told to use a list — detected structurally by asking Python
   (parses in `exec` but not `eval`), never by pattern-matching text.

## Proof on the real failing case

The exact production call, replayed with `data` still a JSON string:

```
AFTER RESOLUTION: data type = dict | series = {'mag': 225}
np.mean(mag)        -> 5.8828
np.median(mag)      -> 5.8
np.std(mag, ddof=1) -> 0.421845
np.max(mag)         -> 7.8
```

`n=225` and max `7.8` match the figures the user's own answer reported from reading the file.

## Chart verified — including accuracy

The same request's chart also failed ("no chart tool produced a marker"). Re-tested end to end:

- `compute` returns the histogram via reference: `[75, 61, 40, 20, 8, 9, 2, 2, 2, 3, 2, 1]` —
  **identical to `np.histogram` computed independently from the raw column**.
- `plot_data` emits a marker and writes a valid **JPEG 760×430, 39.7 KB**.
- **The rendered image was inspected, not assumed.** Every plotted point matches the true
  counts (75, 61, 40, 20, 8, 9 … 3, 2, 1), axes are labelled `Magnitude` / `events`, and the
  source line reads `Source: USGS · retrieved 2026-08-17`. The Gutenberg–Richter decay is
  visible.

Two things worth recording from that check: the marker format is `[[chart:…]]` (lower-case) —
an initial detection regex looked for `[[CHART:` and wrongly reported "no marker"; and charts
are written into **NewX's** static directory, so a 404 from RAICA's own `/static` is expected,
not a fault.

## SI-068 (logged, not fixed)

`plot_data(kind="bar", x_type="quantitative")` renders a **line**:
`data_chart_generator.py:152` gates bar rendering on `x_type == "categorical"`, so the
requested kind falls through silently. For a probability *distribution curve* a line is
arguably the right rendering — so this output was correct — but a silently ignored parameter
will mislead whoever asks for bars next.

## Verification

- **12 tests** (`test_compute_argument_shapes.py`); **9 fail on pre-fix code**.
- Controls included: a real dict still works; a non-JSON string is not mangled and still fails
  honestly; a valid expression is never misread as a script.
- **Tier-0 10/10.** **Unit 659 passed**, the same 4 pre-existing failures. Version sync 19/19.

## Method note

Found by reading the code and the real logged arguments — not by reproducing the 28-call run.
The decisive evidence was one grep of what the model actually sent, and a five-second local
test of the two `data` shapes.
