"""Transient-failure retry for finance data fetches (yfinance / Yahoo Finance).

Yahoo's endpoints intermittently return transient errors for a SINGLE request while other
tickers succeed in the same run — e.g. the quoteSummary/.info endpoint returning
``{'code': 'Internal Server Error', 'description': 'Server caught an exception'}`` or a
JSON-parse failure. Without a retry, one such blip fails the whole ticker's analysis
(no fundamentals, DCF, technicals, or chart — see v1.0.0.172 AVGO incident).

`fetch_with_retry` wraps any fetch callable in a bounded retry with linear backoff. It is
GENERAL transient handling — no error-string matching, no per-ticker special-casing — and
every attempt is logged so failures are transparent (visible recovery). On exhausting all
attempts it re-raises the LAST exception so the caller can surface a clear error rather than
guessing/faking data. This is the shared primitive for hardening all finance fetches.
"""
import time
import logging

logger = logging.getLogger(__name__)


def fetch_with_retry(fn, *, attempts: int = 3, backoff_seconds: float = 0.8,
                     label: str = "fetch", log: "logging.Logger" = None):
    """Call ``fn()`` and return its result; retry on ANY exception up to ``attempts`` total
    tries with linear backoff (``backoff_seconds`` × attempt#). Re-raises the last exception
    if every attempt fails. Each attempt is logged for transparency.

    Args:
        fn: zero-arg callable performing the fetch (raises on transient failure).
        attempts: total tries (>=1). 1 disables retry.
        backoff_seconds: base linear backoff between tries (0 = no sleep).
        label: short description for log lines (e.g. "AVGO yfinance quote fetch").
        log: logger to use (defaults to this module's logger).
    """
    log = log or logger
    attempts = max(1, int(attempts))
    backoff_seconds = max(0.0, float(backoff_seconds))
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            result = fn()
            if i > 1:
                log.info(f"{label}: succeeded on attempt {i}/{attempts} after transient failure(s)")
            return result
        except Exception as e:  # noqa: BLE001 — transient upstream; bounded retry then re-raise
            last_exc = e
            if i < attempts:
                wait = backoff_seconds * i
                log.warning(f"{label}: attempt {i}/{attempts} failed ({str(e)[:140]}) — retrying in {wait:.1f}s")
                if wait > 0:
                    time.sleep(wait)
            else:
                log.error(f"{label}: all {attempts} attempts failed — {str(e)[:200]}")
    raise last_exc
