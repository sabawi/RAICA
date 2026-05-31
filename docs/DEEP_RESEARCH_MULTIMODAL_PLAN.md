# RAICA Deep Research & Multi-Modal Presentation — Staged Design Plan

**Status:** DRAFT (planning) — no code written yet. Each stage is gated on explicit approval.
**Author:** RAICA Development Team (with Claude Code)
**Date:** 2026-05-31
**Scope decisions (locked):**
- **Priority:** Research **depth + fact-checking** first (Stages 1–2), before multi-modal work.
- **Image generation:** **OUT OF SCOPE.** We retrieve *real* images from the internet only. No DALL·E / Stable Diffusion / ComfyUI.
- **Modalities in scope:** Charts/tables (extend existing) + license-aware internet image retrieval/embedding. **No audio, no video** for now.
- **Process:** This doc first; implement stage-by-stage with a review gate at each stage boundary.

---

## 1. Guiding Principles (non-negotiable, from CLAUDE.md)

1. **LLM decides, RAICA executes JSON.** Every new decision point (planning, gap assessment, claim verification, presentation choice) is an LLM call that returns structured JSON. RAICA only parses and executes — no keyword lists, no pattern matching for meaning, no special-case handlers, no silent fallback defaults.
2. **Zero hardcoded config.** All thresholds, depths, round limits, model roles, and feature flags live in `config/llm_config.yaml`. Fail fast if missing.
3. **Reuse existing code.** Build on `search_web`, `get_news_summaries`, `published_papers_search`, `sec_edgar_tool`, `document_search`, `citation_mastery`, `analytical_visualizer`, the `arbitrator`, `text_chunker`, and the existing DECIDE→ACT→VERIFY retry loop. Do not reinvent.
4. **Generalization test.** A novel research topic or media need must work without new branches.

---

## 2. Current-State Assessment (evidence)

| Area | Implementation | Location | Limitation |
|------|----------------|----------|------------|
| Web search | DuckDuckGo via `ddgs` | `fastapi_server_complete.py:1773` `search_web()` | `max_results=3` hardcoded; per-page extract capped at ~5 paragraphs / 2000 chars; single pass |
| News | Google News RSS | `:881` `get_news_summaries()` | Sources configurable; no cross-checking |
| Academic | arXiv-style paper search | `user_tools/research_paper_search.py` | Single-shot |
| SEC | EDGAR filings | `user_tools/sec_edgar_tool.py` | — |
| Docs/RAG | FAISS store | `document_search` | — |
| Citations | Source-block *formatting* only | `user_tools/citation_mastery.py` | No verification; formatting ≠ fact-check |
| "Arbitrator" | Validates **tool results** | `:4908` `arbitrator_validate_tasks()` | Does **not** arbitrate competing research answers |
| Research detection | **Hardcoded keyword list** | `:3236` `_is_research_query()` | Violates anti-keyword directive; only tunes a context threshold |
| Charts | LLM-generated matplotlib → PNG → base64 | `user_tools/analytical_visualizer.py` | Good base; no web images |
| PDF / HTML | Report generators | `user_tools/pdf_generator_tool.py`, `templates/html_report_template.html`, `utils/html_generator.py` | — |
| Image gen / web images / audio / video | **None** | — | Greenfield (image gen intentionally excluded) |

**Model roles available** (`config/llm_config.yaml`): `primary`, `tool_calling`, `arbitrator`, `vision`, plus fallback chain across OpenAI / Anthropic / Gemini / Ollama-cloud. This pool is what makes multi-model arbitration feasible without new infrastructure.

---

## 3. Target Architecture (high level)

