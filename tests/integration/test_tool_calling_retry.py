"""
Unit test for the tool-calling 5xx/timeout retry in llm_providers/openai.py generate_tools (task #21).

The cloud tool endpoint (e.g. glm-5.2:cloud via the Ollama OpenAI proxy) intermittently returns 5xx;
a single blip used to silently degrade to "no tool calls" → no evidence → discarded news posts. These
tests mock the HTTP layer to prove: (1) 5xx then 200 recovers, (2) persistent 5xx raises after N
attempts, (3) 4xx is NOT retried, (4) a clean 200 still works (no regression).

Run: python -m pytest tests/integration/test_tool_calling_retry.py -q
 or: python tests/integration/test_tool_calling_retry.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from llm_providers.openai import OpenAIProvider


class _FakeResp:
    def __init__(self, status, body="", js=None):
        self.status = status
        self._body = body
        self._js = js or {}

    async def text(self):
        return self._body

    async def json(self):
        return self._js


class _FakeCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    """Returns a queued response per .post() call; raises TimeoutError where queued."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, json=None):
        item = self._responses[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return _FakeCtx(item)


_OK_JS = {
    "choices": [{"message": {
        "tool_calls": [{"id": "1", "function": {"name": "search_web", "arguments": "{}"}}],
        "content": "",
    }}],
    "usage": {},
}


def _provider(responses, attempts=3):
    prov = OpenAIProvider({"api_key": "test-key", "base_url": "http://fake/v1",
                           "retry_attempts": attempts, "retry_delay": 0})
    session = _FakeSession(responses)

    async def _fake_get_session():
        return session

    prov._get_session = _fake_get_session
    prov._session = session
    return prov, session


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_recovers_on_500_then_200():
    prov, session = _provider([_FakeResp(500, "Internal Server Error"), _FakeResp(200, js=_OK_JS)])
    res = _run(prov.generate_tools("latest news", "glm-5.2:cloud", []))
    assert session.calls == 2, f"expected 2 attempts, got {session.calls}"
    assert res["tool_calls"][0]["function"]["name"] == "search_web"


def test_recovers_on_timeout_then_200():
    prov, session = _provider([asyncio.TimeoutError(), _FakeResp(200, js=_OK_JS)])
    res = _run(prov.generate_tools("latest news", "glm-5.2:cloud", []))
    assert session.calls == 2
    assert res["tool_calls"][0]["function"]["name"] == "search_web"


def test_persistent_500_raises_after_attempts():
    prov, session = _provider([_FakeResp(500, "boom")] * 3, attempts=3)
    raised = False
    try:
        _run(prov.generate_tools("q", "m", []))
    except Exception as e:
        raised = True
        assert "500" in str(e)
    assert raised, "should raise after exhausting retries"
    assert session.calls == 3, f"expected exactly 3 attempts, got {session.calls}"


def test_4xx_is_not_retried():
    prov, session = _provider([_FakeResp(400, "bad request"), _FakeResp(200, js=_OK_JS)])
    raised = False
    try:
        _run(prov.generate_tools("q", "m", []))
    except Exception:
        raised = True
    assert raised, "4xx should raise"
    assert session.calls == 1, f"4xx must NOT retry; got {session.calls} attempts"


def test_clean_200_no_regression():
    prov, session = _provider([_FakeResp(200, js=_OK_JS)])
    res = _run(prov.generate_tools("q", "m", []))
    assert session.calls == 1
    assert res["tool_calls"][0]["function"]["name"] == "search_web"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print("ALL TESTS PASSED")
