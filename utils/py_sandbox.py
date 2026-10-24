"""Run a model-written Python program in a throwaway gVisor container (docs/DESIGN_run_python_analysis.md).

THREAT MODEL: every program is hostile. Anyone who can post @Ask — or whose text reaches the model through a
fetched page — can make the model write anything. The RAICA process itself is root-equivalent on its host (its user
is in the docker group), so the program must never reach the Docker socket, a host file, a host variable or the
network.

The boundary is the CONTAINER, assembled here with a fixed argument list (no shell, program on stdin only):
  gVisor runtime · --network none · no -v mounts · --read-only root · tmpfs /work and /tmp (noexec) · nobody user ·
  --cap-drop ALL · no-new-privileges · process (nproc) / host-thread (pids) / file / memory / CPU limits · wall-clock kill · --rm + label for reaping.
The two settings without which the rest is worthless — the gVisor runtime and the empty network — are checked on
EVERY call against REQUIRED below, and a configuration that differs makes this module refuse to run anything.
Those two values are security invariants, not tunables; every limit is read from config.

Everything the container sends back is untrusted: the in-container runner is visible to the program and can be
imitated. So the envelope is size-capped while it is read, every field is type-checked, text is truncated, chart
markers in it are disabled, and images are decoded and re-encoded from their pixels before anyone sees them.
"""
import asyncio
import base64
import binascii
import io
import json
import logging
import os
import uuid

import yaml

logger = logging.getLogger(__name__)

# Security invariants (see module docstring). A config that says otherwise is refused, never obeyed.
REQUIRED = {'runtime': 'runsc', 'network': 'none'}
LABEL = 'raica.pysandbox=1'
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'llm_config.yaml')
_NUMERIC = ('pids_limit', 'nproc_limit', 'nofile_limit', 'timeout_seconds', 'kill_grace_seconds', 'max_concurrent', 'queue_wait_seconds',
            'max_program_bytes', 'max_stdout_bytes', 'max_stderr_bytes', 'max_images', 'max_image_bytes',
            'max_image_pixels', 'max_envelope_bytes')

_semaphore = None
_semaphore_key = None


class SandboxRefused(RuntimeError):
    """The sandbox will not run this program (unsafe configuration, oversized program, busy, disabled)."""


def load_settings(path=_CONFIG_PATH):
    with open(path) as f:
        return (yaml.safe_load(f).get('user_tools') or {})['run_python_analysis']


def check_settings(cfg):
    """Refuse any configuration that weakens the boundary. Called on every run, not once at start-up."""
    for key, want in REQUIRED.items():
        if str(cfg.get(key)) != want:
            raise SandboxRefused(f"sandbox refused: {key} must be '{want}', configuration says '{cfg.get(key)}'")
    for key in _NUMERIC:
        if not isinstance(cfg.get(key), int) or cfg[key] <= 0:
            raise SandboxRefused(f"sandbox refused: {key} must be a positive integer")
    for key in ('image', 'user', 'memory', 'cpus', 'tmpfs_size'):
        val = str(cfg.get(key) or '')
        if not val or val.startswith('-') or any(c.isspace() for c in val) or ',' in val:
            raise SandboxRefused(f"sandbox refused: {key} is missing or malformed")


def docker_argv(cfg, name):
    """The complete `docker run` command. Fixed list, no shell; nothing from the host is mounted or passed."""
    check_settings(cfg)
    tmpfs = f"size={cfg['tmpfs_size']},noexec,nosuid,nodev,uid=65534,gid=65534"
    return [
        'docker', 'run', '--rm', '-i', '--name', name, '--label', LABEL,
        '--runtime', cfg['runtime'], '--network', cfg['network'],
        '--read-only', '--tmpfs', f'/work:{tmpfs}', '--tmpfs', f'/tmp:{tmpfs}',
        '--user', str(cfg['user']), '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--pids-limit', str(cfg['pids_limit']),
        '--ulimit', f"nproc={cfg['nproc_limit']}:{cfg['nproc_limit']}",
        '--ulimit', f"nofile={cfg['nofile_limit']}:{cfg['nofile_limit']}",
        '--memory', str(cfg['memory']),
        '--memory-swap', str(cfg['memory']), '--cpus', str(cfg['cpus']),
        '--ipc', 'none', '--hostname', 'sandbox', '--log-driver', 'none',
        cfg['image'],
        str(cfg['timeout_seconds']), str(cfg['max_stdout_bytes']), str(cfg['max_stderr_bytes']),
        str(cfg['max_images']), str(cfg['max_image_bytes']),
    ]


