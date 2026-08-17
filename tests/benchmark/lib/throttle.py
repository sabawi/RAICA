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

# ── two levels, because one number could not do this job ────────────────────────────────
#
# v1.0.0.291 used a SINGLE threshold of 150 and treated crossing it as "this run cannot
# measure". That was wrong in the expensive direction: it produced FOUR false INCONCLUSIVEs
# on runs whose metrics were perfectly healthy. The clearest was v1.0.0.297 at 164 events —
# every one of 33 rows PASS, `citation_count` samples `[14, 14, 14]` against a baseline of
# 13, i.e. ZERO within-arm variance. The guard's own stated premise ("an empty result is
# indistinguishable from a regression") was refuted by the run's own data: nothing was empty.
#
# A throttle COUNT is a proxy for the thing we care about. What actually invalidates a run is
# retrieval COLLAPSING, and that is directly observable in the metrics (see
# scoring.retrieval_collapsed). So the count is now used for what it can support:
#
#   ELEVATED_AT  reporting only. Traffic is heavy; say so. Never degrades a run on its own.
#   CEILING      throttle so extreme the metrics cannot be trusted even if they look fine.
#
# CEILING derivation — honest about a WIDE uncertainty band. Measured:
#     usable results at   ... 164 (all 33 rows PASS), 226
#     no results at all   ... 2,806 (every scenario empty)
# Nothing was measured between 226 and 2,806, so any value in that gap is a judgement call.
# Taking the GEOMETRIC mean of the two boundaries — sqrt(226 * 2806) ~= 796 — puts it at the
# proportional midpoint of what is genuinely unknown, rather than pretending to a precision
# the data does not have. Rounded to 800.
ELEVATED_AT = int(os.getenv("RAICA_BENCH_THROTTLE_ELEVATED", "150"))
CEILING = int(os.getenv("RAICA_BENCH_THROTTLE_CEILING", "800"))

# Back-compat alias: the reporting level is what this name always meant in practice.
THROTTLE_LIMIT = ELEVATED_AT


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
    """(ceiling_exceeded: bool, message: str) — does the COUNT ALONE invalidate the run?

    `[0]` is deliberately NOT "was this run degraded". Degradation is decided by
    `scoring.score_run`, which can also see whether the metrics actually collapsed; throttle
    on its own can only answer the extreme case. A run above ELEVATED_AT but below CEILING
    with healthy metrics is a GOOD run that happened to be noisy, and calling it inconclusive
    was the defect this split fixes.
    """
    limit = CEILING if limit is None else limit
    if events > limit:
        return True, (
            f"{events} rate-limit/captcha responses observed during this run "
            f"(ceiling {limit}). Retrieval was throttled so heavily that no metric can be "
            f"trusted, whatever the values look like."
        )
    if events > ELEVATED_AT:
        return False, (
            f"{events} rate-limit response(s) — ELEVATED (above {ELEVATED_AT}, ceiling "
            f"{limit}). Not degrading on its own: the metrics decide."
        )
    return False, f"{events} rate-limit response(s) — within normal background (limit {ELEVATED_AT})."


def is_elevated(events):
    """Traffic heavy enough that a metric COLLAPSE is plausibly the environment, not the code."""
    return events > ELEVATED_AT
