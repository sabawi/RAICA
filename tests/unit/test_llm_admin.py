"""LLM admin API, read side (/admin/llm/config, /admin/llm/providers/{p}/models; utils/llm_admin.py, v1.0.0.340).

Failures it prevents (NewX docs/DESIGN_ai_service_admin.md §5–§6):
  * a hardcoded list of legs — a leg a future release adds would be missing from the NewX admin page (RAICA rule);
  * an API key leaving RAICA through the admin API (only set / not set and the last 4 characters may);
  * the admin API answering without its token, or answering when no token is configured;
  * a model list that hides the provider's error as "no models", or reaches the provider without its key.
A real HTTP server records what RAICA sends to the provider.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from utils import llm_admin as A

SEEN = []
REPLY = {'status': 200}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append((self.path, self.headers.get('Authorization')))
        if REPLY['status'] != 200:
            b = b'{"error":"bad key"}'
            self.send_response(REPLY['status'])
        else:
            body = {'models': [{'name': 'a:cloud'}, {'name': 'b:7b'}]} if self.path == '/api/tags' else \
                   {'data': [{'id': 'z-model'}, {'id': 'a-model'}]}
            b = json.dumps(body).encode()
            self.send_response(200)
        self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    SEEN.clear(); REPLY['status'] = 200
    s = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield 'http://127.0.0.1:%d' % s.server_port
    s.shutdown()


def _cfg(server='http://127.0.0.1:1'):
    return yaml.safe_load('''
config_version: 2
llm:
  primary: {type: ollama, config: {model: big:cloud}}
  tool_calling: {type: ollama, config: {model: big:cloud}}
  providers:
    ollama: {base_url: %s, api_key: "${TEST_OLLAMA_KEY}"}
    openai: {base_url: %s, api_key: "${TEST_OPENAI_KEY}"}
deep_research: {engine: {model: flash:cloud, enabled: true}}
document_interrogator: {embedding: {provider: openai, model_name: emb-small, dimension: 1024}}
code_generation: {model_presets: {gpt: {provider: openai, model: gpt-x}}}
admin_ui:
  leg_exclude: [code_generation, llm.providers]
  labels: {llm.primary.config: Answer (primary)}
offered_models: []
''' % (server, server))


def test_legs_are_discovered_from_the_config_not_listed_in_code():
    """Every node with a model/model_name is a leg — including one no code knows about — minus the config's own
    exclusions; providers come from the leg, its parent's type, or (flat legs) the primary's."""
    cfg = _cfg()
    cfg['brand_new_feature'] = {'judge': {'model': 'judge-1', 'provider': 'openai'}}
    got = {l['path']: (l['provider'], l['provider_from'], l['model']) for l in A.legs(cfg)}
    assert got == {
        'llm.primary.config': ('ollama', 'leg', 'big:cloud'),
        'llm.tool_calling.config': ('ollama', 'leg', 'big:cloud'),
        'deep_research.engine': ('ollama', 'primary', 'flash:cloud'),
        'document_interrogator.embedding': ('openai', 'leg', 'emb-small'),
        'brand_new_feature.judge': ('openai', 'leg', 'judge-1'),
    }, got
    labels = {l['path']: l['label'] for l in A.legs(cfg)}
    assert labels['llm.primary.config'] == 'Answer (primary)' and labels['deep_research.engine'] == 'deep_research.engine'


def test_exclusions_come_from_the_config():
    """Which nodes are catalogues (not legs) is the site's config, not code: drop the exclusion and they appear."""
    cfg = _cfg()
    cfg['admin_ui']['leg_exclude'] = ['llm.providers']
    assert 'code_generation.model_presets.gpt' in {l['path'] for l in A.legs(cfg)}


