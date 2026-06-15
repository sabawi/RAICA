#!/usr/bin/env python3
"""
CHARACTERIZATION TEST — legacy intent classifier `_verify_task_completion`
==========================================================================

Phase 0 of the Context-and-Action Substrate Convergence
(see docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md).

PURPOSE: This is a *characterization* (a.k.a. golden-master / pin-down) test. It does NOT assert what
the classifier *should* do — it snapshots what it *currently does*, so that the upcoming refactor
(routing intent classification through the LLM decomposer and retiring the 304-line keyword classifier)
cannot silently change behavior. Any drift in `{complete, missing_tools, pattern}` for the corpus below
fails this test and must be a conscious, reviewed decision (regenerate the golden on purpose).

It also encodes the convergence INVARIANTS that must hold regardless of how the refactor is done:
  • I1 — meta-task suppression (OpenWebUI title/tag generation never triggers tools)
  • I2 — information-only requests never trigger post-generation actions

I3 (recipient lock/fail-closed), I5 (single-send) and I6 (DR unchanged) live in
test_recipient_resolution_characterization.py and the DR suite — some activate in Phase 1 once the
relevant logic is extracted into a callable shared module.

RUN:
    venv/bin/python3 -m pytest tests/integration/test_intent_classifier_characterization.py -v
REGENERATE THE GOLDEN (only when a behavior change is intended and reviewed):
    venv/bin/python3 tests/integration/test_intent_classifier_characterization.py --regenerate

NOTE: importing fastapi_server_complete constructs module globals (tool_manager, app, …) but does NOT
start the server (uvicorn.run is guarded by __main__). `_verify_task_completion` does not use
tool_manager, so we pass None.
"""
import os
import sys
import json
import asyncio

import pytest

# Make the project root importable when run directly or via pytest.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

GOLDEN_PATH = os.path.join(_PROJECT_ROOT, "tests", "data", "intent_classifier_golden.json")

# Keys of the classifier result that define observable behavior for the POST-LLM path. `reason` is
# intentionally EXCLUDED from the golden comparison — it is a human-readable string assembled from
# pattern descriptions and is not behavior (its exact wording must be free to change).
BEHAVIOR_KEYS = ("complete", "missing_tools", "pattern")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# CORPUS — representative inputs covering every branch of the current classifier. Each item:
#   id           : stable identifier (golden key)
#   prompt       : the user prompt
#   tools_called : tools the tool-calling phase reported (usually [] at verification time)
#   tools_results: the accumulated tool-results blob (usually '' pre-execution)
# Mined from the classifier's own trigger lists (:5837–5923), the meta/exclusion sets, and the real
# NewX "email the above response as HTML" incident.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
CORPUS = [
    # ---- meta-task (OpenWebUI housekeeping) — INVARIANT I1: must be complete, no tools ----
    {"id": "meta_title_emoji",
     "prompt": "Generate a concise, 3-5 word title with an emoji summarizing the chat history.",
     "tools_called": [], "tools_results": ""},
    {"id": "meta_tags",
     "prompt": "Generate 1-3 broad tags categorizing the main themes of the chat history.",
     "tools_called": [], "tools_results": ""},

    # ---- information-only — INVARIANT I2: no post-generation actions ----
    {"id": "info_just_tell_me", "prompt": "Just tell me what the capital of France is.",
     "tools_called": [], "tools_results": ""},
    {"id": "info_what_are", "prompt": "What are the main causes of inflation?",
     "tools_called": [], "tools_results": ""},
    {"id": "info_research_only", "prompt": "Research the history of the printing press and explain it.",
     "tools_called": [], "tools_results": ""},

    # ---- the real NewX incident ----
    {"id": "newx_email_above_html",
     "prompt": "Email the above response as a HTML document",
     "tools_called": [], "tools_results": ""},

    # ---- delivery / packaging patterns ----
    {"id": "pure_email_to_addr", "prompt": "Send an email to bob@example.com with subject Hello.",
     "tools_called": [], "tools_results": ""},
    {"id": "file_create_and_email", "prompt": "Create a file and email it to me.",
     "tools_called": [], "tools_results": ""},
    {"id": "research_html_report_email",
     "prompt": "Research electric vehicles and create a professional HTML report and email it to me.",
     "tools_called": [], "tools_results": ""},
    {"id": "document_cover_letter_email",
     "prompt": "Write a cover letter and email it to me as a PDF.",
     "tools_called": [], "tools_results": ""},
    {"id": "multi_file_and_email",
     "prompt": "Create a pdf file, a html file, a md file, and a txt file and send them all in one email.",
     "tools_called": [], "tools_results": ""},
    {"id": "news_report_and_email", "prompt": "Email me the news report on the stock market news.",
     "tools_called": [], "tools_results": ""},
    {"id": "save_output_pdf", "prompt": "Save the output to a PDF and email it as an attachment.",
     "tools_called": [], "tools_results": ""},

    # ---- publishing (dynamic tool mapping) ----
    {"id": "publish_wordpress", "prompt": "Publish this article to my WordPress blog.",
     "tools_called": [], "tools_results": ""},
    {"id": "publish_twitter", "prompt": "Tweet this summary.",
     "tools_called": [], "tools_results": ""},
    {"id": "publish_substack", "prompt": "Post this to Substack.",
     "tools_called": [], "tools_results": ""},

    # ---- plain answer, no delivery ----
    {"id": "plain_poem", "prompt": "Write a short poem about autumn leaves.",
     "tools_called": [], "tools_results": ""},

    # ---- already-satisfied / state variants ----
    {"id": "email_already_called",
     "prompt": "Send an email to bob@example.com with the summary.",
     "tools_called": ["secure_email_sender"],
     "tools_results": "Tool: secure_email_sender\nResult: Email sent successfully\n\n"},
    {"id": "email_deferred",
     "prompt": "Create a file and email it to me.",
     "tools_called": ["sandboxed_executor", "secure_email_sender"],
     "tools_results": "Tool: sandboxed_executor\nResult: deferred\n\nTool: secure_email_sender\nResult: deferred\n\n"},
]


