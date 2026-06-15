# CHANGELOG v1.0.0.82

**Date:** 2026-06-05
**Previous:** v1.0.0.81 (NewX delivery privilege on the POST-LLM path)
**Theme:** **Convergence Phase 1 — shared delivery-policy module** (one implementation of
authorization, recipient-locking, and format resolution, consumed by every delivery path)

> Part of the Context-and-Action Substrate Convergence — see
> `docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md`. **Behavior-preserving refactor** guarded by the
> Phase-0 characterization suite. No user-visible behavior change for existing flows; one latent
> security gap (D3) closed by design.

---

## What changed

### New module — `orchestration/policy.py` (pure, stdlib-only, no server import)
Single source of truth for the cross-cutting delivery concerns that were previously duplicated and
drifting across paths:
- `valid_email(email)` — canonical address validation (was inline in ≥2 places).
- `authorize_delivery(data) -> DeliveryAuth{permitted, recipient_locked, locked_recipient}` — the
  unified 3-way authorization + recipient-lock policy. Reproduces `_dr_delivery_permitted` (for
  `permitted`) AND the POST-LLM privilege computation in one place, so the deep-research and legacy
  paths cannot drift.
- `resolve_locked_recipient(recipient_locked, locked_recipient) -> (recipient|None, refused)` — the
  single fail-closed recipient-lock decision (invariant I3).
- `resolve_delivery_format(user_prompt, deliverable_format, candidates, default)` + canonical
  `DR_*` / `POST_LLM_*` candidate sets — reproduces both legacy inline `"pdf" in prompt` chains
  exactly (parameterized so each caller keeps its current behavior).

### New shared send-chokepoint — `_send_email_locked(tool_manager, params, recipient_locked, locked_recipient)`
ONE implementation of "send an email, enforcing the recipient lock" (force `to_email` → locked
address, drop `cc_emails`, fail-closed on invalid lock). Used by **both** the POST-LLM executor's
`_send_secure_email` chokepoint and the email-interceptor path.

### Call sites routed through the shared policy (behavior-identical)
- `_dr_delivery_permitted` → thin wrapper over `authorize_delivery(...).permitted`.
- Deep-research delivery call site → `authorize_delivery(data)` for permitted / recipient_locked /
  locked_recipient (was three separate inline reads).
- `_run_dr_delivery` recipient-lock block → `resolve_locked_recipient` (removed inline regex).
- `_run_dr_delivery` format → `resolve_delivery_format` (DR candidates).
- POST-LLM whitelist auth block → `authorize_delivery(data)` (removed the v1.0.0.81 inline
  `_post_allow_delivery/_post_recipient_locked/_post_locked_recipient` computation).
- POST-LLM executor `_send_secure_email` → delegates to `_send_email_locked`; removed the now-dead
  local `_valid_email`/`re` helpers.
- Legacy executor format chain (pdf/html/md/txt/else-html) → `resolve_delivery_format` (POST-LLM
  candidates).

### Security — D3 latent leak closed by design
The **email-interceptor path** previously had **no recipient lock** — it was safe only because the
tool-offering whitelist happened to hide email from restricted clients (a config coincidence, not a
guarantee). Its send now routes through `_send_email_locked` with `authorize_delivery(data)`. This is
**behavior-identical for current traffic** (auto-trusted clients are never locked, and restricted
clients don't reach this path today) but means a restricted client can **never** be steered to a
prompt-chosen address even if future config exposes email.

## No behavior change (verified)
- The two legacy format chains and the recipient/auth logic are reproduced exactly; equivalence is
  asserted by unit tests (`test_orchestration_policy.py`) against the pre-refactor logic.
- The Phase-0 characterization goldens for `_verify_task_completion` and the recipient resolvers are
  **unchanged and still green** — the intent classifier was deliberately NOT touched in Phase 1.

## Tests
- `tests/utilities/test_orchestration_policy.py` (NEW) — 32 unit tests: `valid_email`,
  `authorize_delivery` (incl. a truth-table vs. the legacy `_dr_delivery_permitted`),
  `resolve_locked_recipient` (I3), and format-equivalence vs. both legacy inline chains.
- `tests/utilities/test_recipient_resolution_characterization.py` — the 3 I3 placeholders are now
  **live** end-to-end tests against `_send_email_locked` (lock override, CC drop, fail-closed,
  auto-trust pass-through).
- Full suite: **76 passed, 0 skipped** (`pytest tests/integration/test_intent_classifier_characterization.py
  tests/utilities/test_recipient_resolution_characterization.py tests/utilities/test_orchestration_policy.py`).
- Server boots healthy on v1.0.0.82 with the new `orchestration` package; no import errors.

## Files
- `orchestration/__init__.py`, `orchestration/policy.py` (NEW)
- `fastapi_server_complete.py` — import the shared policy; route 7 delivery sites + the interceptor
  through it; add module-level `_send_email_locked`; remove the now-redundant inline helpers.
- `tests/utilities/test_orchestration_policy.py` (NEW); `test_recipient_resolution_characterization.py`
  (I3 activated).
- `version.py` (→ 1.0.0.82), `README.md`, this changelog,
  `docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md` (Phase 1 marked done).

## Not in this phase (per the plan)
- Phase 2 (shadow-mode LLM intent classifier), Phase 3 (cut over intent classification — retire the
  keyword classifier), Phase 4 (unify dispatch), Phase 5 (delete dead code incl. `_execute_missing_tools`
  at :6278). The intent classifier (`_verify_task_completion`) is untouched here.
