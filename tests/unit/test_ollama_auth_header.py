"""A configured api_key reaches Ollama as a bearer token, on every Ollama-native route (v1.0.0.338).

Failure it prevents: Ollama cloud (https://ollama.com) refuses calls without `Authorization: Bearer <key>`, and the
local daemon cannot use a key for cloud models (NewX docs/DESIGN_ai_service_admin.md §3, measured 2026-10-19). The
provider, the vision tool and the chart tool sent NO header, and vision ignored its configured base_url. A cloud leg
would get 401 — or stay local without anyone noticing. A real HTTP server records what RAICA actually sends.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

SEEN = []


class H(BaseHTTPRequestHandler):
    def _reply(self, body):
        b = json.dumps(body).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        SEEN.append((self.path, self.headers.get('Authorization')))
        self._reply({'models': []})

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
        SEEN.append((self.path, self.headers.get('Authorization')))
        self._reply({'message': {'role': 'assistant', 'content': '{"description": "ok"}', 'tool_calls': []}, 'done': True})

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    SEEN.clear()
    s = HTTPServer(('127.0.0.1', 0), H)
    t = threading.Thread(target=s.serve_forever, daemon=True); t.start()
    yield 'http://127.0.0.1:%d' % s.server_port
    s.shutdown()


def test_provider_sends_the_key_on_chat_and_health(server):
    from llm_providers.ollama import OllamaProvider
    p = OllamaProvider({'base_url': server, 'model': 'm', 'api_key': 'k-123', 'timeout': 10})

    async def go():
        await p.health_check()
        await p.generate_tools('hi', 'm', [])
        if p.session:
            await p.session.close()
    asyncio.run(go())
    assert ('/api/tags', 'Bearer k-123') in SEEN and ('/api/chat', 'Bearer k-123') in SEEN, SEEN


def test_provider_without_a_key_sends_no_header(server):
    from llm_providers.ollama import OllamaProvider
    p = OllamaProvider({'base_url': server, 'model': 'm', 'timeout': 10})

    async def go():
        await p.health_check()
        if p.session:
            await p.session.close()
    asyncio.run(go())
    assert SEEN and all(auth is None for _, auth in SEEN), SEEN


def test_vision_uses_the_configured_host_and_key(server):
    """It called the module-level ollama.chat(): the library's default host and no key."""
    from user_tools.image_to_text import ImageToTextTool
    tool = ImageToTextTool.__new__(ImageToTextTool)
    tool.vision_config = {'base_url': server, 'api_key': 'v-456', 'timeout': 30}
    try:
        tool._process_with_ollama('m', 'describe', 'aGVsbG8=', 'now')
    except Exception:                                  # the reply parser may object to the stub's content
        pass
    assert ('/api/chat', 'Bearer v-456') in SEEN, SEEN
