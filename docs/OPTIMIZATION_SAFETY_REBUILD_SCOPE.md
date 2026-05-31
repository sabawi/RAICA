# Scope: Rebuilding the Optimization-Safety Engine (Option B)

**Status:** SCOPING ONLY — no implementation. Produced so we can decide whether to build.
**Date:** 2026-05-31
**Context:** The research classifier (Stage 0) feeds a context-optimization subsystem whose **core engine module is missing from the repo** (`archive/experimental/optimization_safety.py` — never committed; only its test survives). This document scopes a careful, fully-hardened rebuild against the surviving spec.

---

## 1. Why this matters / why it was likely set aside

The engine sits **on the critical path between tool results and the Primary LLM**. Its job is to *compress* large tool output so it fits the model context window. The inherent danger:

> Bad compression silently drops tool data the LLM needed → incomplete/wrong answers, with no error raised.

That is a direct violation of the project's cardinal rule ("NEVER regress… NEVER declare fixed until tested end-to-end"). So the subsystem was built **safety-first** (preserve → validate → reject-on-doubt → gradual rollout → auto-rollback). The most plausible reason it was shelved: **the risk of silent context corruption outweighed the benefit**, and rather than ship something not fully trusted, the engine was moved to `archive/experimental/` and then lost, while the *fail-safe* (`_original_processing_fallback`) kept the server correct. Today the server is safe but does **no** validated optimization.

**Strategic value of rebuilding:** Stages 1–3 of the deep-research plan will generate *much larger* multi-source evidence pools. Naive truncation (`TextChunker` at a fixed threshold) risks dropping sources mid-research. A *validated, reversible* compressor with metrics and gradual rollout is the right tool for that future load — **if** it's hardened enough to trust.

---

## 2. What exists vs. what's missing

| Component | State | Location |
|-----------|-------|----------|
| `OptimizationController` (feature flags, % rollout, metrics, health check, emergency rollback) | ✅ Present, production-grade | `integrations/optimization_controller.py` (14KB) |
| Server integration (`process_with_safe_optimization`, adaptive threshold, partial-opt, metrics, admin endpoints `/optimization/*`) | ✅ Present, wired | `fastapi_server_complete.py` |
| `_attempt_partial_optimization` (gentler 2-tier compression) | ✅ Present in server | `fastapi_server_complete.py:3181` |
| Research classifier (sets 0.90/0.95 threshold) | ✅ Present (Stage 0 rebuilt it) | `fastapi_server_complete.py:3277` |
| Test suite (executable spec, 370+ lines) | ✅ Present but un-runnable (import fails) | `tests/integration/test_optimization_safety.py` |
| **Engine: `ToolOutputPreserver`, `OptimizationValidator`, `ValidationResult`, `safe_optimize_llm_input`, `attempt_optimization`** | ❌ **MISSING** | `archive/experimental/optimization_safety.py` (never committed) |

Only **one file** is missing. Everything around it is intact.

---

## 3. Reconstructed API contract (the spec to build against)

Derived from BOTH the test suite (authoritative for unit behavior) AND the live server integration (authoritative for runtime). Where they disagree, the rebuild must satisfy **both** (see §4).

### 3.1 `ToolOutputPreserver`
- `original_data: list | None` — deep copy of input tool_results (isolation: mutating source must NOT change it).
- `preservation_timestamp` — set on preserve.
- `safety_checksums: dict` — keyed `"tool_0"`, `"tool_1"`, … (one per result).
- `preserve_original(tool_results: list) -> str` — stores deep copy + checksums; returns a human-readable summary string containing each tool's name (e.g. `get_news_summaries`, `stock_analyzer`). Handles empty list and malformed entries gracefully.
- `verify_integrity() -> bool` — recompute checksums vs. stored; `False` if `original_data` was mutated/corrupted.

### 3.2 `ValidationResult` (dataclass)
- `score: float` (0–100), `issues: list[str]`, `compression_ratio: float`, `severity_counts: dict` (must include key `"critical"`; expect `high/medium/low` too).

