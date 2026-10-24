"""Planted-defect run for the sandbox red-team suite: each protection is removed IN MEMORY (monkeypatch — no file on
disk is edited) and the test that relies on it must go RED. A test that stays green with its protection gone proves
nothing. Real containers; takes ~2 minutes.  Run: ./venv/bin/python tests/integration/run_pysandbox_plants.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.dirname(__file__))

from utils import py_sandbox as sb                     # noqa: E402
import test_pysandbox_redteam as t                     # noqa: E402

REAL_ARGV, REAL_CHECK = sb.docker_argv, sb.check_settings


def argv_edit(fn):
    def patched(cfg, name):
        return fn(REAL_ARGV(cfg, name))
    return patched


def drop(argv, flag, has_value=True):
    out, i = [], 0
    while i < len(argv):
        if argv[i] == flag:
            i += 2 if has_value else 1
            continue
        out.append(argv[i]); i += 1
    return out


def drop_value(argv, flag, startswith):
    out, i = [], 0
    while i < len(argv):
        if argv[i] == flag and argv[i + 1].startswith(startswith):
            i += 2
            continue
        out.append(argv[i]); i += 1
    return out


def before_image(extra):
    def f(argv):
        k = argv.index(t._cfg()['image'])
        return argv[:k] + extra + argv[k:]
    return f


def replace(flag, value):
    def f(argv):
        a = list(argv); a[a.index(flag) + 1] = value; return a
    return f


PLANTS = [
    ('runc instead of gVisor', t.test_runs_under_gvisor_not_the_host_kernel,
     {'docker_argv': argv_edit(replace('--runtime', 'runc')), 'check_settings': lambda c: None}),
    ('host /tmp mounted', t.test_no_host_file_is_visible,
     {'docker_argv': argv_edit(before_image(['-v', '/tmp:/hosttmp:ro']))}),
    ('docker socket mounted', t.test_docker_socket_is_absent,
     {'docker_argv': argv_edit(before_image(['-v', '/var/run/docker.sock:/var/run/docker.sock']))}),
    ('bridge network', t.test_no_network_internet_metadata_or_host,
     {'docker_argv': argv_edit(replace('--network', 'bridge')), 'check_settings': lambda c: None}),
    ('root user, caps kept', t.test_runs_as_nobody_with_no_capabilities,
     {'docker_argv': argv_edit(lambda a: drop(replace('--user', '0')(a), '--cap-drop'))}),
    ('host env passed', t.test_no_host_environment_variable_reaches_the_program,
     {'docker_argv': argv_edit(before_image(['-e', 'RAICA_TEST_SECRET']))}),
    ('no nproc limit', t.test_fork_bomb_is_capped_by_the_process_limit,
     {'docker_argv': argv_edit(lambda a: drop_value(a, '--ulimit', 'nproc='))}),
    ('4 GB memory', t.test_memory_bomb_is_stopped,
     {'docker_argv': argv_edit(lambda a: replace('--memory-swap', '4g')(replace('--memory', '4g')(a)))}),
    ('writable root', t.test_disk_is_bounded_and_the_root_is_read_only,
     {'docker_argv': argv_edit(lambda a: drop(a, '--read-only', has_value=False))}),
    ('no container removal', t.test_frozen_runner_is_stopped_by_the_host_clock_and_the_container_removed,
     {'docker_argv': argv_edit(lambda a: drop(a, '--rm', has_value=False)), '_docker_quiet': None}),
    ('envelope read uncapped', t.test_output_written_around_the_runner_is_stopped,
     {'_read_capped': None}),
    ('markers not disabled', t.test_program_cannot_forge_a_chart_marker, {'_disable_markers': lambda s: s}),
    ('images not re-encoded', t.test_bad_images_are_dropped, {'_reencode_png': lambda raw, cfg: raw}),
    ('no concurrency limit', t.test_second_run_waits_then_is_refused_when_busy, {'_get_semaphore': None}),
    ('config not checked', lambda: t.test_unsafe_configuration_is_refused({'runtime': 'runc'}),
     {'check_settings': lambda c: None}),
    ('program size not checked', t.test_oversized_program_is_refused, {'_program_cap_off': None}),
]


def apply(patches):
    import asyncio
    saved = {}
    for name, val in patches.items():
        if name == '_docker_quiet':                       # removal disabled: rm -f becomes a no-op
            saved[name] = sb._docker_quiet

            async def noop(*a):
                return None
            sb._docker_quiet = noop
        elif name == '_read_capped':
            saved[name] = sb._read_capped

            async def uncapped(stream, cap):
                return await stream.read(), False
            sb._read_capped = uncapped
        elif name == '_get_semaphore':
            saved[name] = sb._get_semaphore
            sb._get_semaphore = lambda size: asyncio.Semaphore(100)
        elif name == '_program_cap_off':
            saved['_cfg'] = t._cfg
            real = t._cfg
            t._cfg = lambda **o: {**real(**o), 'max_program_bytes': 10 ** 9}
        else:
            saved[name] = getattr(sb, name)
            setattr(sb, name, val)
    return saved


def restore(saved):
    for name, val in saved.items():
        if name == '_cfg':
            t._cfg = val
        else:
            setattr(sb, name, val)


def main():
    import asyncio
    results = []
    for label, test, patches in PLANTS:
        saved = apply(patches)
        try:
            test()
            outcome = 'STAYED GREEN  <-- this test does not guard its protection'
        except BaseException as e:  # noqa: BLE001 — pytest.fail raises a BaseException; any failure is red
            if isinstance(e, KeyboardInterrupt):
                raise
            outcome = f'RED ({type(e).__name__})'
        finally:
            restore(saved)
            asyncio.run(sb.reap_leftovers(t._cfg()))
        results.append((label, outcome))
        print(f'{label:28s} {outcome}', flush=True)
    assert sb.docker_argv is REAL_ARGV and sb.check_settings is REAL_CHECK
    green = [l for l, o in results if o.startswith('STAYED')]
    print(f'\n{len(results) - len(green)}/{len(results)} plants turned their test red')
    sys.exit(1 if green else 0)


if __name__ == '__main__':
    main()
