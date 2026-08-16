"""Detect external rate-limiting during a benchmark run (SI-055).

WHY THIS EXISTS
---------------
The Tier-1 suite runs S1 x3, S3 x3 and S4 x3 over 8 tickers across several search engines.
That volume trips the engines' own rate limiters, the searches then return nothing, and the
empty results were scored as CODE regressions. Measured on 2026-08-16:

    window        429 / captcha   what ran
    23:00-23:30         0         6 E2E runs — all correct
    00:00-00:30     1,015         benchmark
    00:30-01:00       976         benchmark

Same build, same code: **zero throttling while it worked, ~2,600 events while it
"regressed"**. The suite reported `SUITE: REGRESSION` with `citation_count 0 (base 13)`,
`dr_completed False`, `answer_chars 0` — and tagged nearly all of them CODE.

**The benchmark was failing itself.** That is a measurement-integrity defect in both
directions: it blocks a good deploy, and it teaches the reader to discount the suite, which
is how a REAL regression eventually gets waved through.

WHAT THIS DOES
--------------
Counts throttle responses in the server log slice covering the run. It does NOT try to
decide which metric was affected — under heavy throttling the run simply cannot discriminate
code from environment, so the honest outcome is INCONCLUSIVE rather than a guessed verdict.
"""
import os
import re

# HTTP 429, and the interstitials engines serve instead of a 429 (Google's /sorry/ captcha,
# Cloudflare's challenge). Matched against the SERVER's own log of outbound responses.
_PATTERNS = (
    re.compile(r"\b429\b"),
    re.compile(r"/sorry/"),
    re.compile(r"unusual traffic|captcha|rate.?limit", re.I),
)

# DERIVED from the measured distribution across every archived run (2026-08-16), not chosen:
#
#     normal runs          2, 5, 5, 10, 15, 17
#     heavy-search runs    55, 92, 99          <- degraded, but still produced usable results
#     the failed Tier-1    2,806               <- every scenario returned empty
#
# 150 sits above the heaviest run that still measured correctly and an order of magnitude
# below the one that could not measure at all. Set deliberately HIGH: over-triggering would
# make the suite useless by calling healthy runs inconclusive, which is its own way of
# teaching people to ignore it. The count is ALWAYS reported regardless of the threshold, so
# a run drifting toward the limit is visible before it crosses.
THROTTLE_LIMIT = int(os.getenv("RAICA_BENCH_THROTTLE_LIMIT", "150"))


def log_position(log_path):
    """Byte offset to start counting from — captured BEFORE the run."""
    try:
        return os.path.getsize(log_path)
    except OSError:
        return 0


def count_since(log_path, start_offset):
    """Throttle events written to the log since `start_offset`."""
    try:
        with open(log_path, "r", errors="replace") as fh:
            fh.seek(start_offset)
            body = fh.read()
    except OSError:
        return 0
    return sum(1 for line in body.splitlines()
               if any(p.search(line) for p in _PATTERNS))


def assess(events, limit=None):
    """(degraded: bool, message: str) for a run that observed `events` throttle responses."""
    limit = THROTTLE_LIMIT if limit is None else limit
    if events > limit:
        return True, (
            f"{events} rate-limit/captcha responses observed during this run "
            f"(threshold {limit}). Search retrieval was materially degraded, so this run "
            f"CANNOT distinguish a code regression from the environment."
        )
    return False, f"{events} rate-limit response(s) — within normal background (limit {limit})."
