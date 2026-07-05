# RAICA — Deep-Research Citation Liveness (dead "Page not found" links) — Solution Proposal

**Status:** PROPOSAL (for review → design → implementation). **No code changed yet.**
**Author:** drafted 2026-07-04. **Scope:** the citation/output spine of the Deep-Research pipeline
(`research/engine.py`, `research/pipeline.py`, `research/citation_grounding.py`, `research/synthesis.py`) plus
the already-existing live-link verifier in `fastapi_server_complete.py`.
**Risk class:** MEDIUM — touches the evidence→answer citation path, but is additive on top of the existing
grounding machinery and reuses the proven, lenient live-verify code. Designed to be **shadow-able,
feature-flagged, reversible, and no-worse-than-today**.

---

## 1. Problem statement (operator-reported, reproduced)

A live `@Ask deep research …` request (07/04/2026, energy-market/geopolitics topic; server run
11:04:40 → 11:08:41 PM UTC) returned an answer whose **citations included multiple dead "Page not found"
links**, and the follow-up "email me a PDF" delivered a PDF carrying the same dead links.

**Reproduced and quantified** by fetching all 49 cited URLs from the delivered PDF:

| Bucket | Count | Examples |
|---|---:|---|
| **Hard HTTP 404** (dead) | **15 / 49 (31%)** | World Bank `404 Error - Page Not Found`; Federal Reserve `Page not Found`; SF Fed FedViews; CNBC ×2 `Not Found`; USA Today `404`; NAM; IEA; Kitces `Page not found`; Fortune; a BBC article with an opaque ID `c2037d3v4e5o` |
| 403/401 bot-block (probably valid) | 6 | Reuters ×2, IMF ×2, S&P, economykz (429) |
| Connection error (kept, lenient) | 1 | fattaildaily.com.au |
| **OK 200** | 27 | eia.gov, wikipedia, tradingeconomics, kyivindependent, … |

So ~1 in 3 citations was a broken link. This is a **correctness/quality defect**: the reader (and the PDF)
is handed sources that don't resolve. The PDF is **not** a separate bug — it renders from the same answer
body (`answer_body`, `pipeline.py:387`), so one fix covers the chat reply and the PDF.

---

## 2. Current architecture (as-is) — grounded in the code

### 2.1 Gather-time live check exists — but only for each block's *fetched* URL
- `search_web` (`fastapi_server_complete.py:1838`) pulls results via the DDG aggregator, and for **each result
  href** calls `get_text_from_url_simplified` (`:1923`), which is **Layer 3** live-link verification: a hard
  404/410 or a homepage-redirect returns `None` → that result is skipped (`:1905`). `get_news_summaries`
  applies the same via `_filter_live_article_urls` (`:3275`). Config `deep_research.citation_verify`
  (`config/llm_config.yaml:186`, `enabled: true`).
- The verifier is **lenient by design** (`_verify_url_live:3069`): it drops **only** verified-dead URLs
  (hard 404/410, or a redirect to the site homepage); it KEEPS 200/403/paywall/JS-shell/429/5xx/timeout, so a
  valid article that merely bot-blocks the crawler is never lost. This is exactly the behavior we want — the
  problem is only **where** it runs.

### 2.2 The leak: evidence-URL over-capture (root cause)
- `DeepResearchEngine._dispatch_round` (`research/engine.py:410`) builds each evidence item's URL set as:
  ```python
  "urls": sorted(set(_URL_RE.findall(content))),   # _URL_RE = every https?:// match in the WHOLE block
  ```
  (`_URL_RE` at `engine.py:42`). This regex-scrapes **every URL appearing anywhere in the tool output** —
  the block's fetched `source_url` **plus** URLs embedded in **search snippets/descriptions** and inside the
  **extracted page body text / cross-references**. Only the *fetched source_url* passed §2.1's live check;
  the **embedded URLs never do**, yet they land in the citable evidence set.
- Downstream, `_ev_urls` (`pipeline.py:372`) is the union of these per-item URL sets. Any URL in it is a
  "legitimate" citation as far as every later stage is concerned.

