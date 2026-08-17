# CHANGELOG v1.0.0.301 — a transport failure removes a source instead of becoming one

**Date:** 2026-08-17 · **Against:** v1.0.0.300 · **Closes:** SI-066

## How this was found

Chasing a 41-minute silent DR stall on production, all the way down to the transport layer.
The stall itself is still unexplained (SI-064) — but tracing it there exposed a defect that
had been corrupting search results continuously, in the open, for a long time.

## The defect: three layers of exception handling, each hiding the failure

```
sync_pooled_get          catches EVERYTHING  -> {'status_code': 0, 'ok': False,
                                                 'error': 'Connection reset by peer'}
raise_for_status()       correctly raises                    <- the only honest layer
get_text_from_url_...    catches it and returns
                         f"Error extracting content: {e}"    <- PROSE, as page content
```

The failure signal is created at the bottom and **destroyed at the top**. That `error` field
is never read by anything — the same dead-write shape as `article['pub_date']` in v300.

**Measured on production:** 211 occurrences of `Error extracting content` in a single log,
and **13 of them reached the model** inside the `"prompt"` payload under `DATA AND
INFORMATION GATHERED`:

```
Error extracting content: HTTP 403 Error for url: https://www.science.org/...
Error extracting content: HTTP 401 Error for url: https://www.wsj.com/...
Error extracting content: Request failed: HTTPSConnectionPool(... Max retries exceeded
```

403s, 401 paywalls, 429s and TCP resets were served to the LLM **as research evidence**.

### Why that is functionally wrong, not just untidy

- **Nothing could retry.** There was no failure to react to — a transient 429 permanently
  lost that source for the whole request.
- **The benchmark was measuring corrupted inputs.** `citation_count`, `unique_sources` and
  `evidence_items` counted fetches that never returned a page — the very metrics used all
  week to judge answer quality.
- **"Page had little text" was indistinguishable from "connection was reset."**

## The fix

The codebase already had the right convention ten lines above: `return None` means *unusable
source, skip it*, and the caller already honoured it. The fix is to use it.

1. **Failures return the `None` sentinel, never prose** — in the extractor *and* in the
   caller's own duplicate handler, which had the same bug.
2. **`response.close()` in a `finally`** — deterministic release on every path.
3. **Losses are recorded and reported** — each dropped source is logged with URL and reason
   and classified transient (429/5xx/reset/timeout) vs permanent (401/403/404); each search
   logs how many sources it lost. A thin result is now distinguishable from one that was
   never fetched — which is exactly the signal a retry policy will need.

Retry itself (item 2 of the original plan) is deliberately **not** included: it changes
timing behaviour and belongs in its own change.

## Verification

- **14 tests**, `tests/unit/test_search_transport_failure.py`; **9 fail on pre-fix code**.
- **Behavioural, not just structural:** a real refused connection through the actual
  transport layer returns `ok=False` with an error rather than empty success.
- **Tier-0 10/10.** **`make smoke` PASSED 6/6** — `search_web` and `get_news_summaries`
  exercised through the real path. **Unit 637 passed**, the same 4 pre-existing failures.
  Version sync 19/19.

## An attribution that did NOT survive testing

An earlier draft of this change claimed the 43 CLOSE-WAIT sockets on production were caused
by the unclosed response. **That claim is withdrawn.** A harness driving 30 peer-closed
responses leaked **zero** fds both with and without the `close()` fix — the reproduction does
not discriminate in either direction. Those sockets may simply be pooled keep-alive
connections the remote closed and urllib3 has not yet reaped: normal pool behaviour.

`close()` stays because deterministic release is correct hygiene, but it is recorded as
hygiene, not as a bug fixed. The code comment and the test docstrings were corrected to say
so, and the fd test is labelled a regression guard — it passes on pre-fix code, because a
*refused* connection never establishes a socket and cannot reproduce CLOSE-WAIT.

## Three of my own tests were wrong before they were right

Worth recording, because all three failed the same way — asserting a convenient proxy
instead of the invariant:

1. A fixed 4000-char source window truncated mid-handler, failing two tests against correct
   code.
2. A raw-source grep matched **the comment documenting the old bug**, not the code. Fixed by
   stripping comments before asserting.
3. (v300) `assert "1995" not in out` matched the body echoed under `CONTENT:`; the invariant
   was about the date *line*.

## Method note

This is what "root cause" means: not the first application-level story that fits, but the
layer where the signal is actually destroyed. Three earlier explanations this session — a
missing `pub_date`, an unbounded `asyncio.gather`, a hung LLM call — were each plausible,
each partly true, and none of them was the bottom.
