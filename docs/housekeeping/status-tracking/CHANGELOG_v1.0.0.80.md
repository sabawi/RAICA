# CHANGELOG v1.0.0.80

**Date:** 2026-06-05
**Previous:** v1.0.0.79 (Deep Research 5xx — load-based model split)
**Theme:** Deep Research orchestration — **Phase 3: dynamic action dispatch (open-vocabulary tool integration)**

---

## Summary

Completes the Deep Research → orchestration integration described in
`docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md`. Phases 0–2 connected research → authored
paper → the **hardcoded** file+email delivery path. This release fulfils **Principle 6 (open action
vocabulary via dynamic tool discovery)**: the delivery fan-out now **dynamically dispatches ANY
registered tool** the decomposer names — not just the two file/email capability classes.

Before this change, an action like `create_chart` / `generate_infographic` / `post_substack` that the
decomposer correctly emitted (it is already grounded in the live tool catalog) was dead-lettered and
reported *"not wired yet."* Now every such action is actually executed with the research output as
shared context, and **a newly registered tool becomes dispatchable with zero code changes** (the
Generalization Test).

## How it works (LLM arg-binder → blind dispatch)

For each decomposed action whose `type` resolves to a live tool in `tool_manager.available_functions`
(and that is not the file/email secure pipeline), RAICA now:

1. **Binds arguments via the LLM** (`_dr_bind_and_dispatch_action`): one LLM call is shown the tool's
   **full JSON parameter schema** + the **research output** + the user's requested action/args + the
   **results of prior actions** (sequential, dependency-aware). It returns `{"arguments": {...}}` —
   *RAICA never interprets text or hardcodes per-tool args.*
2. **Substitutes the content placeholder** — for any field that should carry the full paper verbatim,
   the binder emits the literal token `{{RESEARCH_OUTPUT}}`; RAICA replaces it with the real paper
   before dispatch (`_dr_inject_research_output`), so the LLM never retypes the (large) paper and no
   tool-field name is special-cased.
3. **Dispatches blindly** via `tool_manager.safe_function_call(tool_name, json.dumps(arguments))`,
   bounded by a per-action timeout.
4. **Feeds the result forward** into the next action's binder context (dependency-aware sequence),
   and reports each outcome in the delivery footnote (successes quiet, failures explicit — never
   silent).

Failure of one action never aborts the run; binding/dispatch errors are caught and reported.

## No regression — the secure pipeline is untouched

- The proven **file + email** delivery path (`_DR_FILE_CAPS` → `sandboxed_executor`,
  `_DR_EMAIL_CAPS` → `secure_email_sender`) is **unchanged**: recipient-locking for restricted
  clients, doc-fail-blocks-email, attachment chaining, TTL sweep all preserved. The generic pass runs
  **before** it.
- Delivery is still gated by the existing 3-way `_dr_delivery_permitted` (explicit `allow_delivery`
  wins; else auto-trust clients with no `allowed_tools`; else deny) — Phase 3 does not widen who may
  deliver.
- `dynamic_dispatch: false`, a missing binder callable, or an action with no matching live tool →
  the action is reported as *"not wired yet"* exactly as before. Legacy behavior is the fallback.

## Configuration (zero-hardcoded-config)

`config/llm_config.yaml` → `deep_research.engine.delivery`:

```yaml
dynamic_dispatch: true        # master toggle for Phase 3 generic dispatch
binder_max_tokens: 1500       # output cap for each arg-binder LLM call (returns a small JSON object)
action_timeout_seconds: 180   # hard per-action dispatch timeout
context_char_budget: 12000    # research-output chars shown to the binder ({{RESEARCH_OUTPUT}} carries full text)
```

## Files

- `fastapi_server_complete.py`
  - **new** `_dr_bind_and_dispatch_action()` — LLM arg-binder + blind dispatch (returns `(ok, summary)`).
  - **new** `_dr_inject_research_output()` — recursive `{{RESEARCH_OUTPUT}}` placeholder substitution.
  - **new** `_dr_dispatch_failed()` — failure detection from RAICA's own structured result markers
    (not NLP on tool content).
  - `_run_dr_delivery()` — new `tool_defs` + `generate_stream` params; runs the generic dispatch pass
    (sequential, dependency-aware) before the file/email pipeline; emits dispatch footnotes.
  - DR branch call site passes `tool_defs=_dr_tool_defs` and `generate_stream=_dr_generate_stream`;
    `_dr_tool_defs` now also initialized in the catalog-build `except` (avoids a NameError when the
    catalog can't be built).
- `config/llm_config.yaml` — `deep_research.engine.delivery`: `dynamic_dispatch`, `binder_max_tokens`,
  `action_timeout_seconds`, `context_char_budget`.
- `version.py` (→ 1.0.0.80), `README.md` (version → 1.0.0.80), this changelog.
- `docs/DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md` — Phase 3 marked done.

## Out of scope (documented boundary)

- **Cross-category artifact handoff** — attaching a *generic* tool's output file to the delivery
  email, or embedding generated media into the rendered PDF. Generic tools run and report; chaining
  their *file artifacts* into the email/PDF is tracked under `DEEP_RESEARCH_MULTIMODAL_PLAN.md`.
- Multimodal/media embedding in the paper itself (separate plan).

## Migration / compatibility

- No breaking changes. Existing research-only and research→PDF→email flows behave identically.
- New behavior activates only when (a) `dynamic_dispatch: true`, (b) the request decomposes into
  actions beyond file/email, and (c) those actions resolve to live tools — and only for clients that
  already pass delivery authorization.

## Verification

Pending live end-to-end verification by the user (a compound request that decomposes into a non
file/email action resolving to a registered tool — confirm the `📦 DR dynamic dispatch ran '<tool>'`
log line and the delivery footnote, with research-only and research→PDF→email flows unchanged).