### 2.3 Synthesis cites from evidence; grounding can't catch in-evidence dead links
- `ResearchSynthesizer.synthesize` cites URLs drawn from the evidence pool. It has no way to know an evidence
  URL is dead.
- `research/citation_grounding.py ground_citations()` (`:145`) is the output-side safety net, but it is a
  **PURE, offline** function (it never fetches). It classifies each cited URL against `_ev_urls`:
  - **FABRICATED** — not in evidence → strip link (keep text).
  - **ROTTED** — in evidence AND in the caller-supplied `dead_urls` set → strip link (keep text).
  - **VALID** — in evidence, not in `dead_urls` → **keep**.
- On this run it **logged nothing** (the `🔗 citation-grounding` line only prints when
  `fabricated|rotted|items_unsourced > 0`). A local test confirms the module's detection works on both
  Markdown and HTML (empty-evidence → all `fabricated`). Therefore the silence proves **all 49 cited URLs —
  including the 15 dead ones — were in `_ev_urls`**: they were classified `VALID` and kept.
- Two further reasons it could not have helped even if a dead URL had been out-of-evidence:
  1. It is called **without `dead_urls`** (`pipeline.py:373`) → the ROTTED branch is dead code.
  2. It is configured **`shadow: true`** (`config/llm_config.yaml:214`) → it only logs; it never edits the
     answer.

### 2.4 No output-side liveness pass
- Nothing between synthesis and delivery **fetches the final cited URLs** to confirm they resolve. The live
  verifier from §2.1 exists but is wired only into gather-time tool calls, and it is time-of-**check** (gather
  ~11:04 PM), not time-of-**use** (delivery / user click minutes-to-hours later).

### 2.5 Compounding failure this run — credibility grading collapsed
- `synthesis.py grade_sources` (`:171`) parses the grader's JSON via `extract_json_object` (`engine.py:90`),
  which is **all-or-nothing**: one malformed entry (an unescaped quote in a `reason`, or truncation at
  `max_tokens=3000` with 100+ domains) raises `JSONDecodeError`; the `except` (`synthesis.py:210`) then maps
  **every** domain to `unknown`. Live log: `🏷️ Credibility grading failed (Expecting ',' delimiter: line 124
  column 54 (char 9396)) → all 'unknown'`. This degraded the audit footer's credibility labels and the
  provenance shadow for the run (its shadow showed `unknown=43`). It did **not** cause the dead links, but it
  is a related resilience defect worth fixing in the same effort.

---

## 3. Root-cause analysis

| # | Cause | Consequence |
|---|---|---|
| R1 | **Evidence-URL over-capture** — `engine.py:410` scrapes *every* URL in a block (snippets, page-body cross-references), not just the verified `source_url` | Unverified (and sometimes dead/nonexistent) URLs enter the citable evidence set |
| R2 | Gather-time live check covers only each block's fetched `source_url`, and is time-of-check not time-of-use | Embedded URLs are never verified; even verified ones can rot before delivery |
| R3 | `ground_citations` is **by-reference only** — cannot detect an in-evidence dead link; additionally in **shadow** and called **without `dead_urls`** | The one output-side net is both structurally blind to this failure and disabled |
| R4 | **No active output-side liveness pass** on the final cited URLs | Dead links flow unchecked into the answer and the PDF |
| G1 | Grader JSON parse is **all-or-nothing** (`extract_json_object`) | One bad entry / truncation zeroes *all* credibility grades → `unknown` |

