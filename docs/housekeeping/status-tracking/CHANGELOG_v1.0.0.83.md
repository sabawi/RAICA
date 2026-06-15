# CHANGELOG v1.0.0.83

**Date:** 2026-06-05
**Previous:** v1.0.0.82 (Convergence Phase 1 — shared delivery-policy module)
**Theme:** **Convergence Phase 2 — shadow-mode LLM intent classifier**

> Part of the Context-and-Action Substrate Convergence — see
> `docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md`. **Zero behavior change**: the shadow classifier is
> observational only (legacy classifier stays authoritative) and is **disabled by default**.

---

## What changed

### New module — `orchestration/intent.py` (LLM intent classifier)
The LLM replacement-in-waiting for the 304-line keyword classifier `_verify_task_completion`. Given a
user request + the LIVE tool catalog, it returns the post-generation delivery/action tools the request
needs — grounded in the catalog (open vocabulary, no keyword matching):
- `classify_intent_actions(collect_fn, tool_catalog, user_prompt)` → `{actions, tools, needs_delivery,
  raw, ok}`. The LLM call is **injected** (`collect_fn`), so the module is decoupled and unit-testable.
- `to_verifier_shape(intent_result, tools_called)` → `{complete, missing_tools}` (legacy-comparable).
- `compare(legacy, shadow)` → divergence record (`agree_complete`, `agree_tools`, `only_legacy`,
  `only_shadow`).

### Shadow runner (fastapi_server_complete.py)
Right after the legacy verifier runs, `_schedule_shadow_classification(...)` fires a **non-blocking
background task** (`_run_shadow_classifier`) that runs the LLM classifier, compares it to the legacy
result, emits a `🕵️ SHADOW CLASSIFIER` log line, and appends disagreements to a JSONL file for offline
analysis. It **never** touches the response path (fully guarded, timed-out, reference-held to avoid GC).
The legacy `verification_result` remains the only thing the request acts on.

### Config — `convergence.shadow_classifier` (new, default OFF)
```yaml
convergence:
  shadow_classifier:
    enabled: false            # turn on to collect divergence data
    sample_rate: 1.0          # fraction of eligible requests to shadow
    model: deepseek-v4-flash:cloud
    max_prompt_chars: 8000    # cost guard
    max_tokens: 800
    timeout_seconds: 60
    divergence_log: logs/shadow_classifier_divergence.jsonl
```

## Why (and what the shadow already shows)
A live end-to-end smoke test of the real LLM classifier already demonstrates the value — and that we
are right NOT to cut over yet:

| Prompt | LLM shadow | Legacy | Note |
|---|---|---|---|
| "Write a short poem about autumn leaves" | `[]` | `[sandboxed_executor, secure_email_sender]` | **LLM correct; legacy false-positive** (`"write a"` trigger) |
| "What is the capital of France?" | `[]` | `[]` | agree |
| "Send an email to bob@example.com" | `[secure_email_sender]` | `[secure_email_sender]` | agree |
| "Email the above response as a HTML document" | `[secure_email_sender]` | `[sandboxed_executor, secure_email_sender]` | diverge — LLM missed the file-creation step |
| "Research EVs → PDF → email" | `[raica_research_agent]` | `[sandboxed_executor, secure_email_sender]` | diverge — LLM picked research, missed delivery |

These divergences are the deliverable of Phase 2: they tell Phase 3 exactly what the classifier prompt
must learn (emailing a *document* implies a file step; a request can need BOTH research and delivery
tools) before the LLM classifier can become authoritative.

## Tests
- `tests/utilities/test_intent_classifier_llm.py` (NEW) — 11 unit tests (fake injected collector, no
  network): parsing, dedup, `unsupported` filtering, prose-wrapped JSON, error safety,
  `to_verifier_shape`, and `compare` (incl. the poem false-positive divergence).
- Full convergence + characterization suite: **86 passed, 0 skipped.**
- Live smoke test confirmed the real LLM path works end-to-end.
- Server boots healthy on v1.0.0.83; shadow disabled by default → no behavior change.

## Files
- `orchestration/intent.py` (NEW)
- `fastapi_server_complete.py` — `_schedule_shadow_classification` / `_run_shadow_classifier` /
  `_append_shadow_divergence`; non-blocking trigger after the verifier.
- `config/llm_config.yaml` — `convergence.shadow_classifier` block.
- `tests/utilities/test_intent_classifier_llm.py` (NEW)
- `version.py` (→ 1.0.0.83), `README.md`, this changelog, convergence doc (Phase 2 marked done).

## Not in this phase
- Phase 3 (cut intent classification over to the LLM, per category, using the divergence data —
  including the classifier-prompt tuning the smoke test flagged), Phase 4 (unify dispatch), Phase 5
  (delete the keyword classifier + dead code). The legacy classifier remains authoritative.
