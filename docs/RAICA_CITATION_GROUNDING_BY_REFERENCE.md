# RAICA — Citation Grounding by Reference (Source-Ledger) — Solution Proposal

**Status:** PROPOSAL (for review → design → implementation). No code changed yet.
**Author:** drafted 2026-06-16. **Scope:** the citation/grounding spine of BOTH the Deep-Research synthesis
path (`research/`) and the non-DR primary-synthesis path (`fastapi_server_complete.py`).
**Risk class:** HIGH — this touches the core evidence→answer pipeline ("the beating heart"). Designed to be
**shadow-able, feature-flagged, reversible, and provably no-worse-than-today** before it becomes authoritative.

---

## 1. Problem statement

A live `@Ask` answer (`sabawi.net/reply/409`) cited two BBC URLs and one Al Jazeera URL that **404** and that
were **never in the gathered evidence** (0 occurrences across the live log + 3 archives); the Wikipedia URLs in
the same answer were real. So the model **fabricated** article URLs — it knows the publisher URL *shape*
(`bbc.com/news/articles/cXXXX`, `aljazeera.com/news/YYYY/M/D/slug`) and invented plausible IDs/slugs.

The deeper cause (the operator's insight): the model often **has the fact but lost the link** somewhere in the
pipeline — gather → dedup/filter → arbitrate → compress → budget → truncate → assemble context — and because we
**force a citation**, it pattern-completes a fake URL to satisfy the rule. **We built the trap by forcing the LLM
to reproduce URLs from memory.**

**Goal:** make URL fabrication *structurally impossible*, preserve the fact↔source binding end-to-end through every
pipeline transformation, and guarantee every shown link is a real, gathered, live source — with a corroboration
quorum so no claim survives without at least one working source ("anti-fake-news").

---

## 2. Current architecture (as-is) — grounded in the code

### 2.1 Two source-block formatters (today)
- `fastapi_server_complete.py:2769 _format_source_block(source_url, title, content, source_num, …)` →
  ```
  📄 SOURCE: {title}
  🔗 CITATION URL: {source_url}
  CONTENT: {content}
  ```
  Used by the tools: `search_web` (:1898), `get_news_summaries`/`_get_news_content_with_article_urls` (:3179),
  `wikipedia_query` (:896), web extraction (:2378). **It already passes a `source_num` — but it is not surfaced
  as a citable token, and the prompt forbids using it (see 2.4).**
- `user_tools/citation_mastery.py:10 format_source_block(...)` → a **latent ID format** already exists:
  ```
  📄 SOURCE BLOCK #{source_num} [REQUIRED CITATION: {source_url}]
  ```
  i.e. RAICA once had a reference-by-number scheme — and we explicitly disabled the model from using it.

### 2.2 Deep-Research path (`research/`)
- `engine.py DeepResearchEngine.run()` → rounds of `_dispatch_round()` → each evidence item is a dict:
  `{ "content": <raw tool output string>, "urls": sorted(set(_URL_RE.findall(content))), "source", "sub_question_id",
  "question", "query", "round", "chars" }` (engine.py:403-412). **The URLs are a FLAT regex extraction from the
  block's text — not bound to specific sentences/claims inside the block.** Dedup is URL-structural (engine.py:41).
- `synthesis.py`:
  - `grade_sources()` (:161) → per-domain credibility tiers.
  - `_allocate_token_budget()` (:233) → per-block token cap to fit `evidence_token_budget`. **It never drops a
    block — every block gets ≥1 token share** (small blocks kept whole; large blocks share the remainder).
  - `_tok_truncate()` (:87) → truncates the **content body** to the cap; the URL header (`_url_line`) is prepended
    *after* truncation in `_evidence_document()` (:263-288), so **the URL header is not severed by truncation.**
  - `_evidence_document()` builds each block as:
    `───── EVIDENCE [sq | source | credibility] ─────\nSOURCE URL(S) for this block — cite … [headline](URL)
    using ONLY these: url1 , url2 …\n{content}`
  - `synthesize()` (:404) → one LLM call with the evidence doc + the synthesis system prompt (the CITATIONS-ARE-
    MANDATORY rules; the link-text rule was added in v1.0.0.122).
  - `verify()` (:547) → extracts claims and checks them **against the evidence** (the "97/97 claims supported"
    audit). **It validates claims, NOT URL existence/liveness** — so a fabricated URL on a true claim passes.
  - reconcile step is DISABLED (2026-06-01).
- **Binding weak points in DR:** (a) per-block URL list is flat → within a multi-article block the model picks which
  URL for which claim → fabrication when it guesses; (b) `verify` doesn't check URLs; (c) the model is told to write
  the raw URL, not a stable reference.

### 2.3 Non-DR path (`fastapi_server_complete.py`)
- Tools run → outputs formatted by `_format_source_block` accumulate into `tools_results` → optional arbitration →
  `_build_structured_context_block()` (:3326) wraps them → Primary LLM call with `primary_model_system_prompt.txt`.
- `_attempt_partial_optimization()` (:3371) is a **middle-truncating compressor** (keeps head+tail, drops the
  middle) that can sever a URL from its content — **but it only runs when `optimization_controller.should_optimize`
  AND total tool size > ~90% of the context window, AND it is currently REPORTED DISABLED on the live box**
  (`OPTIMIZATION_AVAILABLE`/"Optimization system not available"). It is a latent risk if re-enabled.

### 2.4 The prompt rules that *cause* the problem (the irony)
- `primary_model_system_prompt.txt:8` — **"NEVER SHOW [SOURCE BLOCK #] REFERENCE … show clickable [Title](URL) only"**
- `primary_model_system_prompt.txt:55` — "Never Reference citations by [SOURCE BLOCK #], only by [Title](URL)"
- DR synthesis prompt — "cite … [headline](URL) using ONLY these"; "every URL in References MUST be one provided".
- NewX bot preambles — "ONLY use URLs returned by tools; NEVER fabricate/invent."
- **All four force the model to emit the raw URL and forbid the stable reference. We are asking the failure mode.**

### 2.5 Existing liveness guard
- `fastapi_server_complete.py` Layer 3 (`_verify_url_live`, `_filter_live_article_urls`, `_is_homepage_redirect`,
  `_citation_verify_cfg`, v1.0.0.121) verifies **evidence URLs at gather time** (drops hard 404/410/homepage-
  redirect, lenient otherwise). It does **not** see the synthesis OUTPUT, so it cannot catch a URL invented later.

---

## 3. Root-cause analysis

| # | Where the binding breaks | Consequence |
|---|---|---|
| R1 | Model forced to reproduce raw URLs (2.4) | When it lacks the exact URL it fabricates a plausible one |
| R2 | Per-block URL list is flat (2.2a) | Within a multi-source block, claim↔URL is guessed → mis-cite/fabricate |
| R3 | `verify()` checks claims, not URLs (2.2) | Fabricated URL on a true claim passes the audit |
| R4 | Layer 3 verifies evidence, not output (2.5) | Fabricated/invented output URLs bypass liveness |
| R5 | Middle-truncating compressor (2.3, latent) | Can drop the URL while keeping the fact → forces fabrication |
| R6 | Google-News-style aggregator URLs (fixed v1.0.0.125) | One shared URL across many outlets → reuse/confusion |

**The single highest-leverage change addresses R1 directly: stop emitting raw URLs; emit stable references the
SYSTEM expands.** R2–R5 are hardening that make the reference scheme airtight.

---

## 4. Proposed architecture (to-be): the Source Ledger + cite-by-reference

### 4.1 Core idea
1. At **gather** time, every UNIQUE source (keyed by normalized URL) is registered in a per-request **Source Ledger**
   and assigned a stable ID `S1, S2, …` bound to `{id, url, title, domain, live, credibility, first_round}`.
2. Evidence is rendered to the LLM **headed by its ID and title/domain — the raw URL is withheld** (or shown but
   the model is told to cite the ID, never the URL).
3. The synthesis model cites **by ID** (`[S3]`, or `[S3][S7]` for corroboration). **It never writes a URL.**
4. A deterministic **post-synthesis Expansion** step replaces each `[Sn]` with the real clickable link from the
   ledger. Unknown IDs (hallucinated references) are dropped + logged. Any stray raw URL the model wrote is
   grounded against the ledger (safety net).
5. A **Quorum** pass drops/flags any item left with 0 valid sources after expansion.

**Why this is the structural fix:** the ground-truth URL lives in the **ledger (system memory)**, never in the
LLM's lossy working context. The LLM only manipulates short, stable tokens (`S3`) that survive compression,
budgeting, and truncation. It is *impossible* to fabricate a working URL because the model produces no URLs.

### 4.2 New component: `SourceLedger`
```
# research/source_ledger.py  (new, framework-agnostic, no server deps)
class SourceLedger:
    def register(self, url: str, title: str, *, content: str = "", credibility: str = "unknown",
                 round_num: int = 0, live: Optional[bool] = None) -> str   # returns stable "S{n}"; dedups by norm(url)
    def id_for(self, url: str) -> Optional[str]
    def get(self, source_id: str) -> Optional[SourceRef]                   # {id, url, title, domain, live, credibility}
    def render_for_llm(self, source_id: str) -> str                        # "[S3] «Title» (bbc.com)"  — NO raw url
    def expand(self, source_id: str) -> Optional[str]                      # "[Title](real_url)" (or numbered ref)
    def all(self) -> List[SourceRef]
```
- **One ledger per request.** Built at gather (DR: as `_dispatch_round` returns items; non-DR: as tools format
  blocks). URL normalization (strip tracking params like `?at_medium=RSS`, lowercase host, drop fragment) so
  `bbc.com/news/articles/x?at_medium=RSS` and `bbc.com/news/articles/x` are the same `S`.
- `live` is set from the existing Layer-3 verifier at registration (re-use, no new network model).

### 4.3 New component: `CitationExpander`
```
# research/citation_expander.py  (new)
def expand_and_ground(answer: str, ledger: SourceLedger, cfg) -> ExpandResult
   # 1) replace every [Sn] / [Sn][Sm] with ledger.expand(...) (clickable link); drop unknown IDs (+log)
   # 2) detect any RAW http(s) URL the model wrote; ground it against ledger by normalized match:
   #       in ledger -> keep (canonicalized);  not in ledger -> STRIP the link, keep text (+log "fabricated")
   # 3) QUORUM: per block (split on <p>/headings/\n\n), count distinct VALID source ids;
   #       0 valid + had citations -> drop or flag the block per cfg.on_unsourced ('drop'|'flag')
   # returns {text, stats: {expanded, unknown_ids, fabricated_raw, items_dropped, items_flagged}}
```
- Pure function, fully unit-testable offline (no network, no LLM).

### 4.4 The prompt flip (the heart of the change)
- DR `synthesis.py` evidence header → `[S3] «Headline» (bbc.com)` (ID + title + domain, **no URL**).
- DR synthesis rule → "Cite every factual claim by its SOURCE ID in brackets — `[S3]`, or `[S3][S7]` for
  corroboration. **NEVER write a URL or a markdown/HTML link; the system renders the clickable source.** Use ONLY
  IDs that appear in the evidence; if you have no source ID for a claim, omit the claim or mark it unverified."
- `primary_model_system_prompt.txt` → replace the `[Title](URL)` mandate + "NEVER [SOURCE BLOCK #]" with the
  cite-by-`[Sn]` rule. (Reverses 2.4.)
- NewX preambles → align to the same `[Sn]` rule (no raw URLs).
- Corroboration nudge → "Prefer ≥2 distinct source IDs per item."

### 4.5 Pipeline binding-preservation invariants (R2/R5 hardening)
1. **Ledger built from FULL gathered evidence**, before any dedup/budget/compress/truncate.
2. **Per-block ID list, not a flat URL list:** `_evidence_document` emits, per article inside a block, its own
   `[Sn]` next to that article's snippet (split multi-article news blocks into per-article sub-blocks at gather so
   each `[Sn]` hugs its own content — fixes R2).
