# Changelog — v1.0.0.207 → v1.0.0.214

**Date:** 2026-07-20
**Scope:** Make the **data-charting** feature (v1.0.0.206) actually render charts **end-to-end through the
real `/v1` entry point**. v206 was built + unit-validated in isolation; the first real end-to-end runs
surfaced a chain of integration defects that isolated tests could never see. All fixed here, then verified
with repeated live batches (Egypt/US/China/Germany/World/India across population, GDP, GDP-per-capita,
CO₂-per-capita, life-expectancy). Branch `feature/unified-artifacts`. Behavior still flag-gated.

## Why this took several increments — the real pathway bites
Per the architecture-first rule, each fix came from tracing a REAL request end-to-end and reading the
server log for ground truth — never from an assumed model. The defects were strictly ordered: each one had
to be fixed before the next became visible.

### 1. Country NAME → ISO-3166 code (declarative_adapter `_resolve_geo`)
The LLM emits `geo="Egypt"`, but World Bank needs `EGY`. The old path passed the name straight through →
WB returned a 102-byte error envelope → no data, no chart. **Fix:** `geo_resolver: iso3` on the world_bank
source; the adapter resolves a country **name OR code** to alpha-3 via `pycountry` (added to requirements).
Deterministic data resolution, not intent classification. `Egypt`/`egypt`/`EGY`/`United States` all work.

### 2. Marker relayed VERBATIM through standard synthesis (`_ARTIFACT_MARKER_RELAY`)
The data-chart request is the first `[[chart:...]]` case to traverse the **standard** (non-deep-research)
synthesis path, which — unlike the DR path (`research/synthesis.py`) — had no marker-preservation rule. The
LLM "helpfully" rewrote `[[chart:/static/images/media/HASH.jpg|…]]` into a markdown image pointing at a
**hallucinated CDN URL** → HTTP 404, broken image. **Fix:** a mandatory verbatim-relay directive injected
into every tools-executed primary prompt: reproduce `[[chart|image|file:...]]` markers character-for-
character; never convert to `![](…)`/`<img>`; never re-type/re-host the URL.

### 3. FAIL-CLOSED anti-hallucination (same directive, second clause)
When a chart couldn't be produced (source failure), the model **fabricated** a chart — inventing a
`[[chart:src=quickchart&…&data=1.5,1.8,…]]` marker with transcribed numbers, and elsewhere matplotlib code.
That is the exact numbers-by-reference violation the design forbids. **Fix:** policy language — "you CANNOT
create a chart yourself; a visual appears only from a real tool marker; if none is present, describe the
data in prose/table and never fabricate a marker, chart code, quickchart, or inline data." Verified: when a
fetch now fails, the answer degrades to honest prose with **zero** fabricated charts.

### 4. Robust fetch for World Bank's BIMODAL latency (declarative_adapter `_http_get`)
Evidence (curl AND requests): the same WB URL answers in ~0.2 s most of the time but intermittently hangs
30–40 s in a transient Cloudflare burst. A single 30 s timeout stalled the whole gather round. **Fix:**
SHORT per-attempt timeout (10 s) + several retries (4), each on a **fresh** connection (`Connection: close`,
new `Session`) with 0.5 s backoff — abandon a slow edge fast and re-roll for a healthy one. Config-driven
(`fetch_timeout_seconds`, `fetch_retries`, `fetch_retry_backoff_seconds`).

### 5. Dead World Bank indicator code (config catalog)
WB **archived** `EN.ATM.CO2E.PC` (CO₂/capita) — every request 404'd ("deleted or archived"). Validated all
7 catalog indicators; only this one was dead. **Fix:** `co2-per-capita` → `EN.GHG.CO2.PC.CE.AR5` (AR5/EDGAR
series, excl. LULUCF, source=2/WDI, updated 2026-07-13), unit → "t CO₂e per capita".

### 6. Tolerant measure resolution (declarative_adapter `_resolve_measure`)
The LLM sometimes passes the human LABEL (`"CO2 emissions per capita"`) instead of the catalog code
(`"co2-per-capita"`) → `unknown measure` → no chart. **Fix:** resolve the caller's string to a catalog code
by matching (NFKC-normalized, alnum-only) against code then label, exact then substring — so `CO2 emissions
per capita`, `CO₂ emissions per capita` (subscript), and `co2-per-capita` all map correctly; unknown → None
(fail-closed). NFKC folds unicode subscripts (₂→2) so the plain-ASCII LLM string matches the ₂ label.

### 7. Tool-routing lane: search_datasets vs analytical_visualizer (tool descriptions)
Two chart-capable tools compete: `analytical_visualizer` charts data the LLM SUPPLIES (numbers-by-value —
can be invented), while `search_datasets` FETCHES a real public dataset (numbers-by-reference). The planner
sometimes routed a public-statistic chart (e.g. world population) to analytical_visualizer, which then
failed. **Fix (policy language, both descriptions, additive/non-regressive):** analytical_visualizer is for
one-off visuals of data you already have; for a named real-world public statistic (population, GDP,
inflation, unemployment, life expectancy, CO₂, crime, …) use `search_datasets`, which fetches the authentic
numbers. Reconciled so both tool descriptions speak with one voice.

## Known-issue logged (not fixed here)
- **SI-004 [P2]** — `fbi_cde` source endpoint is dead (HTTP 404); the FBI Crime Data Explorer API was
  reorganized. World Bank is unaffected. Fail-closed prevents hallucination when fbi_cde is selected. Needs
  an endpoint/shape rediscovery in a follow-up. See `SUSPECTED_ISSUES.md`.

## Files
- `datasources/declarative_adapter.py` — `_resolve_geo`, `_resolve_measure`, `_norm` (NFKC), robust `_http_get`.
- `fastapi_server_complete.py` — `_ARTIFACT_MARKER_RELAY` (verbatim relay + fail-closed), injected into every
  tools-executed primary prompt.
- `config/llm_config.yaml` — `geo_resolver: iso3`, CO₂ indicator swap, fetch timeout/retry/backoff.
- `user_tools/search_datasets_tool.py`, `user_tools/analytical_visualizer.py` — routing-lane descriptions.
- `requirements.txt` — `pycountry`. `research/engine.py` — planner guidance (verbatim source/measure/geo).
- `docs/housekeeping/status-tracking/SUSPECTED_ISSUES.md` — SI-003.
