# RAICA Context-and-Action Substrate Convergence — Audit + Phased Plan

**Status:** DRAFT (design + phased plan) — NO refactoring code written yet. Every phase is gated on explicit approval.
**Date:** 2026-06-05
**Author:** RAICA Development Team (with Claude Code)
**Related:** [`CONTEXT_FIRST_ARCHITECTURE.md`](CONTEXT_FIRST_ARCHITECTURE.md), [`DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md`](DEEP_RESEARCH_ORCHESTRATION_INTEGRATION.md), [`POST_LLM_EXECUTION_ARCHITECTURE.md`](POST_LLM_EXECUTION_ARCHITECTURE.md), [`PROJECT_CONFIGURATION_DIRECTIVE.md`](PROJECT_CONFIGURATION_DIRECTIVE.md).

> ⚠️ This document plans a refactor of code that guards a large amount of live behavior (the POST-LLM
> auto-execution path that every non-deep-research request flows through). The plan is deliberately
> **strangler-fig + characterization-test + shadow-mode**: behavior is frozen by tests first, the new
> substrate runs in shadow next to the old one with zero behavior change, and cut-over is per-category,
> flag-gated, and individually reversible. **Nothing is deleted until it is provably unused.**

---

## 1. Motivation — two bugs, one disease

In one session we fixed two delivery bugs that looked unrelated:

1. **Deep Research Phase 3 (v1.0.0.80):** the delivery fan-out only wired file+email; any other tool the decomposer named was dead-lettered as "not wired yet."
2. **NewX "email this response as HTML" (v1.0.0.81):** the request's `allow_delivery` privilege was honored by the deep-research delivery path but **ignored** by the legacy POST-LLM path, so the delivery tools were blocked by the zero-trust `allowed_tools` whitelist and nothing was sent.

Both are the **same** disease: **RAICA has multiple parallel execution paths, each re-implementing the same cross-cutting concerns** (intent classification, authorization, recipient resolution, format selection, tool dispatch). Fix a concern in one path and the others silently lag. The user's stated intent — *"fold Deep Research into the context for consumption by all tools and facilities in RAICA"* — is precisely the cure: **one shared context-and-action substrate that every facility consumes**, with cross-cutting concerns implemented exactly once.

This is not a new direction. RAICA's own [`CONTEXT_FIRST_ARCHITECTURE.md`](CONTEXT_FIRST_ARCHITECTURE.md) already states the target principle ("LLM Decides, RAICA Executes — No hardcoded interpretation"; "Discovery, Not Limitation"). The legacy path **violates RAICA's documented architecture**. This plan **restores** it.

---

## 2. Guiding principles (non-negotiable — from CLAUDE.md & CONTEXT_FIRST)

1. **LLM decides intent, RAICA executes JSON.** No keyword/pattern classification of user intent.
2. **One implementation per cross-cutting concern.** Authorization, recipient-locking, format selection, and tool dispatch each live in exactly one place, called by every path.
3. **Open action vocabulary via dynamic registry discovery.** Any registered tool is dispatchable post-content; new tool ⇒ zero code in the classifier/dispatcher (the Generalization Test).
4. **No regression, ever.** Behavior is frozen by characterization tests before any change; the legacy path remains the authoritative fallback until a replacement is proven equal-or-better on real traffic.
5. **Reuse, don't rebuild.** The deep-research path already has the *good* versions (`_decompose_request`, the Phase-3 generic dispatcher, `_dr_delivery_permitted` + recipient-locking). Convergence means routing the legacy path through these, not writing new engines.
6. **Zero hardcoded config.** Flags/thresholds in `config/llm_config.yaml`, fail-fast if missing.

---

## 3. The disconnect inventory (evidence — verified against executing code, v1.0.0.81)

> File references are `fastapi_server_complete.py:<line>` unless noted. Line numbers are current as of v1.0.0.81 and will drift; the symbol names are stable anchors.

### D1 — TWO intent classifiers (the root disconnect) · **risk: HIGH**

| Path | Classifier | Mechanism |
|------|-----------|-----------|
| Deep Research | `_decompose_request` (`research/pipeline.py:218`) | **LLM, open vocabulary**, grounded in live tool catalog ✅ |
| Everything else | `_verify_task_completion` (`:5751–6053`) | **304 lines of hardcoded keyword/pattern matching** ❌ |

