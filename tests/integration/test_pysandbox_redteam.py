"""Red-team suite for the run_python_analysis sandbox (docs/DESIGN_run_python_analysis.md §9).

Every program here is an ATTACK written as a model might be talked into writing it. Each test asserts the attack is
BLOCKED. Each was also run against a deliberately weakened container (the protection it relies on removed) and went
red — see `PLANTS` and `tests/integration/run_pysandbox_plants.py`; a test that cannot fail proves nothing.

REAL CONTAINERS, NO MOCKS: these run Docker with the gVisor runtime. They FAIL (not skip) when Docker or runsc is
missing, because a sandbox suite that silently skips reads as a pass.
Run: ./venv/bin/python -m pytest -q tests/integration/test_pysandbox_redteam.py
"""
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading

import pytest

from utils import py_sandbox as sb

DEFAULTS = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'llm_config.defaults.yaml')


def _cfg(**over):
    import yaml
    with open(DEFAULTS) as f:
        cfg = dict(yaml.safe_load(f)['user_tools']['run_python_analysis'])
    cfg.update({'timeout_seconds': 8, 'kill_grace_seconds': 5, 'queue_wait_seconds': 2})
    cfg.update(over)
    return cfg


def _run(program, **over):
    """Every run is bounded: a hang in the sandbox is a FAILURE here, never a stuck suite."""
    cfg = _cfg(**over)
    limit = cfg['timeout_seconds'] + 4 * cfg['kill_grace_seconds'] + 30
    box = {}

    def target():                     # a thread, not asyncio.wait_for: cancelling waits for the cleanup that hangs
        try:
            box['r'] = asyncio.run(sb.run_program(program, cfg))
        except BaseException as e:    # noqa: BLE001 — re-raised in the test thread below
            box['e'] = e
    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(limit)
    if th.is_alive():
        raise AssertionError(f"sandbox run did not finish within {limit}s — a hang (cleanup or clock)")
    if 'e' in box:
        raise box['e']
    return box['r']


def _report(result):
    """Attack programs print one JSON line starting with REPORT=."""
    for line in result['stdout'].splitlines():
        if line.startswith('REPORT='):
            return json.loads(line[len('REPORT='):])
    raise AssertionError(f"attack program did not report: exit={result['exit']} notes={result['notes']} "
                         f"stderr={result['stderr'][-400:]}")


@pytest.fixture(scope='module', autouse=True)
def _require_sandbox():
    assert shutil.which('docker'), "Docker is required for the sandbox red-team suite"
    info = subprocess.run(['docker', 'info', '--format', '{{json .Runtimes}}'], capture_output=True, text=True)
    assert 'runsc' in info.stdout, "gVisor (runsc) is not a Docker runtime here — install it (design §8)"
    img = subprocess.run(['docker', 'image', 'inspect', _cfg()['image']], capture_output=True)
    assert img.returncode == 0, "image missing: docker build -t raica-pysandbox:1 deploy/pysandbox"
    yield
    asyncio.run(sb.reap_leftovers(_cfg()))


# ── the control case: a legitimate program works ─────────────────────────────────────────────────────────────────
def test_legitimate_program_runs_and_returns_its_chart():
    """Positive control: without it, 'everything is blocked' could mean 'nothing works'."""
    r = _run("import numpy as np, matplotlib.pyplot as plt\n"
             "x=np.linspace(0,1,50); plt.plot(x,x**2); plt.savefig('chart.png')\nprint('sum', round(float((x**2).sum()),3))")
    assert r['ok'] and 'sum 16.837' in r['stdout'] and len(r['images']) == 1
    assert r['images'][0][:3] == b'\xff\xd8\xff'          # re-encoded JPEG, not the program's own bytes


def test_runs_under_gvisor_not_the_host_kernel():
    """A plain container shares the host kernel; one kernel bug is an escape. gVisor serves the syscalls itself."""
    rep = _report(_run("import platform,json; print('REPORT='+json.dumps(platform.release()))"))
    assert 'gvisor' in rep


# ── 1. host files ────────────────────────────────────────────────────────────────────────────────────────────────
SEARCH_TOKEN = r'''
import os, json, sys
tok = TOKEN_REVERSED[::-1]      # the program's own file must not contain the token
found = []
for root, dirs, files in os.walk('/', onerror=lambda e: None):
    dirs[:] = [d for d in dirs if not (root == '/' and d in ('proc', 'sys', 'dev'))]
    for n in files:
        p = os.path.join(root, n)
        try:
            with open(p, 'rb') as f:
                if tok.encode() in f.read(1 << 20):
                    found.append(p)
        except Exception:
            pass
print('REPORT=' + json.dumps(found))
'''