```
User research request
        │
        ▼
[Stage 0] LLM intent classify (replaces keyword _is_research_query)
        │  → {is_research, depth_hint, output_hint}
        ▼
[Stage 1] DEEP RESEARCH ENGINE
   Planner (LLM JSON) → sub-questions + per-question source strategy
        │
        ▼  iterative gather loop (DECIDE→ACT→VERIFY, bounded by config)
   Multi-backend fan-out (web/news/arxiv/wiki/SEC/docs) → dedup → chunk
        │  LLM gap-assessment after each round: "sufficient?" → loop or stop
        ▼
   Evidence pool (source blocks via citation_mastery)
        │
        ▼
[Stage 2] VERIFICATION + ARBITRATION
   Claim extraction (LLM) → cross-source check → labels+confidence
   Ensemble synthesis on N models → arbitrator reconciles disagreements
        │
        ▼
[Stage 3] LONG-FORM ASSEMBLY (optional per request)
   Outline (LLM JSON) → section-by-section gen → structured Report object
        │
        ▼
[Stage 4] PRESENTATION PLANNER (LLM JSON media plan)
   charts (analytical_visualizer) + web image retrieval+embed
        │
        ▼
   Render → HTML / PDF / email / streamed markdown
```

The **Report object** (Stage 3) is the contract between research and presentation: `{title, sections[], claims[], sources[], figures[], confidence}`. Renderers and the presentation planner consume it; nothing downstream re-parses prose.

---

## 4. Stage Details (LLD)

### Stage 0 — Foundations & Quick Wins  *(low risk, prerequisite)*

**Goal:** Remove hardcoded depth limits and the keyword research-detector so later stages have clean, config-driven knobs.

**Changes**
- `config/llm_config.yaml`: new `deep_research:` block (see §5).
- `search_web()` (`:1773`): read `max_results`, per-page char budget, and number of paragraphs from config instead of literals `3` / `2000` / `5`. Replace hard truncation with `text_chunker.py` chunking + LLM-selectable chunks.
- `_is_research_query()` (`:3236`): replace keyword/phrase lists with an LLM classification call returning `{"is_research": bool, "depth": "shallow|standard|deep", "rationale": "..."}`. Cache per request. Keep the existing threshold behavior, now driven by the LLM verdict.

**Files:** `fastapi_server_complete.py`, `config/llm_config.yaml`.
**Acceptance:** Same query yields configurable result counts; research-mode decision logged with LLM rationale; no keyword list remains.
**Risk:** Low. Backward-compatible defaults in config.

---

### Stage 1 — Deep Research Engine  *(primary priority)*

**Goal:** Iterative, multi-source, gap-driven research instead of one shallow pass.

**1a. Research Planner (LLM JSON)**
Input: user request + Stage-0 classification. Output:
```json
{
  "sub_questions": [
    {"id": "q1", "question": "...", "sources": ["web","arxiv","news"], "priority": 1}
  ],
  "max_rounds": 3,
  "stop_condition": "All sub-questions have >=2 independent corroborating sources"
}
```
RAICA executes the listed source backends per sub-question. `max_rounds`/`stop_condition` are LLM-proposed but clamped by config ceilings.

**1b. Multi-backend fan-out + dedup**
A thin dispatcher maps each requested source name to the existing tool (`search_web`, `get_news_summaries`, `published_papers_search`, `sec_edgar`, `wikipedia_query`, `document_search`). Results normalized into `citation_mastery` source blocks. URL-level dedup; near-duplicate detection deferred to a later iteration.

**1c. Iterative gather loop (reuses DECIDE→ACT→VERIFY)**
After each round, an LLM **gap-assessment** call returns:
```json
{"status": "sufficient" | "needs_more",
 "gaps": ["unanswered q3", "only one source for claim X"],
 "next_queries": [{"sub_question_id":"q3","query":"...","source":"web"}]}
```
Loop until `sufficient` or config'd `max_rounds`/time budget. No guessing — the LLM decides completion (consistent with RAICA's existing loop doctrine).

**Files (new):** `user_tools/deep_research_engine.py` (orchestrator + dispatcher). Reuses existing tools; adds no new search backends in this stage.
**Acceptance (user-tested):** A deep query produces an evidence pool spanning ≥3 source types with multiple corroborated sub-questions, visible in logs; depth scales with config, not code.
**Risk:** Medium — latency/cost. Mitigated by config budgets (max rounds, max sources, wall-clock cap) and existing caching in `RAICAKnowledgeClient`.

---

### Stage 2 — Fact-Checking & Multi-Model Arbitration  *(primary priority)*