`_verify_task_completion` contains: `explicit_post_generation_requests` keyword map (`:5770`), `email_keywords` (`:5825`), `exclusion_patterns` (`:5927`), `file_creation_keywords` (`:6036`), and an 11-entry `task_patterns` dict (`:5837–5923`) each with a `triggers` keyword list and a static `required_tools` list. Returns `{complete, reason, missing_tools, pattern}`. **55 keyword-list/indicator literals exist in the file.**
**Fails on:** novel phrasings ("a portable document", "send to my mailbox"), synonyms, other languages, and — critically — **every new tool requires hand-adding keywords**, the exact opposite of Phase-3 open-vocabulary dispatch.
**Consumers (bounded):** produced `:10124`; `complete` → `pending_auto_execution` `:10127–10131`; `pattern=='programming_task'` guard `:10734`; meta-task block `:11012`; POST-LLM exec `:11015–11017`.

### D2 — Format detection by keyword, duplicated · **risk: MED**
`"pdf"/"html" in <prompt>.lower()` appears in **~35 sites**, independently in the DR delivery (`:7493`) and the legacy executor (`:7631–7637`). Two copies that already differ. "Give me a Word doc"/"a printable copy" → wrong/empty format.

### D3 — Recipient resolution, 4+ independent prompt-parsers · **risk: HIGH (latent leak)**
Separate implementations: `_resolve_email_recipients` (`:7252`, DR), `_detect_html_email_request` (`:6870`) and `_detect_html_email_request_in_args` (`:6667`) with their own regex (`:6735/:6762/:6822/:6924`), plus the new `_send_secure_email` lock added in v1.0.0.81. The **email-interceptor path** (`:10924`, params from `:9736`) and the **tool-calling-phase sends** (`:6429/:6452`) have **no recipient lock** — unreachable for NewX *today only because* the tool-offering whitelist happens to hide email. That is a coincidence of configuration, not a guarantee by design. A future change that exposes email to a restricted client would leak.

### D4 — Five would-be dispatch paths · **risk: MED**
(a) DR fan-out `_run_dr_delivery` (`:7430`); (b) POST-LLM executor `_execute_missing_tools_post_llm` (`:7580`); (c) email-interceptor (`:9736→:10924`); (d) tool-calling-phase direct sends (`:6429/:6452`); (e) `_execute_missing_tools` (`:6278`) — **no callers found → likely dead code.** Every cross-cutting policy must be re-applied in each live path; v1.0.0.81 applied delivery-privilege to only 2 of them.

### D5 — Meta-task detection duplicated · **risk: HIGH (over-fire = known past bug)**
Two independent detectors: inside the verifier (`meta_task_indicators` `:5798`, used `:5814`) and inline (`:8964`). Both suppress tool/DR execution for OpenWebUI title/tag housekeeping. Divergence ⇒ either housekeeping calls trigger real tools (the documented gate-over-fire bug) or a real request is mistaken for housekeeping.

### D6 — Tool-offering vs. delivery semantic disconnect · **risk: MED (UX/trust)**
For NewX the LLM is **not offered** delivery tools (whitelist at tool-offering), so it narrates *"I can't email files"* while POST-LLM now delivers anyway. The model's words contradict RAICA's actions.

### D7 — Open-vocabulary dispatch (Phase 3) lives only in DR · **risk: MED**
The legacy path can only dispatch file+email via hardcoded handlers; it cannot dispatch a newly-registered tool. The capability we built for DR does not reach non-research flows.

---

## 4. Target architecture — one substrate, consumed by all