async def _classify(item):
    import fastapi_server_complete as F
    res = await F._verify_task_completion(item["prompt"], item["tools_called"], item["tools_results"], None)
    # normalize: missing_tools order is built deterministically by the classifier; keep as-is but
    # coerce to list for JSON stability.
    return {k: (list(res.get(k)) if isinstance(res.get(k), (list, tuple)) else res.get(k)) for k in BEHAVIOR_KEYS}


def _compute_all():
    async def run():
        out = {}
        for item in CORPUS:
            out[item["id"]] = await _classify(item)
        return out
    return asyncio.run(run())


def _load_golden():
    if not os.path.exists(GOLDEN_PATH):
        return None
    with open(GOLDEN_PATH, "r") as fh:
        return json.load(fh)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def golden():
    g = _load_golden()
    if g is None:
        pytest.skip(f"golden not found at {GOLDEN_PATH} — regenerate with: "
                    f"venv/bin/python3 {os.path.relpath(__file__, _PROJECT_ROOT)} --regenerate")
    return g


@pytest.fixture(scope="module")
def computed():
    return _compute_all()


@pytest.mark.parametrize("item_id", [i["id"] for i in CORPUS])
def test_classifier_matches_golden(item_id, golden, computed):
    """Pin-down: the classifier's observable output for each corpus prompt must match the committed
    golden. Drift here = a behavior change the refactor must justify (regenerate golden deliberately)."""
    assert item_id in golden, f"'{item_id}' missing from golden — regenerate the golden file"
    assert computed[item_id] == golden[item_id], (
        f"CLASSIFIER DRIFT for '{item_id}':\n  now    = {computed[item_id]}\n  golden = {golden[item_id]}")


def test_corpus_and_golden_in_sync(golden, computed):
    """Golden and corpus must cover exactly the same ids (no stale/missing entries)."""
    assert set(golden.keys()) == set(computed.keys()), (
        f"corpus/golden id mismatch: only_in_golden={set(golden)-set(computed)}, "
        f"only_in_corpus={set(computed)-set(golden)}")


# ---- INVARIANT I1 — meta-task suppression (semantic, survives golden regeneration) ----
@pytest.mark.parametrize("prompt", [
    "Generate a concise, 3-5 word title with an emoji summarizing the chat history.",
    "Generate 1-3 broad tags categorizing the main themes of the chat history.",
])
def test_invariant_I1_meta_task_never_triggers_tools(prompt):
    import fastapi_server_complete as F
    res = asyncio.run(F._verify_task_completion(prompt, [], "", None))
    assert res["complete"] is True, f"I1 VIOLATED: meta-task marked incomplete → would run tools: {res}"
    assert not res.get("missing_tools"), f"I1 VIOLATED: meta-task has missing_tools {res}"


# ---- INVARIANT I2 — information-only requests never trigger post-generation actions ----
@pytest.mark.parametrize("prompt", [
    "Just tell me what the capital of France is.",
    "What are the main causes of inflation?",
    "Explain how a four-stroke engine works.",
])
def test_invariant_I2_information_only_no_actions(prompt):
    import fastapi_server_complete as F
    res = asyncio.run(F._verify_task_completion(prompt, [], "", None))
    assert res["complete"] is True, f"I2 VIOLATED: info-only marked incomplete: {res}"
    assert not res.get("missing_tools"), f"I2 VIOLATED: info-only has missing_tools: {res}"


def _regenerate():
    data = _compute_all()
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    print(f"✅ wrote golden ({len(data)} entries) → {GOLDEN_PATH}")
    for k, v in sorted(data.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        print("Run with --regenerate to (re)write the golden, or use pytest to verify.")
