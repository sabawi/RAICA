# CHANGELOG v1.0.0.124

**Date:** 2026-06-15
**Previous:** v1.0.0.123 (Google News coverage)
**Theme:** **Tool selection** — the tool-calling model now reaches for `search_web` on specific-subject
news lookups, so queries like "latest FIFA scores" return clean publisher URLs + rich content.

---

## Why

A "show me the latest FIFA scores" query returned general news, not football. Root cause was in the
tool-calling system prompt (`pre_tool_model_system_prompt.txt`), not the tool descriptions: it mapped the
NEWS intent to `get_the_secret_tool()` + `get_news_summaries()` and listed `search_web()` as merely
**"Optional"** for news. So the model never called `search_web` for a specific-subject news ask — and
`get_news_summaries` returns broad CATEGORY headlines, which don't contain a specific team's scores.

## Change

`pre_tool_model_system_prompt.txt` — a **specific-subject rule** (policy language, no keyword hardcoding),
in two spots:
- a prominent note after the intent table, and
- Section C (News / Current Events): `search_web()` is no longer "optional" — when a news request names a
  SPECIFIC subject a broad category feed might miss (a team / match / score / game, a named person /
  company / product, a particular event, or any uncommon / just-happened detail), the model must call
  BOTH `get_news_summaries()` AND `search_web()`. General "latest news" with no named subject may still use
  `get_news_summaries` alone. Baked-in example: "latest FIFA scores" → `get_the_secret_tool()` +
  `get_news_summaries(filter="sports")` + `search_web(query="latest FIFA scores results today")`.

Also scrubbed pre-existing example PII in this prompt (an email + a `/home/<user>/` path → placeholders).

## Verification (user-confirmed)

Re-test of "show me the latest FIFA scores as of now" on local (1.0.0.124):
`TOOLS EXECUTED: get_the_secret_tool, get_news_summaries, search_web` — search_web now fires, returning
clean publisher URLs (ESPN, LA Times, FIFA.com, MSN, 365Scores, Flashscore, LiveScore) with live scores in
the content ("Spain 0, Cape Verde 0", "Saudi Arabia took a 1-0 lead", "Cape Verde stuns Spain"), plus the
Google News articles from get_news_summaries. User: "WOW! What a difference! Much richer content now."

## Files
- `pre_tool_model_system_prompt.txt` — specific-subject search_web rule + PII scrub.
- `version.py` (→ 1.0.0.124), this changelog.
