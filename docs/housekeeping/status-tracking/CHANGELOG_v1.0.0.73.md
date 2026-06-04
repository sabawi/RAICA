# CHANGELOG v1.0.0.73

**Date:** 2026-06-04
**Previous:** v1.0.0.72
**Trigger:** Security hardening for deep-research delivery — lock the email recipient so a
multi-user-platform bot can't be abused to email arbitrary people.

**Companion:** NewX delivery-privilege system (sets `allow_delivery` + `delivery_recipient`).

---

## Summary

Phase 2 delivery (v1.0.0.72) emailed whatever recipient appeared in the *prompt*. On a shared
platform (NewX), a user could tell a bot "email it to victim@x" or "email everyone", and the bot
would obey. This release makes the recipient **server-authoritative**: a trusted client passes the
requesting user's own account email as `delivery_recipient`, and RAICA emails ONLY that address,
ignoring any recipient named in the prompt.

---

## Changes

- **`OpenAIChatRequest.delivery_recipient`** (Optional[str]) — plumbed end-to-end (endpoint →
  streaming/non-streaming → `native_request_data` → pipeline `data`), mirroring `allow_delivery`.
- **`_run_dr_delivery` recipient policy** (new params `locked_recipient`, `recipient_locked`):
  - **Restricted client** (sends `allowed_tools`, e.g. a NewX bot) → `recipient_locked=True`: email
    goes ONLY to the validated `locked_recipient`; prompt recipients are NEVER honored. No valid
    locked recipient → **email refused (fail-closed)** with a visible message (no silent failure).
  - **Auto-trusted single-user client** (no `allowed_tools`, e.g. OpenWebUI on the firewalled /v1) →
    prompt recipients resolved as before (user is emailing on their own behalf).
  - The DR branch derives `recipient_locked = (allowed_tools is present)` and reads
    `delivery_recipient` from the request.
- **Transparency:** success line shows `✅ Emailed to <addr> (your account email — for safety, bots
  can only email you, not addresses named in the request)`.

## Compliance with CLAUDE.md

- Server-authoritative, fail-closed; no silent failures (refusal is surfaced in the response).
- No regression: lock applies only to restricted clients on the delivery path; OpenWebUI and the
  normal (non-DR) flow are unchanged (the normal flow already blocks bot email via the
  `allowed_tools` whitelist — defense in depth).

## Verification (live, user-confirmed)

- **curl (restricted client):** prompt demanded "email it to decoy-not-me@example.com" with
  `delivery_recipient` set to the account email → RAICA emailed the **account email**, the decoy was
  **never used as a recipient** (`secure_email_sender … 'to_email': '<account>'`); response showed the
  "(your account email — for safety…)" note.
- **Full NewX path:** a privileged user @mentioned `@Ask` ("…email the paper in PDF format to me") →
  NewX logged `delivery PERMITTED … recipient=account email`, RAICA logged `Locked delivery recipient
  forwarded`, deep research produced an academic-review PDF, and `✅ Email sent successfully via gmail
  to 1 recipient(s)` to the account email. User received the email with the PDF.

## Dependencies / Migration

- None new. No client contract change beyond the optional `delivery_recipient` field.

## Files

- `fastapi_server_complete.py` — `delivery_recipient` field + plumbing; recipient-lock policy in
  `_run_dr_delivery`; DR-branch lock derivation.
- `version.py` (→ 1.0.0.73), `README.md`, this changelog.