3. **Header sacrosanct:** truncation shortens only the content body; the `[Sn] «Title» (domain)` header is never cut.
4. **Compressor block-atomic:** if `_attempt_partial_optimization` is ever re-enabled, it must drop whole blocks,
   never sever an ID header from its content (add an assertion/guard).
5. **Ledger is request-scoped and exempt from context budgeting** — it is the citation source of truth.

### 4.6 End-to-end flow (to-be)
```
tools/gather ──► register each source in SourceLedger (id+url+title+live)         [system memory: full, verified]
      │
      ▼ render evidence to LLM as "[S3] «Title» (domain) — content"  (NO raw URL)
synthesize (DR or primary) ──► answer cites [S3]/[S7] only
      │
      ▼ verify() (DR) — unchanged (claims vs evidence)
CitationExpander.expand_and_ground(answer, ledger, cfg)
      │  • [Sn] → [Title](real verified url)
      │  • unknown [Sn] dropped; stray raw URL grounded/stripped
      │  • quorum: 0-valid item dropped/flagged
      ▼
final answer (every link real, gathered, live; ≥1 source/item or dropped)
```

---

## 5. Touch points, change, and per-item risk (cost basis)

| # | File / function (current) | Change | LOC | Risk |
|---|---|---|---|---|
| T1 | `research/source_ledger.py` (NEW) | SourceLedger + URL normalization | ~120 | Low (new, isolated, unit-tested) |
| T2 | `research/citation_expander.py` (NEW) | Expansion + grounding + quorum | ~150 | Low (pure fn, unit-tested) |
| T3 | `research/engine.py` `_dispatch_round` (:403) | register sources in ledger; split multi-article blocks; carry ledger in result | ~40 | **Med** (evidence shape) |
| T4 | `research/synthesis.py` `_evidence_document` (:263) | render `[Sn]` headers (no raw url); per-article IDs | ~30 | **Med** (prompt input) |
| T5 | `research/synthesis.py` synth prompt (:404) | cite-by-ID rule + corroboration | ~15 | **High** (LLM behavior) |
| T6 | `research/synthesis.py` orchestration / `run()` caller | call expander after synth/verify; thread ledger | ~25 | **Med** |
| T7 | `fastapi_server_complete.py` `_format_source_block` (:2769) | optional `[Sn]` header variant (flagged) | ~20 | Med (shared by 4 tools) |
| T8 | non-DR primary assembly (:3326) + `primary_model_system_prompt.txt` | cite-by-ID rule; run expander on primary output | ~40 | **High** (LLM behavior) |
| T9 | NewX `newx/ai_plugins/*.yaml` (7 bots) | align preambles to `[Sn]` | ~10 | Med (cross-repo) |
| T10 | `config/llm_config.yaml` | `citation_grounding:` block (enabled/mode/on_unsourced/quorum_min) | ~10 | Low |
| T11 | tests | golden + zero-fabrication + quorum + expansion units | ~250 | Low |

