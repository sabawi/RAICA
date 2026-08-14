# Generalized Search → Extract → Chart (fallback tier)

**Status:** INVESTIGATION + FEASIBILITY — **awaiting sign-off, nothing implemented**
**Requested:** 2026-08-11 · **Supersedes:** SI-028 ("add a Treasury source"), withdrawn as a
per-site band-aid
**Scope:** a general path used **only when no specialized mechanism is available or offered.**
Specialized tools stay primary and unchanged.

---

## 1. Why the per-site idea was wrong

The trigger was a user asking for a chart of daily Treasury yields. The first proposal was to add
a Treasury data source. That is exactly the pattern the project's **Generalization Directive**
forbids: the next request is BLS, then ECB, then a CSV on someone's GitHub, each demanding its own
tool. The right question is not "how do we add Treasury" but **"why can RAICA not read a CSV?"**

---

## 2. What actually breaks today (traced, not assumed)

A live `@Ask` run on prod (2026-08-11 11:35) requesting the Treasury daily CSV:

```
tool SELECTED    : lookup_website, called TWICE — correctly one per year        OK
URLs CONSTRUCTED : both correct, right year parameters                          OK
CONTENT EXTRACTED: ERROR: Failed to extract content   (both files)              FAIL
yield numbers in context: 0
```

The endpoint itself is healthy — verified independently: **HTTP 200, `text/csv; charset=UTF-8`,
12,422 bytes, 153 rows, 15 maturities**, and *fresher* than FRED (08/10 vs 08/07).

**Root cause — `fastapi_server_complete.py:2167` `lookup_website`:**

```python
if self._is_pdf_url(url):                 # dispatch on the URL STRING
    result = self._extract_pdf_content(url)
else:
    result = self._extract_web_content(url)   # everything else assumed HTML
```

Two branches, and the else-branch presumes HTML. Three consequences:

1. **CSV / JSON / XML / TSV all fall into the HTML extractor and die.**
2. Dispatch reads the **URL pattern**, not the response's `Content-Type` — so
   `daily-treasury-rates.csv/2026/all?type=...` isn't recognised even by its own name, and the
   server's honest `text/csv` header is never consulted.
3. It fails **closed and silent** — `ERROR: Failed to extract content`, with no indication that a
   perfectly good machine-readable file was on the other end.

This blocks *every* data file on the web, not just Treasury.

---

## 3. What already exists (the pleasant surprise)

The generic chart mechanism **is already built and in production** — it is simply never fed from
outside the dataset catalog.

| piece | location | already generic? |
|---|---|---|
| `publish_chart(png_bytes, hint) -> url` | `utils/chart_publisher.py:184` | **YES** — PNG in, URL out, zero source coupling |
| `_marker(url, align, cap) -> "[[chart:…]]"` | `datasources/data_chart_builder.py:29` | **YES** |
| `generate_data_chart(series, kind)` | `utils/data_chart_generator.py` | **YES** — line/bar/scatter/auto from a `DatasetSeries` |
| `DatasetSeries` | `utils/dataset_block.py:50` | **YES**, and provenance is *mandatory* |
| `publish_fn` injection point | `data_chart_builder.py:116` | **YES** — already parameterised |
| marker relay to the answer | `fastapi_server_complete.py:3199` `_ARTIFACT_MARKER_RELAY` | **YES** |
| marker repair (LLM corrupts URLs) | `fastapi_server_complete.py` `_CHART_MARKER_RE_SRV` | **YES** |

So the pipeline `series → PNG → upload → marker → rendered by NewX` exists, is tested, and is
source-agnostic. **Only the intake is welded to the catalog.**

### Provenance is already enforced — this matters

`DatasetSeries` validates **fail-closed** in `__post_init__` and requires `title, source, url,
x_name, x_type, x, series`, with optional `retrieved`, `methodology`, `discontinuities` and:

```python
_X_TYPES = ("temporal", "quantitative", "categorical")
_TIERS   = ("structured_api", "bulk_file", "html_table", "unknown")   # fidelity, best→worst
```

