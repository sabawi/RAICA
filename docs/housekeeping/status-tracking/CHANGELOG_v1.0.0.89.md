# CHANGELOG v1.0.0.89

**Date:** 2026-06-06
**Previous:** v1.0.0.88 (intent-classifier fix #1 reframed)
**Theme:** **Delivery-awareness is now conditional on `allow_delivery` — non-delivery bots can no
longer falsely claim "email sent"**

---

## The bug (live dev validation)

After the NewX per-bot gate correctly DENIED delivery for @raicaNews (a non-delivery bot), the bot's
posted reply still **opened with a false success claim**:

> *"Here is your breaking news briefing formatted as an HTML attachment. **The email has been sent
> with the file ready for download.**"* (no email was sent)

## Root cause

RAICA's primary-LLM system prompt (`primary_model_system_prompt.txt`) **unconditionally** contained a
"POST-LLM EXECUTION AWARENESS" block: *"Email sending … handled automatically … **DO NOT add disclaimers
such as 'I cannot send an email'** … the system handles the rest."* That is correct only when delivery
is actually happening. For a non-delivery request it (a) told the LLM email was handled, and (b) forbade
it from disclaiming — so the LLM claimed success. NewX's "you cannot deliver / never claim success"
directive couldn't beat RAICA's explicit "do not disclaim."

## The fix

The awareness block is no longer hardcoded in the static file. RAICA now injects the **correct version
based on the actual permission** for the request (`orchestration.policy.authorize_delivery(data).permitted`,
which also covers auto-trust clients like OpenWebUI):

- **Delivery permitted** → the original positive block ("handled automatically; focus on content;
  don't disclaim").
- **Delivery NOT permitted** → a negative block: *"Outbound delivery/actions are NOT available for this
  request. Do NOT claim you performed them — you did NOT. Provide the content and add one brief note
  that the action isn't available. NEVER state or imply that an email was sent / a file was attached /
  anything was posted."*

So a non-delivery bot now provides its content + a truthful "not available" note, and **cannot claim
success**. A delivery-enabled bot is unchanged.

## Files
- `primary_model_system_prompt.txt` — removed the hardcoded POST-LLM EXECUTION AWARENESS block.
- `fastapi_server_complete.py` — `_POS_DELIVERY_AWARENESS` / `_NEG_DELIVERY_AWARENESS` constants;
  `_build_enhanced_primary_system_prompt(..., allow_delivery=True)` injects the right one for all return
  paths; call site passes `allow_delivery=delivery_policy.authorize_delivery(data).permitted`.
- `version.py` (→ 1.0.0.89), `README.md`, this changelog.

## Companion (NewX, prior step, repo /home/sabawi/Development/NewX)
The graceful-degrade messaging was also generalized in NewX `call_raica` — one ACTION-AGNOSTIC
"DELIVERY & ACTIONS" directive (permitted / not-permitted), action-agnostic so it extends to calendar,
social posting, research delegation, and compound requests with zero per-bot edits. The "DELIVERY &
ACTIONS" (NewX, answering-LLM guidance) and this "OUTBOUND ACTIONS" (RAICA, primary-LLM guidance) now
agree.

## Re-test expectation
@raicaNews "email me an HTML file of the news" → posts the news content (with citations) **+ a brief
"delivery isn't available" note**, NO email, and **no false 'email sent' claim**. @Ask "email me …" →
content + actual email to your own account.

## Status
Dev: RAICA v1.0.0.89 (`mode: llm`), NewX restarted. Reversible. Not committed.
