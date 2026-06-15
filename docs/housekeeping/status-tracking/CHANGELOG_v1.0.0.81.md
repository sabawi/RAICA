# CHANGELOG v1.0.0.81

**Date:** 2026-06-05
**Previous:** v1.0.0.80 (Deep Research Phase 3 — dynamic action dispatch)
**Theme:** **Delivery privilege on the legacy POST-LLM path** — NewX "email this response as X"
requests now honored (with airtight recipient locking)

---

## Trigger (evidenced, live)

A NewX `@Ask` test — *"email the above response as a HTML document"* — produced **no delivery**.
Live log (`logs/server_complete.log`, 07:26–07:28):

```
📦 Client allow_delivery flag forwarded to pipeline: True
📦 Locked delivery recipient forwarded to pipeline: user@example.com
...
🔍 DEBUG: pending_auto_execution=True, verification_result={'missing_tools':
   ['sandboxed_executor', 'secure_email_sender'], 'pattern': 'research_html_report_email + ...'}
🔒 POST-LLM WHITELIST: Blocked tools not in allowed_tools: ['sandboxed_executor', 'secure_email_sender']
🔒 POST-LLM AUTO-EXECUTION SKIPPED: All missing tools blocked by whitelist
```

## Root cause

The request was **not** a deep-research request, so the DR gate correctly did not fire and the
DR delivery path (which *does* honor `allow_delivery`) was never reached. It went through the
**legacy POST-LLM auto-executor**, whose whitelist check (`fastapi_server_complete.py`) filtered the
required delivery tools against the request's zero-trust `allowed_tools` whitelist — which (by design)
excludes `sandboxed_executor` + `secure_email_sender`. That check **never consulted `allow_delivery`/
`delivery_recipient`**. So the user's delivery privilege was honored for deep-research deliveries but
**not** for ordinary "package this response and email it" deliveries — divergent authorization between
the two delivery paths.

## Fix — extend the delivery privilege to the POST-LLM path, with recipient locking

1. **Whitelist (POST-LLM auto-exec):** when the request presents an explicit `allow_delivery=True`
   privilege, the delivery tools (`sandboxed_executor`, `secure_email_sender`) are added to the
   *effective* allowed set even though they are excluded from the client's `allowed_tools`. Non-
   privileged requests are unchanged (still blocked).
2. **Recipient locking (security, airtight):** `_execute_missing_tools_post_llm` gained
   `locked_recipient` + `recipient_locked` params. A new **single send-chokepoint** `_send_secure_email`
   wraps **all four** email send sites in the executor:
   - For a **restricted** client (one that sends an `allowed_tools` whitelist, e.g. a NewX bot), every
     email is forced to `locked_recipient` (the user's server-authoritative account email); any
     prompt-/LLM-derived `to_email` is overridden and any `cc_emails` is dropped. If no valid
     `locked_recipient` is available → **fail-closed** (refuse to send).
   - For an **auto-trusted** client (no `allowed_tools`, e.g. OpenWebUI) → unchanged (prompt recipient).
   This mirrors the deep-research path's `_dr_delivery_permitted` + `_run_dr_delivery` model exactly,
   so both delivery paths now share one authorization + recipient-locking policy.

## Security notes

- A NewX bot still **cannot** email an arbitrary address: with privilege it can email only the
  requesting user's own verified account (`delivery_recipient`), enforced at the single chokepoint
  (`to_email` override + `cc_emails` strip + fail-closed).
- The **email-interceptor path** (`email_intercepted=True`, Path 1) is unaffected and unreachable for
  NewX: the tool-calling phase only offers tools in `allowed_tools`, so the LLM cannot emit a
  `secure_email_sender` call to intercept. This change only opens the **POST-LLM auto-exec** whitelist,
  not tool-offering. (If that path is ever opened to restricted clients, it must adopt the same lock.)
- No config widening of *who* may deliver — authorization is still driven entirely by the
  client-supplied `allow_delivery` privilege (NewX's per-user "email via RAICA" right, v1.0.0.73).

## Files

- `fastapi_server_complete.py`
  - POST-LLM whitelist block: `allow_delivery` opens `{sandboxed_executor, secure_email_sender}`;
    computes `_post_locked_recipient` / `_post_recipient_locked`; logs the privilege decision.
  - Executor call site passes `locked_recipient` + `recipient_locked`.
  - `_execute_missing_tools_post_llm`: new params + `_send_secure_email` send-chokepoint
    (`to_email` lock, `cc_emails` strip, fail-closed); all four executor send sites routed through it.
- `version.py` (→ 1.0.0.81), `README.md` (→ 1.0.0.81), this changelog.

## Verification

Pending live re-run by the user (the same NewX `@Ask` "email the above response as a HTML document").
Expected log signals: `📦 POST-LLM DELIVERY PRIVILEGE: allow_delivery=True → delivery tools permitted;
recipient LOCKED to user@example.com`, file creation + email send proceed, and the email arrives at
the user's own account only.