`bulk_file` is *precisely* the tier for a downloaded CSV; `html_table` for a scraped table. The
vocabulary already anticipates this work. Anything routed through this contract inherits a source
URL, a retrieval date and an honest fidelity label — which answers the main risk in §6.

---

## 4. Proposed design — three pieces, none source-specific

### P1 — Content-type dispatch in the fetch tool  *(the actual bug)*
Dispatch on the response `Content-Type` (fall back to URL/extension only when the header is
absent or generic):

| type | handling |
|---|---|
| `text/html` | existing `_extract_web_content` — unchanged |
| `application/pdf` | existing `_extract_pdf_content` — unchanged |
| `text/csv`, `text/tab-separated-values` | **pass through**, with a row/byte cap |
| `application/json` | **pass through** (pretty-printed, capped) |
| `application/xml`, `text/xml` | **pass through** or shallow-parse |
| anything else | return the raw text **labelled with its content-type**, so the LLM decides |

Per the Generalization Directive this is discovery, not a static allow-list: an unknown type is
surfaced with its label rather than rejected. Fixes Treasury, BLS, ECB, and every future CSV at
once.

### P2 — A generic `plot_data` tool
A **thin** wrapper the model calls with data it has already obtained:

```
plot_data(
  title, source, url,            # provenance — REQUIRED, inherited from DatasetSeries
  x_name, x_type,                # temporal | quantitative | categorical
  x:      [...],                 # >= 2 points
  series: [{name, unit, y:[...]}, ...],
  kind:   auto|line|bar|scatter,
  source_tier: bulk_file | html_table | structured_api | unknown
) -> "[[chart:...]]" marker + a short digest
```

It builds a `DatasetSeries`, calls `generate_data_chart` → `publish_chart` → `_marker`. **No code
generation and no sandboxed execution** — this is the crucial difference from wiring
`analytical_visualizer`, which generates and *runs* chart code and would open a security surface
for no benefit.

### P2b — Restricted numpy expression evaluator  *(supersedes a `series_stats` tool)*

> **STATUS: BUILT v1.0.0.261 (2026-08-13), signed off by the user.**
> `utils/restricted_numpy_eval.py` (fence + allow-lists + caps) · `user_tools/compute_tool.py`
> (tool wrapper + wall-clock timeout) · `tests/unit/test_restricted_numpy_eval.py` (27 tests).
> Reproduces the motivating failure exactly: `np.min(y30-y10)` = **0.18** and `np.max` = **0.69**
> against the production answer's +0.19 and +0.53.
> **All 12 attack vectors below were shown to DISCRIMINATE**, by running the suite against a
> deliberately permissive plain-`eval` build: 27/27 pass on the real evaluator, and all 12 vectors
> FAIL on the permissive one. Two vectors initially passed on the permissive build — V2 (numpy
> 2.3.2 wraps the allowed functions in `_ArrayFunctionDispatcher`, which has no `__globals__`, so
> the payload raised AttributeError instead of being blocked) and V12 (Cyrillic 'а' does not
> NFKC-normalise to 'a', and the target file did not exist). Both were rewritten to attacks that
> genuinely succeed when unguarded. **Still REQUIRED for this to reach the failure that motivated
> it: P3** — `compute` is invisible to @Ask until it is added to that bot's `allowed_tools`.

**Why this instead of more calculators.** The 2026-08-11 Treasury answer fetched 401 real daily
rows and then reported the minimum 30Y-10Y spread as **+0.19** while quoting the two yields that
produce **+0.67**, and named a maximum of +0.53 when the true maximum is **+0.69**, a year
earlier. Every value it *quoted* was exact; only values it **derived** were wrong. The model was
eyeballing extrema over a 401-row table.

Writing a `series_stats` tool would fix min/max and leave correlation, percentiles, diffs,
normalisation and rolling windows to be added one at a time — precisely the per-case
proliferation the Generalization Directive forbids. Instead, expose **numpy** and let the LLM
choose the function.

