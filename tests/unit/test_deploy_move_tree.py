"""scripts/deploy.sh move_tree (v1.0.0.337): the deploy tool must reach its target in BOTH directions and prove it.

Failure it prevents: until v1.0.0.337 `deploy.sh --rollback` (and --to an older commit) re-checked-out the branch tip
after a detached checkout, so it stayed on the NEWER code and still printed "✓ DEPLOYED" — present since v1.0.0.323,
found 2026-10-19 by the NewX installer's rollback test (RAICA stayed forward while NewX reported a full rollback).
The function is extracted from deploy.sh itself, so this tests the shipped code.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def move_tree_src():
    s = (REPO / 'scripts' / 'deploy.sh').read_text()
    m = re.search(r'^move_tree\(\) \{\n.*?^\}\n', s, re.S | re.M)
    assert m, 'move_tree() not found in scripts/deploy.sh'
    return m.group(0)


def sh(cwd, cmd):
    r = subprocess.run(['bash', '-c', cmd], cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def repo(tmp_path):
    """c1: config/llm_config.yaml TRACKED (pre-336) · c2: renamed to defaults + ignored (336) · c3: a later change."""
    d = tmp_path / 'r'
    d.mkdir()
    g = 'git -c user.email=t@example.com -c user.name=t'
    sh(d, 'git init -q -b main && mkdir config && echo "model: m1" > config/llm_config.yaml && git add -A && %s commit -qm c1' % g)
    sh(d, 'git mv config/llm_config.yaml config/llm_config.defaults.yaml && echo config/llm_config.yaml > .gitignore '
          '&& git add -A && %s commit -qm c2 && cp config/llm_config.defaults.yaml config/llm_config.yaml' % g)
    sh(d, 'echo v3 > x && git add -A && %s commit -qm c3' % g)
    shas = sh(d, 'git rev-list --reverse HEAD')[1].split()
    return d, shas


def run_move(d, target):
    script = 'red() { echo "RED $*"; }; ylw() { echo "YLW $*"; }\n' + move_tree_src() + '\nmove_tree %s' % target
    return sh(d, script)


def test_forward_moves_the_branch(tmp_path):
    d, (c1, c2, c3) = repo(tmp_path)
    sh(d, 'git reset -q --hard %s' % c2)
    rc, _ = run_move(d, c3)
    assert rc == 0 and sh(d, 'git rev-parse HEAD')[1] == c3 and sh(d, 'git rev-parse --abbrev-ref HEAD')[1] == 'main'


def test_backward_really_goes_back(tmp_path):
    """THE bug: a rollback must leave the tree at the OLDER commit, on the branch (not detached, not the tip)."""
    d, (c1, c2, c3) = repo(tmp_path)
    rc, out = run_move(d, c2)
    assert rc == 0, out
    assert sh(d, 'git rev-parse HEAD')[1] == c2 and sh(d, 'git rev-parse --abbrev-ref HEAD')[1] == 'main'


def test_rolling_back_across_the_config_change_keeps_the_sites_file(tmp_path):
    """Back to a commit that TRACKS llm_config.yaml: git replaces the site's file — a copy must be kept, and said."""
    d, (c1, c2, c3) = repo(tmp_path)
    (d / 'config' / 'llm_config.yaml').write_text('model: chosen-by-admin\n')
    rc, out = run_move(d, c1)
    assert rc == 0, out
    assert (d / 'config' / 'llm_config.yaml').read_text().strip() == 'model: m1'          # the tracked file again
    kept = list((d / 'config').glob('llm_config.yaml.site-before-rollback-*'))
    assert len(kept) == 1 and kept[0].read_text().strip() == 'model: chosen-by-admin'
    assert 'YLW' in out and 'kept as' in out
