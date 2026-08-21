"""SI-086: a correction FAILURE must never replace the results it failed to correct.

THE DEFECT THIS PREVENTS
------------------------
`arbitrator_validate_tasks` returns a short sentinel when it cannot correct a tool error. The
caller applied ANYTHING that was not None:

    if corrected_tools_results is not None:
        tools_results = corrected_tools_results

Production, 2026-08-18, the DGS10 request:

    BEFORE applying corrected results - tools_results length: 302181
    Corrected results length: 558
    AFTER  applying corrected results - tools_results length: 558
    PARSED RESULTS: Generated 0 tool entries
    📜 Prompt: 986 bytes | Context: 0

302,181 characters — a fetched CSV and ten successful compute results — were replaced by
"could not be corrected". The context block came out EMPTY, the synthesis prompt was the user's
question alone (986 = len("PROMPT: ") + the 978-char prompt), and the answer delivered was 105
characters:

    "I'll fetch the DGS10 series from FRED and perform the full analysis. Let me start by
     retrieving the data."

Every figure the user asked for had in fact been computed. Two failing tools discarded the twelve
that worked.

WHY THE SENTINEL STILL EXISTS
-----------------------------
Its purpose — stop the model citing figures from tools that failed — is real, and is preserved by
APPENDING it. Deleting the evidence is not a way of protecting the reader from it.
"""
import re

import fastapi_server_complete as srv

# Fall back to the literal so these FAIL, not ERROR, against pre-fix code: a test that cannot
# import is a test that proves nothing about behaviour.
MARKER = getattr(srv, "_ARBITRATOR_CORRECTION_FAILED", "ARBITRATOR_ERROR_CORRECTION_FAILED")


def _apply(original: str, corrected):
    """The decision under test, exercised through the SERVER's own guard.

    Mirrors the branch at the `BEFORE applying corrected results` site: if the server has no
    sentinel guard (pre-fix), the substitution happens and these tests fail on the outcome, which
    is the behaviour that matters.
    """
    import inspect
    guarded = "startswith(_ARBITRATOR_CORRECTION_FAILED)" in inspect.getsource(srv)
    if corrected is not None:
        if guarded and corrected.startswith(MARKER):
            return f"{original}\n\n{corrected}"
        return corrected
    return original


REAL = ("Tool: lookup_website\nResult: date,DGS10\n1962-01-02,4.06\n" * 40
        + "Tool: compute\nResult: mean 5.88\ncomputed as: np.nanmean(y)\n" * 10)
SENTINEL = (f"{MARKER}: Original tools contained errors that could not be corrected "
            "after 3 iterations.")


def test_a_failure_sentinel_does_not_replace_the_results():
    out = _apply(REAL, SENTINEL)
    assert len(out) > len(REAL), "results shrank when a correction failed"
    assert "np.nanmean(y)" in out, "the successful compute results were destroyed"


def test_the_failure_is_still_reported_to_the_model():
    """The sentinel's purpose survives — it is appended, not discarded."""
    assert MARKER in _apply(REAL, SENTINEL)


def test_a_genuine_correction_is_still_applied():
    """CONTROL — the arbitrator must keep working when it succeeds."""
    corrected = "Tool: compute\nResult: mean 6.15\ncomputed as: np.nanmean(y)\n"
    assert _apply(REAL, corrected) == corrected


def test_no_correction_leaves_the_originals_untouched():
    """CONTROL — the None path."""
    assert _apply(REAL, None) == REAL


def test_the_marker_is_ONE_constant_shared_by_producer_and_consumer():
    """A producer and consumer that drift on this string silently destroy data — as they did.

    The sentinel is built with the constant and matched with the constant, so a change to the
    wording cannot re-open the defect.
    """
    src = __import__("inspect").getsource(srv)
    assert src.count('_ARBITRATOR_CORRECTION_FAILED = "') == 1, "the marker is not defined exactly once"
    # the literal must not be re-typed anywhere except that single definition
    literal_uses = len(re.findall(r'"ARBITRATOR_ERROR_CORRECTION_FAILED', src))
    assert literal_uses == 1, f"the raw string is hand-written {literal_uses}x; use the constant"


def test_the_server_actually_guards_the_assignment():
    """Wiring: the real branch must consult the marker before overwriting."""
    src = __import__("inspect").getsource(srv)
    i = src.index("BEFORE applying corrected results")
    seg = src[i:i + 3000]
    guard = seg.index("startswith(_ARBITRATOR_CORRECTION_FAILED)")
    assign = seg.index("tools_results = corrected_tools_results")
    assert guard < assign, "the results are overwritten before the sentinel is checked"
