"""SI-037 — a data file was cut by a limit written for prose, and every derived figure went wrong.

FOUND 2026-08-14 while investigating why `compute` was not being selected. The tool's own log:

    Content too large (20198 chars), truncating to 10000
    2025: tool returned 10,698 chars, 142 lines      <- 2025 has 249 trading days

TWO truncation layers collided. `_extract_data_content` (SI-028 P1) bounds a data file by BYTES
(2 MB) and discloses the outcome honestly — "N lines retrieved (complete)" or "TRUNCATED at N
bytes". The call site then ran `_safe_truncate` on the result UNCONDITIONALLY: a 10,000-character
prose limit that cuts at a SENTENCE boundary. Applied to a CSV that is a rule about nothing, and
it silently discarded the second half of the year.

WHY IT MATTERED, precisely: the true maximum 30Y-10Y spread over 2025-2026 is **0.69, on
09/04/2025** — inside the discarded rows. The production answer reported **0.67**, the maximum of
what survived. The minimum (0.18, on 01/13/2025) was in the retained half and came out right, which
is what made the failure look like a rounding quibble rather than a truncated series. Observation
count was reported as 406 against a true 404.

This is the silent-wrong-number class: no error, no crash, a confident figure computed over half a
table. Nothing downstream could detect it — liveness, provenance and citation checks all pass on a
partial table.

These tests fail on the pre-fix code.
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


import fastapi_server_complete as _srv          # noqa: E402
# Captured at IMPORT time on purpose: another test module swaps srv.AsyncToolManager for a stub
# during execution, so looking it up lazily yields that stub and every assertion here becomes a
# statement about someone else's fake.
_REAL_TOOL_MANAGER = _srv.AsyncToolManager


def _tm():
    return _REAL_TOOL_MANAGER()


class TestDataFilesBypassProseTruncation:

    def test_a_data_result_is_not_prose_truncated(self):
        """THE regression. A data payload well over the article limit must reach the caller whole —
        including its LAST row, which is where a maximum may live."""
        import asyncio
        tm = _tm()
        # Sized well beyond ANY plausible article limit without consulting the new config helper,
        # so this fails on the pre-fix code by actually LOSING THE DATA rather than by tripping
        # over a method that does not exist there yet.
        article_limit = 10000
        rows = "\n".join(
            f"01/{i:02d}/2025,{4.0 + i / 100:.2f},{3.9 + i / 100:.2f},{5.1 + i / 100:.2f}"
            for i in range(1, 1200))
        payload = f"[csv file: 1200 lines retrieved (complete)]\nDate,5Yr,10Yr,30Yr\n{rows}\nLASTROW,9.99,9.99,9.99"
        assert len(payload) > article_limit, "payload must exceed the article limit to discriminate"

        target = _REAL_TOOL_MANAGER

        def fake_extract(self, url, ctype, timeout=45):
            return {"success": True, "title": "csv data file", "author": None, "date": None,
                    "content": payload, "data_label": "csv", "lines": 400, "truncated": False}

        def fake_probe(self, url, timeout=30):
            return "text/csv"

        orig_e, orig_p = target._extract_data_content, target._probe_content_type
        try:
            target._extract_data_content, target._probe_content_type = fake_extract, fake_probe
            # Fresh loop: the global one may already be closed by an earlier test in the suite.
            loop = asyncio.new_event_loop()
            try:
                out = loop.run_until_complete(tm.lookup_website("https://example.org/rates.csv"))
            finally:
                loop.close()
        finally:
            target._extract_data_content, target._probe_content_type = orig_e, orig_p

        assert "LASTROW,9.99" in out, "the final row was discarded — an extremum over this is wrong"
        assert "CONTENT TRUNCATED" not in out

    def test_prose_is_still_truncated(self):
        """The article limit must survive: this fix narrows it to prose, it does not remove it."""
        tm = _tm()
        out = tm._safe_truncate("word " * 5000)
        assert "CONTENT TRUNCATED" in out
        assert len(out) < 25000


class TestLimitsAreConfigured:

    def test_limits_come_from_config_not_constants(self):
        """CLAUDE.md configuration directive: no hardcoded configuration values. The 10,000 that
        caused this was a default buried in a method signature."""
        tm = _tm()
        article, data = tm._lookup_website_limits()
        cfg = yaml.safe_load((ROOT / "config/llm_config.yaml").read_text())["lookup_website"]
        assert article == cfg["max_article_chars"]
        assert data == cfg["max_data_bytes"]

    def test_data_budget_fits_a_year_of_daily_public_data(self):
        """The concrete bar this failed: one year of daily Treasury rates is ~20 KB, and the answer
        must not be computed over part of it."""
        _, data_bytes = _tm()._lookup_website_limits()
        assert data_bytes >= 1_000_000

    def test_limits_are_fail_safe(self):
        """An unreadable config must not make the limits zero — that would truncate everything."""
        original = _srv.config_loader.load_config
        try:
            _srv.config_loader.load_config = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
            article, data = _REAL_TOOL_MANAGER._lookup_website_limits()
        finally:
            _srv.config_loader.load_config = original
        assert article > 0 and data > 0
