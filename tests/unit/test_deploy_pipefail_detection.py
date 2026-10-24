"""Shell checks of the form `cmd | grep -q PATTERN` under `set -o pipefail` (2026-10-24, found deploying 1.0.0.348).

`grep -q` exits at the first match; `cmd` may still be writing, gets SIGPIPE, and pipefail turns the whole pipeline
into a FAILURE although the pattern matched. On production `systemd_managed` answered "no" 1 time in 6 with
raica.service installed — deploy.sh then restarts by hand-start scripts that defer to the unit (the process never
cycles), and install_raica_service.sh would treat a REJECTED unit as clean. Each check must capture the output first.
The stand-in commands below print the match early and then far more than a pipe buffer, which makes SIGPIPE certain.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FLOOD = 'yes "x unrelated.service enabled enabled" | head -c 300000'


def _run(script, stub_name, stub_body, tmp_path):
    (tmp_path / stub_name).write_text(f"#!/bin/bash\n{stub_body}\n")
    (tmp_path / stub_name).chmod(0o755)
    r = subprocess.run(['bash', '-c', 'set -uo pipefail\n' + script], capture_output=True, text=True,
                       env={'PATH': f'{tmp_path}:/usr/bin:/bin'})
    return r.stdout.strip()


def test_deploy_detects_the_unit_even_when_the_listing_is_long(tmp_path):
    src = (REPO / 'scripts' / 'deploy.sh').read_text()
    fn = re.search(r'^systemd_managed\(\) \{\n.*?^\}\n', src, re.S | re.M)
    assert fn, 'systemd_managed() not found in scripts/deploy.sh'
    script = 'SERVICE="raica.service"\n' + fn.group(0) + \
        'for i in 1 2 3 4 5; do systemd_managed && echo yes || echo no; done'
    out = _run(script, 'systemctl', f'echo "UNIT FILE STATE PRESET"; echo "raica.service enabled enabled"; {FLOOD}',
               tmp_path)
    assert out.split() == ['yes'] * 5, out


def test_unit_verifier_rejects_a_bad_unit_even_when_the_report_is_long(tmp_path):
    src = (REPO / 'scripts' / 'install_raica_service.sh').read_text()
    block = re.search(r'^    if (.*systemd-analyze verify.*)\; then$', src, re.M)
    assert block, 'systemd-analyze verify check not found in scripts/install_raica_service.sh'
    script = f'TMP_UNIT=/dev/null\nif {block.group(1)}; then echo rejected; else echo clean; fi'
    out = _run(script, 'systemd-analyze', f'echo "raica.service: Unknown key name Foo"; {FLOOD}', tmp_path)
    assert out == 'rejected', out