### 3.3 `OptimizationValidator`
- `min_validation_score: float` (default ~75; the server treats ≥ threshold as pass; test sets it to 99 to force failure and to 0-ish implicitly for pass).
- `async validate_optimization(original, optimized: str, user_prompt: str) -> ValidationResult`
  - **`original` may be a `list[dict]` (test) OR a pre-joined `str` (server).** Must accept both, positional and keyword.
  - Checks (each contributes to score & issues):
    1. **Tool coverage** — every tool's content/signature represented in `optimized`; missing tools → `severity_counts["critical"] > 0`, score < 75.
    2. **Keyword preservation** — salient terms from the *original* retained; many missing → score < 75.
    3. **User-intent alignment** — intent terms from `user_prompt` present; missing → issue text contains `"intent keywords missing"`.
    4. **Compression ratio** — `len(optimized)/len(original)`; `< 0.2` → `"Excessive compression"` issue + critical; healthy band ~`0.2–1.5`.
  - **Generalization requirement:** keyword/intent/coverage signals must be derived **dynamically from the actual original text and prompt** — NOT a static domain dictionary (per CLAUDE.md anti-hardcoding directive).

### 3.4 module-level `async attempt_optimization(tool_results, user_prompt) -> str`
- The actual compressor (LLM- or TextChunker-based summarization that fits the window while keeping every tool's key facts).
- **Must be a module-level, monkey-patchable coroutine** (the test patches `optimization_safety.attempt_optimization`).

### 3.5 `async safe_optimize_llm_input(tool_results, user_prompt, preserver, validator) -> dict`
Orchestration + the four documented outcomes:

| Outcome | `input_type` | Required keys | Trigger |
|---------|--------------|---------------|---------|
| Success | `"optimized"` | `content`, `original_backup`, `validation_score` (≥ min) | compression validated |
| Validation fail | `"original_fallback"` | `content`*, `optimization_attempted: True`, `fallback_reason`, `validation_score` | score < min |
| Exception | `"original_safe"` | `content`*, `error`, `validation_score: 0` | `attempt_optimization` raised |
| Integrity fail | `"emergency_fallback"` | `content`*, `error` containing `"integrity check failed"` | `verify_integrity()` False |

\* **`content` is required on EVERY return** because the live server reads `optimization_result["content"]` in the fallback branch (`fastapi_server_complete.py:3492`). In fallback shapes, `content` = the preserved original text. (The unit test does not assert this, but the server will `KeyError` without it — this is conflict #2.)

---

## 4. Contract conflicts & ambiguities discovered (the risk hot-spots)

1. **`validate_optimization` dual signature** — test: `(list, str, str)` positional; server `_attempt_partial_optimization`: `(original_content=str, optimized_content=str, user_prompt=str)` keyword. → Build a tolerant signature normalizing `original` to text internally.
2. **`content` missing in fallback contracts** — server requires it; tests don't. → Always include `content`.
3. **`fallback_reason` type** — server does `"validation" in optimization_result.get("fallback_reason", [])` (treats it as a **list/iterable**), then elsewhere logs it as a string. → Make it a `list[str]` and ensure substring checks still work.
4. **`validation_score` presence** — server reads `.get("validation_score", 0)`; success path needs the real score. → Always include.
5. **Pre-existing hardcoded-overflow bug (from audit)** — `docs/DEEP_CODE_AUDIT_2026-05-05.md` ISSUE ~line 100: fallback uses hardcoded `65536 * 1.05`, not the model's real `num_ctx`. The engine's "needs compression?" math (`max_context_window * 0.8 * threshold`) similarly estimates. → Fix to use real model context window during this work.
6. **Hardcoded tool list in `_attempt_partial_optimization`** — `high_priority_tools = ['search_web', ...]` violates the anti-hardcoding directive. → Replace with config or LLM-decided priority during the rebuild.

These six items are exactly why a naive rebuild "to pass the tests" would still break production. A *hardened* rebuild must satisfy the union of test + server + audit.

---

## 5. Hardening requirements (non-negotiable for this engine)

1. **Never lose data silently.** Original is deep-copied + checksummed before any compression; integrity verified before trusting output.
2. **Reject on doubt.** Any validation failure, exception, or integrity failure → return preserved original (the server still gets usable `content`).
3. **Bounded by the real model window.** Use actual `num_ctx`/`context_window_size` from config/request, not a hardcoded constant (fixes audit issue #1).
4. **Generalized signals.** Coverage/keyword/intent derived from actual content, no static domain lists (CLAUDE.md).
5. **Observable.** Every attempt records via `optimization_controller.record_attempt(success, score, time, error_type)`; admin endpoints already expose status.
6. **Gradually rollable + auto-revertible.** Ship behind the controller at low rollout %; `_check_system_health` already triggers `emergency_rollback` on error-rate spikes. Keep `OPTIMIZATION_AVAILABLE` honest.
7. **Deterministic enough to test, semantic enough to be useful.** Validator must be reproducible (no flaky LLM-only scoring for unit tests) — use structural signals for validation; the LLM may do the *compression*, but validation should be deterministic.

---

## 6. Test & verification strategy

- **Fix the test import** (`tests/integration/test_optimization_safety.py:18`) — it imports bare `optimization_safety`; either restore the module to an importable location and add it to `sys.path`, or update to `archive.experimental.optimization_safety`. Decide module home first (see §8).
- **Pass the existing suite** (13 tests across Preserver/Validator/SafeOptimization) — green is the unit gate.
- **Add server-contract tests** the existing suite lacks: `content`-present-on-fallback, dual `validate_optimization` signature, `fallback_reason` as list, real-window sizing.
- **Live end-to-end** (per CLAUDE.md): enable at low rollout %, send a large multi-tool research prompt, confirm via `server_complete.log` that optimization fires, validates, and that the Primary LLM still sees every source. **User confirms** before raising rollout.
- **Rollout ladder:** 0% → unit green → 5% → monitor error/score metrics → 25% → 100%, with auto-rollback armed.

---

## 7. Effort & complexity estimate

| Component | Lines (est.) | Complexity | Risk |
|-----------|-------------|------------|------|
| `ToolOutputPreserver` | ~80 | Low | Low |
| `ValidationResult` | ~20 | Low | Low |
| `OptimizationValidator` (scoring tuned to spec + dynamic signals) | ~200–300 | **High** | Med (scoring tuning is fiddly) |
| `attempt_optimization` (LLM/TextChunker compressor) | ~80–150 | Med | **High** (it's the actual compressor on the hot path) |
| `safe_optimize_llm_input` (orchestrator, 4 outcomes, dual contract) | ~100 | Med | Med |
| Contract/audit fixes (#5,#6) + integration tests | ~100 | Med | Med |
| **Total** | **~600–750** | — | — |

**Rough effort:** ~3 focused sessions — (1) module to pass existing tests; (2) reconcile server contract + audit fixes + integration tests on a running server; (3) gradual-rollout validation with user sign-off. This is a **self-contained work item**, parallelizable with the research stages but **not** part of Stage 0.

---

## 8. Open decisions before building

1. **Module home:** restore at root (`optimization_safety.py`, simplest import) vs. keep `archive/experimental/` (matches the original import path but "experimental" implies untrusted). **Recommend root**, treat as production once tested.
2. **Compressor backend for `attempt_optimization`:** reuse `TextChunker.summary_by_semantics` (already in the fallback, deterministic-ish) vs. a dedicated LLM summarization call (higher quality, more cost/latency). **Recommend** starting from `TextChunker` and adding LLM compression behind config.
3. **Do we want it at all vs. simpler path:** alternative is to skip the engine and make the *existing* `TextChunker` fallback research-aware (Option A — ~30 lines, no validation layer). The engine's added value is the **validation + safety + rollout** guarantees; the cost is ~600 lines on a hot path.

---

## 9. Recommendation

The rebuild is **tractable and bounded** (a complete executable spec exists), and **strategically aligned** with deeper/longer research. The risk that shelved it is **real but designed-against** — provided we honor §5 hardening and the §4 conflict fixes, and roll out gradually with auto-rollback. 

**Recommended path:** treat Option B as a **dedicated, gated work item AFTER** research Stages 1–2 (which is where large evidence pools — the actual justification for compression — first appear). In the meantime, if Stage 0's classifier should have *any* live effect sooner, apply the minimal **Option A** wiring. Building the full engine *before* there's large research output to compress would be solving a problem we don't yet have.
