# CHANGELOG v1.0.0.76

**Date:** 2026-06-04
**Previous:** v1.0.0.75
**Trigger:** Deep-research delivery output hygiene + a privacy fix for published (NewX) posts.

---

## Background

Non-streaming clients (NewX) COLLECT the whole streamed response and publish it as a permanent,
often PUBLIC post. That meant transient status and delivery housekeeping were getting baked into the
published artifact — including, on success, the recipient's email address (`📎 …emailed to
<you@email>`), which leaked the requesting user's email into a public post.

## Changes (`fastapi_server_complete.py`)

- **Delivery → single housekeeping footnote** (`_run_dr_delivery` rewritten): the fan-out now does the
  PDF render + email **silently** and emits ONE line at the end instead of the verbose multi-step
  section:
  - success: `*📎 Delivery: the document was emailed to <recipient>.*`
  - failures stay **clear and never silent** (`⚠️ **Delivery:** …`) — and carry no email address.
  Removed the verbose `📦 Delivery` header.
- **Document stays clean** (unchanged, reconfirmed): the PDF/HTML is rendered from the paper body;
  delivery/footer are appended to the RESPONSE only, never to the document.
- **Non-streaming output hygiene** (the collector, `openai_non_streaming_response`): strips, from the
  assembled content,
  - the transient `⏳ retrying…` keepalive lines (meaningless once collected; the bytes still flowed
    over the wire to keep the connection warm during retry waits), and
  - the `📎 Delivery` SUCCESS footnote — **so the recipient's email is never echoed into a public
    post**. The delivery email is itself the confirmation.
  Failure alerts (`⚠️`) are KEPT (no email, must not be silent). A now-dangling trailing separator is
  trimmed.

### Net behavior

| | Streaming (OpenWebUI, private) | Non-streaming (NewX, public post) |
|---|---|---|
| Document (PDF/HTML) | clean paper | clean paper |
| Delivery success | `📎 emailed to <you>` shown | stripped (no email leaked) |
| Delivery failure | shown (no email) | shown (no email; no silent failure) |
| Transient `⏳` retry | shown live | stripped (bytes still flow for warmth) |

## Verification (live)

- Non-streaming (`stream:false`) delivery run: response contains **no `📎` footnote, no email address,
  no `⏳`**, ends cleanly on the audit footer — and the email was **still sent**
  (`✅ Email sent successfully via gmail`). The emailed PDF is the clean paper.
- Prior run (pre-strip) confirmed the leak existed (`📎 …emailed to <email>` in the content), so the
  fix is doing exactly what's intended.

## Dependencies / Migration

- None. Output-formatting + privacy change only; no contract change.

## Files

- `fastapi_server_complete.py` — `_run_dr_delivery` footnote rewrite, removed verbose header,
  non-streaming strip of transient + success-footnote lines.
- `version.py` (→ 1.0.0.76), `README.md`, this changelog.
