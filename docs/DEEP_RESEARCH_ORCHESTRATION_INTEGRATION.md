# Deep Research → Orchestration Integration (Context-Producer Model)

**Status:** DRAFT (design + phased plan) — NO code written yet. Each phase is gated on explicit approval.
**Date:** 2026-06-03
**Author:** RAICA Development Team (with Claude Code)
**Related:** [`DEEP_RESEARCH_MULTIMODAL_PLAN.md`](DEEP_RESEARCH_MULTIMODAL_PLAN.md) (research depth + multimodal *presentation* — sibling concern), [`POST_LLM_EXECUTION_ARCHITECTURE.md`](POST_LLM_EXECUTION_ARCHITECTURE.md) (the action substrate we reuse), [`CONTEXT_FIRST_ARCHITECTURE.md`](CONTEXT_FIRST_ARCHITECTURE.md).

---

## 1. Motivation

RAICA = **RAG AI Context Agency**. Deep Research was built laser-focused on producing an excellent *research answer*, but as a **terminal, text-only mode**: when the gate fires, the pipeline runs and the request `return`s before any action machinery. This severs research from the rest of RAICA's purpose — making the research output the **context that downstream subagents act on** (format to PDF/HTML, save to file, email, post to Substack/Medium/social).

### Triggering incident (2026-06-03, via OpenWebUI)

Prompt (compound): *"do a deep research on … produce an academic paper … ≥1500 words … Generate the final publishable paper in PDF format. Email the paper to user@example.com."*

Outcome: full refusal. Root causes (from `logs/server_complete.log`, run at 21:21):
1. **Architectural:** gate fired → pipeline ran → `return` at `fastapi_server_complete.py:~8268`, **bypassing POST-LLM execution** (the path that does PDF/file/email). The tools *exist* (`user_tools/pdf_generator_tool.py`, `user_tools/secure_email_sender.py`) but were unreachable in this path.
2. **Synthesis saw the action verbs:** the synthesizer was handed *"Generate PDF, email it"* and refused the whole task (incl. writing the paper) instead of producing the deliverable text. `synthesize 9.4s`, `Claims checked: 0`.
3. **Thin evidence (independent):** Semantic Scholar `429`, DOAJ `404`, arXiv `429`, many source fetches `403/404/410` → off-topic/insufficient corpus; `Stop reason: max_rounds`.

This doc addresses #1 and #2 (orchestration). #3 (backend reliability) and presentation/multimodal are tracked separately.

---

## 2. Guiding principles (from CLAUDE.md — non-negotiable)

1. **LLM decides, RAICA executes JSON.** Request decomposition (research vs. deliverable vs. delivery actions) is an LLM call returning structured JSON — **no keyword matching** on "PDF"/"email".
2. **Separate research / authoring / delivery.** Research produces *context*; authoring writes the *deliverable*; delivery *consumes* it. The research/synthesis stage must never see action verbs (that is exactly what caused the refusal).
3. **Reuse, don't rebuild.** Action fan-out targets the **existing POST-LLM execution machinery** + existing tools. No parallel action engine.
4. **No regression.** Deep Research must keep working at every phase boundary. The terminal "just answer" path remains the default when there are no action directives.
5. **Zero hardcoded config.** New thresholds/flags live in `config/llm_config.yaml`; fail fast if missing.

---

## 3. Current state (evidence)