**Estimated effort:** ~3–5 focused days incl. shadow validation. **No external dependency added.** Re-uses the
existing Layer-3 verifier and the existing `source_num` plumbing. The two highest behavioral risks are **T5/T8**
(does the model reliably switch to `[Sn]`?) — de-risked by shadow mode (§7).

---

## 6. Risk register & mitigations

- **Model ignores `[Sn]` and still writes URLs (T5/T8).** → Expander's raw-URL grounding (4.3 step 2) catches it;
  shadow mode measures the `[Sn]`-adoption rate before cutover; keep a one-flag rollback to today's behavior.
- **Mis-attribution (cites a real but wrong `[Sn]`).** Reference scheme prevents *fabrication*, not *wrong
  attribution*. → `verify()` already grounds claims in evidence; add an optional "claim-near-its-cited-snippet"
  check in Phase 4. Out of scope for Phase 1–3 (no worse than today, which can also mis-attribute).
- **Over-dropping on thin evidence (quorum).** → `on_unsourced: flag` default first (visible ⚠️, nothing deleted);
  switch to `drop` after profiling. `quorum_min: 1` default (not 2) to avoid gutting sparse topics.
- **Per-article block splitting changes DR evidence counts/budgets.** → behind the flag; compare evidence char/token
  totals shadow vs live; budget math unchanged (still per-block caps).
