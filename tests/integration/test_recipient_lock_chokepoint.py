#!/usr/bin/env python3
"""
Phase 0 (context/action substrate convergence) — UNIVERSAL RECIPIENT-LOCK CHOKEPOINT test.

Proves that AsyncToolManager.secure_email_sender enforces the server-authoritative recipient lock for
EVERY send — a direct tool call (what the LLM will do once the tool is exposed in Phase 1) AND the
_send_email_locked wrapper (POST-LLM / interceptor / DR paths) — driven by the per-request
_delivery_lock_ctx ContextVar. This is the safety precondition that lets us expose the email tool to
the LLM without the bot being abusable to email arbitrary recipients.

Only the underlying email transport (SecureEmailSenderTool.execute) is mocked, so NO real email is
sent; the chokepoint logic under test is the real production code.

Run: python tests/integration/test_recipient_lock_chokepoint.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import fastapi_server_complete as srv          # noqa: E402
import user_tools.secure_email_sender as ses_mod  # noqa: E402

_captured = {}


class _FakeEmailTool:
    """Stand-in for SecureEmailSenderTool — records the kwargs the chokepoint actually passes."""
    async def execute(self, **kwargs):
        _captured.clear()
        _captured.update(kwargs)
        return {"success": True, "result": "✅ (mock) Email accepted"}


def _patch_transport():
    # The chokepoint does `from user_tools.secure_email_sender import SecureEmailSenderTool` at call
    # time, so patching the attribute on the module makes it pick up the fake.
    ses_mod.SecureEmailSenderTool = _FakeEmailTool


async def _send(to_email, cc=None):
    args = {"to_email": to_email, "subject": "t", "body": "b"}
    if cc is not None:
        args["cc_emails"] = cc
    return await srv.tool_manager.secure_email_sender(json.dumps(args))


async def main():
    _patch_transport()
    failures = []

    def check(name, cond, detail=""):
        print(("✓ " if cond else "✗ ") + name + (("  — " + detail) if (detail and not cond) else ""))
        if not cond:
            failures.append(name)

    # a) RESTRICTED client + valid lock → recipient forced to lock, CC dropped, prompt address ignored
    srv._delivery_lock_ctx.set((True, "owner@example.com"))
    await _send("attacker@evil.com", cc="snoop@evil.com")
    check("a) restricted+valid lock overrides recipient to owner@example.com",
          _captured.get("to_email") == "owner@example.com", str(_captured))
    check("a) restricted+valid lock drops CC", _captured.get("cc_emails") in (None,), str(_captured))

    # b) RESTRICTED client + NO valid lock → REFUSE (fail-closed); transport NEVER invoked
    _captured.clear()
    srv._delivery_lock_ctx.set((True, None))
    r = await _send("attacker@evil.com")
    check("b) restricted+absent lock REFUSES the send", "refused" in r.lower(), r)
    check("b) restricted+absent lock does NOT invoke transport", _captured == {}, str(_captured))

    # c) AUTO-TRUSTED client (no lock) → pass through unchanged (OpenWebUI behavior preserved)
    _captured.clear()
    srv._delivery_lock_ctx.set((False, None))
    await _send("user@example.com")
    check("c) auto-trusted (no lock) leaves recipient unchanged",
          _captured.get("to_email") == "user@example.com", str(_captured))

    # d) _send_email_locked wrapper publishes its own context + delegates to the SAME chokepoint,
    #    then restores the prior ambient context.
    _captured.clear()
    srv._delivery_lock_ctx.set((False, None))  # ambient = unlocked, to prove the wrapper supplies the lock
    await srv._send_email_locked(
        srv.tool_manager,
        {"to_email": "attacker@evil.com", "subject": "t", "body": "b", "cc_emails": "x@evil.com"},
        True, "owner@example.com")
    check("d) _send_email_locked locks recipient via chokepoint",
          _captured.get("to_email") == "owner@example.com", str(_captured))
    check("d) _send_email_locked drops CC", _captured.get("cc_emails") in (None,), str(_captured))
    check("d) _send_email_locked restores ambient context after send",
          srv._delivery_lock_ctx.get() == (False, None), str(srv._delivery_lock_ctx.get()))

    print()
    if failures:
        print(f"❌ {len(failures)} ASSERTION(S) FAILED: {failures}")
        sys.exit(1)
    print("✅ ALL PHASE-0 CHOKEPOINT ASSERTIONS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
