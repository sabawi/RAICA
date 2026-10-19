"""
Site-owned configuration: `config/llm_config.yaml` belongs to the INSTALLATION; releases ship defaults + structure
migrations (owner decisions 2026-10-18/19, NewX docs/DESIGN_ai_service_admin.md §4).

  config/llm_config.defaults.yaml   tracked; the release's defaults (developers edit THIS file)
  config/llm_config.yaml            untracked (.gitignore), mode 444; the site's live file — RAICA reads only this
  config/migrations/mNNNN_*.py      structure migrations: VERSION, MOVES {old.path: new.path}, REMOVES [path]

Rules this module enforces (each one is checked, not assumed):
  * a missing live file is created as a VERBATIM copy of the defaults (comments and all)
  * a key the defaults have and the site lacks is ADDED with the default (an addition, not a change)
  * a value the site has is NEVER changed: the only exceptions are the MOVES a migration declares (the value is
    carried to its new path) and the REMOVES it declares (allowed only in the release whose code stops reading
    the key). An undeclared change makes the migration refuse, and the live file is left untouched.
  * before any rewrite the current file is kept as llm_config.yaml.v<N>.bak; code older than the file (a
    rollback) restores the newest backup it understands, or refuses to start.
  * every write is atomic (temp file + rename) and leaves the file mode 444.

Standalone on purpose (stdlib + PyYAML): it runs before anything else imports the configuration.
"""
import copy
import importlib.util
import logging
import os
import tempfile
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

LIVE_NAME = 'llm_config.yaml'
DEFAULTS_NAME = 'llm_config.defaults.yaml'
VERSION_KEY = 'config_version'
READ_ONLY = 0o444


class ConfigMigrationError(RuntimeError):
    """The live configuration could not be migrated safely. It was left exactly as it was."""


# ── small path helpers over nested dicts ────────────────────────────────────────────────────────────────────────
def _get(d, path):
    for part in path.split('.'):
        if not isinstance(d, dict) or part not in d:
            raise KeyError(path)
        d = d[part]
    return d


def _has(d, path):
    try:
        _get(d, path)
        return True
    except KeyError:
        return False


def _set(d, path, value):
    parts = path.split('.')
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _delete(d, path):
    parts = path.split('.')
    for part in parts[:-1]:
        d = d.get(part, {})
    d.pop(parts[-1], None)


def leaves(d, prefix=''):
    """{dotted.path: value} for every non-dict value (lists count as values)."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            p = '%s.%s' % (prefix, k) if prefix else str(k)
            if isinstance(v, dict) and v:
                out.update(leaves(v, p))
            else:
                out[p] = v
    return out


def add_missing(site, defaults):
    """Add every key the defaults have and the site lacks (deep). Returns the list of added paths."""
    added = []

    def walk(s, d, prefix):
        for k, v in d.items():
            p = '%s.%s' % (prefix, k) if prefix else str(k)
            if k not in s:
                s[k] = copy.deepcopy(v)
                added.append(p)
            elif isinstance(v, dict) and isinstance(s[k], dict):
                walk(s[k], v, p)
    walk(site, defaults, '')
    return added


# ── migrations ──────────────────────────────────────────────────────────────────────────────────────────────────
def load_migrations(migrations_dir):
    """Every mNNNN_*.py, ordered by VERSION; versions must be 1..N with no gaps or repeats."""
    found = []
    for f in sorted(Path(migrations_dir).glob('m[0-9][0-9][0-9][0-9]_*.py')):
        spec = importlib.util.spec_from_file_location('raica_cfg_' + f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        found.append(mod)
    found.sort(key=lambda m: m.VERSION)
    versions = [m.VERSION for m in found]
    if versions != list(range(1, len(versions) + 1)):
        raise ConfigMigrationError('config migrations must be numbered 1..N without gaps: %s' % versions)
    return found


def migrate(site, defaults, migrations, from_version):
    """Pure function: (new site dict, report). Raises ConfigMigrationError on any undeclared value change."""
    new = copy.deepcopy(site)
    report = {'moved': [], 'removed': [], 'added': [], 'to_version': from_version}
    declared_moves, declared_removes = {}, set()
    for m in migrations:
        if m.VERSION <= from_version:
            continue
        for old, dst in getattr(m, 'MOVES', {}).items():
            if _has(new, old):
                if _has(new, dst):
                    raise ConfigMigrationError('migration %d: cannot move %s to %s — the target already exists'
                                               % (m.VERSION, old, dst))
                _set(new, dst, _get(new, old))
                _delete(new, old)
                declared_moves[old] = dst
                report['moved'].append('%s -> %s' % (old, dst))
        for path in getattr(m, 'REMOVES', []):
            if _has(new, path):
                _delete(new, path)
                declared_removes.add(path)
                report['removed'].append(path)
        report['to_version'] = m.VERSION
    report['added'] = add_missing(new, {k: v for k, v in defaults.items() if k != VERSION_KEY})
    new[VERSION_KEY] = report['to_version']

    # THE invariant (owner: "installation-invariant"): every value the site had is still there, unchanged, at its
    # own path or at the path a migration moved it to — unless a migration removed it.
    after = leaves(new)
    for path, value in leaves(site).items():
        if path == VERSION_KEY:
            continue
        target = path
        for old, dst in declared_moves.items():
            if path == old or path.startswith(old + '.'):
                target = dst + path[len(old):]
        if any(path == r or path.startswith(r + '.') for r in declared_removes):
            continue
        if target not in after or after[target] != value:
            raise ConfigMigrationError('a value would change: %s (%r -> %r); refused' % (path, value, after.get(target)))
    return new, report


# ── files ───────────────────────────────────────────────────────────────────────────────────────────────────────
def atomic_write(path, text, mode=READ_ONLY):
    """Write `text` to `path` through a temp file in the same folder and rename it over the target: never a
    half-written config, and it works on a read-only target (the folder is what must be writable)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def site_version(cfg):
    v = cfg.get(VERSION_KEY) if isinstance(cfg, dict) else None
    return v if isinstance(v, int) else 0


