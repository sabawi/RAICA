"""
LLM admin API logic — `/admin/llm/*` (NewX docs/DESIGN_ai_service_admin.md §5–§6; owner decisions 2026-10-18/19/23).

Read side (this module, step 2a):
  * token_ok()        every call needs header X-RAICA-Admin-Token == RAICA_ADMIN_TOKEN from RAICA's .env. No token
                      configured -> the admin API is OFF (fail closed), even though RAICA listens on 127.0.0.1 only.
  * legs()            the legs are DISCOVERED from the site's config, never listed in code (RAICA rule): every node
                      with a `model` or `model_name`, except the paths under `admin_ui.leg_exclude` (config). Labels
                      come from `admin_ui.labels` (config). A leg added by a future release appears with no code change.
  * providers()       the provider blocks under `llm.providers`.
  * Secrets are reported ONLY as {name, set, last4}: a value never leaves this module.

The config is read RAW (no ${VAR} expansion) so that which secret a value refers to stays visible; the provider used for
a model list or a test is built exactly as RAICA builds a leg: the named provider block overlaid with the leg's own
settings (utils/config_loader.get_llm_config), then expanded.
"""
import hmac
import os
import re
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / 'config'
LIVE = CONFIG_DIR / 'llm_config.yaml'
TOKEN_ENV = 'RAICA_ADMIN_TOKEN'
TOKEN_HEADER = 'X-RAICA-Admin-Token'
MIN_TOKEN_LEN = 24
_REF = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


# ── access ───────────────────────────────────────────────────────────────────────────────────────────────────────
def token_problem(presented):
    """None when the presented token is the configured one, else (HTTP status, why not): 403 when the API is off
    (no usable token configured), 401 when the token is missing or wrong."""
    want = os.environ.get(TOKEN_ENV, '')
    if len(want) < MIN_TOKEN_LEN:
        return 403, 'the LLM admin API is off: %s is not set (or shorter than %d characters) in RAICA .env' % (
            TOKEN_ENV, MIN_TOKEN_LEN)
    if not presented or not hmac.compare_digest(str(presented).encode(), want.encode()):
        return 401, 'missing or wrong %s' % TOKEN_HEADER
    return None


# ── reading the site's file ──────────────────────────────────────────────────────────────────────────────────────
def raw_config(path=None):
    """The site's llm_config.yaml as written (no ${VAR} expansion)."""
    return yaml.safe_load(Path(path or LIVE).read_text()) or {}


def _get(d, path):
    for part in path.split('.'):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def secret(name):
    """{name, set, last4} — never the value."""
    v = os.environ.get(name, '')
    return {'name': name, 'set': bool(v), 'last4': v[-4:] if len(v) >= 8 else ''}


def refs(node):
    """Every ${NAME} referenced by the scalar values of a node (not its children's children)."""
    out = []
    if isinstance(node, dict):
        for v in node.values():
            if isinstance(v, str):
                out += [n for n in _REF.findall(v) if n not in out]
    return out


def _scalars(node):
    """A node's own scalar settings, with any ${NAME} shown as the reference, never expanded."""
    return {k: v for k, v in node.items() if not isinstance(v, (dict, list))} if isinstance(node, dict) else {}


# ── legs (discovered) ────────────────────────────────────────────────────────────────────────────────────────────
def _excluded(path, excludes):
    return any(path == e or path.startswith(e + '.') for e in excludes)


def legs(cfg):
    """Every leg the site's config has: [{path, label, provider, provider_from, model, model_key, settings, secrets}]."""
    ui = cfg.get('admin_ui') or {}
    excludes = [str(x) for x in (ui.get('leg_exclude') or [])]
    labels = ui.get('labels') or {}
    primary_type = _get(cfg, 'llm.primary.type')
    out = []

    def walk(node, path, parent):
        if not isinstance(node, dict) or _excluded(path, excludes):
            return
        key = 'model' if 'model' in node else ('model_name' if 'model_name' in node else None)
        if key and not isinstance(node[key], (dict, list)):
            if node.get('provider') or node.get('type'):
                prov, src = node.get('provider') or node.get('type'), 'leg'
            elif isinstance(parent, dict) and parent.get('type'):
                prov, src = parent.get('type'), 'leg'
            else:
                prov, src = primary_type, 'primary'          # flat legs call through the primary's provider
            names = refs(node) + [n for n in refs(_get(cfg, 'llm.providers.%s' % prov) or {}) if n not in refs(node)]
            out.append({'path': path, 'label': labels.get(path) or path, 'provider': prov, 'provider_from': src,
                        'model': node[key], 'model_key': key, 'settings': _scalars(node),
                        'secrets': [secret(n) for n in names]})
        for k, v in node.items():
            walk(v, '%s.%s' % (path, k) if path else str(k), node)

    walk(cfg, '', None)
    return out


