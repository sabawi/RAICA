# CHANGELOG — v1.0.0.267

**Date:** 2026-08-14
**Type:** Bug fix ×3 — all three causes NAMED by the v1.0.0.266 diagnosis round
**Issue:** SI-036

---

## What the instrumentation found

One production run with argument-shape logging resolved three separate causes and **refuted the
hypothesis I had been working from**. The reference shape was correct all along:

```
shapes={'expr': "str[21]='place[np.argmax(mag)]'",
        'data': {'mag': "dict['column','from']", 'place': "dict['column','from']"}}
```

`dict['column', 'from']` is exactly what the resolver expects, and there were zero
`NOTHING RESOLVED` lines. The failures were elsewhere.

## 1. `compute` rejected TEXT columns

```
data['place'] is not numeric: could not convert string to float: '226 km ...'   (x12)
data['time']  is not numeric: could not convert string to float: '2026-...'     (x12)
```

The model wrote `place[np.argmax(mag)]` and `time[np.argmax(mag)]` — the correct expressions for
"where and when did the largest earthquake occur", which is what the user asked. A tool built to
stop the model eyeballing a table **could not answer which row an extremum is in**, so it went back
to eyeballing and reported the wrong place and depth.

Numeric coercion is still tried first, so arithmetic is unchanged; only genuinely non-numeric
columns arrive as text, where indexing and comparison are all that is needed.

## 2. `np.size` was not in the allow-list

Rejected ×5 while answering "how many events are in the file" — a pure shape query with no I/O, no
callable and no allocation. Added, with `amin`, `amax`, `argsort` and `take`.

## 3. An unresolvable reference leaked raw dicts into the tool

```python
except ReferenceError_:
    resolved = dict(args)      # references still {"from": …, "column": …}
```

The tool then reported `data['mag'] is not numeric: … not 'dict'` — a type error that **hid** the
real problem (an unknown output id) and cost a full diagnosis round to see through. The call now
fails with the reference's own message, which both tools surface verbatim so the model can correct
the id.

## Verification

| check | result |
|---|---|
| the three production expressions | `np.size(mag)`=3, `place[np.argmax(mag)]`='Philippines', `time[np.argmax(mag)]`='2026-06-07' |
| new regression tests | 6, all **failing on pre-fix code** |
| escape vectors vs permissive build | **12/12 still discriminate** — fence intact |
| unit suite | **428 passed**, 4 pre-existing failures unchanged |

## A test whose premise changed

`test_non_numeric_data_is_rejected_cleanly` asserted that text input is REJECTED — correct when
`compute` was numbers-only, and wrong under the new contract. Rewritten as
`test_arithmetic_on_a_text_column_fails_cleanly`, asserting what still holds: arithmetic over text
fails as a clean rejection rather than a traceback. Recorded rather than quietly deleted.
