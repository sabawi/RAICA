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
    import http_helpers
    from http_pool_manager import HTTPPoolManager
    pool = HTTPPoolManager()                  # RAICA's pool keeps ONE session, bound to the event loop that made it: an
    monkeypatch.setattr(http_helpers, 'http_pool', pool)   # earlier test's loop must not leak in (the server has one)

    async def both():                     # one event loop, as in the server
        try:
            a = await A.test_leg(_tcfg(llm), 'document_interrogator.embedding')
            MODE['dims'] = 5
            b = await A.test_leg(_tcfg(llm), 'document_interrogator.embedding', model='emb-big')
            return a, b
        finally:
            await pool.cleanup()
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


# ── step 2c: change a leg / a key -> restart -> self-test -> keep or restore ──────────────────────────────────────
import os
import stat
from pathlib import Path


def _start():
    """A NEW process start (the once-per-process marker belongs to the previous one)."""
    os.environ.pop('_RAICA_LLM_ADMIN_START', None)
    return A.pending_on_start()


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """A temporary site: config dir with a live file, an .env, and the module pointed at them."""
    from utils.config_migrate import _dump, atomic_write
    cfgdir = tmp_path / 'config'; cfgdir.mkdir()
    live = cfgdir / 'llm_config.yaml'
    c = _cfg('http://127.0.0.1:1')
    c['llm']['primary']['config'].update(temperature=0.7, base_url='http://127.0.0.1:1')
    c['admin_ui'].update(test_prompt='Reply OK.', test_max_tokens=8)
    atomic_write(live, _dump(c))
    env = tmp_path / '.env'
    env.write_text('# keys\nTEST_OPENAI_KEY=sk-old-0000\nOTHER=keep-me\n'); env.chmod(0o600)
    for name, val in (('CONFIG_DIR', cfgdir), ('LIVE', live), ('PENDING', cfgdir / '.llm_admin_pending.json'),
                      ('LAST', cfgdir / '.llm_admin_last.json'), ('ENV_FILE', env)):
        monkeypatch.setattr(A, name, val)
    monkeypatch.setattr(A, 'supervised', lambda: False)
    monkeypatch.delenv('_RAICA_LLM_ADMIN_START', raising=False)
    return {'dir': cfgdir, 'live': live, 'env': env}


def test_a_leg_change_keeps_the_rules():
    """Only discovered legs; only EXISTING settings, same type; never a ${SECRET} reference; the provider only where
    the leg names its own, and only one under llm.providers."""
    c = _cfg(); c['llm']['primary']['config']['temperature'] = 0.7
    new = A.apply_leg_change(c, 'llm.primary.config', model='other:cloud', settings={'temperature': 0.2})
    assert new['llm']['primary']['config'] == {'model': 'other:cloud', 'temperature': 0.2}
    assert c['llm']['primary']['config']['model'] == 'big:cloud'                       # the input is not modified
    for bad in [dict(path='llm.providers.openai', model='x'),                          # a catalogue, not a leg
                dict(path='llm.primary.config', settings={'brand_new': 1}),            # not an existing setting
                dict(path='llm.primary.config', settings={'temperature': 'hot'}),      # type change
                dict(path='llm.primary.config', model='${EVIL}'),
                dict(path='deep_research.engine', provider='openai'),                  # uses the primary's provider
                dict(path='llm.primary.config', provider='nope')]:
        with pytest.raises(A.ChangeError):
            A.apply_leg_change(c, **bad)
    c['llm']['primary']['config']['api_key'] = '${TEST_OLLAMA_KEY}'
    with pytest.raises(A.ChangeError):
        A.apply_leg_change(c, 'llm.primary.config', settings={'api_key': 'plaintext-key'})
    moved = A.apply_leg_change(c, 'llm.primary.config', provider='openai')
    assert moved['llm']['primary']['type'] == 'openai'


def test_a_change_is_backed_up_written_read_only_and_pending(site):
    A.change_leg('llm.primary.config', model='other:cloud')
    assert 'other:cloud' in site['live'].read_text()
    assert stat.S_IMODE(site['live'].stat().st_mode) == 0o444
    p = A.change_status()['pending']
    assert p and p['attempts'] == 0 and p['test_paths'] == ['llm.primary.config']
    bak = Path(p['backups'][str(site['live'])])
    assert 'big:cloud' in bak.read_text() and 'other:cloud' not in bak.read_text()
    with pytest.raises(A.ChangeBusy):                                                   # one change at a time
        A.change_leg('llm.primary.config', model='third:cloud')


def test_a_change_that_crashes_the_first_start_is_restored_at_the_next(site):
    """The case nothing outside RAICA could fix: the new file stops RAICA from starting. Start #1 records its attempt;
    start #2 finds it unconfirmed and restores the previous file BEFORE the config is read."""
    A.change_leg('llm.primary.config', model='broken:cloud')
    assert _start() == 'trying'
    assert _start() == 'restored'                                                        # start #1 died
    assert 'big:cloud' in site['live'].read_text() and 'broken:cloud' not in site['live'].read_text()
    st = A.change_status()
    assert st['pending'] is None and st['last']['result'] == 'restored', st