- **Two formatters drift (`_format_source_block` vs `citation_mastery`).** → consolidate onto one in T7 (the
  citation_mastery `SOURCE BLOCK #` format is the conceptual ancestor — fold it in).
- **NewX/RAICA prompt inconsistency** (LLM-Policy-Gate NO-INCONSISTENCY). → T9 done in lockstep with T5/T8.

---

## 7. Rollout (no-fail discipline)

1. **Phase 0 — Ledger + Expander, dark.** Build T1/T2 + tests. Wire T3/T6 to BUILD the ledger and run the expander
   in **SHADOW**: compute what *would* change, log `{fabricated_raw, unknown_ids, items_unsourced}`, but emit the
   unchanged answer. Zero user impact. Gives a real fabrication-rate baseline on live traffic.
2. **Phase 1 — Expander authoritative, prompts unchanged.** Turn on raw-URL grounding + liveness on the OUTPUT
   (strip fabricated/dead links, `on_unsourced: flag`). This alone fixes reply-409-class bugs **without** the prompt
   flip — lowest-risk win.
3. **Phase 2 — Prompt flip to `[Sn]` (T4/T5/T8/T9) behind `citation_grounding.mode: reference`.** Shadow first
   (measure adoption), then enable. Expander now mostly expands IDs; raw-URL grounding becomes the safety net.
