#!/usr/bin/env python3
"""
CHARACTERIZATION TEST — recipient resolution (and the recipient-lock contract)
==============================================================================

Phase 0 of the Context-and-Action Substrate Convergence
(see docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md, disconnect D3).

Today RAICA resolves email recipients in several disconnected places. This pins down the CURRENT
behavior of the callable resolvers so that Phase 1 — which extracts a single shared
`resolve_recipient()` used by every delivery path — provably preserves it:

  • `_resolve_email_recipients(action_args, user_prompt)`  — the deep-research-side resolver
  • `_detect_html_email_request(tools_results, user_prompt)` — legacy HTML-email detector
  • `_detect_html_email_request_in_args(args, user_prompt)`   — legacy interceptor detector

It also WRITES DOWN the security INVARIANT I3 (recipient lock / fail-closed) as executable
expectations. The lock logic currently lives INSIDE `_run_dr_delivery` and the nested
`_send_secure_email` (not separately callable), so those I3 cases are marked xfail/skip and ACTIVATE
in Phase 1 the moment the logic is extracted into the shared `resolve_recipient()`. Writing them now
makes the contract explicit and ready.

RUN:
    venv/bin/python3 -m pytest tests/utilities/test_recipient_resolution_characterization.py -v
REGENERATE GOLDEN (only when an intended, reviewed change):
    venv/bin/python3 tests/utilities/test_recipient_resolution_characterization.py --regenerate
"""
import os
import sys
import json
import asyncio

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

GOLDEN_PATH = os.path.join(_PROJECT_ROOT, "tests", "data", "recipient_resolution_golden.json")

# ─────────────────────────────────────────────────────────────────────────────────────────────────
# CORPUS for `_resolve_email_recipients(action_args, user_prompt)` (sync) — covers: structured-args
# precedence, prompt fallback, multiple/dedup, none-found, mixed key names.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
RESOLVE_CORPUS = [
    {"id": "structured_to_wins_over_prompt", "args": {"to": ["a@b.com"]}, "prompt": "send to c@d.com"},
    {"id": "prompt_fallback", "args": {}, "prompt": "please email it to c@d.com"},
    {"id": "none_found", "args": {}, "prompt": "no address anywhere here"},
    {"id": "recipients_list", "args": {"recipients": ["x@y.com", "z@w.com"]}, "prompt": ""},
    {"id": "dedup", "args": {"to": ["dup@x.com", "dup@x.com"]}, "prompt": "also dup@x.com"},
    {"id": "recipient_singular_key", "args": {"recipient": "single@x.com"}, "prompt": ""},
    {"id": "email_key", "args": {"email": "ek@x.com"}, "prompt": ""},
    {"id": "prompt_multiple", "args": {}, "prompt": "email to one@x.com and two@y.com"},
]

# CORPUS for the two async legacy detectors. They return dicts; we snapshot them verbatim.
DETECT_HTML_CORPUS = [
    {"id": "html_with_addr", "tools_results": "", "prompt": "email the above response to bob@x.com as an html attachment"},
    {"id": "html_no_addr", "tools_results": "", "prompt": "email the above response as html"},
    {"id": "plain_no_email", "tools_results": "", "prompt": "write a poem"},
]
DETECT_ARGS_CORPUS = [
    {"id": "args_to_email", "args": {"to_email": "a@b.com"}, "prompt": "email it as html"},
    {"id": "args_empty_prompt_addr", "args": {}, "prompt": "email html to c@d.com"},
    {"id": "args_empty_no_addr", "args": {}, "prompt": "make an html file"},
]


def _compute_all():
    import fastapi_server_complete as F

    async def run():
        out = {"_resolve_email_recipients": {}, "_detect_html_email_request": {}, "_detect_html_email_request_in_args": {}}
        for c in RESOLVE_CORPUS:
            out["_resolve_email_recipients"][c["id"]] = F._resolve_email_recipients(c["args"], c["prompt"])
        for c in DETECT_HTML_CORPUS:
            out["_detect_html_email_request"][c["id"]] = await F._detect_html_email_request(c["tools_results"], c["prompt"])
        for c in DETECT_ARGS_CORPUS:
            out["_detect_html_email_request_in_args"][c["id"]] = await F._detect_html_email_request_in_args(c["args"], c["prompt"])
        return out
    return asyncio.run(run())


def _load_golden():
    if not os.path.exists(GOLDEN_PATH):
        return None
    with open(GOLDEN_PATH, "r") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def golden():
    g = _load_golden()
    if g is None:
        pytest.skip(f"golden not found — regenerate with: venv/bin/python3 "
                    f"{os.path.relpath(__file__, _PROJECT_ROOT)} --regenerate")
    return g


