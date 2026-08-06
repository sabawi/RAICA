#!/usr/bin/env python3
"""
Version-consistency acceptance test (Tier-0 deterministic gate).

Locks in the single-source-of-truth versioning contract so a bump to version.py can never
silently drift from the surfaces that display it:

  - version.py VERSION is the AUTHORITY, and its derived accessors agree with it;
  - README.md agrees on EVERY surface it shows the version on (title, badge, release
    link, About heading, Version History) — not just the badge;
  - config/logging_config.json agrees (it cannot import version.py, so it is written
    by utils/version_sync.py and rots silently);
  - /health serves the IMPORTED __version__ symbol rather than a literal, so the
    endpoint cannot drift by construction.

Why this exists: RAICA had no version test, and both non-importing surfaces had rotted
badly — README sat at 1.0.0.189 (44 builds stale) and logging_config.json at 1.0.3.122
(a different version series entirely) while version.py was at 1.0.0.233. NewX's
newx/test_version.py had been catching exactly this class for it; RAICA had no equivalent.

Deliberately OFFLINE and boot-free: it never imports fastapi_server_complete (which loads
models and would make a fast pre-commit gate slow and flaky). The /health contract is
asserted statically instead — see test_health_endpoint_cannot_drift.

Run:  python tests/integration/test_version_sync.py
      make benchmark            # runs it as part of Tier 0
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
sys.path.insert(0, REPO_ROOT)

import version as V  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


def test_version_format():
    print("version.py is a well-formed single source of truth:")
    check("VERSION is MAJOR.MINOR.PATCH.BUILD",
          bool(re.fullmatch(r'\d+\.\d+\.\d+\.\d+', V.VERSION)), V.VERSION)
    check("__version__ == VERSION", V.__version__ == V.VERSION, V.__version__)
    check("get_version_info()['version'] == VERSION",
          V.get_version_info().get('version') == V.VERSION)
    check("get_release_string() contains VERSION", V.VERSION in V.get_release_string())
    check("VERSION_TUPLE matches VERSION",
          list(V.VERSION_TUPLE) == [int(p) for p in V.VERSION.split('.')], V.VERSION_TUPLE)


def test_readme_matches_on_every_surface():
    """The README claims the current version in several places; ALL must agree.

    Checking only the badge is what let the title, About heading and Version History
    line rot together — they drift as a group because they are updated by hand.

    Scope note: this asserts the surfaces that CLAIM TO BE CURRENT, not every version
    string in the file. RAICA was forked from Agentic-RAG-System, so the README
    legitimately cites UPSTREAM releases ("Inherited from v1.0.3.123", "v1.0.3.43
    introduces …"). Those are historical facts and must NOT be rewritten by a bump —
    a test that flagged them would be wrong, and would be silenced rather than fixed.
    """
    print("README.md agrees on every surface that claims the current version:")
    readme = _read('README.md')

    badge = re.search(r'version-([0-9]+(?:\.[0-9]+)+)-blue', readme)
    check("README has a version badge", badge is not None)
    check("README badge == VERSION", bool(badge) and badge.group(1) == V.VERSION,
          badge.group(1) if badge else None)

    tag = re.search(r'releases/tag/v([0-9]+(?:\.[0-9]+)+)', readme)
    check("README release link == VERSION", bool(tag) and tag.group(1) == V.VERSION,
          tag.group(1) if tag else 'no release link found')

    # Any version stated right next to the RAICA name is a claim about OUR version
    # (title, About heading, Version History line). "Agentic-RAG-System v…" does not
    # contain "RAICA", so upstream citations are excluded by construction.
    claimed = set(re.findall(r'RAICA[^\n]{0,40}?v(\d+\.\d+\.\d+\.\d+)', readme))
    check("README states at least one 'RAICA vX' version", bool(claimed))
    stale = sorted(found for found in claimed if found != V.VERSION)
    check("every 'RAICA vX' claim == VERSION", not stale,
          f"found {stale}, expected {V.VERSION}")


def test_logging_config_matches():
    """config/logging_config.json cannot import version.py, so it rots silently."""
    print("config/logging_config.json agrees:")
    path = os.path.join(REPO_ROOT, 'config', 'logging_config.json')
    check("logging_config.json exists", os.path.exists(path), path)
    if not os.path.exists(path):
        return
    try:
        config = json.loads(_read('config', 'logging_config.json'))
    except ValueError as exc:
        check("logging_config.json is valid JSON", False, str(exc)[:60])
        return
    check("logging_config.json is valid JSON", True)
    check("logging_config.json version == VERSION",
          config.get('version') == V.VERSION,
          f"{config.get('version')} != {V.VERSION} (run utils/version_sync.py)")


def test_version_sync_utility_agrees():
    """utils/version_sync.py is the writer for non-importing files; its own
    consistency check must agree that everything is in sync."""
    print("utils/version_sync.py verify_version_consistency():")
    try:
        from utils.version_sync import verify_version_consistency
    except Exception as exc:  # import error is itself a failure worth surfacing
        check("verify_version_consistency() importable", False, str(exc)[:70])
        return
    check("verify_version_consistency() importable", True)
    result = verify_version_consistency()
    check("reports version == VERSION", result.get('version') == V.VERSION)
    check("reports consistent", result.get('consistent') is True,
          '; '.join(result.get('issues') or [])[:110])


def test_health_endpoint_cannot_drift():
    """/health must serve the IMPORTED symbol, never a hardcoded literal.

    Asserted statically so this gate stays offline and fast — importing
    fastapi_server_complete boots the whole server stack.
    """
    print("/health serves the imported version (cannot drift):")
    server = _read('fastapi_server_complete.py')
    check("server imports __version__ from version",
          re.search(r'^from version import .*__version__', server, re.M) is not None)
    check('/health returns "version": __version__',
          re.search(r'"version":\s*__version__', server) is not None)
    # A literal version string in the server would silently outrank the import.
    literals = sorted(set(re.findall(r'"version":\s*"(\d+\.\d+\.\d+\.\d+)"', server)))
    check("no hardcoded version literal served by the API", not literals, literals)


if __name__ == '__main__':
    test_version_format()
    test_readme_matches_on_every_surface()
    test_logging_config_matches()
    test_version_sync_utility_agrees()
    test_health_endpoint_cannot_drift()
    print("=" * 62)
    print(f"Results: {PASS}/{PASS + FAIL} passed ({FAIL} failed)")
    if FAIL:
        print("\nA version surface has drifted from version.py.")
        print("Fix the listed file(s), or run: python utils/version_sync.py")
    sys.exit(1 if FAIL else 0)