```
ANY request (DR or not)
   │
   ▼  INTENT  — one LLM decomposition (research_spec?, deliverable_spec, actions[])
   │           open vocabulary, grounded in the live tool registry. (= today's _decompose_request)
   │           Replaces _verify_task_completion's keyword classification.
   │
   ▼  CONTENT — produced by the appropriate context producer:
   │             • deep research pipeline  → research context/paper
   │             • normal LLM answer       → complete_llm_response
   │           (Research output is just ONE context producer among several.)
   │
   ▼  ACTION SUBSTRATE  (single shared module — every path calls it)
   │     authorize(action, client)       ← one policy  (unifies _dr_delivery_permitted + POST-LLM privilege)
   │     resolve_recipient(action, client)← one policy  (locking + fail-closed, used everywhere)
   │     resolve_format(deliverable)      ← one resolver (LLM-or-spec, replaces "pdf in prompt" ×35)
   │     dispatch(action, content, ctx)   ← one generic dispatcher (the Phase-3 arg-binder)
   │
   ▼  Aggregated result → reported to the user (and the model's narration matches what ran)
```

**Key property:** a fix to any cross-cutting concern (a new auth rule, a recipient-lock tweak, a new format) is made **once** and is live on every path. New tools become available to every path with **zero** classifier/dispatcher changes.

---

## 5. Invariants that MUST NOT regress (the test contract)

These are frozen by Phase 0 characterization tests and checked at every later phase:

- **I1 — Meta-task suppression:** OpenWebUI title/tag generation never triggers tools, delivery, or deep research. (Both `:5814` and `:8964` behaviors.)
- **I2 — Information-only requests** (research/explain/list with no delivery verb) never trigger post-generation actions. (`exclusion_patterns` `:5933`.)
- **I3 — Recipient locking / fail-closed:** a restricted client (sends `allowed_tools`) with delivery privilege emails ONLY its server-authoritative `delivery_recipient`; prompt/LLM addresses and CC are ignored; no valid locked recipient ⇒ refuse. (`_send_secure_email`, `_run_dr_delivery`.)
- **I4 — Whitelist still enforced:** without `allow_delivery`, delivery tools remain blocked for restricted clients.
- **I5 — Single-send:** an email/action is performed exactly once (no double execution across the retry/verify loop).
- **I6 — Deep-research behavior unchanged** at every phase boundary.
- **I7 — No prompt-keyword routing reintroduced** (Generalization Test on new code).

---

## 6. Regression-safety strategy (how we avoid breaking anything)

1. **Characterization tests FIRST (Phase 0).** Snapshot the *current* output of `_verify_task_completion`, the recipient resolvers, and the format selector across a corpus mined from (a) the trigger lists themselves, (b) real prompts in `logs/` + `logs/archive/`, (c) the invariant scenarios. These golden files define "no regression."
2. **Shadow mode.** New classifier/substrate runs **next to** the legacy one in production behind a config flag; divergences are logged, but the **legacy result stays authoritative**. We gather real-traffic divergence data before changing any behavior.
3. **Strangler-fig cut-over.** Replace the legacy path **per category** (info-only → email → file → publish → meta-task), each behind its own flag, each independently reversible, each gated on shadow data showing parity-or-better.
4. **Delete last.** Keyword lists and dead code are removed only after every consumer is provably routed away and stable for a release.
5. **Per-phase rollback.** Each phase is a single flag flip or revert; no phase requires undoing a prior one.

---

## 7. Phased plan (each phase: independently shippable, version-bumped, approval-gated)

### Phase 0 — Freeze behavior (safety net) · risk: NONE (tests only)
- Add `tests/integration/test_intent_classifier_characterization.py`: corpus → golden `{complete, missing_tools, pattern}` for `_verify_task_completion`.
- Add `tests/utilities/test_recipient_and_format_resolution.py`: golden recipient/format outputs incl. the locking + fail-closed cases (I3).
- Encode I1–I6 as explicit scenario tests.
- **Exit:** green suite that locks today's behavior. No production code touched.

### Phase 1 — Extract the shared policy module (pure refactor) · risk: LOW–MED — **✅ DONE (v1.0.0.82, 2026-06-05)**
- **Shipped.** New `orchestration/policy.py` (pure, stdlib-only): `valid_email`,
  `authorize_delivery() -> DeliveryAuth{permitted, recipient_locked, locked_recipient}`,
  `resolve_locked_recipient()` (fail-closed, I3), `resolve_delivery_format()` (+ canonical DR/POST-LLM
  candidate sets reproducing both legacy inline `"pdf" in prompt` chains EXACTLY). Plus module-level
  `_send_email_locked` — ONE "send-with-lock" used by both the POST-LLM executor chokepoint and the
  email-interceptor.
