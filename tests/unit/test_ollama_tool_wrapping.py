"""Guards the tool payload the Ollama provider sends (llm_providers/ollama.py generate_tools).

Since the initial commit the provider wrapped every tool as {"type": "function", "function": tool}
— but its callers already send that shape, so each definition went out DOUBLE-wrapped. Ollama
cannot read a name one level too deep: the tool model saw no schema at all and could call only
tools the system prompt named in prose. Found 2026-09-25 when the model, asked for the weather,
invented `get_weather` / `get_current_weather` instead of calling `weather_info`. Measured on the
live endpoint: single-wrapped -> `weather_info` called; double-wrapped -> "I don't have access to
a real-time weather tool".
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_providers.ollama import OllamaProvider  # noqa: E402

FN = {"name": "weather_info", "description": "current weather for a city",
      "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


class _Resp:
    status = 200

    async def json(self):
        return {"message": {"role": "assistant", "content": "", "tool_calls": []}, "done_reason": "stop"}

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self):
        self.payload = None

    def post(self, url, json=None, headers=None):
        self.payload = json
        return _Resp()


def _sent_tools(tools):
    prov = OllamaProvider({"base_url": "http://127.0.0.1:11434", "model": "m"})
    sess = _Session()

    async def _get_session():
        return sess
    prov._get_session = _get_session
    asyncio.run(prov.generate_tools("what is the weather in Paris?", "m", tools))
    return sess.payload["tools"]


def test_pre_wrapped_tools_are_sent_single_wrapped():
    """FAILS PRE-FIX: the already-wrapped definition was wrapped again, burying the name."""
    sent = _sent_tools([{"type": "function", "function": FN}])
    assert sent == [{"type": "function", "function": FN}], sent
    assert sent[0]["function"]["name"] == "weather_info"


def test_bare_function_definitions_are_still_wrapped_once():
    """CONTROL (passes before and after): a bare definition gets exactly one wrapper."""
    sent = _sent_tools([FN])
    assert sent == [{"type": "function", "function": FN}], sent


def test_every_tool_in_a_mixed_list_ends_up_named_at_the_readable_level():
    """Whatever mix arrives, each sent tool must expose its name at function.name."""
    sent = _sent_tools([FN, {"type": "function", "function": dict(FN, name="search_web")}])
    assert [t["function"].get("name") for t in sent] == ["weather_info", "search_web"], sent
