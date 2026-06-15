#!/usr/bin/env python3
"""
Phase 1 + 2 (delivery-tool exposure) tests — exercises the REAL production functions:
  • _restrict_sandboxed_executor_def — restricted clients see create_file ONLY (no shell)
  • safe_function_call scope backstop  — restricted clients are REFUSED any sandbox action but create_file
  • auto-bind                          — a file created during a delivery request is auto-attached to the
                                         (locked) email even if the LLM never threaded the path

Only the email transport is mocked; everything under test is the real code. No real email is sent.
Run: python tests/integration/test_delivery_tool_exposure.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import fastapi_server_complete as srv             # noqa: E402
import user_tools.secure_email_sender as ses_mod  # noqa: E402

_captured = {}


class _FakeEmailTool:
    async def execute(self, **kwargs):
        _captured.clear()
        _captured.update(kwargs)
        return {"success": True, "result": "✅ (mock) Email accepted"}


_failures = []


def check(name, cond, detail=""):
    print(("✓ " if cond else "✗ ") + name + (("  — " + detail) if (detail and not cond) else ""))
    if not cond:
        _failures.append(name)


async def main():
    ses_mod.SecureEmailSenderTool = _FakeEmailTool
    # These features are gated behind the LLM-driven-delivery master switch (default OFF in production
    # until the multi-round loop lands); enable it here to exercise the gated behavior under test.
    srv._LLM_DRIVEN_DELIVERY = True

    # ── 1) _restrict_sandboxed_executor_def: sandbox tool narrowed to create_file; others untouched ──
    sbx = {"type": "function", "function": {"name": "sandboxed_executor", "parameters": {"type": "object",
           "properties": {"action": {"type": "string",
                          "enum": ["execute", "create_file", "run_code", "delete_file"],
                          "description": "orig"}}}}}
    r = srv._restrict_sandboxed_executor_def(sbx)
    check("1) restricted sandboxed_executor exposes ONLY create_file",
          r["function"]["parameters"]["properties"]["action"]["enum"] == ["create_file"],
          str(r["function"]["parameters"]["properties"]["action"]["enum"]))
    check("1) original def not mutated (deepcopy)",
          sbx["function"]["parameters"]["properties"]["action"]["enum"] != ["create_file"])
    other = {"type": "function", "function": {"name": "search_web", "parameters": {"type": "object",
             "properties": {"query": {"type": "string"}}}}}
    check("1) non-sandbox tool passes through unchanged",
          srv._restrict_sandboxed_executor_def(other) == other)

    # ── 2) safe_function_call scope backstop (restricted client = lock present) ──
    # Register a fake sandboxed_executor (user tools load lazily and aren't registered at import) so the
    # call reaches the scope guard; the fake records whether it was actually DISPATCHED.
    _cf_called = {}

    async def _fake_sbx(args):
        _cf_called["args"] = args
        return "✅ (mock) sandbox ran"
    _orig_sbx = srv.tool_manager.available_functions.get("sandboxed_executor")
    srv.tool_manager.available_functions["sandboxed_executor"] = _fake_sbx
    try:
        # restricted client: shell 'execute' REFUSED before dispatch (fake must NOT be called)
        srv._delivery_lock_ctx.set((True, "owner@example.com"))
        _cf_called.clear()
        blocked = await srv.tool_manager.safe_function_call(
            "sandboxed_executor", json.dumps({"action": "execute", "command": "rm -rf ~"}))
        check("2) restricted client: shell action 'execute' is REFUSED", "blocked" in blocked.lower(), blocked)
        check("2) restricted client: refused shell action does NOT dispatch the tool", "args" not in _cf_called)

        # restricted client: create_file ALLOWED through the guard (fake IS called)
        _cf_called.clear()
        await srv.tool_manager.safe_function_call(
            "sandboxed_executor", json.dumps({"action": "create_file", "filename": "x.html", "content": "hi"}))
        check("2) restricted client: create_file is ALLOWED through the guard", "args" in _cf_called)

        # auto-trusted client (no lock): shell action NOT blocked by this guard (fake IS called)
        srv._delivery_lock_ctx.set((False, None))
        _cf_called.clear()
        await srv.tool_manager.safe_function_call(
            "sandboxed_executor", json.dumps({"action": "execute", "command": "echo hi"}))
        check("2) auto-trusted client: shell action not blocked by scope guard", "args" in _cf_called)
    finally:
        if _orig_sbx is not None:
            srv.tool_manager.available_functions["sandboxed_executor"] = _orig_sbx
        else:
            srv.tool_manager.available_functions.pop("sandboxed_executor", None)

    # ── 3) auto-bind: a file created during the request is attached even if LLM passed no attachments ──
    sbx_dir = os.path.join(os.path.expanduser("~"), "sandbox_workspace")
    os.makedirs(sbx_dir, exist_ok=True)
    baseline = srv._list_sandbox_files()                 # snapshot BEFORE creating the artifact
    test_name = "_phase2_autobind_probe.html"
    test_path = os.path.join(sbx_dir, test_name)
    with open(test_path, "w") as f:
        f.write("<h1>probe</h1>")
    try:
        srv._artifact_baseline_ctx.set(baseline)          # delivery request baseline (without the new file)
        srv._delivery_lock_ctx.set((False, None))         # unlocked → no recipient override interfering
        _captured.clear()
        await srv.tool_manager.secure_email_sender(json.dumps(
            {"to_email": "user@example.com", "subject": "t", "body": "b"}))  # NOTE: no attachments passed
        att = str(_captured.get("attachments") or "")
        check("3) auto-bind attaches the request-created artifact", test_name in att, att)
    finally:
        srv._artifact_baseline_ctx.set(None)
        try:
            os.remove(test_path)
        except OSError:
            pass

    # auto-bind inert when NOT a delivery request (baseline None)
    srv._artifact_baseline_ctx.set(None)
    _captured.clear()
    await srv.tool_manager.secure_email_sender(json.dumps(
        {"to_email": "user@example.com", "subject": "t", "body": "b"}))
    check("3) auto-bind inert when baseline is None (non-delivery)",
          not _captured.get("attachments"), str(_captured.get("attachments")))

    print()
    if _failures:
        print(f"❌ {len(_failures)} ASSERTION(S) FAILED: {_failures}")
        sys.exit(1)
    print("✅ ALL PHASE 1+2 EXPOSURE/SCOPE/AUTO-BIND ASSERTIONS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
