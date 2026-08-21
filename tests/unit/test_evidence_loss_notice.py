"""SI-093 — an empty evidence block must not be handled as "no tools executed".

THE FAILURE THIS PREVENTS
-------------------------
Production, 2026-08-21 04:41 UTC. The `@raicaMiddleEast` bot published EIGHT fabricated news
items to a live public feed — named towns (Kfar Tibnit, Haret Hreik), specific casualty
figures, named officials — dated 2025-07-09/11, thirteen months stale, tagged #BreakingNews,
with NO sources. "Kfar Tibnit" appears ZERO times in any get_news_summaries result: the
specifics were invented, not retrieved.

Upstream, SI-086 had discarded 21,396 characters of real news for a 1,510-char failure
sentinel:

    BEFORE applying corrected results - tools_results length: 21396
    Corrected results length: 1510
    PARSED RESULTS: Generated 0 tool entries
    Context: 0 | System: 14728

But SI-086 was only the route in. The defect this file guards is what happened NEXT:

    if context_block.strip():
        ...
    else:
        # If no tools executed, use original context only     <- WRONG for this case
        in_prompt = f"PROMPT: {transformed_prompt}"           <- sent anyway, silently

Two different situations reached that branch — "no tools were asked for" (normal) and "tools
ran and their evidence vanished" (an error) — and the code could not tell them apart. The
model then received its full mandate ("You are a Middle East news correspondent. Report hard
news: what happened, where, when, who is involved") with zero evidence, and filled the vacuum
from training data. `Context: 0` was logged at :12274 and read by NOTHING.

A rate limit, a timeout, or a blocked search reaches the same branch — the trigger here was a
tool returning `empty_response`. So this is not fixed by fixing SI-086; SI-086 preserves
results that EXIST, and if retrieval returns nothing there is nothing to preserve.

THE RULE: tools called + empty context = EVIDENCE LOSS. Tell the model plainly, and log it as
an error rather than a number.
"""
import pytest

from fastapi_server_complete import _EVIDENCE_UNAVAILABLE_NOTICE, _evidence_loss_lead


# ------------------------------------------------- the condition that published fiction

def test_tools_ran_but_context_is_empty_yields_the_notice():
    """FAILS pre-SI-093: this case was indistinguishable from 'no tools executed'."""
    lead = _evidence_loss_lead("", ["get_news_summaries", "search_web"])
    assert lead == _EVIDENCE_UNAVAILABLE_NOTICE


def test_the_exact_production_tool_set_is_caught():
    """The six tools from the 04:41 run that produced the fabricated post."""
    tools = ["get_the_secret_tool", "get_news_summaries", "search_web",
             "search_web", "get_news_summaries", "search_web"]
    assert _evidence_loss_lead("", tools) == _EVIDENCE_UNAVAILABLE_NOTICE


def test_whitespace_only_context_is_still_empty():
    assert _evidence_loss_lead("   \n\t ", ["search_web"]) == _EVIDENCE_UNAVAILABLE_NOTICE


def test_a_none_context_does_not_crash():
    assert _evidence_loss_lead(None, ["search_web"]) == _EVIDENCE_UNAVAILABLE_NOTICE


# ------------------------------------------------- the normal cases must not change

def test_no_tools_asked_for_is_NOT_evidence_loss():
    """CONTROL. Nothing is missing when nothing was requested — this must stay silent, or
    every ordinary chat reply would be told it has no sources."""
    assert _evidence_loss_lead("", []) == ""
    assert _evidence_loss_lead("", None) == ""


def test_a_populated_context_is_never_flagged():
    """CONTROL. The 04:36 run in the same log had Context: 22119 and 6 tool entries."""
    ctx = "TOOLS EXECUTED: get_news_summaries\n\nDATA AND INFORMATION GATHERED:\n\ntool: x\nresult: y"
    assert _evidence_loss_lead(ctx, ["get_news_summaries"]) == ""


# ------------------------------------------------- what the notice must actually say

def test_the_notice_forbids_asserting_unretrieved_facts():
    """A caveat is not enough — the post that caused this DID carry a disclaimer ('Specific
    article URLs were not available') and published casualty claims anyway."""
    n = _EVIDENCE_UNAVAILABLE_NOTICE.lower()
    assert "zero sources" in n
    assert "must not state" in n
    assert "could not be retrieved" in n
    assert "do not soften this into a" in n          # the disclaimer-and-proceed loophole


def test_the_notice_states_the_loss_without_classifying_the_request():
    """Per the project's LLM-policy directive: state the FACT and let the model reason. No
    keyword list, no request-type classification, no per-bot special casing."""
    n = _EVIDENCE_UNAVAILABLE_NOTICE
    for forbidden in ("news", "chart", "stock", "correspondent", "bot"):
        assert forbidden not in n.lower(), f"notice must not special-case {forbidden!r}"
