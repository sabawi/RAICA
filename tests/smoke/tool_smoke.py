#!/usr/bin/env python3
"""Pre-deploy TOOL SMOKE TEST — actually INVOKES each core read/search tool through the real code
path and asserts it does not crash with a code error.

Why this exists: a missing per-function `import re` (v1.0.0.142) made `_is_specific_article_url`
raise NameError, which `search_web` SWALLOWED into a generic "An error occurred…" string. ALL web
search was dead for ~6 days and every offline gate stayed green, because nothing ever *called* the
tool. Tier-0 is fixture/offline; it cannot see "the tool crashes when invoked." This closes that gap.

Design (CODE vs ENV — never a flaky alarm):
  • HARD FAIL (exit 1) only on a Python-exception signature — a raised exception, or a signature
    (`NameError`, `is not defined`, `Traceback`, `UnboundLocalError`, …) found in the result OR in the
    tool's captured stdout (this is how the swallowed `search_web` NameError is caught deterministically).
  • WARN (exit 0) if a tool returns empty / a generic non-exception error — that is usually ENV
    (network/egress/403), not our code, and must not block a deploy on its own.
  • PASS if the tool returns real content.

Fast (~30s), no LLM. Run before EVERY push/deploy:  python tests/smoke/tool_smoke.py
"""
import os
import sys
import io
import json
import asyncio
import contextlib

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

import fastapi_server_complete as F  # noqa: E402  (creates module-level `tool_manager`)

# Representative, side-effect-free calls. Email + trivial tools are intentionally excluded.
CHECKS = [
    ("search_web",                 {"query": "latest world news today"}),
    ("wikipedia_query",            {"query": "Python (programming language)"}),
    ("get_news_summaries",         {"query": "technology"}),
    ("get_stock_and_company_data", {"ticker": "AAPL"}),
    ("lookup_website",             {"url": "https://example.com"}),
]

# Signatures of a real CODE defect (not ENV). Lowercased match against result + captured stdout.
EXC_SIGNATURES = (
    "is not defined", "traceback (most recent call last)", "nameerror",
    "unboundlocalerror", "attributeerror", "keyerror", "typeerror:", "importerror",
    "modulenotfounderror", "indentationerror", "syntaxerror",
)
PER_CALL_TIMEOUT = 30


async def _invoke(name, args):
    fn = F.tool_manager.available_functions[name]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = await asyncio.wait_for(fn(json.dumps(args)), timeout=PER_CALL_TIMEOUT)
    return (res or ""), buf.getvalue()


def main():
    print("=" * 74)
    print("  RAICA TOOL SMOKE — invoking core tools through the real code path")
    print("=" * 74)
    code_fail, warn = [], []
    for name, args in CHECKS:
        try:
            res, captured = asyncio.run(_invoke(name, args))
        except Exception as e:  # noqa: BLE001 — a raised exception IS a code failure
            code_fail.append(f"{name}: RAISED {type(e).__name__}: {e}")
            print(f"  ✗ CODE  {name:<28} RAISED {type(e).__name__}: {str(e)[:80]}")
            continue
        hay = (res + "\n" + captured).lower()
        sig = next((s for s in EXC_SIGNATURES if s in hay), None)
        if sig:
            code_fail.append(f"{name}: exception signature {sig!r} (swallowed) — real code bug")
            print(f"  ✗ CODE  {name:<28} exception signature {sig!r} in output (swallowed error)")
        elif len(res.strip()) < 20 or "an error occurred" in res.lower():
            warn.append(f"{name}: empty / generic error (likely ENV: network/egress)")
            print(f"  ⚠ WARN  {name:<28} empty/generic result (likely ENV) | {res[:90]!r}")
        else:
            print(f"  ✓ PASS  {name:<28} {len(res)} chars of real content")
    print("-" * 74)
    if code_fail:
        print(f"  SMOKE FAILED — {len(code_fail)} CODE defect(s); a tool crashes on invocation:")
        for f in code_fail:
            print(f"     - {f}")
        if warn:
            print(f"  (also {len(warn)} ENV warning(s): {', '.join(w.split(':')[0] for w in warn)})")
        return 1
    if warn:
        print(f"  SMOKE PASSED (no CODE defects) — {len(warn)} ENV warning(s), review before deploy:")
        for w in warn:
            print(f"     - {w}")
        return 0
    print("  SMOKE PASSED — all core tools return real content, no crashes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
