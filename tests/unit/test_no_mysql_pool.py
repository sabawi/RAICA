"""SI-003 — the vestigial MySQL pool is gone, and with it the boot footgun.

WHAT WAS THERE. `fastapi_server_complete` carried a full aiomysql connection pool — `init_db_pool`,
`close_db_pool`, `get_db_connection`, `execute_query` — that nothing ever used: `execute_query()`
had **0 callers**. All RAICA storage is SQLite + FAISS.

TWO REAL COSTS, not just tidiness:
  1. `ServerConfig` raised `RuntimeError` at import time unless `DB_PASSWORD` was set, so a fresh
     install refused to start without a secret for a database that does not exist.
  2. `/health` reported `"database": "unavailable"`, which reads as an outage to anyone watching.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_server_imports_without_DB_PASSWORD():
    """THE FOOTGUN, isolated. On pre-fix code this exits without IMPORT_OK, raising
    'DB_PASSWORD environment variable is required. Set it before starting the server.'

    Clearing os.environ is NOT enough and the first version of this test passed for that
    reason: `load_dotenv()` runs at import and repopulates DB_PASSWORD from the local .env,
    so the footgun was hidden by a dev machine that happens to have one. This injects every
    .env value EXCEPT the DB_* keys and stubs dotenv, which is precisely a fresh install.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("DB_")}
    dotenv = REPO / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                if not key.startswith("DB_"):
                    env.setdefault(key, val.strip().strip('"').strip("'"))
    assert not any(k.startswith("DB_") for k in env), "DB_* leaked into the fresh-install env"

    code = (
        "import sys, types\n"
        "stub = types.ModuleType('dotenv')\n"
        "stub.load_dotenv = lambda *a, **k: None\n"
        "stub.find_dotenv = lambda *a, **k: ''\n"
        "sys.modules['dotenv'] = stub\n"
        "import fastapi_server_complete; print('IMPORT_OK')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=600)
    assert "IMPORT_OK" in proc.stdout, (
        f"server will not import without DB_PASSWORD — the fresh-install footgun is still "
        f"present.\nstderr tail:\n{proc.stderr[-1200:]}")


def test_no_mysql_symbols_remain_in_the_server():
    """A half-removal is worse than none: a leftover reference to a deleted global is a
    NameError waiting for the first request. (One did survive the first edit — `/metrics`
    still referenced `db_stats` after its definition was cut.)"""
    src = (REPO / "fastapi_server_complete.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for symbol in ("aiomysql", "db_pool", "db_stats", "init_db_pool",
                   "close_db_pool", "get_db_connection", "execute_query"):
        assert symbol not in code, f"{symbol!r} still referenced in server code"


def test_health_no_longer_reports_a_phantom_database():
    """`services` must not carry a database key at all — RAICA has no SQL database, and
    reporting one as 'unavailable' forever is a false alarm."""
    src = (REPO / "fastapi_server_complete.py").read_text()
    assert 'services = {"cache": "memory", "ollama": "unknown"}' in src
    assert '"database": "unavailable"' not in src


def test_requirements_and_env_example_no_longer_advertise_mysql():
    """A dependency nothing imports is install weight and an audit surface; a DB_* block in
    .env.example tells the next installer to invent a password for nothing."""
    assert "aiomysql" not in (REPO / "requirements.txt").read_text()
    env_example = (REPO / ".env.example").read_text()
    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_POOL_SIZE", "DB_MAX_OVERFLOW"):
        assert key not in env_example, f"{key} still advertised in .env.example"
