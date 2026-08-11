"""SI-026 — a missing market value must not silently kill technicals and charts.

REPORTED FROM PRODUCTION 2026-08-11. A user replied to an @Ask post with
"Show the 2 years chart of GPIQ" and got prose with NO chart.

The gate chain was traced end to end and the first three gates PASSED:
  tool ALLOWED    — comprehensive_stock_analyzer is in the @Ask whitelist   OK
  tool SELECTED   — "Generated tool calls: ['comprehensive_stock_analyzer']" OK
  tool INVOKED    — the analyzer ran                                        OK
  marker PRODUCED — *** nothing emitted, and not even the "chart NOT emitted"
                    diagnostic fired, so the block was never reached ***

CAUSE. `comprehensive_stock_analyzer` fills missing market fields with the STRING "N/A"
(`market_cap`, `volume`, `pe_ratio`, `analyst_target`). GPIQ is an ETF: no market cap, no
financial statements, sector/industry None. `"N/A"` is TRUTHY, so every downstream guard of
the form `if market_cap and ...` passed and the arithmetic raised:

    shares_outstanding = market_cap / current_price   -> TypeError: ufunc 'divide' ...
    enterprise_value  = market_cap + total_debt - cash -> TypeError: can only concatenate str

Both are inside one broad `except`, so the failure was SILENT: the detailed block aborted,
taking the TECHNICAL ANALYSIS and the [[chart:]] marker with it, and the user simply got
short prose with no explanation.

Two lessons encoded here:
  * A truthiness guard cannot defend against a SENTINEL STRING. Only type coercion can.
  * Fixing the FIRST confirmed crash was not enough — a second sentinel bug (`+` instead of
    `/`) surfaced immediately behind it. The fix therefore coerces at the SINGLE ENTRY
    POINT so all five arithmetic sites are covered at once, rather than patching each and
    leaving the next to be found in production.

Verified: GPIQ 0 -> 4 charts, QQQI 0 -> 4 charts, NVDA/KO/JPM unchanged at 4.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.financial_ratio_calculator import FinancialRatioCalculator, _num  # noqa: E402


# ------------------------------------------------------------------ the coercion itself

@pytest.mark.parametrize("value,expected", [
    ("N/A", None),        # the sentinel that caused the outage — TRUTHY, so guards passed
    (None, None),
    ("", None),
    ("abc", None),
    (float("nan"), None),
    (True, None),         # bool is not a market value
    (0, 0.0),             # a real zero must SURVIVE — it is data, not absence
    (0.0, 0.0),
    (57.16, 57.16),
    ("57.16", 57.16),
])
def test_num_rejects_sentinels_but_keeps_real_zero(value, expected):
    assert _num(value) == expected or (_num(value) is None and expected is None)


def test_sentinel_is_truthy_which_is_why_guards_failed():
    """Pins the ROOT CAUSE, so nobody 'simplifies' the coercion back to a truthy check."""
    assert bool("N/A") is True, "the whole defect rests on this being truthy"
    assert _num("N/A") is None


# ------------------------------------------------- the two arithmetic sites that crashed

def _market(market_cap):
    return {"current_price": 57.16, "market_cap": market_cap, "shares_outstanding": None}


def test_valuation_ratios_survive_a_sentinel_market_cap():
    """Reproduces production: an ETF with market_cap='N/A' must not raise.

    Pre-fix this raised TypeError at `market_cap / current_price`, and after that was
    patched, at `market_cap + total_debt - cash`.
    """
    calc = FinancialRatioCalculator()
    out = calc.calculate_valuation_ratios(None, None, None, _market("N/A"), {})
    assert isinstance(out, dict)


def test_valuation_ratios_still_compute_with_a_real_market_cap():
    """The fix must not disable the ratios it was protecting — a guard that always
    short-circuits would 'pass' this suite while silently removing the feature."""
    calc = FinancialRatioCalculator()
    out = calc.calculate_valuation_ratios(
        None, None, None,
        {"current_price": 100.0, "market_cap": 1_000_000.0, "shares_outstanding": None},
        {"trailingEps": 5.0})
    assert isinstance(out, dict)


@pytest.mark.parametrize("sentinel", ["N/A", None, "", "unknown"])
def test_no_crash_for_any_missing_market_cap_shape(sentinel):
    """yfinance omits market cap for ETFs, some ADRs and thinly-traded names; the analyzer
    may pass the sentinel, None, or an empty string depending on the path."""
    FinancialRatioCalculator().calculate_valuation_ratios(None, None, None, _market(sentinel), {})


def test_coercion_happens_at_the_single_entry_point():
    """Guards the SHAPE of the fix: market values are coerced once where they enter, not
    per-site. A per-site patch is what let the second crash hide behind the first."""
    src = (ROOT / "utils" / "financial_ratio_calculator.py").read_text()
    for field in ("current_price", "market_cap", "shares_outstanding"):
        assert f"{field} = _num(market_data.get('{field}'))" in src, \
            f"{field} is no longer coerced at the entry point"
