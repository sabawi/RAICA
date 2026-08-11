"""SI-029 — a feature flag must not depend on how many times it has been called.

FOUND ON PRODUCTION 2026-08-11 while checking whether Deep Research could reach the dataset
tools. Same process, no arguments, four consecutive calls:

    call 1: False    call 2: True    call 3: True    call 4: True

CAUSE — an ordering error inside the function. `data_charts_enabled()` read the
RAICA_DATA_CHARTS_ENABLED override BEFORE calling `data_charts_cfg()` — but it is
`config_loader.load_config()`, invoked inside that helper, which POPULATES os.environ from .env.
Proven on prod:

    before anything        : None
    after importing loader : None
    after load_config()    : 'true'      <- the loader populates the environment

So the FIRST caller saw None, fell through to the config file's `false`, and got the wrong
answer; every later caller got `true`.

IMPACT — `DeepResearchEngine._allowed_sources` adds `search_datasets`/`compare_datasets` only
`if _data_charts_enabled()`. Whether Deep Research could reach the dataset tools therefore
depended on whether that property happened to be the FIRST caller in the process: feature
availability decided by import order.

TWO WRONG DIAGNOSES were recorded before this one — "lazy config cache" (refuted: load_config()
returned a stable `enabled: False` on every call) and "load_dotenv timing" (refuted: the var was
still None immediately after load_dotenv()). The fix rests on the third, which was verified by
watching os.environ change across the loader call.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_first_call_equals_later_calls_in_a_fresh_process():
    """THE regression test. Must run in a FRESH interpreter — the defect exists only on the
    first call, so any in-process test that has already touched the config cannot see it.
    """
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from datasources import data_charts_enabled\n"
        "print([data_charts_enabled() for _ in range(4)])\n" % str(ROOT)
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(ROOT), timeout=180)
    line = [l for l in out.stdout.splitlines() if l.startswith("[")]
    assert line, f"probe produced no verdict: {out.stdout[-300:]} {out.stderr[-300:]}"
    vals = eval(line[-1])
    assert len(set(vals)) == 1, (
        f"data_charts_enabled() is call-order dependent: {vals} — the first caller in a process "
        "gets a different answer, so feature availability depends on import order")


def test_config_is_loaded_before_the_env_override_is_read():
    """Pins the FIX's shape, not just its effect.

    Reading os.getenv first is the bug; the config load must come first because it is what makes
    the override visible. A future 'tidy-up' that reorders these lines reintroduces SI-029.
    """
    src = (ROOT / "datasources" / "__init__.py").read_text()
    body = src[src.index("def data_charts_enabled("):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    cfg_at = body.index("data_charts_cfg()")
    env_at = body.index('os.getenv("RAICA_DATA_CHARTS_ENABLED")')
    assert cfg_at < env_at, "the config must be loaded BEFORE the env override is read (SI-029)"


def test_env_override_still_wins_when_set():
    """The fix must not break the override's precedence — it exists so prod can toggle the
    feature without editing a git-tracked file."""
    for val, expected in (("true", True), ("false", False)):
        code = (
            "import sys, os; sys.path.insert(0, %r)\n"
            "os.environ['RAICA_DATA_CHARTS_ENABLED'] = %r\n"
            "from datasources import data_charts_enabled\n"
            "print('RESULT', data_charts_enabled())\n" % (str(ROOT), val)
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=str(ROOT), timeout=180)
        got = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
        assert got, f"no verdict for {val}: {out.stderr[-200:]}"
        assert got[-1].endswith(str(expected)), f"override {val!r} -> {got[-1]}"