| Component | Location | Role today |
|-----------|----------|-----------|
| Gate | `research/gate.py` `deep_research_gate()` | Fires on research-y prompts (semantic). Over-fires on OpenWebUI title/tag follow-ups. |
| Pipeline | `research/pipeline.py:203` `run_deep_research_pipeline()` | Returns `{answer, evidence?, engine_metadata, synth_metadata, total_seconds}` — already a clean **context object** (`:253`). |
| Engine (Stage 1) | `research/engine.py` | plan → gather → grade → returns `evidence` list + metadata. |
| Synthesizer (Stage 2) | `research/synthesis.py` `run()` :579 | Writes `final_answer`. **VERIFIED:** threads raw `user_request` (incl. action verbs) into every prompt — roster :330, audit :357, `synthesize` :466, `arbitrate` :507, `verify` :553. Refusal root cause. |
| DR branch (terminal) | `fastapi_server_complete.py` :8214 `if _dr_triggered` → task :8246 (passes `actual_user_prompt` :8248) → **`return` :8274** | Bypasses everything below incl. POST-LLM execution. |
| POST-LLM execution | `_execute_missing_tools_post_llm()` **def :7200, call site :10531** (doc's old 8947/9156 are STALE); `email_intercepted` :9229, `pending_auto_execution` :9624; deferral :8939-9193 | Turns `complete_llm_response` → HTML/PDF/MD/TXT → email-with-attachment. |
| Format/recipient detection | inside the executor :7220-7327 | **VERIFIED:** format via `if "pdf" in user_prompt_lower` (:7221); recipient via `_detect_html_email_request(tools_results, user_prompt)` (:7327); filename/title via `_generate_dynamic_*(user_prompt,…)`. **Parses the user prompt** — see Audit Finding A. |
| Formatters/tools | `utils/html_generator.py`, `user_tools/pdf_generator_tool.py` (`_generate_pdf` :328), `user_tools/secure_email_sender.py` (registered in tool_manager :456) | Action subagents that already exist. |
| Email channel | `config/communication_hub.yaml` :43 | **VERIFIED** `email: enabled: false` (NewX lockdown). Must be re-enabled, scoped to trusted clients. |

**Key insight:** RAICA already has *both halves* — a context producer (the pipeline) and an action executor (POST-LLM). They are disconnected by one early `return` (:8274).

### 3a. Code audit findings (verified against executing code, 2026-06-03)

Cursory audit confirming this doc matches `fastapi_server_complete.py` (v1.0.0.69), `research/synthesis.py`, `research/pipeline.py`, `config/communication_hub.yaml`.

- **All structural claims hold.** Context producer (pipeline returns `{answer, evidence, metadata}` :253), terminal early-return (:8274), POST-LLM executor (:7200/:10531), deferral (:8939-9193), tools, and disabled email channel (:43) all exist as described.
- **Stale line numbers corrected.** `POST_LLM_EXECUTION_ARCHITECTURE.md` (Oct-2025, "v1.0.3.7") cites the executor at 8947/9156; in current code it's def :7200, call :10531. That doc needs a refresh (tracked separately). This doc now uses verified numbers.
- **Finding A — the POST-LLM executor decides format & recipient by parsing `user_prompt`** (`if "pdf" in user_prompt_lower` :7221; `_detect_html_email_request(...)` :7327; `_generate_dynamic_filename/title(user_prompt,…)`). Two consequences:
  1. *Validates the research/delivery split.* The full prompt (with "PDF", "email to X") must reach the **executor**, while the **synthesizer** must NOT see it. Same original request, two consumers, fed differently — exactly the Phase 0/Phase 2 separation. The minimal Phase 2 bridge can pass the original prompt straight to the executor and reuse its existing (working) parsing; an explicit typed action plan is a later refinement (Open Decision #2).
  2. *Pre-existing anti-pattern.* This keyword parsing technically violates the CLAUDE.md "no keyword routing" rule. We are **reusing** it, not extending it; if/when we replace prompt-parsing with the orchestrator's structured action plan, that also retires the anti-pattern. Not a blocker for the retrofit.
- **Finding B — the failing PDF/email would have worked in the normal flow.** `"pdf" in user_prompt_lower` (:7221) matches "...in PDF format", and the recipient is in the prompt — so the tools were ready; only the DR early-return (:8274) blocked them. Confirms the retrofit is a *connection* problem, not a missing-capability problem.
- **Finding C — Phase 0 is precisely scoped.** `research/synthesis.py` interpolates `user_request` into all five prompts (:330/:357/:466/:507/:553), sourced from `actual_user_prompt` passed at :8248. Phase 0 = pass a research-only spec to the pipeline/synthesizer while preserving the full request for the (future) orchestrator + executor.

---

## 4. Target architecture

```
Compound request  (e.g. "research X → academic paper → PDF → email")
   │
   ▼  ORCHESTRATOR — LLM-driven decomposition (structured JSON):
   │     { research_spec:   {...},                      // what to research
   │       deliverable_spec:{format:"academic_paper", min_words:1500, style:"arXiv"},
   │       actions: [ {type:"render_pdf"}, {type:"email", to:["user@example.com"]} ] }
   │     (actions empty → behaves exactly like today: terminal answer)
   │
   ▼  RESEARCH STAGE  (async / independent — already an asyncio task)
   │     run_deep_research_pipeline(research_spec ONLY — no action verbs)
   │     → RESEARCH CONTEXT { answer, evidence[], citations, audit_metadata }
   │
   ▼  AUTHORING STAGE  (consumes context; only if a deliverable_spec is present)
   │     subagent writes the formatted deliverable FROM research context
   │     → complete_llm_response  (the publication-ready paper text)
   │
   ▼  ACTION FAN-OUT  (reuse POST-LLM execution; subagents parallelizable)
   │     feed complete_llm_response + actions into the SAME machinery Path 1/2 use:
   │       ├─ render_pdf  → pdf_generator_tool
   │       ├─ save_file   → sandboxed_executor(create_file)
   │       ├─ email       → secure_email_sender (attach rendered file)
   │       └─ post_*      → (future) Substack / Medium / social subagents
   │
   ▼  Orchestrator aggregates results → reports deliverables to user
```

### The bridge (concrete)

Today POST-LLM execution is gated on flags set during the tool-calling phase (`email_intercepted` :9229, `pending_auto_execution` :9624, `verification_result`) and consumes `complete_llm_response`; the executor is `_execute_missing_tools_post_llm(missing_tools, tool_manager, tools_results, complete_llm_response, user_prompt, llm_manager)` (def :7200, called :10531). The DR path sets none of these and exits early at :8274. The bridge:

- Instead of `return` at :8274, when `actions` is non-empty: call `_execute_missing_tools_post_llm()` directly with `complete_llm_response = <authored deliverable>`, `missing_tools = [<sandboxed_executor/create_file>, <secure_email_sender>]` derived from the action plan, and `user_prompt = <the original request, WITH action verbs>` (the executor parses it for format + recipient — Finding A), `tools_results = <research evidence/context>`.
- When `actions` is empty: unchanged — stream the answer and return (today's behavior).

This keeps **one** action executor (POST-LLM), satisfying "reuse, don't rebuild."

---

## 5. Phased implementation plan

Each phase is independently shippable, version-bumped, and leaves Deep Research working. **Gated on approval at each boundary.**

### Phase 0 — Decouple research from action verbs (fix the refusal) — *smallest, highest value*
- Strip/neutralize delivery directives from the text the **synthesizer** sees, so it always produces the best answer/paper and never refuses because of PDF/email it "can't do."
- Where: `research/synthesis.py` (and/or the gate handoff in `fastapi_server_complete.py`).
- Outcome: the exact failing prompt now returns the *paper text* (no PDF/email yet, but no refusal). De-risks everything downstream.
- Risk: low. No new subsystems.

### Phase 1 — Orchestrator decomposition (detect compound requests)
- Add an LLM-driven decomposition call that returns `{research_spec, deliverable_spec, actions[]}` as JSON. Empty `actions` → today's terminal path.
- Where: a new pre-DR step in the DR branch (`fastapi_server_complete.py`), config-driven prompt.
- Outcome: RAICA *knows* a request is "research + deliver", without changing behavior yet (actions parsed but not executed → still terminal). Observability log of the parsed plan.
- Risk: low/medium. Pure addition; gated behind a config flag.

### Phase 2 — Bridge research output → POST-LLM execution (PDF + file + email)
- Wire `actions` → the existing Path 1/Path 2 POST-LLM functions, using the authored content as the body. Re-enable `secure_email_sender` for trusted clients (scope: OpenWebUI yes, locked-down NewX bots no — via `communication_hub.yaml` + per-request scoping).
- Outcome: the failing prompt now **researches → writes paper → renders PDF → emails it.** End-to-end.
- Risk: medium. Reuses proven machinery; main work is the bridge + email-scope policy.

### Phase 3 — Authoring stage (publication-grade deliverable)
- A dedicated authoring subagent (or a `deliverable_spec`-parameterized synthesis mode) that turns research context into the requested artifact: arXiv-format sections, ≥N words, footnotes, references section.
- Outcome: deliverable quality matches "publishable paper" requests, distinct from a normal research answer.
- Risk: medium. Mostly prompt/format engineering on existing context.

### Phase 4 — Additional delivery channels (subagents)
- Add Substack / Medium / social / file-export subagents on the same fan-out (each a tool the action plan can target). License/format-aware (ties into `DEEP_RESEARCH_MULTIMODAL_PLAN.md` for embedded media).
- Risk: per-channel; additive.

### Cross-cutting (fold in opportunistically)
- **Gate over-fire guard:** skip the DR gate for OpenWebUI housekeeping calls (title/tag generation) — detect by the OpenWebUI task envelope, not by topic. (`research/gate.py` / endpoint.)
- **Research-backend reliability:** Semantic Scholar/DOAJ/arXiv throttling/404 — independent; improves evidence quality regardless of orchestration.
- **Email channel scoping:** `communication_hub.yaml` `email.enabled` is currently false; Phase 2 needs a client-scoped re-enable (trusted endpoints can email; NewX bots stay locked).

---

## 6. Open design decisions (to resolve during Phase 1 doc review)

1. **Authoring vs. synthesis:** extend `research/synthesis.py` with a `deliverable_spec`, or a separate authoring subagent? (Leaning: separate, so research synthesis stays clean.)
2. **Action plan schema:** finalize the JSON contract for `actions[]` so it maps 1:1 onto POST-LLM's existing `missing_tools` / intercepted-email shapes.
3. **Parallelism:** which actions run concurrently (e.g. render PDF then email is sequential; save-file + post-social are parallel)? Orchestrator dependency graph vs. simple sequence for v1.
4. **Streaming UX:** how to stream progress across research → authoring → actions (reuse the DR `on_progress` channel).
5. **Email-scope policy:** how a client declares trust (OpenWebUI) vs. locked-down (NewX) — per-request flag like `deep_research`, or endpoint/config-based.

---

## 7. Non-goals (this doc)
- Image/audio/video generation (see multimodal plan; image *generation* explicitly out of scope there).
- Fixing search-backend rate limits (separate reliability track).
- Replacing the POST-LLM executor (we reuse it).
