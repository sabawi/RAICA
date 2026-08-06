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
    ("get_stock_and_company_data", {"symbol": "AAPL"}),  # tool reads the `symbol` key (fastapi_server_complete.py:952)
    ("lookup_website",             {"url": "https://example.com"}),
    # Deep Research's academic retrieval path, and the science bot's primary source.
    # Added v1.0.0.235: it was NOT smoke-covered, and that is exactly how it rotted —
    # 4 of its 11 databases were silently returning nothing (PubMed had NEVER worked:
    # `from Bio import Entrez` with biopython missing from requirements.txt entirely).
    # A tool nothing ever invokes cannot be caught failing.
    # Pinned to arxiv+pubmed (2.8s). The full 11-database call takes ~85s, well past
    # PER_CALL_TIMEOUT, and this gate's job is "does the tool crash on invocation",
    # not "are all 11 databases healthy". PubMed is named deliberately: it is the
    # source that had never worked, so this check fails if biopython goes missing again.
    ("published_papers_search",    {"query": "CRISPR gene editing",
                                    "sources": ["arxiv", "pubmed"], "max_results": 3}),
]

# Signatures of a real CODE defect (not ENV). Lowercased match against result + captured stdout.
EXC_SIGNATURES = (
    "is not defined", "traceback (most recent call last)", "nameerror",
    "unboundlocalerror", "attributeerror", "keyerror", "typeerror:", "importerror",
    "modulenotfounderror", "indentationerror", "syntaxerror",
)
# Result-level FAILURE phrases — the tool didn't crash but returned a "nothing / failed" message. These
# are usually ENV (network/rate-limit/bad data) or a bad call, so they WARN (review) — they do NOT hard
# block. Added after a false-pass: a "no data found" stock reply was scored PASS on length alone.
RESULT_FAILURE_PHRASES = (
    "an error occurred", "no data found", "no price data", "possibly delisted",
    "stock data error", "no results found", "couldn't find", "could not find",
)
PER_CALL_TIMEOUT = 30


async def _invoke(name, args):
    # USER tools (published_papers_search, comprehensive_stock_analyzer, …) are
    # registered by an ASYNC loader that importing the module does not run, so
    # available_functions holds only the 7 built-ins until this is awaited — the
    # smoke suite was blind to the other 17 tools, published_papers_search among
    # them. Idempotent, so calling it per invocation is safe.
    if name not in F.tool_manager.available_functions:
        await F.tool_manager._load_user_tools_async()

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
        elif len(res.strip()) < 20 or any(p in res.lower() for p in RESULT_FAILURE_PHRASES):
            warn.append(f"{name}: empty / failure-message result (likely ENV or a bad call)")
            print(f"  ⚠ WARN  {name:<28} empty/failure result (likely ENV) | {res[:90]!r}")
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