def test_a_secret_value_never_leaves_the_admin_api(monkeypatch):
    """Only set / not set and the last 4 characters; a short value shows no characters at all."""
    monkeypatch.setenv('TEST_OPENAI_KEY', 'sk-VERY-SECRET-VALUE-1234')
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'short')
    out = json.dumps(A.summary(_cfg()))
    assert 'VERY-SECRET' not in out and 'sk-' not in out and 'short' not in out, out
    emb = [l for l in A.legs(_cfg()) if l['path'] == 'document_interrogator.embedding'][0]
    assert {'name': 'TEST_OPENAI_KEY', 'set': True, 'last4': '1234'} in emb['secrets'], emb['secrets']
    prov = {p['name']: p for p in A.providers(_cfg())}
    assert prov['ollama']['secrets'] == [{'name': 'TEST_OLLAMA_KEY', 'set': True, 'last4': ''}]
    assert prov['ollama']['settings']['api_key'] == '${TEST_OLLAMA_KEY}'          # the reference, never the value


def test_the_token_is_required_and_no_token_means_off(monkeypatch):
    monkeypatch.delenv(A.TOKEN_ENV, raising=False)
    assert A.token_problem('anything')[0] == 403
    monkeypatch.setenv(A.TOKEN_ENV, 'too-short')
    assert A.token_problem('too-short')[0] == 403
    monkeypatch.setenv(A.TOKEN_ENV, 'x' * 32)
    assert A.token_problem(None)[0] == 401 and A.token_problem('y' * 32)[0] == 401
    assert A.token_problem('x' * 32) is None


def test_ollama_models_are_listed_with_the_key(server, monkeypatch):
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'ok-key-123')
    names = asyncio.run(A.list_models(_cfg(server), 'ollama'))
    assert names == ['a:cloud', 'b:7b'] and SEEN == [('/api/tags', 'Bearer ok-key-123')], (names, SEEN)


def test_openai_compatible_models_are_listed_with_the_key(server, monkeypatch):
    monkeypatch.setenv('TEST_OPENAI_KEY', 'sk-test-9876')
    names = asyncio.run(A.list_models(_cfg(server), 'openai'))
    assert names == ['a-model', 'z-model'] and SEEN == [('/models', 'Bearer sk-test-9876')], (names, SEEN)


def test_a_provider_error_is_raised_not_hidden_as_no_models(server, monkeypatch):
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'ok-key-123')
    REPLY['status'] = 401
    with pytest.raises(RuntimeError) as e:
        asyncio.run(A.list_models(_cfg(server), 'ollama'))
    assert '401' in str(e.value)
    with pytest.raises(LookupError):
        asyncio.run(A.list_models(_cfg(server), 'nope'))


def test_provider_config_is_the_same_merge_raica_applies_to_a_leg(monkeypatch):
    """provider block, overlaid with the leg's settings, then expanded — utils/config_loader.get_llm_config's rule."""
    monkeypatch.setenv('TEST_OPENAI_KEY', 'sk-merge-0001')
    got = A.provider_config(_cfg('http://p'), 'openai', {'model': 'm2', 'base_url': 'http://leg'})
    assert got == {'base_url': 'http://leg', 'api_key': 'sk-merge-0001', 'model': 'm2'}, got


def test_the_release_defaults_discover_exactly_the_designed_legs():
    """On the shipped defaults: the 10 legs of the design's table, and no catalogue entry."""
    cfg = A.raw_config(A.CONFIG_DIR / 'llm_config.defaults.yaml')
    paths = sorted(l['path'] for l in A.legs(cfg))
    assert paths == sorted([
        'llm.primary.config', 'llm.tool_calling.config', 'arbitrator.config', 'vision.config',
        'deep_research.engine', 'convergence.intent_classifier', 'convergence.shadow_classifier',
        'tool_calling.gather_gate', 'document_interrogator.embedding', 'embeddings_api.local']), paths


# ── step 2b: POST /admin/llm/test — ONE real call ─────────────────────────────────────────────────────────────────
POSTS = []
MODE = {'chat': 'ok', 'dims': 3}


