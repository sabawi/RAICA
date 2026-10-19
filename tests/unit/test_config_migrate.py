"""Site-owned configuration (v1.0.0.336, utils/config_migrate.py). Owner rules 2026-10-18/19: the installation's
values are invariant; releases may only migrate the STRUCTURE (add, move); a key is removed only by the release whose
code stops reading it. Each test names the failure it prevents.
"""
import ast
import os
import random
import stat
from pathlib import Path

import pytest
import yaml

from utils import config_migrate as cm

REPO = Path(__file__).resolve().parents[2]


def mig(tmp, version, moves=None, removes=None):
    d = tmp / 'migrations'
    d.mkdir(exist_ok=True)
    (d / ('m%04d_t.py' % version)).write_text('VERSION=%d\nMOVES=%r\nREMOVES=%r\n' % (version, moves or {}, removes or []))
    return d


def setup(tmp, defaults_text, migrations=((1, None, None),)):
    cfg = tmp / 'config'
    cfg.mkdir()
    (cfg / cm.DEFAULTS_NAME).write_text(defaults_text)
    for v, mv, rm in migrations:
        mig(cfg, v, mv, rm)
    return cfg


DEFAULTS = '# a comment the site must keep\nconfig_version: 1\nllm:\n  primary:\n    model: m-default   # inline\n  timeout: 30\n'


def test_install_copies_the_defaults_verbatim_and_read_only(tmp_path):
    """A first start creates the live file as an EXACT copy (comments included), mode 444 — not a re-dump."""
    cfg = setup(tmp_path, DEFAULTS)
    assert cm.ensure_site_config(cfg)['action'] == 'created'
    live = cfg / cm.LIVE_NAME
    assert live.read_text() == DEFAULTS
    assert stat.S_IMODE(live.stat().st_mode) == 0o444


def test_a_current_file_is_not_rewritten(tmp_path):
    """Nothing to do = no write (no backup churn, comments survive)."""
    cfg = setup(tmp_path, DEFAULTS)
    cm.ensure_site_config(cfg)
    before = (cfg / cm.LIVE_NAME).stat().st_mtime_ns
    assert cm.ensure_site_config(cfg)['action'] == 'current'
    assert (cfg / cm.LIVE_NAME).stat().st_mtime_ns == before
    assert not list(cfg.glob('*.bak'))


def test_a_new_default_key_is_added_and_an_admin_value_is_kept(tmp_path):
    """The owner's rule: a release's NEW key arrives with its default; a value the site has never changes, even when
    the release now recommends another one."""
    cfg = setup(tmp_path, DEFAULTS)
    cm.ensure_site_config(cfg)
    live = cfg / cm.LIVE_NAME
    site = yaml.safe_load(live.read_text())
    site['llm']['primary']['model'] = 'm-chosen-by-admin'
    cm.atomic_write(live, yaml.safe_dump(site, sort_keys=False))
    (cfg / cm.DEFAULTS_NAME).write_text(DEFAULTS.replace('m-default', 'm-better') + 'vision:\n  model: v-default\n')
    r = cm.ensure_site_config(cfg)
    after = yaml.safe_load(live.read_text())
    assert after['llm']['primary']['model'] == 'm-chosen-by-admin'
    assert after['vision']['model'] == 'v-default'
    assert 'vision' in r['added'] and r['backup']
    assert cm.differs_from_defaults(cfg) == {'llm.primary.model': {'site': 'm-chosen-by-admin', 'release': 'm-better'}}


def test_a_moved_key_carries_the_sites_value(tmp_path):
    """A rename must not lose the admin's value (the release's default for the new path must NOT win)."""
    cfg = setup(tmp_path, DEFAULTS)
    cm.ensure_site_config(cfg)
    live = cfg / cm.LIVE_NAME
    site = yaml.safe_load(live.read_text()); site['llm']['primary']['model'] = 'm-admin'
    cm.atomic_write(live, yaml.safe_dump(site, sort_keys=False))
    mig(cfg, 2, moves={'llm.primary.model': 'llm.primary.config.model'})
    (cfg / cm.DEFAULTS_NAME).write_text('config_version: 2\nllm:\n  primary:\n    config:\n      model: m-new-default\n  timeout: 30\n')
    cm.ensure_site_config(cfg)
    after = yaml.safe_load(live.read_text())
    assert after['llm']['primary']['config']['model'] == 'm-admin'
    assert 'model' not in after['llm']['primary'] and after['config_version'] == 2


def test_only_a_declared_removal_removes(tmp_path):
    """Keys the defaults no longer list are KEPT unless a migration removes them (the code-in-sync rule)."""
    cfg = setup(tmp_path, DEFAULTS)
    cm.ensure_site_config(cfg)
    (cfg / cm.DEFAULTS_NAME).write_text('config_version: 1\nllm:\n  primary:\n    model: m-default\n')
    cm.ensure_site_config(cfg)
    assert yaml.safe_load((cfg / cm.LIVE_NAME).read_text())['llm']['timeout'] == 30      # still there
    mig(cfg, 2, removes=['llm.timeout'])
    (cfg / cm.DEFAULTS_NAME).write_text('config_version: 2\nllm:\n  primary:\n    model: m-default\n')
    cm.ensure_site_config(cfg)
    assert 'timeout' not in yaml.safe_load((cfg / cm.LIVE_NAME).read_text())['llm']