```
compute(expr="np.min(y30 - y10)",
        data={"y30": [...], "y10": [...]},
        label="minimum 30Y-10Y spread")
  -> {value, expr, n, dtype}          # the EXPRESSION is returned for citation
```

numpy is already a dependency (2.3.2). Verified on the real failure:

```
np.min(y30 - y10)            = 0.18    <- true minimum   (answer said 0.19)
np.max(y30 - y10)            = 0.69    <- true maximum   (answer said 0.53)
np.corrcoef(y30, y10)[0][1]  = 0.738
```

**Provenance benefit, not just correctness.** The expression is citable — *"minimum spread,
computed as `np.min(y30 - y10)`, = 0.18 on 2025-01-13"* is auditable in a way "the model read the
table" never is. That speaks directly to D7, the weakest measured dimension (40.2% over_captured).

#### The fence — defence in depth, and NOT code execution

This is **not** sandboxing Python. It is a *restricted expression language that happens to use
Python syntax*: the AST is validated **before** anything is evaluated, and the permitted node set
is small enough to audit by eye.

> `sandboxed_executor` is explicitly **rejected** as the substrate. It is a command whitelist over
> `subprocess` (strict/permissive/unrestricted) with path restrictions — no seccomp, no container,
> no isolation boundary. Routing LLM-authored code through it on a user-facing path is real RCE
> surface.

| layer | rule |
|---|---|
| 1. AST allow-list | only `Expression, BinOp, UnaryOp, Call, Name, Load, Constant, Attribute, Subscript, Slice, Tuple, List` + arithmetic/comparison operators. Everything else — comprehensions, lambdas, walrus, f-strings, starargs, imports — **rejected** |
| 2. Attribute rule | `Attribute` permitted **only** as `np.<name>` where `<name>` is in the function allow-list. No chained attributes, no dunder, ever |
| 3. Name binding | names must be either `np` or a key of the caller-supplied `data` dict |
| 4. Builtins | `eval` runs with `{"__builtins__": {}}` |
| 5. numpy allow-list | **ALLOW-list of pure math only, never a deny-list.** numpy ships genuinely dangerous callables — `np.load` (executes pickles), `np.frombuffer`, `np.save`, `np.vectorize` (takes a callable), `np.memmap`. A deny-list would miss the next one |
| 6. Resource caps | max array length, max total elements, and a wall-clock timeout — otherwise `np.zeros(10**12)` or a crafted broadcast hangs a worker |

#### Adversarial checklist — MUST be attempted before shipping

A restricted-eval escape is a well-populated genre. Each of these gets a **named test that fails
on a permissive implementation**:

1. dunder traversal — `().__class__.__bases__[0].__subclasses__()`
2. globals reach-through on an allowed callable — `np.min.__globals__`
3. `getattr` / `vars` / `globals` / `eval` / `exec` by name
4. import smuggling — `__import__('os')`
5. file access — `open(...)`, and `np.load` on a crafted path (pickle execution)
6. callable injection — `np.vectorize(...)`, `np.apply_along_axis(f, ...)`
7. comprehension / generator / lambda side effects
8. f-string and `format` evaluation
9. subscript on a non-data object
10. resource exhaustion — huge allocation, pathological broadcast, deep recursion
11. name shadowing — binding `np` through `data`
12. unicode / homoglyph attribute names

**A clean pass is a red flag until the attack list is shown** — per the adversarial-audit gate.

#### Policy alignment (P4 extension)

- Any **derived** figure over retrieved data — extremum, correlation, spread, percentile, growth
  rate — must come from `compute`, not from reading the table.
- The **expression and the n** must be stated alongside the result.
- An extremum must carry **its date/label**, and must be arithmetically consistent with any values
  quoted beside it. *(The 2026-08-11 answer stated `4.64 - 3.97 = 0.19` — self-refuting on its
  face, and the cheapest possible check.)*

#### Sizing

