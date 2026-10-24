"""py_sandbox.check_host_memory — the sandbox must not start a program the server cannot afford (2026-10-24 audit:
production ~1 GB available with swap in use; a program at its limit costs limit + ~65 MB). No container is started:
every path here refuses before `docker run`, and `asyncio.create_subprocess_exec` is replaced by a stand-in that
fails the test if reached."""
import asyncio

import pytest

from utils import py_sandbox

CFG = {'memory': '512m', 'min_host_available_mb': 400, 'max_concurrent': 1, 'queue_wait_seconds': 1}


def test_refuses_when_limit_plus_margin_is_not_available():
    with pytest.raises(py_sandbox.SandboxRefused, match='short of memory'):
        py_sandbox.check_host_memory(CFG, available_mb=900)        # 512 + 400 = 912 needed


def test_starts_when_enough_remains():
    py_sandbox.check_host_memory(CFG, available_mb=1000)


@pytest.mark.parametrize('memory,mb', [('512m', 512), ('1g', 1024), ('262144k', 256), (str(256 * 2**20), 256)])
def test_reads_docker_memory_notation(memory, mb):
    assert py_sandbox._memory_mb(memory) == mb


def test_unreadable_limit_refuses():
    with pytest.raises(py_sandbox.SandboxRefused):
        py_sandbox.check_host_memory({**CFG, 'memory': 'lots'}, available_mb=10_000)


def test_refusal_releases_the_lock(monkeypatch):
    """The check runs AFTER the one-program lock is taken. If a refusal kept the lock, the tool would answer
    'another program is running' to everyone until RAICA restarted. Two refusals in a row must both say
    'short of memory', never 'another program is running'."""
    cfg = {**py_sandbox.load_settings(), 'max_concurrent': 1, 'queue_wait_seconds': 1}
    monkeypatch.setattr(py_sandbox, '_host_available_mb', lambda: 1.0)

    async def no_docker(*a, **k):
        raise AssertionError('docker run reached: the memory check did not refuse first')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_docker)

    async def twice():
        msgs = []
        for _ in range(2):
            with pytest.raises(py_sandbox.SandboxRefused) as e:
                await py_sandbox.run_program('print(1)', cfg)
            msgs.append(str(e.value))
        return msgs
    msgs = asyncio.run(twice())
    assert all('short of memory' in m for m in msgs), msgs