class P(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        POSTS.append((self.path, body.get('model'), self.headers.get('Authorization')))
        if self.path == '/api/generate':
            if MODE['chat'] == 'error':
                b = b'{"error":"model \\"nope:cloud\\" not found"}'
                self.send_response(404); self.send_header('Content-Length', str(len(b))); self.end_headers()
                self.wfile.write(b); return
            lines = [{'response': 'OK', 'done': False}, {'response': '', 'done': True}]
            b = ''.join(json.dumps(x) + '\n' for x in lines).encode()
        else:                                            # OpenAI-compatible /embeddings
            b = json.dumps({'data': [{'index': 0, 'embedding': [0.1] * MODE['dims']}],
                            'usage': {'prompt_tokens': 2}}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


@pytest.fixture()
def llm():
    POSTS.clear(); MODE.update(chat='ok', dims=3)
    s = HTTPServer(('127.0.0.1', 0), P)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield 'http://127.0.0.1:%d' % s.server_port
    s.shutdown()


def _tcfg(url):
    c = _cfg(url)
    c['document_interrogator']['embedding'].update(dimension=3, timeout={'embedding_request': 5},
                                                   service={'base_url': url, 'api_key': '${TEST_OPENAI_KEY}'})
    c['admin_ui'].update(embedding_legs=['document_interrogator.embedding'], test_prompt='Reply OK.', test_max_tokens=8)
    return c


def test_a_chat_leg_is_tested_with_one_real_call(llm, monkeypatch):
    """The test reaches the provider ONCE, on the leg's model, and returns what the model said."""
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'ok-key-123')
    r = asyncio.run(A.test_leg(_tcfg(llm), 'llm.primary.config'))
    assert r['ok'] and r['kind'] == 'chat' and r['reply'] == 'OK' and r['model'] == 'big:cloud', r
    assert POSTS == [('/api/generate', 'big:cloud', 'Bearer ok-key-123')], POSTS


def test_a_proposed_model_is_what_gets_called(llm, monkeypatch):
    """'Test before saving': the PROPOSED model is called, not the current one."""
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'ok-key-123')
    r = asyncio.run(A.test_leg(_tcfg(llm), 'deep_research.engine', model='other:cloud'))
    assert r['ok'] and POSTS[-1][1] == 'other:cloud', (r, POSTS)


def test_a_failing_model_returns_the_providers_error_not_a_success(llm, monkeypatch):
    monkeypatch.setenv('TEST_OLLAMA_KEY', 'ok-key-123')
    MODE['chat'] = 'error'
    r = asyncio.run(A.test_leg(_tcfg(llm), 'llm.primary.config', model='nope:cloud'))
    assert r['ok'] is False and 'error' in r and 'reply' not in r, r


def test_an_embedding_leg_embeds_and_checks_the_dimension(llm, monkeypatch):
    """An embedding leg is tested by embedding one word with RAICA's own code — and a model whose vectors do not have
    the configured size FAILS (switching to it would break the document index)."""
    monkeypatch.setenv('TEST_OPENAI_KEY', 'sk-emb-4321')

    async def both():                     # one event loop, as in the server (RAICA's HTTP pool is per loop)
        a = await A.test_leg(_tcfg(llm), 'document_interrogator.embedding')
        MODE['dims'] = 5
        b = await A.test_leg(_tcfg(llm), 'document_interrogator.embedding', model='emb-big')
        return a, b
    r, r2 = asyncio.run(both())
    assert r['ok'] and r['kind'] == 'embedding' and r['dims'] == 3, r
    assert POSTS[0] == ('/embeddings', 'emb-small', 'Bearer sk-emb-4321'), POSTS
    assert r2['ok'] is False and POSTS[-1][1] == 'emb-big' and 'dimension' in r2['error'].lower(), (r2, POSTS)


def test_only_discovered_legs_and_configured_providers_can_be_tested(llm):
    with pytest.raises(LookupError):
        asyncio.run(A.test_leg(_tcfg(llm), 'llm.providers.openai'))          # a catalogue, not a leg
    with pytest.raises(LookupError):
        asyncio.run(A.test_leg(_tcfg(llm), 'llm.primary.config', provider='evil'))
    assert POSTS == []