def providers(cfg):
    """[{name, settings, secrets}] for every block under llm.providers."""
    out = []
    for name, block in (_get(cfg, 'llm.providers') or {}).items():
        out.append({'name': name, 'settings': _scalars(block), 'secrets': [secret(n) for n in refs(block)]})
    return out


def summary(cfg=None):
    cfg = cfg if cfg is not None else raw_config()
    return {'config_version': cfg.get('config_version'), 'legs': legs(cfg), 'providers': providers(cfg),
            'offered_models': cfg.get('offered_models') or []}


# ── building a provider exactly as RAICA does ────────────────────────────────────────────────────────────────────
def provider_config(cfg, provider, overrides=None):
    """The named provider block overlaid with `overrides` (a leg's own settings), then ${VAR}-expanded — the same merge
    utils/config_loader.get_llm_config applies to a leg."""
    block = dict(_get(cfg, 'llm.providers.%s' % provider) or {})
    block.update(_scalars(overrides or {}))
    return {k: (os.path.expandvars(v) if isinstance(v, str) else v) for k, v in block.items()}


async def list_models(cfg, provider):
    """The provider's OWN model list (labelled 'listed' by the caller: listed is not proof a model works)."""
    from llm_providers.factory import LLMProviderFactory
    if provider not in (_get(cfg, 'llm.providers') or {}):
        raise LookupError('no provider %r under llm.providers' % provider)
    p = LLMProviderFactory.create_provider(provider, provider_config(cfg, provider))
    try:
        return await p.list_models()
    finally:
        s = getattr(p, 'session', None)
        if s is not None and not s.closed:
            await s.close()


# ── testing a leg: ONE real call (step 2b) ───────────────────────────────────────────────────────────────────────
def find_leg(cfg, path):
    for l in legs(cfg):
        if l['path'] == path:
            return l
    return None


async def _close(p):
    s = getattr(p, 'session', None)
    if s is not None and not getattr(s, 'closed', True):
        await s.close()


async def test_leg(cfg, path, model=None, provider=None):
    """One real call on a leg's current model, or on a proposed model/provider for it. Returns
    {ok, kind, provider, model, ms, reply | dims, error}. Never raises for a provider failure: the error is the result.
    Chat legs get admin_ui.test_prompt (config); legs listed in admin_ui.embedding_legs (config) embed one word through
    RAICA's own embeddings code, which also checks the vector dimension the leg is configured for."""
    import time
    leg = find_leg(cfg, path)
    if leg is None:
        raise LookupError('no leg %r in the site config' % path)
    prov = provider or leg['provider']
    if prov not in (_get(cfg, 'llm.providers') or {}):
        raise LookupError('no provider %r under llm.providers' % prov)
    mdl = model or leg['model']
    if not mdl:
        raise LookupError('leg %r has no model set; name one to test' % path)
    ui = cfg.get('admin_ui') or {}
    prompt, cap = ui.get('test_prompt'), ui.get('test_max_tokens')
    if not prompt or not isinstance(cap, int) or cap < 1:
        raise LookupError('admin_ui.test_prompt / admin_ui.test_max_tokens are not set in the site config')
    node = _get(cfg, path) or {}
    out = {'path': path, 'provider': prov, 'model': mdl, 'ok': False}
    t0 = time.monotonic()
    try:
        if path in (ui.get('embedding_legs') or []):
            from utils.embeddings_api import embed_texts
            svc = node.get('service') or {}
            same = prov == leg['provider']
            ec = {'provider': prov, 'model': mdl, 'dimension': int(node.get('dimension')),
                  'base_url': os.path.expandvars(str((svc.get('base_url') if same else None)
                                                     or provider_config(cfg, prov).get('base_url'))).rstrip('/'),
                  'api_key': os.path.expandvars(str((svc.get('api_key') if same else None)
                                                    or provider_config(cfg, prov).get('api_key') or '')),
                  'timeout': float(node['timeout']['embedding_request'])}   # config, no fallback (RAICA rule)
            vectors, tokens = await embed_texts([str(prompt)], ec)
            out.update(ok=True, kind='embedding', dims=len(vectors[0]) if vectors else 0, tokens=tokens)
        else:
            from llm_providers.factory import LLMProviderFactory
            own = _scalars(node) if prov == leg['provider'] else {}
            p = LLMProviderFactory.create_provider(prov, provider_config(cfg, prov, own))
            text = ''
            try:
                async for chunk in p.generate_stream(str(prompt), mdl, temperature=0, max_tokens=cap, num_predict=cap,
                                                     stream=True):
                    text += chunk or ''
                    if len(text) > 400:
                        break
            finally:
                await _close(p)
            if not text.strip():
                raise RuntimeError('the model answered with no text')
            out.update(ok=True, kind='chat', reply=' '.join(text.split())[:160])
    except Exception as e:                                   # noqa: BLE001 — the provider's error IS the result
        out['error'] = '%s: %s' % (type(e).__name__, str(e)[:300])
    out['ms'] = int((time.monotonic() - t0) * 1000)
    return out


