# CHANGELOG v1.0.0.85

**Date:** 2026-06-05
**Previous:** v1.0.0.84 (Convergence Phase 3a baseline + 3b prompt tuning)
**Theme:** **Convergence Phase 3c — LLM intent classifier cutover (full tool set), flag-gated, OFF by default**

> Part of the Context-and-Action Substrate Convergence — `docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md`.
> **Ships dark: default `mode: legacy` → ZERO behavior change.** The cutover only activates when an
> operator flips `convergence.intent_classifier.mode` to `llm`.

---

## What changed

### `_maybe_llm_authoritative` (fastapi_server_complete.py)
A new step right after the legacy verifier. When `convergence.intent_classifier.mode == 'llm'`, it runs
the LLM intent classifier (`orchestration.intent.classify_intent_actions`) **inline** and uses its
result — the **FULL tool set** (decision + actual tools) — as the authoritative `verification_result`
(legacy-shaped `{complete, missing_tools, pattern:"llm_intent", reason}`). The legacy classifier is
**always still computed and is the fallback**: wrong mode, over-length prompt, classifier not-ok, or
timeout → the legacy result is returned untouched. So `mode: legacy` (the default) is a guaranteed
no-op.

The Phase-2 shadow comparison is skipped when the LLM is already authoritative (the comparison would be
self-referential).

### Config — `convergence.intent_classifier` (new, default `mode: legacy`)
```yaml
convergence:
  intent_classifier:
    mode: legacy                     # legacy | llm
    model: deepseek-v4-flash:cloud
    max_tokens: 800
    timeout_seconds: 30              # exceeded → legacy fallback
    max_prompt_chars: 12000          # over → legacy fallback (latency/cost guard)
```

## Why this is safe to ship now
- **Default off** → no behavior change; committing/restarting changes nothing.
- **Legacy is the fallback** on every failure path (mode, length, error, timeout).
- Functionally verified (direct calls): `mode=legacy` returns the legacy dict unchanged; `mode=llm`
  turns the legacy "write a poem" FALSE-POSITIVE (`missing=[sandboxed_executor, secure_email_sender]`)
  into the correct `complete=True, missing=[]`, and resolves "email the above as HTML" to the full
  `[pdf_generator, secure_email_sender]`.
- Baseline (v1.0.0.84): LLM delivery-decision 100% stable vs legacy 71.9%; exact-tool stability 93.8%.

## Executor coupling (Phase 4 boundary)
When `mode: llm`, the LLM's chosen `missing_tools` feed the existing POST-LLM executor, which natively
dispatches **file** (`sandboxed_executor`), **email** (`secure_email_sender`), and **publish**
(`social_media_*`, via the deferred-plugin branch). Other LLM picks (e.g. an image/chart tool) await
**Phase 4** generic dispatch in the executor; failures there return error strings (no crash). This is
the known, documented coupling the full-tool-set scope entails.

## How to activate (operator)
Set `convergence.intent_classifier.mode: llm` and restart. Watch for `🧭 INTENT(llm) AUTHORITATIVE`
log lines (they show the LLM decision and what legacy would have said). Revert by setting `mode: legacy`.
**Recommended:** enable on a non-production/observed window first; verify the invariants (meta-task
suppression, no spurious delivery on "Thanks!"/questions, correct delivery on real requests) end-to-end.

## Tests
- Deterministic suite unchanged & green (mode defaults to legacy): characterization goldens, policy,
  intent unit, legacy baseline. Full convergence suite **92 passed**.
- Server boots healthy on v1.0.0.85.

## Files
- `fastapi_server_complete.py` — `_maybe_llm_authoritative`; wired at the verifier call site; shadow
  skipped in llm mode.
- `config/llm_config.yaml` — `convergence.intent_classifier` block.
- `version.py` (→ 1.0.0.85), `README.md`, this changelog, convergence doc (Phase 3c marked shipped-dark).

## Next
- **Operator validation** of `mode: llm` end-to-end, then default it on once confident.
- **Phase 4** — unify dispatch so the executor can run ANY LLM-chosen tool (image/chart/etc.), not just
  file/email/publish; then **Phase 5** — delete the legacy keyword classifier + dead code.