def _disable_markers(text):
    """Program output may not carry RAICA markers ([[chart:…]] and the like): only the tool creates those."""
    return text.replace('[[', '[​[')


def _reencode_png(raw, cfg):
    """Decode an untrusted image and re-encode it from its pixels. None if it is not a sane PNG."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format != 'PNG' or probe.width * probe.height > cfg['max_image_pixels']:
                return None
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            out = io.BytesIO()
            img.convert('RGB').save(out, format='PNG', optimize=True)
            return out.getvalue()
    except Exception:  # noqa: BLE001 — any decoder complaint means "not a usable image", reported by the caller
        return None


def parse_envelope(raw, cfg):
    """Turn the container's bytes into a checked result. Never raises on hostile input; reports what it dropped."""
    notes = []
    try:
        env = json.loads(raw.decode('utf-8'))
        if not isinstance(env, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return {'ok': False, 'exit': None, 'timed_out': False, 'stdout': '', 'stderr': '', 'images': [],
                'notes': ['the program produced no readable result (output was not the expected envelope)']}
    stdout = env.get('stdout') if isinstance(env.get('stdout'), str) else ''
    stderr = env.get('stderr') if isinstance(env.get('stderr'), str) else ''
    if len(stdout) > cfg['max_stdout_bytes']:
        stdout = stdout[:cfg['max_stdout_bytes']]
        notes.append(f"output cut at {cfg['max_stdout_bytes']} characters")
    stderr = stderr[-cfg['max_stderr_bytes']:]
    exit_code = env.get('exit') if isinstance(env.get('exit'), int) and not isinstance(env.get('exit'), bool) else None
    images = []
    files = env.get('files') if isinstance(env.get('files'), dict) else {}
    for fname, b64 in list(files.items())[:cfg['max_images']]:
        if not isinstance(b64, str) or len(b64) > cfg['max_image_bytes'] * 4 // 3 + 4:
            notes.append(f"image {str(fname)[:40]!r} dropped (too large)")
            continue
        try:
            jpg = _reencode_png(base64.b64decode(b64, validate=True), cfg)
        except (binascii.Error, ValueError):
            jpg = None
        if jpg is None:
            notes.append(f"image {str(fname)[:40]!r} dropped (not a valid PNG within the size limit)")
        else:
            images.append(jpg)
    timed_out = env.get('timed_out') is True
    return {'ok': exit_code == 0 and not timed_out, 'exit': exit_code, 'timed_out': timed_out,
            'stdout': _disable_markers(stdout), 'stderr': _disable_markers(stderr), 'images': images,
            'notes': notes}


async def _docker_quiet(*args):
    p = await asyncio.create_subprocess_exec('docker', *args, stdout=asyncio.subprocess.DEVNULL,
                                             stderr=asyncio.subprocess.DEVNULL)
    await p.wait()


async def reap_leftovers(cfg=None):
    """Remove any sandbox container still present (a timeout, a RAICA restart mid-run). Safe to call any time, and
    bounded: a `docker` call that hangs is logged and abandoned, never waited on forever."""
    cfg = cfg if cfg is not None else load_settings()
    limit = cfg['kill_grace_seconds'] * 2
    p = await asyncio.create_subprocess_exec('docker', 'ps', '-aq', '--filter', f'label={LABEL}',
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        p.kill()
        logger.error("🧪 py-sandbox: listing leftover containers hung for %ss", limit)
        return -1
    ids = out.decode().split()
    if ids:
        try:
            await asyncio.wait_for(_docker_quiet('rm', '-f', *ids), timeout=limit)
            logger.warning("🧪 py-sandbox: reaped %d leftover container(s)", len(ids))
        except asyncio.TimeoutError:
            logger.error("🧪 py-sandbox: could not remove %d leftover container(s) within %ss", len(ids), limit)
            return -1
    return len(ids)


def _get_semaphore(size):
    """One limiter per event loop and size (a semaphore must not be shared across loops)."""
    global _semaphore, _semaphore_key
    key = (id(asyncio.get_running_loop()), size)
    if _semaphore is None or _semaphore_key != key:
        _semaphore, _semaphore_key = asyncio.Semaphore(size), key
    return _semaphore


async def _read_capped(stream, cap):
    buf = bytearray()
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf), False
        buf += chunk
        if len(buf) > cap:
            return bytes(buf[:cap]), True


async def run_program(program, cfg=None):
    """Run `program` (str) in a fresh sandbox. Returns the checked result dict; raises SandboxRefused."""
    cfg = cfg if cfg is not None else load_settings()
    check_settings(cfg)
    data = program.encode('utf-8')
    if len(data) > cfg['max_program_bytes']:
        raise SandboxRefused(f"sandbox refused: program is {len(data)} bytes (limit {cfg['max_program_bytes']})")
    sem = _get_semaphore(cfg['max_concurrent'])
    try:
        await asyncio.wait_for(sem.acquire(), timeout=cfg['queue_wait_seconds'])
    except asyncio.TimeoutError:
        raise SandboxRefused("sandbox busy: another program is running; try again shortly") from None
    name = f"raica-pysbx-{uuid.uuid4().hex[:16]}"
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_argv(cfg, name), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        proc.stdin.write(data)
        await proc.stdin.drain()
        proc.stdin.close()
        try:
            raw, overflow = await asyncio.wait_for(
                _read_capped(proc.stdout, cfg['max_envelope_bytes']),
                timeout=cfg['timeout_seconds'] + cfg['kill_grace_seconds'])
        except asyncio.TimeoutError:
            logger.warning("🧪 py-sandbox: %s exceeded the wall clock — killed", name)
            return {'ok': False, 'exit': None, 'timed_out': True, 'stdout': '', 'stderr': '', 'images': [],
                    'notes': [f"the program was stopped after {cfg['timeout_seconds']} s"]}
        if overflow:
            logger.warning("🧪 py-sandbox: %s exceeded the output limit — killed", name)
            return {'ok': False, 'exit': None, 'timed_out': False, 'stdout': '', 'stderr': '', 'images': [],
                    'notes': ['the program produced more output than allowed and was stopped']}
        try:
            await asyncio.wait_for(proc.wait(), timeout=cfg['kill_grace_seconds'])
        except asyncio.TimeoutError:
            pass                               # the finally block removes it
        result = parse_envelope(raw, cfg)
        logger.info("🧪 py-sandbox: %s exit=%s timed_out=%s stdout=%d chars images=%d notes=%s", name,
                    result['exit'], result['timed_out'], len(result['stdout']), len(result['images']),
                    result['notes'])
        return result
    finally:
        if proc is not None and proc.returncode is None:
            # ORDER MATTERS (found 2026-10-24): once we stop reading, a program still writing blocks on a full pipe,
            # and `docker rm -f` hangs for as long as the attached client holds that stream. So detach the client
            # FIRST, then remove the container — and bound every step, so cleanup can never outlive the clock.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(_docker_quiet('rm', '-f', name), timeout=cfg['kill_grace_seconds'] * 2)
            except asyncio.TimeoutError:
                logger.error("🧪 py-sandbox: could not remove %s within %ss — left for reap_leftovers()", name,
                             cfg['kill_grace_seconds'] * 2)
            try:
                await asyncio.wait_for(proc.wait(), timeout=cfg['kill_grace_seconds'])
            except asyncio.TimeoutError:
                logger.error("🧪 py-sandbox: docker client for %s did not exit after kill", name)
        sem.release()