def test_no_host_file_is_visible():
    """A secret in a host file (stand-in for RAICA's .env) must not be readable from anywhere in the container."""
    tok = 'HOSTSECRET-' + secrets.token_hex(8)
    with tempfile.TemporaryDirectory(dir='/tmp') as d:
        os.chmod(d, 0o755)                                 # world-readable: only the absent MOUNT can protect it
        with open(os.path.join(d, '.env'), 'w') as f:
            f.write(f'API_KEY={tok}\n')
        os.chmod(os.path.join(d, '.env'), 0o644)
        found = _report(_run(f"TOKEN_REVERSED={tok[::-1]!r}\n" + SEARCH_TOKEN))
    assert found == []


def test_docker_socket_is_absent():
    """The socket would hand the program root on the host."""
    rep = _report(_run("import os,json; print('REPORT='+json.dumps([p for p in "
                       "('/var/run/docker.sock','/run/docker.sock') if os.path.exists(p)]))"))
    assert rep == []


# ── 2. network ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_no_network_internet_metadata_or_host():
    """No route anywhere: internet, AWS instance metadata (cloud credentials), or a service on the host."""
    tok = 'NETSECRET-' + secrets.token_hex(8)
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 0))
    srv.listen(4)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve():
        srv.settimeout(0.5)
        while not stop.is_set():
            try:
                c, _ = srv.accept()
                c.sendall(tok.encode())
                c.close()
            except OSError:
                pass
    threading.Thread(target=serve, daemon=True).start()
    try:
        prog = f'''
import socket, json
res = {{}}
for host, port in [('1.1.1.1', 53), ('169.254.169.254', 80), ('172.17.0.1', {port}), ('10.0.2.2', {port}),
                   ('host.docker.internal', {port}), ('127.0.0.1', 5000), ('127.0.0.1', 5432), ('127.0.0.1', 6379)]:
    try:
        s = socket.create_connection((host, port), timeout=2); res[f"{{host}}:{{port}}"] = s.recv(64).decode(); s.close()
    except Exception as e:
        res[f"{{host}}:{{port}}"] = 'BLOCKED ' + type(e).__name__
print('REPORT=' + json.dumps(res))
'''
        rep = _report(_run(prog))
    finally:
        stop.set()
        srv.close()
    assert all(v.startswith('BLOCKED') for v in rep.values()), rep
    assert tok not in json.dumps(rep)


# ── 3. identity, privileges, environment ─────────────────────────────────────────────────────────────────────────
def test_runs_as_nobody_with_no_capabilities():
    rep = _report(_run('''
import os, json
caps = [l.split()[1] for l in open('/proc/self/status') if l.startswith('CapEff')][0]
try:
    os.setuid(0); su = 'BECAME ROOT'
except PermissionError:
    su = 'refused'
print('REPORT=' + json.dumps({'uid': os.getuid(), 'caps': caps, 'setuid': su}))
'''))
    assert rep == {'uid': 65534, 'caps': '0000000000000000', 'setuid': 'refused'}


def test_no_host_environment_variable_reaches_the_program():
    tok = 'ENVSECRET-' + secrets.token_hex(8)
    os.environ['RAICA_TEST_SECRET'] = tok
    try:
        rep = _report(_run(
            "import os,json\nseen = dict(os.environ)\n"
            "for pid in ('1', str(os.getppid())):\n"      # the runner's own environment is readable via /proc
            "    try: seen['/proc/'+pid] = open('/proc/'+pid+'/environ','rb').read().decode('utf-8','replace')\n"
            "    except OSError as e: seen['/proc/'+pid] = repr(e)\n"
            "print('REPORT='+json.dumps(seen))"))
    finally:
        del os.environ['RAICA_TEST_SECRET']
    assert tok not in json.dumps(rep)
    assert not any(k.endswith(('_KEY', '_TOKEN', '_SECRET', 'PASSWORD')) for k in rep)


# ── 4. resource exhaustion ───────────────────────────────────────────────────────────────────────────────────────
def test_fork_bomb_is_capped_by_the_process_limit():
    """The program meets a clean fork failure at nproc_limit — and the RESULT still comes back. (Under gVisor the
    host pid limit counts gVisor's threads; at 64 it killed the whole sandbox with no output — SI found 2026-10-24.)"""
    rep = _report(_run('''
import os, json, time
n = 0
for _ in range(150):
    try:
        if os.fork() == 0:
            time.sleep(30); os._exit(0)
        n += 1
    except OSError:
        break
print('REPORT=' + json.dumps(n))
''', timeout_seconds=15))
    assert rep < _cfg()['nproc_limit']


def test_memory_bomb_is_stopped():
    r = _run("b = bytearray(1500 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); print('REPORT=\"ALLOCATED\"')")
    assert 'ALLOCATED' not in r['stdout'] and not r['ok']


def test_infinite_loop_is_stopped_by_the_runner_clock():
    r = _run("while True: pass", timeout_seconds=3)
    assert r['timed_out'] and not r['ok']