4. **Phase 3 — Quorum `on_unsourced: drop`, `quorum_min` tuning.**
5. **Phase 4 (optional) — claim↔evidence re-linking** (recover a real source for a true-but-mislinked claim).

**Config (all fail-open):**
```yaml
citation_grounding:
  enabled: true
  mode: ground_only        # ground_only (Phase 1) | reference (Phase 2+)
  on_unsourced: flag       # flag | drop
  quorum_min: 1
  verify_output_liveness: true   # reuse Layer-3 on output URLs
  shadow: false            # true = compute+log, do not alter answer
```

---

## 8. Test strategy (must pass before each phase)
- **Zero-fabrication unit:** given a ledger of {S1..S5} and an answer citing `[S3]`, `[S9]`(unknown), and a raw
  `bbc.com/news/articles/FAKE`(not in ledger) → expander output contains S3's real link, no S9, no FAKE link.
- **Quorum unit:** an item whose only sources are unknown/dead → dropped (or flagged) per cfg.
- **Liveness backstop:** reuse `test_citation_link_verification` patterns on output URLs.
- **DR golden:** the reply-409 evidence set replayed → asserts 0 out-of-ledger URLs in the final answer.
- **No-regression:** existing `test_citation_source_filtering` / `_link_verification` / `_delivery_*` stay green.
- **Live shadow metric:** fabrication rate (raw URLs not in ledger) per answer, pre/post — target → 0.

---

## 9. Open questions for review
1. **Render style:** expand `[S3]` to inline `[Headline](url)` (current look) or to numbered superscripts `[3]`
   + a `## Sources` list (cleaner, de-duped, supports corroboration counts)? 
2. **Withhold raw URL from the model entirely**, or show `domain` only, or show full URL but forbid copying?
   (Withholding maximizes anti-fabrication; showing domain maximizes correct attribution.)
3. **Quorum default:** `flag` vs `drop`, and `quorum_min` 1 vs 2 for news bots specifically.
4. **Scope of Phase 2:** DR-only first, or DR + non-DR together?
5. **Phase 4 re-linking** appetite (it's the only way to *save* a true-but-mislinked claim rather than drop it).

---

## 10. Why this is safe to attempt on the core
- Additive + flagged + shadow-first: today's behavior is the default until each phase is measured.
- Re-uses existing primitives (`source_num`, Layer-3 verifier, `_evidence_document`), no new deps.
- The Expander is a pure, fully-tested function; the Ledger is request-scoped and isolated.
- Every phase has a single-flag rollback and a "no-worse-than-today" gate.

> Bottom line: we move the URL out of the LLM's lossy memory and into a verified, request-scoped ledger the LLM
> references by stable ID — making fabricated links impossible by construction, while a quorum guarantees no claim
> survives without a real, working source.
