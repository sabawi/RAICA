# CHANGELOG v1.0.0.120

**Date:** 2026-06-15
**Previous:** v1.0.0.119 (one delivery substrate + single-source PDF/HTML rendering)
**Theme:** **Delivery truthfulness** — a failed email send is now reported as a failure, not a false success.

---

## The bug (false-success delivery reporting)

A live `@Ask` delivery on production created the document and invoked the email tool correctly, but the
actual send failed (`Tool 'secure_email_sender' error: Failed to send email via sendmail`). RAICA still
logged `✅ POST-LLM AUTO-EXECUTION COMPLETED` and reported the delivery as sent — a **false success**. A
future transport problem would again be invisible.

### Root cause
The email send result is **stringified** by the user-tool wrapper before it reaches the delivery code:
- success → the tool's message (e.g. `✅ Email sent successfully via gmail …`)
- failure → `Tool '<name>' error: <msg>` (via `AsyncToolManager._create_user_tool_wrapper`)

`_deliver_document` then tried to recover success/failure from that prose, guarding only on a `❌` prefix
(`result.lstrip().startswith("❌")`). The real failure string starts with `Tool '…'`, not `❌`, and is a
`str` (not a dict), so it slipped past both checks into the `else` → `("sent")`. The tool's actual
`{"success": bool}` had been discarded one layer down. (This brittleness is exactly what the LLM-Policy
Gate warns about: deciding meaning by matching text prefixes.)

## The fix (propagate the tool's real success flag)

- **`_last_user_tool_ok` contextvar** — `AsyncToolManager._create_user_tool_wrapper` now records the
  tool's actual `result.get("success")` (True/False) at its single success/failure fork, the one place
  that still holds the boolean before it is stringified. Per-async-task → concurrency-safe. This is **not**
  keyword matching: it carries the tool's own boolean, not an interpretation of its text.
- **`_deliver_document`** reads that flag to decide `("sent")` vs `("failed", reason)`, and uses
  `asyncio.timeout()` (not `asyncio.wait_for`) for the send so it runs in the **same task context** and the
  flag propagates (a `wait_for` Task runs in a copied context and would hide it). The old dict/`❌`-prefix
  checks remain only as a defensive fallback when the structured flag is unavailable.
- **`_send_secure_email`** (POST-LLM Route-1 helper) — `_postllm_email_mark_sent` is now gated on the real
  success flag, not "any string came back" (a failure string previously counted as sent).
- **Caller framing** — the post-LLM executor's blanket `✅ POST-LLM AUTO-EXECUTION COMPLETED` log and
  `✅ POST-PROCESSING COMPLETED` user stream header are now neutral (`FINISHED` / `RESULT`); the per-action
  status (`✅ emailed …` / `⚠️ delivery {failed|…}: …`, already built from `email_outcome`) carries the
  truth, so a failed send is no longer wrapped in a blanket success claim.

Result: when delivery fails, the log and the user-visible result both say so; the Deep Research path
benefits automatically (it shares `_deliver_document`). Successful sends are unchanged.

## Tests
- New `tests/integration/test_delivery_failure_reporting.py` — drives the **real** `_deliver_document` +
  `safe_function_call` + `_create_user_tool_wrapper`, faking only the leaf effects (sandbox file write +
  SMTP result). Asserts a failing email tool → `email_outcome == ("failed", …)` and a succeeding one →
  `("sent", …)`. Fails on the pre-fix code (the failed send was reported "sent").

## Files
- `fastapi_server_complete.py` — `_last_user_tool_ok` contextvar + wrapper sets; `_deliver_document`
  structured outcome (+ `asyncio.timeout`); `_send_secure_email` mark-sent gate; neutral post-LLM
  log/stream framing.
- `tests/integration/test_delivery_failure_reporting.py` (new), `version.py` (→ 1.0.0.120), this changelog.

## Operational note (not a code change)
RAICA email delivery on the live server requires `GMAIL_SENDER_EMAIL` + `GMAIL_APP_PASSWORD` in `~/RAICA/.env`
(it otherwise falls back to a local `sendmail` MTA that isn't installed on the AWS box → the failure above).
Configured on live 2026-06-15, mirroring NewX's Gmail SMTP transport. A fresh install/installer must set these.

## Known follow-ups (tracked, not in this commit)
- `AsyncToolManager.secure_email_sender` (the method) is **dead code** — overridden in `available_functions`
  by the user-tool wrapper, so its inline recipient-lock + `❌`-style returns never run. The active recipient
  lock holds via the POST-LLM/DR caller passing the locked recipient + the bot `allowed_tools` whitelist, but
  the method's defense-in-depth lock is inert and should be removed or re-homed into the active path.
