# CHANGELOG v1.0.0.71

**Date:** 2026-06-04
**Previous:** v1.0.0.70
**Trigger:** Phase 1 of the Deep Research → Orchestration integration — LLM-driven request
decomposition with an OPEN, tool-grounded action vocabulary.

**Design reference:** `docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md` (Phase 1 + Principle 6).

---

## Summary

Generalizes Phase 0's research-request normalizer into a full **request decomposer**. Before
researching, an LLM call now decomposes a (possibly compound) request into three parts:

```json
{ "research_request": "<delivery-stripped research+writing intent>",
  "deliverable_spec": { "format": "...", "min_words": 0, "style": "...", "sections": ["..."] },
  "actions": [ { "type": "<capability from the LIVE tool catalog>", "args": {} } ] }
```

The action vocabulary is **open and grounded in dynamic tool discovery** (Principle 6): the decomposer
is fed RAICA's live tool catalog (`tool_manager.get_tools_definitions()` — every tool/plugin name +
description) and may only name capabilities that actually exist; anything the user asks for with no
matching tool is tagged `{"type":"unsupported"}` rather than invented. New tool → new possible action,
with **no code change** in the decomposer or orchestrator.

**Phase 1 is parse-only:** research + synthesis still run on `research_request` (Phase 0 behavior
preserved — no refusing over "can't email/PDF"); `deliverable_spec` + `actions[]` are **logged and
returned** for the orchestrator's downstream fan-out (Phase 2), **not executed**.

---

## Changes

- **`research/pipeline.py`:**
  - `_normalize_research_request` → **`_decompose_request(generate_stream, config, user_request, tool_catalog)`**
    returning `{research_request, deliverable_spec, actions}`. Reuses `_collect_stream` +
    `extract_json_object`. Graceful fallback to `{research_request: original, deliverable_spec: {}, actions: []}`
    on any failure (no regression).
  - New `_format_tool_catalog()` renders the live catalog into the decomposition prompt.
  - `run_deep_research_pipeline()` gains a `tool_catalog` param; logs the parsed plan
    (`🧩 Request decomposed — …`); returns `deliverable_spec` + `actions` in its result dict.
- **`fastapi_server_complete.py`** (deep-research branch): builds the live tool catalog via
  `tool_manager.get_tools_definitions()` (name + description, incl. user tools & plugins) and passes
  `tool_catalog=` to the pipeline.
- **`docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md`:** added Principle 6 (open action vocabulary via
  dynamic tool discovery) + the open-vocabulary decomposition contract (§4).

## Compliance with CLAUDE.md

- LLM decides → JSON; RAICA only parses. **No keyword matching**; **no hardcoded action enum**.
- Open vocabulary via **dynamic discovery** of the live registry (Generalization Directive).
- Unknown capability → reported (`unsupported`), never faked (fail explicitly, no silent guess).
- No regression: parse-only; failure path = legacy behavior; `normalize_request` toggle still applies.

## Verification (live, user-confirmed via OpenWebUI)

Re-ran the food-cuisine academic-paper compound prompt:

- `🧩 Request decomposed — deliverable_spec={'format':'academic_paper','min_words':1500,'style':'arXiv',
  'sections':['abstract','introduction','background','main_content','discussion','conclusion','references']},
  actions=['pdf_generator','secure_email_sender']` — deliverable captured; both actions correctly mapped
  to REAL registered tools (no hallucination, nothing `unsupported`).
- No regression: pipeline complete in 258.5s, 86 claims checked (77 supported / 9 unverified), paper delivered.

## Known limitations / follow-ups

- **Actions not executed yet (Phase 2).** Bridge `actions[]` → existing POST-LLM executor
  (`_execute_missing_tools_post_llm` :7200 / call :10531). Note the decomposer emits `pdf_generator`
  while the POST-LLM file/PDF path uses `sandboxed_executor` + PDF conversion → Phase 2 needs a small
  action→executor name mapping.
- Email channel still `enabled: false` in `communication_hub.yaml` (Phase 2 client-scoped re-enable).
- Research-backend reliability + gate over-fire on OpenWebUI housekeeping calls — independent, tracked separately.

## Dependencies

- None new.

## Migration

- None required. Same `deep_research.engine.normalize_request` toggle now controls decomposition
  (default enabled). No request/response contract change for clients.

## Files

- `research/pipeline.py` — `_decompose_request` + `_format_tool_catalog` + pipeline wiring/return.
- `fastapi_server_complete.py` — live tool-catalog build + `tool_catalog=` pass-through.
- `docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md` — Principle 6 + contract.
- `version.py` (→ 1.0.0.71), `README.md`, this changelog.
