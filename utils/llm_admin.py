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
