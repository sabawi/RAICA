#!/usr/bin/env python3
"""
Unit tests for orchestration/policy.py — the shared delivery policy extracted in Phase 1 of the
Context-and-Action Substrate Convergence (docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md).

These assert that the extracted functions reproduce the EXACT behavior of the call sites they replace
(behavior-preserving refactor), and they activate invariant I3 (recipient lock / fail-closed), which
was a Phase-0 placeholder.

RUN: venv/bin/python3 -m pytest tests/utilities/test_orchestration_policy.py -v
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from orchestration import policy  # noqa: E402  (pure module, no server import)


# ── valid_email ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("email,expected", [
    ("a@b.com", True), ("  user@own.com  ", True), ("first.last+tag@sub.domain.io", True),
    ("", False), (None, False), ("not-an-email", False), ("a@b", False),
    ("two@x.com three@y.com", False),  # must be a SINGLE full-match address
])
def test_valid_email(email, expected):
    assert policy.valid_email(email) is expected


# ── authorize_delivery: reproduces _dr_delivery_permitted + POST-LLM privilege computation ───────
@pytest.mark.parametrize("data,permitted,locked,locked_recip", [
    # explicit True, restricted client (NewX) → permitted, locked to delivery_recipient
    ({"allow_delivery": True, "allowed_tools": ["search_web"], "delivery_recipient": "u@own.com"},
     True, True, "u@own.com"),
    # explicit False, restricted client → denied (and no locked recipient exposed)
    ({"allow_delivery": False, "allowed_tools": ["search_web"], "delivery_recipient": "u@own.com"},
     False, True, None),
    # no explicit flag, NO allowed_tools (OpenWebUI) → auto-trust permit, not locked
    ({"delivery_recipient": "u@own.com"}, True, False, None),
    # no explicit flag, restricted client (allowed_tools present) → denied, locked, no recipient
    ({"allowed_tools": [], "delivery_recipient": "u@own.com"}, False, True, None),
    # explicit True, auto-trust client (no allowed_tools) → permitted, not locked
    ({"allow_delivery": True}, True, False, None),
])
def test_authorize_delivery(data, permitted, locked, locked_recip):
    auth = policy.authorize_delivery(data)
    assert auth.permitted is permitted
    assert auth.recipient_locked is locked
    assert auth.locked_recipient == locked_recip


def test_authorize_delivery_matches_legacy_permitted_truth_table():
    """`permitted` must equal the legacy `_dr_delivery_permitted` for all flag combinations."""
    def legacy_permitted(data):
        explicit = data.get("allow_delivery", None)
        if explicit is not None:
            return bool(explicit)
        return data.get("allowed_tools", None) is None
    for allow in (None, True, False):
        for allowed_tools in (None, [], ["x"]):
            data = {}
            if allow is not None:
                data["allow_delivery"] = allow
            if allowed_tools is not None:
                data["allowed_tools"] = allowed_tools
            assert policy.authorize_delivery(data).permitted == legacy_permitted(data), data


# ── resolve_locked_recipient: INVARIANT I3 (now live) ────────────────────────────────────────────
def test_I3_restricted_client_forces_locked_recipient():
    rec, refused = policy.resolve_locked_recipient(True, "user@own.com")
    assert rec == "user@own.com" and refused is False


def test_I3_restricted_client_strips_whitespace():
    rec, refused = policy.resolve_locked_recipient(True, "  user@own.com  ")
    assert rec == "user@own.com" and refused is False


def test_I3_restricted_client_no_valid_lock_fails_closed():
    for bad in (None, "", "not-an-email"):
        rec, refused = policy.resolve_locked_recipient(True, bad)
        assert rec is None and refused is True, bad


def test_I3_auto_trusted_client_defers_to_caller():
    rec, refused = policy.resolve_locked_recipient(False, "anything@x.com")
    assert rec is None and refused is False  # not locked → caller resolves normally


# ── resolve_delivery_format: reproduces both legacy inline sites exactly ──────────────────────────
def _legacy_dr_ext(fmt, prompt):
    fmt = (fmt or "").lower(); up = (prompt or "").lower()
    return "pdf" if ("pdf" in fmt or "pdf" in up) else ("html" if ("html" in fmt or "html" in up) else "pdf")


def _legacy_post_llm_ext(prompt):
    p = (prompt or "").lower()
    if "pdf" in p:
        return "pdf"
    elif "html" in p:
        return "html"
    elif "markdown" in p or "md" in p:
        return "md"
    elif "text" in p or "txt" in p:
        return "txt"
    return "html"


@pytest.mark.parametrize("fmt,prompt", [
    ("academic_paper", "email it to me as a PDF"),
    ("html_report", "send html please"),
    ("", "just email the thing"),
    ("pdf", ""), ("", "html"), ("", "a markdown file"), ("", "plain text please"),
])
def test_resolve_format_dr_matches_legacy(fmt, prompt):
    got = policy.resolve_delivery_format(prompt, deliverable_format=fmt,
                                         candidates=policy.DR_FORMAT_CANDIDATES, default=policy.DR_FORMAT_DEFAULT)
    assert got == _legacy_dr_ext(fmt, prompt), (fmt, prompt)


@pytest.mark.parametrize("prompt", [
    "email the above response as a HTML document", "save it to a pdf", "give me a markdown file",
    "plain text please", "just send it", "make an md export", "no format mentioned at all",
])
def test_resolve_format_post_llm_matches_legacy(prompt):
    got = policy.resolve_delivery_format(prompt, deliverable_format="",
                                         candidates=policy.POST_LLM_FORMAT_CANDIDATES,
                                         default=policy.POST_LLM_FORMAT_DEFAULT)
    assert got == _legacy_post_llm_ext(prompt), prompt