# ── changing a leg or a key: write, restart, verify, restore (step 2c) ───────────────────────────────────────────
# A bad change can stop RAICA from starting, and then nothing outside can ask it to restore. So the safety net is HERE:
#   PUT -> backup + atomic write + PENDING marker -> restart (SIGTERM to itself under systemd, which starts it again)
#   start #1 -> pending_on_start(): attempts 1, run with the change -> verify_after_start(): test the changed leg once
#            -> ok: confirmed (marker removed)      -> fail: restore the backup, restart again
#   a start that finds attempts already >= 1 (start #1 crashed or never verified) -> restore BEFORE the config is read.
PENDING = CONFIG_DIR / '.llm_admin_pending.json'
LAST = CONFIG_DIR / '.llm_admin_last.json'
ENV_FILE = CONFIG_DIR.parent / '.env'
_SAFE_SECRET = re.compile(r'^[A-Za-z0-9._~:+/=@-]{8,512}$')   # parsed identically by python-dotenv and systemd
_VALID_NAME = re.compile(r'^[A-Z][A-Z0-9_]{1,63}$')


class ChangeError(ValueError):
    pass


class ChangeBusy(ChangeError):
    """Another change is still being verified (HTTP 409)."""


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _read_json(p):
    import json
    try:
        return json.loads(Path(p).read_text())
    except Exception:                                   # noqa: BLE001
        return None


def _write_json(p, obj, mode=0o600):
    import json
    from utils.config_migrate import atomic_write
    atomic_write(p, json.dumps(obj, indent=1, default=str), mode=mode)


def change_status():
    return {'pending': _read_json(PENDING), 'last': _read_json(LAST)}


def _same_type(old, new):
    if isinstance(old, bool) or isinstance(new, bool):
        return isinstance(old, bool) and isinstance(new, bool)
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return True
    return isinstance(old, str) and isinstance(new, str)


def apply_leg_change(cfg, path, model=None, provider=None, settings=None):
    """A copy of `cfg` with the leg changed. Rules (no list of legs or keys in code): the leg must be discovered; a
    setting must ALREADY exist on the leg as a scalar and keep its type; nothing that is or would become a ${SECRET}
    reference is written here (keys go through set_secret); the provider can change only on a leg that names its own,
    and must exist under llm.providers."""
    import copy
    leg = find_leg(cfg, path)
    if leg is None:
        raise ChangeError('no leg %r in the site config' % path)
    new = copy.deepcopy(cfg)
    node = _get(new, path)
    if model is not None:
        if not isinstance(model, str) or not model.strip() or '${' in model:
            raise ChangeError('model must be a non-empty name')
        node[leg['model_key']] = model.strip()
    if provider is not None:
        if provider not in (_get(new, 'llm.providers') or {}):
            raise ChangeError('no provider %r under llm.providers' % provider)
        if leg['provider_from'] != 'leg':
            raise ChangeError('%s uses the primary leg\'s provider; change that leg instead' % path)
        if node.get('provider') or node.get('type'):
            node['provider' if node.get('provider') else 'type'] = provider
        else:
            parent = _get(new, path.rsplit('.', 1)[0])
            parent['type'] = provider
    for k, v in (settings or {}).items():
        if k in ('model', 'model_name', 'provider', 'type'):
            raise ChangeError('%s: use the model / provider fields' % k)
        if k not in node or isinstance(node[k], (dict, list)):
            raise ChangeError('%s is not a setting of %s (only existing settings can be changed)' % (k, path))
        if isinstance(node[k], str) and '${' in node[k]:
            raise ChangeError('%s refers to a secret; set the key with PUT /admin/llm/secrets/{NAME}' % k)
        if isinstance(v, (dict, list)) or v is None or not _same_type(node[k], v):
            raise ChangeError('%s must stay a %s' % (k, type(node[k]).__name__))
        if isinstance(v, str) and '${' in v:
            raise ChangeError('%s: a value may not contain ${' % k)
        node[k] = v
    return new