def test_a_change_that_fails_its_self_test_is_restored_and_restarted(site, monkeypatch):
    restarts = []
    monkeypatch.setattr(A, 'restart', lambda: restarts.append(1) or {})

    async def failing(cfg, path, model=None, provider=None):
        return {'ok': False, 'error': 'model not found'}
    monkeypatch.setattr(A, 'test_leg', failing)
    A.change_leg('llm.primary.config', model='nope:cloud')
    _start()
    assert asyncio.run(A.verify_after_start()) == 'restored'
    assert 'big:cloud' in site['live'].read_text() and restarts == [1]
    assert A.change_status()['last']['result'] == 'restored'


def test_a_change_that_passes_its_self_test_is_kept(site, monkeypatch):
    async def passing(cfg, path, model=None, provider=None):
        return {'ok': True, 'reply': 'OK'}
    monkeypatch.setattr(A, 'test_leg', passing)
    A.change_leg('llm.primary.config', model='good:cloud')
    _start()
    assert asyncio.run(A.verify_after_start()) == 'confirmed'
    assert 'good:cloud' in site['live'].read_text()
    st = A.change_status()
    assert st['pending'] is None and st['last']['result'] == 'confirmed'
    assert _start() is None                                                              # a later start: nothing to do


def test_a_key_is_written_safely_and_only_for_a_referenced_name(site):
    """Only names the config uses; only characters python-dotenv and systemd read the same; the line is replaced,
    other lines kept, mode 600; the old .env is backed up so a failed self-test restores it."""
    for name, val in (('NOT_USED_ANYWHERE', 'abcdefgh1234'), ('TEST_OPENAI_KEY', 'has space 123'),
                      ('TEST_OPENAI_KEY', 'quote"d-123456'), ('TEST_OPENAI_KEY', 'dollar$x-123456'), ('lower', 'x' * 10)):
        with pytest.raises(A.ChangeError):
            A.set_secret(name, val)
    out = A.set_secret('TEST_OPENAI_KEY', 'sk-new-9999')
    assert out['last4'] == '9999' and 'sk-new' not in json.dumps(out)
    assert site['env'].read_text() == '# keys\nTEST_OPENAI_KEY=sk-new-9999\nOTHER=keep-me\n'
    assert stat.S_IMODE(site['env'].stat().st_mode) == 0o600
    p = A.change_status()['pending']
    _start(); _start()                                                                   # crash -> restore
    assert 'TEST_OPENAI_KEY=sk-old-0000' in site['env'].read_text()


def test_the_start_check_counts_once_per_process(site):
    """uvicorn.run("fastapi_server_complete:app") imports the server module twice in one start: the check must count
    ONE attempt per process, or a change that never failed is restored (found through the real server, 2026-10-23)."""
    A.change_leg('llm.primary.config', model='good:cloud')
    assert _start() == 'trying'
    assert A.pending_on_start() == 'already checked'                                     # same process, 2nd import
    assert A.change_status()['pending']['attempts'] == 1 and 'good:cloud' in site['live'].read_text()


def test_supervised_means_systemd_will_start_raica_again(monkeypatch):
    """Only the MainPID of the .service unit RAICA runs in, with Restart=always. An inherited INVOCATION_ID (any shell
    started by systemd passes it on) is not evidence: a hand-started RAICA once stopped itself and stayed down."""
    me = str(os.getpid())
    monkeypatch.setenv('INVOCATION_ID', 'inherited-from-the-terminal')
    monkeypatch.setattr(A, '_own_cgroup', lambda: '/user.slice/user-1000.slice/user@1000.service/app.slice/vte.scope')
    monkeypatch.setattr(A, '_systemctl_show', lambda unit, user: {'MainPID': me, 'Restart': 'always'})
    assert A.supervised() is False                                                       # a terminal scope
    monkeypatch.setattr(A, '_own_cgroup', lambda: '/system.slice/raica.service')
    assert A.supervised() is True
    monkeypatch.setattr(A, '_systemctl_show', lambda unit, user: {'MainPID': '1', 'Restart': 'always'})
    assert A.supervised() is False                                                       # not its main process
    monkeypatch.setattr(A, '_systemctl_show', lambda unit, user: {'MainPID': me, 'Restart': 'on-failure'})
    assert A.supervised() is False                                                       # a clean exit is not restarted


def test_restart_only_through_a_supervisor(monkeypatch):
    """Under systemd, SIGTERM to itself (Restart=always starts it again). Without one, NEVER stop: say so."""
    calls = []

    class Loop:
        def call_later(self, delay, fn, *args):
            calls.append((delay, fn, args))
    monkeypatch.setattr(asyncio, 'get_event_loop', lambda: Loop())
    monkeypatch.setattr(A, 'supervised', lambda: False)
    assert A.restart()['restarting'] is False and calls == []
    monkeypatch.setattr(A, 'supervised', lambda: True)
    assert A.restart()['restarting'] is True
    import signal
    assert calls and calls[0][1] is os.kill and calls[0][2] == (os.getpid(), signal.SIGTERM)
