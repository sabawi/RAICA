# CHANGELOG v1.0.0.330

**Date:** 2026-09-26
**Theme:** writing a post is not publishing it — the delivery classifier stops asking to tweet every bot post

## Fixed (SI-105)

After the overnight bot run, every NewX bot request got `missing_tools: ['social_media_twitter_test']` from the
LLM intent classifier; only each bot's tool whitelist stopped a test plugin from firing. It had been happening for
weeks (29 times on 09-18).

- **Cause:** NewX's scheduler asks RAICA to "Create a new social media post about: …". The classifier's policy
  treated any "post" as a request to publish, with no distinction between writing the post (NewX publishes the
  returned text itself) and sending content out to an account or service.
- **Fix — `orchestration/intent.py` (policy language):** writing a post, caption, reply or announcement is the
  answer and needs no publishing tool; sending content out — to the user's followers, account, blog or a named
  service — is a publishing delivery.
- **Evidence:** the real bot prompt on the live classifier model, 3 runs: Twitter tool 3/3 → none 3/3. The 34-case
  live intent eval: 34/34 on the delivery decision and the tool kinds. An earlier draft that exempted "tweet"
  wholesale failed two publish cases and was refined before shipping.

## Test harness

- `tests/utilities/run_intent_eval.py` read a hardcoded `deepseek-v4-flash:cloud`, retired on 2026-09-25 — every
  call failed and the eval reported nonsense. It now reads `convergence.shadow_classifier.model` from config and
  refuses to run if it is unset.
- `tests/utilities/intent_eval_scoring.py` counts `plot_data` (the chart tool since v1.0.0.305) as an image tool.

## Also in this checkpoint

`SUSPECTED_ISSUES.md`: SI-104 marked owner-verified, with a correction — the planner's repeated ticker calls do not
execute twice (exact repeats are skipped at dispatch).

## Breaking changes / migration

None.
