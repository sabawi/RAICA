# CHANGELOG v1.0.0.88

**Date:** 2026-06-06
**Previous:** v1.0.0.87 (POST-LLM email used the locked recipient when none typed)
**Theme:** **Intent-classifier fix #1 reframed: "detect intent; the system enforces permission"**
(+ companion NewX-side per-bot delivery capability — cross-repo, see below)

---

## RAICA change — `orchestration/intent.py`

Reframed the classifier directive that copes with embedded platform/system instructions. Previously it
told the classifier to *"ignore platform directives like 'do not create files'."* Per the design
decision that RAICA must **respect** NewX policy (not override it) and let enforcement happen at the
privilege gate, it now reads:

> *"DETECT THE USER'S REQUEST; DO NOT MAKE THE PERMISSION CALL. … Your ONE job is to detect what the
> user's LATEST request asks to deliver. You do NOT decide whether it is allowed and you do NOT refuse —
> whether a delivery is permitted, and to whom, is enforced AFTERWARD by a separate system gate (a
> per-user privilege check + a recipient lock). … (A USER's own negation still means no delivery.)"*

Same effect (the classifier reads user intent and isn't suppressed by "don't call the email/file tool
yourself" directives — including the one `call_raica` injects), but it now defers permission to RAICA's
gate instead of "ignoring" platform policy.

**Validation (eval harness, 34 cases, 3 runs):** LLM delivery-decision **100% (34/34)**, full+stable
**97.1%**, **100% stable** across runs. The system-preamble bias case (`mt_newx_email_file`) is still
handled correctly; the one "miss" (`email_notes`) is the benign ground-truth-debatable over-inclusion.

## Companion NewX change (repo: /home/sabawi/Development/NewX) — per-bot delivery capability

The double-email was traced to NewX gating `allow_delivery` on the **actor's** privilege only, so any
bot delivered when a privileged user asked. Per the design ("delivery is a per-BOT privilege; Ask
delivers, news bots do not"):
- `newx/app/ai_connector/responder.py` — `allow_delivery` now requires **both** the bot's opt-in AND
  the actor's per-user privilege: `allow_delivery = bot_delivery_enabled AND actor_privileged`. Logs a
  clear "delivery DENIED — bot not delivery-enabled" when a privileged actor uses a non-delivery bot.
- `newx/ai_plugins/Ask.yaml` — added `delivery_enabled: true`; replaced the "you CANNOT send emails /
  REFUSE" preamble with a truthful **DELIVERY POLICY** (deliver only to the requesting user's own
  verified account, never external; RAICA-enforced); removed the conflicting "DO NOT CREATE OR GENERATE
  FILES" line. All other bots keep their no-delivery preamble and have no flag (default = no delivery).

**Security invariant preserved (unchanged):** the per-bot gate only makes delivery STRICTER (an extra
AND). The recipient is still 100% locked to the requesting user — `delivery_recipient = actor.email`
only, and RAICA's `_send_email_locked` still forces `to_email` to it, drops CC, and fail-closes. A bot
can never email anyone but the requesting user.

## Activation
- RAICA: live on v1.0.0.88, `intent_classifier.mode: llm`.
- **NewX must be restarted** (web + Celery workers) to load the new `Ask.yaml` and `responder.py`.

## Files
- RAICA: `orchestration/intent.py`, `version.py` (→ 1.0.0.88), `README.md`, this changelog.
- NewX: `newx/app/ai_connector/responder.py`, `newx/ai_plugins/Ask.yaml`.

## Expected behavior after NewX restart
A reply to a news bot that @mentions @Ask → both bots respond, but **only @Ask delivers** (raicaMiddleEast
denied at the per-bot gate) → **one email**, to your own account, with @Ask's content. Rolling the
truthful DELIVERY POLICY preamble to the other 6 bots is deferred until you choose which (if any) should
also be delivery-enabled.