**Goal:** Turn "cited" into "verified," and reconcile multiple models' answers.

**2a. Claim extraction (LLM JSON)**
From the synthesized draft:
```json
{"claims": [{"id":"c1","text":"X grew 20% in 2025","needs_source": true}]}
```

**2b. Cross-source verification (LLM JSON, per claim)**
Each claim checked against the evidence pool (and, if thin, a targeted fresh search):
```json
{"id":"c1","verdict":"supported|contradicted|unverified",
 "confidence":0.0-1.0,"citations":["url1","url2"],
 "note":"two independent sources agree"}
```
Unverified/contradicted claims are flagged inline in the final report (not silently dropped).

**2c. Ensemble synthesis + arbitration**
Run synthesis on **N models** from the existing provider pool (config'd list). Extend the existing `arbitrator` role to a new `arbitrate_research_answers()` path that takes the N drafts + verification table and returns a reconciled answer plus a disagreement summary. Reuses arbitrator monitoring/metrics already in `fastapi_server_complete.py:3740+`.

**Files:** new `user_tools/fact_checker.py`; extend arbitrator logic in `fastapi_server_complete.py` (new function, parallel to `arbitrator_validate_tasks`). Config: `deep_research.arbitration.models`, `deep_research.fact_check.min_sources`.
**Acceptance (user-tested):** Final answer carries a verification table; injected false claims get labeled `contradicted/unverified`; two models disagreeing produces a surfaced, reconciled result.
**Risk:** Medium — N× model cost. Mitigated by config: arbitration only when `depth=deep` or request asks for it.

---

### Stage 3 — Long-Form Report Assembly  *(secondary)*

**Goal:** Break the single-context length ceiling for long reports.

- LLM emits an **outline** (`{sections:[{heading, intent, source_question_ids}]}`).
- Generate **section-by-section**, each grounded in the relevant evidence + verified claims.
- Assemble into the **Report object** (`{title, sections[], claims[], sources[], figures[], confidence}`) — the contract for Stage 4 renderers.

**Files:** new `user_tools/report_builder.py`. Reuses verification output from Stage 2.
**Acceptance:** A "comprehensive report on X" yields a multi-section document longer than a single model context, internally consistent, every section cited.
**Risk:** Low–medium (consistency across sections) — mitigated by passing prior section summaries forward.

---

### Stage 4 — Multi-Modal Presentation (charts + web images only)  *(after research quality lands)*

**Goal:** Let an LLM choose appropriate media and have RAICA produce it. **No generated images.**

**4a. Presentation planner (LLM JSON)**
Given the Report object:
```json
{"media": [
  {"type":"chart","spec":"bar chart of revenue by year","data_ref":"section2"},
  {"type":"web_image","query":"NYSE trading floor","license":"reuse-allowed","section":"intro"},
  {"type":"table","data_ref":"section3"}
]}
```

**4b. Executors**
- `chart` / `table` → extend `user_tools/analytical_visualizer.py` (already LLM-generates matplotlib → PNG → base64; add table rendering).
- `web_image` → **new** `user_tools/web_image_retriever.py`: search images, **filter by license/usage rights**, fetch, validate (size/type, honor the 100-byte binary-logging rule from CLAUDE.md), embed with source attribution. No synthesis.

**4c. Render targets:** existing HTML template, `pdf_generator_tool.py`, email attachments, and streamed markdown with embedded images.

**Files:** extend `analytical_visualizer.py`; new `web_image_retriever.py`; extend renderers. Config: `presentation.web_images.{enabled,license_filter,max_images,max_bytes}`.
**Acceptance (user-tested):** A report renders with relevant charts and at least one correctly-attributed, license-cleared internet image, in HTML and PDF.
**Risk:** Medium — image licensing/correctness. Mitigated by mandatory license filter + attribution; fail-soft (omit image, never block the report).

---

### Stage 5 — Hardening & Evaluation

- Confirm **all** knobs in `llm_config.yaml`; no literals leaked into code.
- Cost/rate controls: per-request round cap, model-call budget, wall-clock timeout.
- Eval harness under `tests/`: research-quality rubric (coverage, corroboration) + citation-accuracy check (do cited URLs actually support the claim?) on a fixed query set.
- Update docs: `README.md`, `docs/production/USER_GUIDE.md` + `DEVELOPER_GUIDE.md`, and a `CHANGELOG_vX.X.X.XX.md` per release. Version bump in `fastapi_server_complete.py` on each code stage.

---

## 5. Configuration Additions (`config/llm_config.yaml`)

```yaml
deep_research:
  enabled: true
  search:
    web_max_results: 8          # replaces hardcoded 3
    per_page_char_budget: 6000  # replaces hardcoded 2000
    per_page_max_blocks: 12     # replaces hardcoded 5 paragraphs
  loop:
    max_rounds_ceiling: 4       # clamps LLM-proposed max_rounds
    wall_clock_seconds: 240
  fact_check:
    enabled: true
    min_sources: 2              # corroboration threshold for "supported"
  arbitration:
    enabled_when: "deep"        # deep | always | never
    models:                     # drawn from existing provider pool
      - deepseek-v4-pro:cloud
      - gpt-oss:120b-cloud
presentation:
  charts: { enabled: true }
  web_images:
    enabled: true
    license_filter: "reuse-allowed"
    max_images: 4
    max_bytes: 5000000
```
(Exact keys finalized at implementation; values above are defaults, not literals in code.)

---

## 6. Sequencing & Gates

| Order | Stage | Gate (user-verified before next) |
|-------|-------|----------------------------------|
| 1 | Stage 0 | Config-driven depth + LLM research-detect working; no keyword list |
| 2 | Stage 1 | Deep multi-round, multi-source evidence pool verified end-to-end |
| 3 | Stage 2 | Verification table + arbitration verified with injected-false-claim test |
| 4 | Stage 3 | Long-form multi-section report verified |
| 5 | Stage 4 | Charts + license-cleared web images render in HTML/PDF |
| 6 | Stage 5 | Eval harness green; docs + version + changelog updated |

Per CLAUDE.md, **no stage is "done" until you test it end-to-end as a user and confirm.** Each stage is a separate review/commit.

### Stage 0 — DONE (v1.0.0.63, verified 2026-05-31)
Web-search depth de-hardcoded (3→8 results, 6000 char/page) and keyword research-detector replaced with an LLM classifier. Verified live on a complex "Sumerian Problem" research request: 27 source blocks / 112 KB delivered intact; final answer passed a grounding audit (0 fabricated URLs). See `CHANGELOG_v1.0.0.63.md`.

### Concrete acceptance criteria derived from the Stage 0 live test
The Stage 0 answer was hallucination-safe but exposed three *credibility* gaps. These are now the acceptance bar for Stages 1–2:

| # | Observed gap (v1.0.0.63) | Must be fixed by | Acceptance test |
|---|--------------------------|------------------|-----------------|
| C1 | Source oversimplification inherited verbatim ("Kramer *coined* it in 1956" vs. the ~1870s reality) | **Stage 2** cross-source reconciliation | Inject two sources that disagree on a date/attribution → final answer flags the conflict instead of picking one silently |
| C2 | Real-but-tangential papers (space archaeology, muon imaging) cited as on-topic | **Stage 1** relevance/credibility weighting | Off-topic retrieved sources are down-ranked/excluded, not woven in as relevant |
| C3 | Closing disclaimer called popular sites (loresandlegends, armstronginstitute) "academic/peer-reviewed" | **Stage 1** credibility grading + **Stage 2** claim labeling | Each source carries a credibility tier; final answer never blanket-labels mixed sources as peer-reviewed |

---

## 7. Open Questions for Implementation Time
1. Stage 2 arbitration default model set — confirm the 2 models to ensemble (cost vs. quality).
2. Web image license source — start with a license-filtered search backend (e.g., openverse/wikimedia-style), confirm preferred provider at Stage 4.
3. Whether long-form (Stage 3) should be automatic for `depth=deep` or only on explicit "report"/"comprehensive" intent (LLM-classified, not keyword).
```
