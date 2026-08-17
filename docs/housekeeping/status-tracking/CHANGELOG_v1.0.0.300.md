# CHANGELOG v1.0.0.300 — news articles carry the publication date the feed already gave us

**Date:** 2026-08-17 · **Against:** v1.0.0.299 · **Closes:** SI-065

## The report

A live news bot, asked for a briefing on the last 8 hours, answered:

> "the tool results I received do not contain any news items with publication timestamps from
> the last 8 hours. The most recent datable content in my sources is from December 2025, and
> the news summaries provided are undated aggregates"

**It was telling the truth on every count.**

## What was NOT wrong

Retrieval. At `03:37:21 PM` — that same request — the news tool fetched fine:

```
📰 Parallel fetch completed in 1.4s with 8 articles
📰 Parallel fetch completed in 2.3s with 16 articles
```

24 fresh articles in under 3 seconds, and they reached the model (`evidence=30`, 56,021-char
context, 0 fabricated citations). Nothing was filtered out and nothing was broken.

An earlier note in this investigation claimed the news tool "returned nothing, silently."
That was wrong: those `Parallel fetch completed` lines are `print()` output with no timestamp
prefix, and the grep used to look for them required `^<timestamp>`. **The tool was never
broken; the search for evidence of it working was.**

## What was wrong

Every one of those 24 articles arrived **without a timestamp**, so the bot could not show any
of them fell inside the 8-hour window, and refused to fabricate one.

The RSS parser had already extracted the feed's date:

```python
# fastapi_server_complete.py:3131
if pub_date:
    article['pub_date'] = pub_date
```

**Nothing ever read it.** `pub_date` occurred four times in the file and all four were
writes. The date printed in a source block came solely from `_extract_content_date`, which
regex-hunts the article BODY for a literal `Published: August 17, 2026` string that RSS
descriptions essentially never contain. The call site even documented the assumption:
`# Use description as content (date will be extracted by _format_source_block)`.

Measured locally through the real tool call: **1 of 16 articles carried a date.**

Fresh content, made unusable by dropping the one field that proved it was fresh.

## The fix

- New `_normalize_pub_date()` — RFC-822 (with and without zone) and ISO-8601 → `August 17,
  2026 15:16 UTC`, converting to a single frame of reference. **Keeps the TIME**, because a
  bare day cannot answer "the last 8 hours". Anything unparseable falls through to the raw
  feed string: a date shown verbatim beats no date, and being strict here would recreate the
  outage for every feed with an unusual format. Reuses
  `email.utils.parsedate_to_datetime`, already this project's RFC-822 parser.
- `_format_source_block(..., pub_date=None)` — prefers the caller's structured date over the
  body scrape. Optional, so the three other call sites are untouched.
- The news path forwards `article.get('pub_date')`.

The feed date deliberately **wins** over the body scrape: a story published today may discuss
events of 1995, and scraping the body would date the source 1995.

## Proof, through the real tool call

| | before | after |
|---|---|---|
| articles returned | 16 | 16 |
| carrying `📅 Published:` | **1** | **16** |

And the question that actually failed:

```
now (UTC)        : August 17, 2026 16:27
timestamps parsed: 16/16
newest           : 0.2 h old
oldest           : 61.8 h old
within last 8h   : 13/16
```

**13 verifiable articles inside the window the bot was asked about**, where it previously had
zero it could place.

Sample block:

```
📄 SOURCE: Nvidia investing $1.5B in SoftBank data center developer behind OpenAI project
🔗 CITATION URL: https://techcrunch.com/2026/08/17/nvidia-investing-1-5b-in-softbank-...
📅 Published: August 17, 2026 15:16 UTC
❓ Access: Accessibility unknown
CONTENT: ...
```

## Verification

- **12 new tests** (`test_news_publication_dates.py`); **8 fail on pre-fix code**, including
  all three wiring tests. Covers RFC-822, offset→UTC, ISO-8601, unparseable pass-through,
  empty input, feed-date-wins, no-date-invented, and existing callers unaffected.
- **Tier-0 10/10.** **`make smoke` PASSED** — 6/6 tools, `get_news_summaries` returning 5,292
  chars through the real path. **Unit 623 passed**, the same 4 pre-existing failures.
  Version sync 19/19.
- One of my own tests was wrong and was fixed: it asserted `"1995" not in out` against the
  whole block, but the body is echoed verbatim under `CONTENT:`, so correct code failed it.
  Now asserts on the `📅 Published:` line — the actual invariant, not a convenient proxy.

## Not fixed here (separate defect)

The same request's `search_web` calls ran as `breaking world news today December 2025` — the
tool-calling model wrote a stale date into the query, which is where the bot's "December
2025" came from. Those results were correctly dated; they were simply about the wrong period.
That is a prompt/tool-argument problem, not a formatting one, and is deliberately left for its
own change rather than bundled here.