- Routed: `_dr_delivery_permitted` (now a wrapper), the DR delivery call site, `_run_dr_delivery`
  recipient+format, the POST-LLM whitelist auth block, the executor `_send_secure_email`, and the
  legacy executor format chain. Removed the redundant inline `_valid_email`/regex/`_post_*` code.
- **D3 latent leak CLOSED by design** at the email-interceptor (routes through `_send_email_locked` +
  `authorize_delivery(data)`) — behavior-identical now, but a restricted client can never be steered to
  a prompt-chosen address. (Dead `_execute_missing_tools` `:6429/:6452` left for Phase 5 deletion.)
- **Behavior-preserving & verified:** Phase-0 goldens unchanged & green; `test_orchestration_policy.py`
  (32 tests) asserts equivalence to the pre-refactor logic (incl. a truth-table vs. legacy
  `_dr_delivery_permitted`); the 3 I3 tests now run live at the send chokepoint. Full suite **76 passed,
  0 skipped**; server healthy on .82. Changelog `CHANGELOG_v1.0.0.82.md`. Classifier untouched.

### Phase 2 — Shadow-mode LLM intent classifier · risk: LOW — **✅ DONE (v1.0.0.83, 2026-06-05)**
- **Shipped.** New `orchestration/intent.py` (`classify_intent_actions` — LLM, catalog-grounded, open
  vocabulary; `to_verifier_shape`; `compare`). A non-blocking background runner
  (`_schedule_shadow_classification`/`_run_shadow_classifier`) executes it alongside
  `_verify_task_completion`, logs `🕵️ SHADOW CLASSIFIER`, and appends disagreements to a JSONL file.
  Legacy stays authoritative; **disabled by default** (config `convergence.shadow_classifier`).
- **Zero behavior change**; fully guarded/timed-out/GC-safe background task.
- **Live smoke test** confirmed the LLM path works AND already produced useful divergence data: the LLM
  correctly rejects the "write a poem" false-positive (legacy bug), agrees on info-only and pure-email,
  but misses the file-creation step for "email as a document" and picks the research agent for compound
  research+deliver — the exact gaps Phase 3 must tune before cutover.
- Tests: `test_intent_classifier_llm.py` (11). Full suite 86 passed, 0 skipped. Changelog
  `CHANGELOG_v1.0.0.83.md`.
- **Exit met:** shadow runs and produces a divergence report over real traffic; no behavior change.

### Phase 3 — Cut over intent classification, per category · risk: MED (reversible)

**Phase 3a — Labeled baseline (no behavior change) · ✅ DONE (2026-06-05)**
- New LABELED eval corpus `tests/data/intent_eval_corpus.py` — 32 ground-truth cases across info_only,
  plain_answer, pure_email, file_email, file_only, publish, image, meta_task, **edge**, and
  **multi_turn** (embedded conversation history, distractors, follow-ups, compound).
- Harness `tests/utilities/run_intent_eval.py` runs BOTH classifiers vs ground truth (kind-based
  scoring). Deterministic legacy baseline pinned by `tests/integration/test_intent_eval_baseline.py`.
- **Baseline result:** delivery-decision correct — **LLM 100% (32/32) vs LEGACY 71.9% (23/32)**; full
  (decision+kinds) — LLM 100% vs LEGACY 53.1%. Legacy collapses on plain_answer (0%), edge (20%),
  multi_turn (66.7%) with dangerous false-positives ("Thanks!" → email; pure question whose history
  contains "email" → email; "don't email this" → email; "how do I email a PDF?" → email).
