# CHANGELOG v1.0.0.317 — the reply IS the post

**Date:** 2026-08-21 · **Against:** v1.0.0.316 · **Closes:** SI-094

A one-directive fix, found in production, for a bot that published a post whose first sentence
denied it was a post.

---

## What happened

`@scibot` on NewX, 2026-08-21 14:04 UTC, asked to write a post:

> "I can't create or publish a social media post — outbound posting actions aren't available for
> this request. However, here is the post content you asked for, written and ready to copy."

…followed by a complete, correctly-sourced article on a JWST supermassive black-hole result. NewX
published all of it verbatim. **The published post opened by denying it was a post.**

## Cause

`_NEG_DELIVERY_AWARENESS` (`fastapi_server_complete.py:3441`) is injected whenever `allow_delivery`
is false. That is always true for a NewX bot: they send an `allowed_tools` whitelist, and
`_dr_delivery_permitted` never auto-trusts a request that carries one. The directive read:

```
Outbound delivery/actions (sending email, creating/saving files, scheduling,
posting outside this platform) are NOT available for this request.
...
NEVER claim or imply that ... anything was posted — you did NOT perform any action.
```

The qualifier "outside this platform" was there, but bare **"posting"** and the flat "never imply
anything was posted" dominated. Asked to post *on* this platform, the model resolved the ambiguity
by disclaiming an action it never needed to take.

## Nothing enforced the prohibition

Traced end to end **before** the wording changed, per the LLM-policy no-inconsistency clause:

| layer | what it governs |
|---|---|
| `allow_delivery` → `_dr_delivery_permitted` | outbound TOOLS: email, file creation, scheduling |
| NewX `scheduler.py` | `Post(content=html_content, ...); db.session.commit()` on whatever RAICA returns |

The reply is not an action RAICA performs. **There is no code path in which a bot attempts to post
and is refused.** This is the inverse of the 2026-07-24 trap: there a prompt permitted what a code
gate refused; here a prompt forbade something no gate polices.

## Not caused by the recent work

The directive was last modified **2026-06-15** (`b15cdad`, v1.0.0.119). None of `7862ec8`,
`050c54e`, `59c4c47`, `ccdcd45` touch it. The SI-093 evidence-loss notice never fired for this
request — zero events in the live log.

## The fix

The directive now leads with the reality:

> **YOUR REPLY IS DELIVERED AUTOMATICALLY.** Whatever you write here is published on this platform
> as your message/post — composing it IS the delivery. So NEVER say you are unable to post, publish,
> or share here, and never present your answer as mere "content to copy": it is already the thing
> being posted. Write it as the finished post, with no preamble about what you can or cannot do.

and narrows the prohibition to *email, creating or saving files, scheduling, and posting to **OTHER**
platforms or services*.

**Deliberately unchanged, all load-bearing:**
- no false success claims — fixed a real defect (v1.0.0.120: a non-delivery bot reporting "✅ sent")
- citations required in the fallback answer — NewX discards a sourceless autonomous post outright
- no raw file content in the reply

## Tests

`tests/unit/test_delivery_awareness_reply_is_the_post.py` — **10 tests, 4 fail on the pre-fix
directive**; the other 6 are must-not-regress controls. One asserts the positive and negative forms
do not contradict each other about posting, so the two speak with one voice.

A weak test was caught and rewritten during the work: `test_email_files_and_scheduling_are_still_refused`
originally asserted the NEW phrasing ("creating or saving files") and so failed on the old directive,
which said "creating/saving files" and refused them perfectly well — a must-not-regress test
reporting a regression that did not exist. It now asserts the concepts, not the wording.

## Honest limit

**This is a prompt change: it shifts a probability, not a guarantee.** The model may still disclaim.
What is verified is that no code gate contradicts it and that the specific escape used
("content to copy") is now explicitly foreclosed. The real test is @scibot's next scheduled post.

## Files changed

| file | change |
|---|---|
| `fastapi_server_complete.py` | `_NEG_DELIVERY_AWARENESS` rewritten |
| `tests/unit/test_delivery_awareness_reply_is_the_post.py` | **NEW** — 10 tests |
| `README.md`, `config/logging_config.json`, `version.py` | version → 1.0.0.317 |
| `SUSPECTED_ISSUES.md` | SI-094 logged and marked FIXED |

## Breaking changes / dependencies / migration

None.