def test_a_migration_that_would_overwrite_a_value_is_refused_and_the_file_untouched(tmp_path):
    """Moving onto an existing key would silently replace the site's value there: refused, nothing written."""
    cfg = setup(tmp_path, DEFAULTS + 'old:\n  x: 1\nnew:\n  x: 2\n')
    cm.ensure_site_config(cfg)
    live = cfg / cm.LIVE_NAME
    before = live.read_text()
    mig(cfg, 2, moves={'old.x': 'new.x'})
    with pytest.raises(cm.ConfigMigrationError):
        cm.ensure_site_config(cfg)
    assert live.read_text() == before


def test_property_no_value_ever_changes_on_random_sites(tmp_path):
    """200 random site files against random new defaults: every original value survives, unchanged."""
    rnd = random.Random(1017)
    for i in range(200):
        site = {'config_version': 1}
        defaults = {'config_version': 1}
        for k in range(8):
            key = 'k%d' % rnd.randint(0, 12)
            site.setdefault('s', {})[key] = rnd.choice([1, 'a', None, [1, 2], True, {'z': rnd.random()}])
            defaults.setdefault('s', {})['k%d' % rnd.randint(0, 12)] = rnd.choice([2, 'b', False])
        new, _ = cm.migrate(site, defaults, [], 1)
        for path, value in cm.leaves(site).items():
            assert cm.leaves(new)[path] == value, (i, path)


def test_older_code_restores_the_backup_or_refuses(tmp_path):
    """A rollback to code that knows version 1 finds a version-2 file: it must restore the v1 backup, not run on a
    structure it does not understand; with no backup it refuses to start."""
    cfg = setup(tmp_path, DEFAULTS)
    cm.ensure_site_config(cfg)
    v1_text = (cfg / cm.LIVE_NAME).read_text()
    mig(cfg, 2, moves={'llm.timeout': 'llm.limits.timeout'})
    (cfg / cm.DEFAULTS_NAME).write_text('config_version: 2\nllm:\n  primary:\n    model: m-default\n  limits:\n    timeout: 30\n')
    cm.ensure_site_config(cfg)
    (cfg / 'migrations' / 'm0002_t.py').unlink()                                   # the older code
    assert cm.ensure_site_config(cfg)['action'] == 'restored'
    assert (cfg / cm.LIVE_NAME).read_text() == v1_text
    cm.atomic_write(cfg / cm.LIVE_NAME, 'config_version: 5\n')
    for b in cfg.glob('*.bak'):
        os.chmod(b, 0o600); b.unlink()
    with pytest.raises(cm.ConfigMigrationError):
        cm.ensure_site_config(cfg)


def test_atomic_write_replaces_a_read_only_file(tmp_path):
    """The live file is 444: the writer must still replace it (the folder is what must be writable) and keep 444."""
    f = tmp_path / 'x.yaml'
    f.write_text('a: 1\n'); os.chmod(f, 0o444)
    cm.atomic_write(f, 'a: 2\n')
    assert f.read_text() == 'a: 2\n' and stat.S_IMODE(f.stat().st_mode) == 0o444
    assert [p.name for p in tmp_path.iterdir()] == ['x.yaml']                       # no temp file left


def test_migration_numbering_gaps_are_refused(tmp_path):
    cfg = setup(tmp_path, DEFAULTS, migrations=((1, None, None), (3, None, None)))
    with pytest.raises(cm.ConfigMigrationError):
        cm.ensure_site_config(cfg)


def test_repo_defaults_version_matches_the_latest_migration():
    """The shipped defaults must claim the version the shipped migrations reach, or every site migrates forever."""
    d = yaml.safe_load((REPO / 'config' / cm.DEFAULTS_NAME).read_text())
    ms = cm.load_migrations(REPO / 'config' / 'migrations')
    assert d['config_version'] == ms[-1].VERSION


def test_the_live_file_is_not_tracked_and_is_ignored():
    """`git add config/llm_config.yaml` must never happen again: it is the installation's, not the release's."""
    import subprocess
    tracked = subprocess.run(['git', 'ls-files', 'config/llm_config.yaml'], cwd=REPO, capture_output=True, text=True).stdout
    ignored = subprocess.run(['git', 'check-ignore', 'config/llm_config.yaml'], cwd=REPO, capture_output=True, text=True).returncode
    assert tracked.strip() == '' and ignored == 0


def test_the_server_migrates_before_anything_reads_the_config():
    """The ensure call must run before the first project import (a release that stops tracking the file makes
    `git pull` delete it on existing clones)."""
    tree = ast.parse((REPO / 'fastapi_server_complete.py').read_text())
    body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert isinstance(body[0], ast.ImportFrom) and body[0].module == 'utils.config_migrate'
    assert isinstance(body[1], ast.Expr) and isinstance(body[1].value, ast.Call) \
        and body[1].value.func.id == '_ensure_site_config'