def validate(new_cfg):
    """The proposed file must load through RAICA's own loader and still show the changed legs."""
    import tempfile
    from utils.config_loader import ConfigLoader
    from utils.config_migrate import _dump
    fd, tmp = tempfile.mkstemp(prefix='.llm_config.proposed.', suffix='.yaml', dir=str(CONFIG_DIR))
    try:
        with os.fdopen(fd, 'w') as fh:
            fh.write(_dump(new_cfg))
        loaded = ConfigLoader(tmp).load_config(reload=True)
        if not isinstance(loaded, dict) or 'llm' not in loaded:
            raise ChangeError('the proposed file does not load as a configuration')
    finally:
        os.unlink(tmp)


def _begin(kind, detail, test_paths, write):
    """Back up, write, record the pending change. `write()` performs the atomic write(s)."""
    if PENDING.exists():
        raise ChangeBusy('another change is still being verified; see GET /admin/llm/change')
    from datetime import datetime
    from utils.config_migrate import atomic_write
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backups = {}
    bak = LIVE.with_name('llm_config.yaml.admin-%s.bak' % stamp)
    atomic_write(bak, LIVE.read_text(), mode=0o400)
    backups[str(LIVE)] = str(bak)
    if kind == 'secret' and ENV_FILE.exists():
        ebak = ENV_FILE.with_name('.env.admin-%s.bak' % stamp)
        atomic_write(ebak, ENV_FILE.read_text(), mode=0o600)
        backups[str(ENV_FILE)] = str(ebak)
    _write_json(PENDING, {'kind': kind, 'detail': detail, 'test_paths': test_paths, 'backups': backups,
                          'at': _now(), 'attempts': 0})
    try:
        write()
    except Exception:
        _restore(backups)
        PENDING.unlink(missing_ok=True)
        raise
    return backups


def _restore(backups):
    from utils.config_migrate import atomic_write
    for target, bak in backups.items():
        mode = 0o444 if Path(target) == LIVE else 0o600
        atomic_write(target, Path(bak).read_text(), mode=mode)


def change_leg(path, model=None, provider=None, settings=None):
    cfg = raw_config()
    new = apply_leg_change(cfg, path, model=model, provider=provider, settings=settings)
    validate(new)
    from utils.config_migrate import atomic_write, _dump
    detail = {'path': path, 'model': model, 'provider': provider, 'settings': settings or {}}
    _begin('leg', detail, [path], lambda: atomic_write(LIVE, _dump(new)))
    return detail


def env_line_value(value):
    if not isinstance(value, str) or not _SAFE_SECRET.match(value):
        raise ChangeError('a key may only contain letters, digits and ._~:+/=@- (8 to 512 characters): it is written '
                          'unquoted so that python-dotenv and systemd read the same value')
    return value


def set_secret(name, value):
    """Write NAME=value into RAICA's .env (mode 600). Only a name the site config already refers to as ${NAME}."""
    cfg = raw_config()
    if not _VALID_NAME.match(name or ''):
        raise ChangeError('not a valid variable name')
    used = [l['path'] for l in legs(cfg) if any(s['name'] == name for s in l['secrets'])]
    if not used and not any(name in refs(b) for b in (_get(cfg, 'llm.providers') or {}).values()):
        raise ChangeError('%s is not referred to by the site config (no ${%s} anywhere)' % (name, name))
    line = '%s=%s' % (name, env_line_value(value))
    from utils.config_migrate import atomic_write

    def write():
        lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
        out, done = [], False
        for l in lines:
            if re.match(r'^\s*(export\s+)?%s\s*=' % re.escape(name), l):
                if not done:
                    out.append(line); done = True
                continue
            out.append(l)
        if not done:
            out.append(line)
        atomic_write(ENV_FILE, '\n'.join(out) + '\n', mode=0o600)
    _begin('secret', {'name': name, 'last4': value[-4:]}, used[:1], write)
    return {'name': name, 'used_by': used, 'last4': value[-4:]}


def _systemctl_show(unit, user):
    import subprocess
    cmd = ['systemctl'] + (['--user'] if user else []) + ['show', unit, '-p', 'MainPID', '-p', 'Restart']
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    return dict(l.split('=', 1) for l in out.splitlines() if '=' in l)