@pytest.fixture(scope="module")
def computed():
    return _compute_all()


@pytest.mark.parametrize("fn,item_id", [("_resolve_email_recipients", c["id"]) for c in RESOLVE_CORPUS]
                         + [("_detect_html_email_request", c["id"]) for c in DETECT_HTML_CORPUS]
                         + [("_detect_html_email_request_in_args", c["id"]) for c in DETECT_ARGS_CORPUS])
def test_recipient_resolution_matches_golden(fn, item_id, golden, computed):
    assert fn in golden and item_id in golden[fn], f"{fn}/{item_id} missing from golden — regenerate"
    assert computed[fn][item_id] == golden[fn][item_id], (
        f"RECIPIENT RESOLUTION DRIFT {fn}/{item_id}:\n  now    = {computed[fn][item_id]}\n"
        f"  golden = {golden[fn][item_id]}")


# ---- Semantic checks that must hold regardless of golden (structured-args precedence + dedup) ----
def test_structured_args_take_precedence_over_prompt():
    import fastapi_server_complete as F
    assert F._resolve_email_recipients({"to": ["a@b.com"]}, "send to c@d.com") == ["a@b.com"]


def test_no_address_yields_empty():
    import fastapi_server_complete as F
    assert F._resolve_email_recipients({}, "no address here") == []


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# INVARIANT I3 — recipient lock / fail-closed. The lock logic currently lives inside _run_dr_delivery
# and the nested _send_secure_email. PHASE 1 extracted the shared `_send_email_locked` (module-level)
# and orchestration/policy.resolve_locked_recipient, so these now run for real (end-to-end at the send
# chokepoint that BOTH the POST-LLM executor and the email-interceptor route through). The pure-policy
# decision is also covered in tests/utilities/test_orchestration_policy.py.
# ─────────────────────────────────────────────────────────────────────────────────────────────────
class _FakeToolManager:
    """Records every secure_email_sender call so we can assert what address actually got used."""
    def __init__(self):
        self.sent = []

    async def safe_function_call(self, name, params):
        self.sent.append((name, dict(params)))
        return "Email sent successfully"


def test_I3_restricted_client_forces_locked_recipient():
    """Restricted client + valid delivery_recipient → email ONLY the locked address; prompt recipient
    and CC are discarded."""
    import fastapi_server_complete as F
    tm = _FakeToolManager()
    res = asyncio.run(F._send_email_locked(
        tm, {"to_email": "attacker@evil.com", "cc_emails": "leak@evil.com", "body": "x"},
        recipient_locked=True, locked_recipient="user@own.com"))
    assert tm.sent, "I3 VIOLATED: nothing was sent"
    sent_params = tm.sent[0][1]
    assert sent_params["to_email"] == "user@own.com", f"I3 VIOLATED: to_email={sent_params['to_email']}"
    assert sent_params["cc_emails"] is None, "I3 VIOLATED: CC not dropped for locked client"
    assert "Email sent" in res


def test_I3_restricted_client_no_valid_lock_fails_closed():
    """Restricted client + privilege but NO valid locked recipient → REFUSE (no send, no fallback)."""
    import fastapi_server_complete as F
    for bad in (None, "", "not-an-email"):
        tm = _FakeToolManager()
        res = asyncio.run(F._send_email_locked(
            tm, {"to_email": "attacker@evil.com", "body": "x"},
            recipient_locked=True, locked_recipient=bad))
        assert tm.sent == [], f"I3 VIOLATED: sent despite invalid lock ({bad!r})"
        assert res.lstrip().startswith("❌"), f"I3 VIOLATED: did not refuse for {bad!r}: {res}"


def test_I3_auto_trusted_client_keeps_prompt_recipient():
    """Auto-trusted client (not locked) → recipient passes through unchanged."""
    import fastapi_server_complete as F
    tm = _FakeToolManager()
    asyncio.run(F._send_email_locked(
        tm, {"to_email": "a@b.com", "cc_emails": "c@d.com", "body": "x"},
        recipient_locked=False, locked_recipient=None))
    assert tm.sent[0][1]["to_email"] == "a@b.com"
    assert tm.sent[0][1]["cc_emails"] == "c@d.com"  # unchanged when not locked


def _regenerate():
    data = _compute_all()
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    print(f"✅ wrote golden → {GOLDEN_PATH}")
    print(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    if "--regenerate" in sys.argv:
        _regenerate()
    else:
        print("Run with --regenerate to (re)write the golden, or use pytest to verify.")