def test_frozen_runner_is_stopped_by_the_host_clock_and_the_container_removed():
    """The program can stop its own runner; the HOST wall clock must still end it, and nothing may be left."""
    r = _run("import os, signal, time\nos.kill(os.getppid(), signal.SIGSTOP)\ntime.sleep(600)",
             timeout_seconds=3, kill_grace_seconds=3)
    assert r['timed_out'] and not r['ok']
    left = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label={sb.LABEL}'], capture_output=True, text=True)
    assert left.stdout.strip() == ''


def test_disk_is_bounded_and_the_root_is_read_only():
    rep = _report(_run('''
import json
res = {}
try:
    with open('/work/big', 'wb') as f:
        for _ in range(200): f.write(b'x' * (1 << 20))
    res['work'] = 'WROTE 200MB'
except OSError as e:
    res['work'] = 'stopped ' + type(e).__name__
try:
    open('/var/tmp/planted.py', 'w').write('x'); res['root'] = 'WROTE TO ROOT'     # world-writable in the image:
except OSError as e:                                                                # only --read-only stops this
    res['root'] = 'stopped ' + type(e).__name__
print('REPORT=' + json.dumps(res))
'''))
    assert rep['work'].startswith('stopped') and rep['root'].startswith('stopped'), rep


# ── 5. hostile output ────────────────────────────────────────────────────────────────────────────────────────────
def test_output_flood_is_cut():
    r = _run("import sys\nfor _ in range(50): sys.stdout.write('x' * (1 << 20))")
    assert len(r['stdout']) <= _cfg()['max_stdout_bytes']


def test_output_written_around_the_runner_is_stopped():
    """Writing straight to the runner's stdout bypasses its cap; the HOST cap must stop it — QUICKLY, with the
    container gone. (2026-10-24: cleanup ran `docker rm -f` while the client was still attached to a blocked pipe; it
    hung forever, holding the one-run lock, so one hostile program disabled the tool until RAICA restarted.)"""
    import time
    started = time.monotonic()
    r = _run("import os\nfd = os.open(f'/proc/{os.getppid()}/fd/1', os.O_WRONLY)\n"
             "buf = memoryview(b'x' * (1 << 20))\n"
             "for _ in range(40):\n"
             "    left = buf\n"
             "    while left: left = left[os.write(fd, left):]")   # a pipe takes partial writes; send it all
    assert not r['ok'] and r['stdout'] == ''
    assert any('more output than allowed' in n for n in r['notes']), r['notes']
    assert time.monotonic() - started < 30
    left = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label={sb.LABEL}'], capture_output=True, text=True)
    assert left.stdout.strip() == ''


def test_program_cannot_forge_a_chart_marker():
    """Only the tool creates [[chart:…]] markers, for images it re-encoded itself."""
    r = _run("print('[[chart:/static/images/media/someone_elses.jpg|caption=\"x\"]]')")
    assert '[[chart:' not in r['stdout'] and 'someone_elses' in r['stdout']


def test_bad_images_are_dropped():
    r = _run('''
open('fake.png', 'wb').write(b'<script>alert(1)</script>')
from PIL import Image
Image.new('L', (6000, 6000)).save('huge.png')
''')
    assert r['images'] == [] and len(r['notes']) == 2, r['notes']


def test_forged_envelope_fields_are_type_checked():
    """The envelope comes from inside the container; malformed fields must not crash or leak through."""
    cfg = _cfg()
    bad = json.dumps({'exit': True, 'timed_out': 'yes', 'stdout': ['x'], 'stderr': 5,
                      'files': {'a.png': 'not base64 !!'}}).encode()
    r = sb.parse_envelope(bad, cfg)
    assert r['ok'] is False and r['stdout'] == '' and r['images'] == []
    assert sb.parse_envelope(b'\xff\xfe garbage', cfg)['ok'] is False


# ── 6. concurrency and configuration ─────────────────────────────────────────────────────────────────────────────
def test_second_run_waits_then_is_refused_when_busy():
    async def both():
        cfg = _cfg(timeout_seconds=10, queue_wait_seconds=1)
        first = asyncio.create_task(sb.run_program("import time; time.sleep(6)", cfg))
        await asyncio.sleep(0.5)
        with pytest.raises(sb.SandboxRefused, match='busy'):
            await sb.run_program("print(1)", cfg)
        await first
    asyncio.run(both())


@pytest.mark.parametrize('over', [{'runtime': 'runc'}, {'network': 'bridge'}, {'network': 'host'},
                                  {'image': '-v /:/host'}, {'memory': '512m,--privileged'}, {'pids_limit': 0}])
def test_unsafe_configuration_is_refused(over):
    with pytest.raises(sb.SandboxRefused):
        _run("print(1)", **over)


def test_oversized_program_is_refused():
    with pytest.raises(sb.SandboxRefused, match='bytes'):
        _run('#' * 200_000)