- **Caveat (informs cutover):** the hardest compound multi_turn case showed run-to-run LLM variance
  (cloud inference isn't perfectly deterministic at temp 0) — so cutover MUST keep legacy fallback.

**Phase 3b — Tune the intent prompt · ✅ DONE (v1.0.0.84, 2026-06-05)**
- Tuned `INTENT_SYSTEM_PROMPT` (orchestration/intent.py): research/search/sub-agent tools are NOT
  delivery (kills the raica_research_agent trap); emailing/saving a document needs BOTH file + email;
  document≠chart (file-writing tool vs visualization tool).
- **Result (3 runs/case):** delivery decision **100% (32/32), 100% stable**; exact tool-set stability
  **93.8% (30/32)**. The 2 residual wobbles are benign over-inclusion (extra file step on ambiguous
  "email the notes"/"visualize and email") — not dangerous. Justifies full-mode cutover WITH legacy
  fallback. Only production-code change is the shadow prompt (still off by default → no behavior change).

**Phase 3c — LLM cutover (FULL tool set) · ✅ SHIPPED DARK (v1.0.0.85, 2026-06-05) — default OFF**
- User chose **full tool set** (LLM picks the decision AND the actual tools, not legacy's keyword
  mapping). Implemented as `_maybe_llm_authoritative` at the verifier call site: when
  `convergence.intent_classifier.mode == 'llm'`, the LLM result is authoritative; the legacy classifier
  is ALWAYS computed and is the fallback (wrong mode / over-length / not-ok / timeout → legacy untouched).
  **Default `mode: legacy` → guaranteed no-op (zero behavior change); ships dark.**
- Functionally verified: legacy-mode no-op; llm-mode fixes the "poem" false-positive and resolves
  "email as HTML" to `[pdf_generator, secure_email_sender]`. Shadow skipped when llm-authoritative.
- **Executor coupling (Phase 4 boundary):** the LLM's missing_tools feed the existing POST-LLM executor,
  which natively dispatches file + email + social_media_* (publish); image/other picks await Phase 4.
- **REMAINING before this phase is fully "done":** operator end-to-end validation of `mode: llm`
  (invariants I1–I6 live), then default it on. D5 (unify meta-task detection) / D6 (model aware it can
  deliver) still to fold in. Changelog `CHANGELOG_v1.0.0.85.md`.
- **Exit (pending):** LLM classifier validated live + defaulted on; invariants green.

### Phase 4 — Unify dispatch (open vocabulary everywhere) · risk: MED
- Route the legacy path's post-content actions through the Phase-3 generic dispatcher (D7), so any registered tool is dispatchable, not just file+email. Retire `task_patterns`' static `required_tools`.
- **Exit:** a brand-new tool is deliverable from BOTH DR and normal flows with zero classifier changes.

### Phase 5 — Retire dead/duplicated code · risk: LOW
- Delete the keyword lists in `_verify_task_completion`, the duplicate meta-task detector, the redundant recipient regex parsers, and dead `_execute_missing_tools` (`:6278`) — **only after** confirming no live caller (grep + a release of shadow/te­lemetry).
- **Exit:** one classifier, one dispatcher, one policy module; the 55 keyword literals are gone.

---

## 8. Open design decisions (resolve during Phase 1–2 review)
1. **Module home/name:** `delivery/policy.py` vs `orchestration/substrate.py` vs extend `research/`. (Leaning: a top-level `orchestration/` package so it's clearly not DR-specific.)
2. **One classifier call or two?** Can the *same* decomposition serve both "is this research?" (gate) and "what actions?" (delivery), or stay as gate + decomposer? (Leaning: keep the DR gate; share the action-decomposer.)
3. **Format resolution internals:** LLM-driven vs `deliverable_spec`-driven vs both; when to drop the keyword fallback.
4. **Meta-task detection home:** fold into the LLM classifier, or keep a fast deterministic pre-check for the known OpenWebUI envelopes (cheaper, and I1 is safety-critical)? (Leaning: deterministic envelope pre-check is acceptable — it keys on the OpenWebUI task structure, not user-intent keywords, so it is not the forbidden anti-pattern.)
5. **Shadow telemetry sink:** log-only vs a small divergence file for analysis.

## 9. Non-goals (this document)
- Changing deep-research research quality, multimodal/media embedding (see `DEEP_RESEARCH_MULTIMODAL_PLAN.md`).
- Cross-category artifact handoff (generic tool's output file → email attachment / PDF embed) — tracked separately.
- Replacing the POST-LLM executor wholesale — we route it through shared policy and the generic dispatcher, we do not rewrite its file-creation internals.
- The `/v1` firewall and NewX privilege backend (separate action items).

---

## 10. Status / next step
DRAFT for review. **No code written.** On approval, the first concrete step is **Phase 0 only** (characterization tests — zero production risk), after which we review the golden corpus together before touching any production path.
