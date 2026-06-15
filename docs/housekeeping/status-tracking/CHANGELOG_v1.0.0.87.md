# CHANGELOG v1.0.0.87

**Date:** 2026-06-06
**Previous:** v1.0.0.86 (intent classifier prompt hardening)
**Theme:** **Fix: POST-LLM email skipped "email me" requests with no typed address (ignored the locked recipient)**

---

## The bug (live dev validation)

NewX `@Ask email the above to me in html formatted file` produced a posted reply but **no email**. Log:

```
📦 POST-LLM DELIVERY PRIVILEGE: allow_delivery=True → delivery tools permitted; recipient LOCKED to user@example.com
🎯 POST-LLM AUTO-EXECUTION: executing missing tools: ['secure_email_sender']
⚠️ POST-LLM EMAIL: No email address found in prompt - skipping
```

## Root cause

The POST-LLM executor resolves the email recipient by scanning the **user prompt** for an address. The
user said "email **me**" with no typed address, so it found none and **skipped — without using the
server-authoritative `locked_recipient`** (`user@example.com`) that the delivery-privilege system had
already set. The recipient-LOCK in `_send_email_locked` would have forced the right address, but these
recipient-RESOLUTION branches bail out *before* the send, so the lock never applied.

This affected **both** executor email branches (the attachment path and the no-attachment "send as body"
path), i.e. any "email me / send it to me" request without an explicit address.

## The fix

At both recipient-resolution sites in `_execute_missing_tools_post_llm`, the **server-authoritative
locked recipient now wins**: when `recipient_locked` and `locked_recipient` is a valid address, use it
as the recipient (and don't skip for a missing prompt address). CC from the prompt is also not used when
locked (consistent with `_send_email_locked`, which drops CC for locked clients). Non-locked clients are
unchanged (prompt address as before).

This means a privileged NewX "email me ..." request now reliably emails the user's own account email,
even when no address is typed — which is exactly the intended behavior of the locked-recipient policy.

## Known residual (separate, lesser issue — A)

On the *very large* real NewX prompt, the LLM intent classifier sometimes picks `['secure_email_sender']`
only (dropping the file-creation tool) for "email as an HTML file" — so the email may be sent as the
response **body** rather than as an attached HTML file. With this v1.0.0.87 fix the email now *arrives*
either way; getting the HTML *attachment* reliably needs classifier-robustness work on long prompts
(tracked for the next iteration). The short-prompt eval corpus is 100% on this; the miss only reproduces
on the full production-size prompt.

## Files
- `fastapi_server_complete.py` — both recipient-resolution branches in `_execute_missing_tools_post_llm`
  prefer the locked recipient.
- `version.py` (→ 1.0.0.87), `README.md`, this changelog.

## Status
Dev server on v1.0.0.87, `intent_classifier.mode: llm`, for continued live validation. Reversible
(`mode: legacy`). Not committed.