def _own_cgroup():
    return Path('/proc/self/cgroup').read_text().strip().splitlines()[-1].split(':', 2)[-1]


def supervised():
    """True only when systemd will start RAICA again after it exits: this process is the MainPID of the .service unit
    whose cgroup it runs in, and that unit has Restart=always (a SIGTERM ends RAICA cleanly; only `always` restarts a
    clean exit). INVOCATION_ID is NOT evidence: a shell started by systemd passes it to everything it launches
    (found 2026-10-23: a hand-started RAICA sent itself SIGTERM and stayed down)."""
    try:
        cg = _own_cgroup()
        unit = cg.rstrip('/').rsplit('/', 1)[-1]
        if not unit.endswith('.service'):
            return False
        props = _systemctl_show(unit, user='/user.slice/' in cg)
        return props.get('MainPID') == str(os.getpid()) and props.get('Restart') == 'always'
    except Exception:                                   # noqa: BLE001 — unknown means "not supervised": never stop
        return False


def restart():
    """Restart RAICA through its supervisor: SIGTERM to this (main) process under systemd (Restart=always starts it
    again — the path scripts/deploy.sh uses). Without a supervisor, say so: stopping would leave RAICA down."""
    if not supervised():
        return {'restarting': False, 'note': 'no supervisor (systemd) detected: restart RAICA yourself '
                                             '(./stop_complete.sh && ./start_complete.sh); the change is verified at '
                                             'that start'}
    import asyncio
    import signal
    asyncio.get_event_loop().call_later(1.0, os.kill, os.getpid(), signal.SIGTERM)
    return {'restarting': True, 'note': 'RAICA restarts in about a second; it then tests the change and keeps it, '
                                        'or restores the previous file and restarts again'}


def pending_on_start():
    """FIRST thing at start (before the config is read). A start that finds a pending change it already tried once
    (the previous start crashed or never confirmed it) restores the backup. Never raises."""
    import logging
    log = logging.getLogger(__name__)
    # Once per PROCESS: uvicorn.run("fastapi_server_complete:app") imports the server module a second time, so its
    # top-level code runs twice in one start (found 2026-10-23: the second run counted a second attempt and restored a
    # change that had not failed). The process environment is shared by both imports.
    if os.environ.get('_RAICA_LLM_ADMIN_START') == str(os.getpid()):
        return 'already checked'
    os.environ['_RAICA_LLM_ADMIN_START'] = str(os.getpid())
    try:
        p = _read_json(PENDING)
        if not p:
            return None
        if int(p.get('attempts', 0)) >= 1:
            _restore(p.get('backups') or {})
            PENDING.unlink(missing_ok=True)
            _write_json(LAST, {'result': 'restored', 'why': 'RAICA did not confirm the change on its first start '
                               '(it crashed or stopped before its self-test)', 'change': p, 'at': _now()})
            log.error('↩ LLM admin: the pending change was NOT confirmed on its first start — previous files restored '
                      '(%s)', p.get('detail'))
            return 'restored'
        p['attempts'] = int(p.get('attempts', 0)) + 1
        _write_json(PENDING, p)
        return 'trying'
    except Exception as e:                              # noqa: BLE001
        log.error('LLM admin: pending-change check failed: %s', e)
        return None


async def verify_after_start():
    """Background, once the server has started with a pending change: test the changed leg once. Pass -> confirmed;
    fail -> restore the previous files and restart (or ask for a restart without a supervisor)."""
    import logging
    log = logging.getLogger(__name__)
    p = _read_json(PENDING)
    if not p:
        return None
    results = []
    try:
        cfg = raw_config()
        for path in p.get('test_paths') or []:
            results.append(await test_leg(cfg, path))
    except Exception as e:                              # noqa: BLE001
        results.append({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
    if all(r.get('ok') for r in results):
        PENDING.unlink(missing_ok=True)
        _write_json(LAST, {'result': 'confirmed', 'tests': results, 'change': p, 'at': _now()})
        log.warning('✅ LLM admin: change confirmed (%s)', p.get('detail'))
        return 'confirmed'
    _restore(p.get('backups') or {})
    PENDING.unlink(missing_ok=True)
    _write_json(LAST, {'result': 'restored', 'why': 'the self-test after the restart failed', 'tests': results,
                       'change': p, 'at': _now()})
    log.error('↩ LLM admin: the change FAILED its self-test — previous files restored, restarting (%s)', results)
    restart()
    return 'restored'
