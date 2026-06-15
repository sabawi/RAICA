#!/usr/bin/env python3
"""
Unit tests for orchestration/intent.py — the LLM intent classifier (Phase 2 shadow / future
authoritative). See docs/RAICA_CONTEXT_SUBSTRATE_CONVERGENCE.md.

The LLM call is INJECTED (collect_fn), so these run with a fake collector — no model, no network.

RUN: venv/bin/python3 -m pytest tests/utilities/test_intent_classifier_llm.py -v
"""
import os
import sys
import asyncio

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from orchestration import intent  # noqa: E402

CATALOG = [
    {"name": "sandboxed_executor", "description": "Create/run files (PDF/HTML/etc.)"},
    {"name": "secure_email_sender", "description": "Send email with attachments"},
    {"name": "social_media_substack", "description": "Publish a post to Substack"},
]


def _fake_collect(return_text):
    async def _c(prompt, system_prompt, max_tokens):
        return return_text
    return _c


# ── classify_intent_actions: parsing ──────────────────────────────────────────────────────────────
def test_classify_extracts_actions_and_tools():
    raw = '{"actions":[{"type":"sandboxed_executor","args":{}},{"type":"secure_email_sender","args":{"to":["a@b.com"]}}],"needs_delivery":true}'
    res = asyncio.run(intent.classify_intent_actions(_fake_collect(raw), CATALOG, "make a pdf and email it"))
    assert res["ok"] is True
    assert res["tools"] == ["sandboxed_executor", "secure_email_sender"]
    assert res["needs_delivery"] is True


def test_classify_dedups_and_drops_unsupported():
    raw = '{"actions":[{"type":"secure_email_sender"},{"type":"secure_email_sender"},{"type":"unsupported","args":{"requested":"fax it"}}]}'
    res = asyncio.run(intent.classify_intent_actions(_fake_collect(raw), CATALOG, "email it twice and fax it"))
    assert res["tools"] == ["secure_email_sender"]  # dedup + 'unsupported' excluded
    assert res["needs_delivery"] is True            # has a real tool


def test_classify_empty_actions_means_no_delivery():
    res = asyncio.run(intent.classify_intent_actions(_fake_collect('{"actions":[],"needs_delivery":false}'),
                                                     CATALOG, "what is the capital of France?"))
    assert res["tools"] == [] and res["needs_delivery"] is False


def test_classify_tolerates_prose_wrapped_json():
    raw = 'Sure!\n{"actions":[{"type":"sandboxed_executor"}],"needs_delivery":true}\nHope that helps.'
    res = asyncio.run(intent.classify_intent_actions(_fake_collect(raw), CATALOG, "save a file"))
    assert res["tools"] == ["sandboxed_executor"]


def test_classify_error_path_is_safe():
    async def _boom(prompt, system_prompt, max_tokens):
        raise RuntimeError("model down")
    res = asyncio.run(intent.classify_intent_actions(_boom, CATALOG, "anything"))
    assert res["ok"] is False and res["tools"] == [] and res["needs_delivery"] is False


# ── to_verifier_shape ─────────────────────────────────────────────────────────────────────────────
def test_to_verifier_shape_missing_and_complete():
    ir = {"tools": ["sandboxed_executor", "secure_email_sender"]}
    assert intent.to_verifier_shape(ir, []) == {"complete": False, "missing_tools": ["sandboxed_executor", "secure_email_sender"]}


def test_to_verifier_shape_respects_tools_called():
    ir = {"tools": ["secure_email_sender"]}
    assert intent.to_verifier_shape(ir, ["secure_email_sender"]) == {"complete": True, "missing_tools": []}


def test_to_verifier_shape_no_tools_is_complete():
    assert intent.to_verifier_shape({"tools": []}, []) == {"complete": True, "missing_tools": []}


# ── compare (divergence reporting) ──────────────────────────────────────────────────────────────
def test_compare_full_agreement():
    legacy = {"complete": False, "missing_tools": ["secure_email_sender"]}
    shadow = {"complete": False, "missing_tools": ["secure_email_sender"]}
    c = intent.compare(legacy, shadow)
    assert c["agree_complete"] and c["agree_tools"] and c["only_legacy"] == [] and c["only_shadow"] == []


def test_compare_detects_divergence():
    # The real "write a poem" false-positive: legacy wants file+email, LLM wants nothing.
    legacy = {"complete": False, "missing_tools": ["sandboxed_executor", "secure_email_sender"]}
    shadow = {"complete": True, "missing_tools": []}
    c = intent.compare(legacy, shadow)
    assert c["agree_complete"] is False and c["agree_tools"] is False
    assert c["only_legacy"] == ["sandboxed_executor", "secure_email_sender"]
    assert c["only_shadow"] == []