**Highest-leverage change:** R4 — an active, lenient, output-side liveness pass on the **actually-cited**
URLs. It catches both the over-captured-unverified case (R1/R2) and time-of-use rot, and it feeds the exact
signal (`dead_urls`) the already-built grounding stage needs. R1 (don't over-capture) is a valuable deeper
hardening but is more invasive and does not catch rot, so it is proposed as a **complementary** later step,
not the primary fix.

---

## 4. Proposed fix

### 4.1 Primary — output-side citation liveness (reuse the proven verifier)
Insert **one** step at the existing grounding call site (`pipeline.py:373`), gated by a new flag:

1. **Extract the actually-cited URLs** from the synthesized `answer` (reuse the same `_HTML_LINK`/`_MD_LINK`
   patterns `ground_citations` already uses — export a tiny `extract_cited_urls(answer)` helper from
   `citation_grounding.py` so there is ONE link-parsing definition).
2. **Verify liveness** of just those cited URLs (not the whole evidence set — bounded cost) using the
   **existing** `_filter_live_article_urls` / `_verify_url_live` — **lenient**: drop only hard 404/410 or
   homepage-redirect; keep 403/paywall/JS/timeout/5xx. Parallel, per-URL timeout, one timeout-window per batch.
3. **Pass the verified-dead set as `dead_urls=`** into `ground_citations`, and run grounding **enforcing**
   (not shadow) for this dead-link strip: a dead cited link becomes `rotted` → **the headline text is kept,
   only the broken link is removed** (never drops the substance; mirrors the existing lossless design).

**Reuse, not rewrite (per project rule):** the verifier already exists and is battle-tested. Because
`research/` must not import `fastapi_server_complete.py` (would be circular; `research/` currently has zero
coupling to it), **move** `_verify_url_live`, `_filter_live_article_urls`, `_is_homepage_redirect`, and
`_citation_verify_cfg` into a shared home both sides import — proposed: **`http_helpers.py`** (root core module;
already hosts `requests_compatible_get` at `:239`, the verifier's only non-stdlib dependency), or a new
`research/link_liveness.py` that imports `requests_compatible_get` from `http_helpers`. `fastapi_server_complete.py`
then imports the same functions (no behavior change to the gather-time path).

### 4.2 Complementary (later) — stop over-capturing unverified URLs (R1)
Optionally tighten `engine.py:410` so an evidence item's **citable** URL set is the block's **verified
`source_url`(s)**, keeping body-embedded URLs as *context only* (not citation targets). This removes the leak
at the source but does **not** catch rot, so it complements — not replaces — §4.1. Deferred to a follow-up
phase to keep the first change small and reversible.

### 4.3 Grading resilience (G1, bundled per operator request)
Make credibility grading **degrade per-entry, not all-or-nothing**:
- **Salvage partial JSON** — on `JSONDecodeError`, recover the entries that *did* parse (structural, not
  semantic — allowed) and map only the unrecoverable domains to `unknown`, instead of collapsing the whole
  batch. Keep it in the shared `extract_json_object` or a grading-local tolerant path.
- **Right-size the output budget** — auto-scale `grade_sources` `max_tokens` to the domain count (156 domains
  × `{tier,reason}` can exceed the current fixed `3000`), so large runs don't truncate mid-JSON.
- Net: a single malformed `reason` or a big run no longer zeroes every credibility grade.

---

## 5. Touch points & cost basis

| # | File / function (line) | Change | LOC | Risk |
|---|---|---|---|---|
| A | `http_helpers.py` (or new `research/link_liveness.py`) | **Move** `_verify_url_live`, `_filter_live_article_urls`, `_is_homepage_redirect`, `_citation_verify_cfg` here (verbatim); re-export from `fastapi_server_complete.py` | ~5 net | Low |
| B | `research/citation_grounding.py` | export `extract_cited_urls(answer)` (reuse existing regexes) | ~8 | Low |
| C | `research/pipeline.py` (`:373`) | new gated step: extract cited URLs → verify liveness → pass `dead_urls=` → enforce dead-strip | ~20 | **Med** (behavior + latency) |
| D | `config/llm_config.yaml` `deep_research.engine.citation_grounding` | add `verify_live: {enabled, shadow, timeout_seconds, max_workers}`; note `shadow` gate | ~6 | Low |
| E | `research/synthesis.py grade_sources` (`:171`) + `engine.py extract_json_object` (`:90`) | partial-salvage parse + auto-size grading `max_tokens` | ~25 | Low/Med |
| F | tests | live-verify unit (mock 404/redirect/403-kept); pipeline dead_urls→strip golden; partial-JSON-salvage unit; no-regression on healthy path | ~120 | Low |

**Estimated effort:** ~1–2 focused days incl. shadow validation. No new dependency. Added latency = one
lenient liveness batch over the *cited* URLs (~50), bounded by `timeout_seconds` (default 6) × ceil(n/workers)
— a few seconds on a run that already takes ~240s; gated so it can be tuned or disabled.

---

## 6. LLM-Policy-Gate & consistency compliance
- **No-Hardcoding:** liveness is **empirical** (fetch → HTTP status / redirect target), never a keyword or
  domain allow/deny list. `ground_citations` is **by-reference/structural**. No code decides a URL's *meaning*.
- **No-Inconsistency:** the lenient rule ("drop ONLY verified-dead; keep bot-blocks/paywalls/timeouts") is
  stated **once** and reused by both gather-time and output-side checks — one voice, no stage contradicting
  another. Grading salvage is structural parsing, not intent interpretation.

---

## 7. Config (fail-open, reversible)
```yaml
deep_research:
  engine:
    citation_grounding:
      enabled: true
      shadow: true                # existing fabricated/unsourced grounding stays shadow for now
      on_unsourced: flag
      verify_live:                # NEW — §4.1 output-side liveness
        enabled: true
        shadow: true              # true = fetch + log would-be dead-strips, answer UNCHANGED (baseline first)
        timeout_seconds: 6        # lenient per-URL liveness timeout (a timeout KEEPS the URL)
        max_workers: 8
```
Any failure (extraction, fetch, grounding) → today's behavior for that step (answer never discarded).

---

## 8. Rollout (no-fail discipline, mirrors citation-grounding / provenance)
1. **Phase 0 — shadow.** §4.1 fetches cited URLs and logs the would-be dead-strips (count + sample), answer
   unchanged. Gives a live baseline: real dead-link rate per DR run. Ship G1 grading fix here too (pure
   resilience, safe).
2. **Phase 1 — enforce dead-strip.** Flip `verify_live.shadow: false` → dead cited links are stripped (text
   kept). Re-run `make benchmark-full` (Tier-1) for no-regression; verify a real `@Ask` DR reply end-to-end.
3. **Phase 2 (optional) — R1 hardening.** Stop over-capturing body-embedded URLs into the citable set.

Each phase behind its flag, fail-open, gated on "no-worse-than-today."

---

## 9. Test strategy
- **Live-verify unit** (mocked): 404/410 → dropped; article→homepage redirect → dropped; 200 → kept; 403 /
  timeout / 5xx → **kept** (lenient).
- **Pipeline golden:** answer citing an in-evidence URL that is dead → with `verify_live` enforced, the link
  is stripped and the **headline text is preserved**; a live URL is untouched; output is byte-identical when
  nothing is dead.
- **Grading salvage unit:** a grader JSON with one malformed `reason` → all *other* domains keep their tiers;
  only the broken one falls to `unknown` (not the whole batch).
- **No-regression:** existing `test_citation_*`, grounding tests, and DR benchmark scenarios stay green.

---

## 10. Open questions for review
1. **Verifier home:** `http_helpers.py` (root core, already has `requests_compatible_get`) vs a new
   `research/link_liveness.py`? (Proposed: `http_helpers.py`.)
2. **Scope of liveness:** verify only the **cited** URLs (proposed, cheap) vs the whole evidence set (thorough
   but wasteful)?
3. **Homepage-redirect strictness:** keep the existing "article-path → bare homepage = dead" rule as-is
   (proposed) — any false positives observed in shadow?
4. **R1 now or later:** fold the over-capture tightening into Phase 1, or keep it a separate Phase 2?
5. **Non-DR path:** the non-DR streaming path already has gather-time `citation_verify`; do we also want the
   output-side pass there, or DR-only for now (proposed: DR-only)?

> Bottom line: the dead links are real URLs that entered the **evidence** set unverified (over-capture) and
> were never re-checked at output. Add a **lenient, empirical, output-side liveness pass on the cited URLs**,
> feed its dead set into the grounding stage we already have, and harden the grader's JSON parse — stripping
> only broken links (never the substance), shadow-first, flagged, and no-worse-than-today.