def _dump(cfg):
    return yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, default_flow_style=False)


def ensure_site_config(config_dir=None, migrations_dir=None):
    """Make the live file exist and be current. Called first thing at server start and by the config loader.
    Returns a short report; raises ConfigMigrationError when it cannot proceed safely (the file is untouched)."""
    config_dir = Path(config_dir or Path(__file__).resolve().parent.parent / 'config')
    migrations_dir = Path(migrations_dir or config_dir / 'migrations')
    live, defaults_path = config_dir / LIVE_NAME, config_dir / DEFAULTS_NAME
    if not defaults_path.exists():
        return {'action': 'none', 'why': 'no %s (pre-1.0.0.336 layout)' % DEFAULTS_NAME}
    defaults_text = defaults_path.read_text()
    defaults = yaml.safe_load(defaults_text) or {}
    migrations = load_migrations(migrations_dir) if migrations_dir.exists() else []
    code_version = migrations[-1].VERSION if migrations else 0

    if not live.exists():
        atomic_write(live, defaults_text)          # VERBATIM: comments and all
        logger.warning('🆕 %s created from the release defaults (%s), config_version %s', live, DEFAULTS_NAME,
                       site_version(defaults))
        return {'action': 'created', 'version': site_version(defaults)}

    site = yaml.safe_load(live.read_text()) or {}
    have = site_version(site)
    if have > code_version:
        # this code is OLDER than the file (a rollback): restore the newest backup it understands
        for v in range(code_version, -1, -1):
            bak = live.with_name('%s.v%d.bak' % (LIVE_NAME, v))
            if bak.exists():
                atomic_write(live, bak.read_text())
                logger.warning('↩ %s restored from %s (code knows config_version %d, the file was %d)',
                               live, bak.name, code_version, have)
                return {'action': 'restored', 'from': bak.name}
        raise ConfigMigrationError('%s is config_version %d but this code only knows %d, and no backup can be '
                                   'restored. Run the newer release, or restore the file from a backup.'
                                   % (live, have, code_version))

    new, report = migrate(site, defaults, migrations, have)
    if have == code_version and not report['added']:
        return {'action': 'current', 'version': have}
    bak = live.with_name('%s.v%d.bak' % (LIVE_NAME, have))
    atomic_write(bak, live.read_text(), mode=0o400)
    atomic_write(live, _dump(new))
    logger.warning('🔧 %s migrated %d -> %d (moved %s, removed %s, added %s); previous file kept as %s',
                   live, have, report['to_version'], report['moved'] or 'nothing', report['removed'] or 'nothing',
                   report['added'] or 'nothing', bak.name)
    return {'action': 'migrated', **report, 'backup': bak.name}


def differs_from_defaults(config_dir=None):
    """Where the site's value differs from the CURRENT release default — shown as a recommendation, never applied."""
    config_dir = Path(config_dir or Path(__file__).resolve().parent.parent / 'config')
    site = yaml.safe_load((config_dir / LIVE_NAME).read_text()) or {}
    defaults = yaml.safe_load((config_dir / DEFAULTS_NAME).read_text()) or {}
    s, d = leaves(site), leaves(defaults)
    return {p: {'site': s[p], 'release': d[p]} for p in d if p in s and s[p] != d[p] and p != VERSION_KEY}


if __name__ == '__main__':          # python -m utils.config_migrate   (what deploy/upgrade tooling calls)
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        print(json.dumps(ensure_site_config(), default=str))
    except ConfigMigrationError as e:
        print('CONFIG MIGRATION REFUSED: %s' % e, file=sys.stderr)
        sys.exit(2)
