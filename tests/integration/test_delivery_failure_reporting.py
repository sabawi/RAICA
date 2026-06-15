"""
Regression test for the delivery FALSE-SUCCESS bug (fixed v1.0.0.120).

Bug: when an email send FAILED, _deliver_document reported email_outcome=("sent", …). Root cause: the
email tool's failure is stringified by the user-tool wrapper as "Tool '<name>' error: …" (no ❌ prefix),
and the outcome guard only recognised a ❌ prefix — so the failure fell through to the "sent" branch and
the user/log saw a false success.

Fix: the user-tool wrapper records the tool's ACTUAL {"success": bool} in a contextvar
(_last_user_tool_ok); _deliver_document reads that structured flag instead of sniffing the prose result.

This test drives the REAL code (_deliver_document + AsyncToolManager.safe_function_call +
_create_user_tool_wrapper); only the LEAF effects are faked — the sandbox file write and the SMTP send
RESULT. It asserts the reported outcome matches the tool's real success. It would FAIL on the pre-fix
code (a failed send was reported "sent").

Run: python -m pytest tests/integration/test_delivery_failure_reporting.py -q
 or: python tests/integration/test_delivery_failure_reporting.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import fastapi_server_complete as F


class _FakeSandboxed:
    """Stand-in for sandboxed_executor.create_file — reports success without writing real bytes."""
    name = "sandboxed_executor"

    async def execute(self, **kwargs):
        return {"success": True, "result": f"created {kwargs.get('filename')}"}


class _FakeEmailTool:
    """Mimics SecureEmailSenderTool.execute()'s return contract: {"success": bool, ...}."""
    name = "secure_email_sender"

    def __init__(self, succeed):
        self._succeed = succeed

    async def execute(self, **kwargs):
        if self._succeed:
            return {"success": True, "result": "✅ Email sent successfully via gmail to 1 recipient(s)"}
        # The exact failure shape that fooled the old guard (success=False → wrapper emits "Tool '…' error:")
        return {"success": False, "error": "Failed to send email via sendmail"}


def _make_tm(email_succeeds):
    """Real AsyncToolManager; only the two leaf tools are fakes. The email tool is registered through the
    REAL _create_user_tool_wrapper — the code under test for setting the structured success flag."""
    tm = F.AsyncToolManager()
    tm.available_functions["secure_email_sender"] = tm._create_user_tool_wrapper(_FakeEmailTool(email_succeeds))
    tm.user_tools = [_FakeSandboxed()]
    return tm


async def _deliver(email_succeeds, slug, subject):
    tm = _make_tm(email_succeeds)
    return await F._deliver_document(
        content="# Test Document\n\nBody paragraph.", title="Test Document", slug=slug,
        formats=["html"], tool_manager=tm, send_email=True, recipients=["user@example.com"],
        recipient_locked=False, locked_recipient=None, subject=subject,
        body="Please find attached the requested document(s).")


def test_failed_send_is_reported_failed():
    res = asyncio.run(_deliver(False, "fail_case_doc", "Delivery Fail Case"))
    assert res["created_files"], "file should still be created"
    assert res["email_outcome"] is not None, "email_outcome must be set when send_email=True"
    assert res["email_outcome"][0] == "failed", \
        f"a FAILED send must report 'failed', got {res['email_outcome']!r}"


def test_successful_send_is_reported_sent():
    res = asyncio.run(_deliver(True, "ok_case_doc", "Delivery OK Case"))
    assert res["created_files"]
    assert res["email_outcome"][0] == "sent", \
        f"a successful send must report 'sent', got {res['email_outcome']!r}"


if __name__ == "__main__":
    test_failed_send_is_reported_failed()
    print("PASS: failed send -> ('failed', …)")
    test_successful_send_is_reported_sent()
    print("PASS: successful send -> ('sent', …)")
    print("ALL TESTS PASSED")