| item | est. |
|---|---|
| evaluator + allow-lists + caps | ~120 LOC |
| adversarial test suite (12 vectors above) | ~150 LOC |
| tool wrapper + schema + policy | ~60 LOC |
| **total** | **~1.5–2 days**, of which **half is the adversarial pass** |

### P3 — Availability
Add `plot_data` to the `@Ask` whitelist (`newx/ai_plugins/Ask.yaml`) — config only.

### P4 — Policy (prose)
State the **fallback ordering**: prefer a specialized tool when one covers the request
(`comprehensive_stock_analyzer` for a ticker, `compare_datasets` for a catalog indicator); use
fetch + `plot_data` only when none does. State that plotted data must come from a retrieved
artifact, never from model recall, and that the columns plotted must be named.

---

## 5. Feasibility and sizing

| piece | est. | risk | notes |
|---|---|---|---|
| **P1** content-type dispatch | **~60 LOC + tests, 0.5 day** | LOW | one function; existing branches untouched; caps needed (a 12 KB CSV is fine, a 50 MB one is not) |
| **P2** `plot_data` tool | **~150–200 LOC + tests, 1–1.5 days** | LOW–MED | thin wrapper over 4 tested primitives; risk is schema-shape errors from the LLM, contained by fail-closed `validate()` |
| **P3** whitelist | **1 line, minutes** | LOW | |
| **P4** policy + fallback ordering | **~1 hour** | MED | must not cannibalise specialized tools — see §6 |
| **E2E + baseline** | **0.5–1 day** | — | S9 spectrum scenario; measure against D1–D7 before/after |

**Total ≈ 4.5–5 days** (P1 done; P2a chart ~1.5d, P2b compute ~1.5–2d, P3/P4 ~1h) including tests, an end-to-end run through the real `@Ask` path, and a baseline
measurement. **P1 alone (~half a day) would have answered the user's actual question** — the table
and items 1–3 — leaving only the chart missing.

---

## 6. Risks, and what would falsify this design

1. **Cannibalising specialized tools.** If the model reaches for fetch+`plot_data` when
   `comprehensive_stock_analyzer` would serve, quality drops: the specialized tools carry known
   schemas, computed indicators and correct units. **Mitigation:** P4 ordering policy, plus a
   spectrum scenario asserting a ticker question still routes to the analyzer.
2. **LLM misreads columns.** A general path hands column interpretation to the model — the axis
   where D7 provenance is already weakest (**40.2% over_captured**). **Mitigation:** `DatasetSeries`
   forces `source`/`url`/`source_tier`; policy requires naming the columns plotted; `bulk_file`
   and `html_table` tiers make fidelity visible to the reader.
3. **Payload size.** Two years × 15 maturities ≈ 500 rows crowds the context. **Mitigation:** caps
   in P1, and the model may request a narrower window or subset.
4. **Fabricated series.** The model could invent `y` values. **Mitigation:** policy that data must
   come from a retrieved artifact; the `[[chart:]]` marker is only mintable via `publish_chart`, so
   a fabricated chart cannot render — but fabricated *numbers inside* a real chart remain possible
   and are the residual risk worth watching in review.
5. **`analytical_visualizer` is NOT the answer.** It generates and executes code, emits no
   `[[chart:]]` marker (0 occurrences), and writes to a sandbox path. Explicitly rejected in favour
   of P2.

---

## 7. Open questions for sign-off

1. **P1 only, or the full P1–P4?** P1 is small, independently valuable, and unblocks every data
   file on the web. P2 is what actually produces the chart.
2. **Row/byte caps for pass-through** — what limit before truncation, and does truncation get
   disclosed in the tool result (it should, per SI-027's granularity lesson)?
3. **Should `plot_data` be offered on the DR path too**, or only the non-DR tool path? DR already
   has `compare_datasets`; adding a second charting route there risks §6.1.
4. **Does this earn a spectrum scenario (S9)** in `tests/benchmark/scenarios/`? Recommended — it is
   the class of request that currently fails silently.

**Nothing here is implemented. No code has been written.**
