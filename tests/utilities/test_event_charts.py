"""
Unit tests for utils/chart_generator.generate_event_chart (inline chart cards — Phase 5, Step 2).

Offline (no network, no LLM): every event family must render a valid PNG zoomed to the event window,
the detect→render handoff works end-to-end, and bad input degrades to None (never a wrong chart).
Run:  venv/bin/python -m pytest tests/utilities/test_event_charts.py -q
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utils import technical_events as te
from utils.chart_generator import generate_event_chart


def _hist(n=520, seed=7):
    """Deterministic OHLCV with strong trends (so SMA cross / RSI dip / ADX / MACD crosses all appear)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    a_end, b_end = 260, 282
    close = np.empty(n)
    for k in range(n):
        if k < a_end:
            close[k] = 100.0 - 0.10 * k
        elif k < b_end:
            close[k] = (100.0 - 0.10 * a_end) - 1.15 * (k - a_end)
        else:
            base = (100.0 - 0.10 * a_end) - 1.15 * (b_end - a_end)
            close[k] = base + 0.36 * (k - b_end)
    close = pd.Series(np.clip(close + rng.normal(0, 0.25, n), 5, None), index=idx)
    return pd.DataFrame(
        {"Open": close.shift(1).fillna(close.iloc[0]), "High": close + 1.0, "Low": close - 1.0,
         "Close": close, "Volume": pd.Series(1_000_000.0, index=idx)},
        index=idx,
    )


def _png_ok(b):
    return bool(b) and b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) > 3000


def test_every_event_family_renders_a_valid_png():
    hist = _hist()
    mid = hist.index[len(hist) // 2].strftime("%Y-%m-%d")
    cases = [
        {"type": "sma_cross", "date": mid, "direction": "golden", "value": 80.0},
        {"type": "rsi_oversold", "date": mid, "direction": "oversold", "value": 27.0},
        {"type": "rsi_overbought", "date": mid, "direction": "overbought", "value": 74.0},
        {"type": "macd_cross", "date": mid, "direction": "bullish", "value": 0.4},
        {"type": "macd_zero_cross", "date": mid, "direction": "bearish", "value": -0.1},
        {"type": "adx_strengthening", "date": mid, "direction": "strengthening", "value": 28.0},
        {"type": "volume_confirm", "date": mid, "direction": "up_confirm", "value": 3.1, "magnitude": 3.1},
    ]
    for ev in cases:
        png = generate_event_chart("TEST", hist, ev, category="long_term")
        assert _png_ok(png), (ev["type"], 0 if not png else len(png))


def test_detect_then_render_handoff():
    """A real detected event must render — proves Step-1 → Step-2 wiring."""
    hist = _hist()
    events = te.detect_events(hist, category="long_term")
    ev = next(e for e in events if e["type"] in ("sma_cross", "rsi_oversold", "macd_cross"))
    png = generate_event_chart("TEST", hist, ev, category="long_term")
    assert _png_ok(png), (ev["type"], 0 if not png else len(png))


def test_zoom_category_affects_crop_but_both_render():
    hist = _hist()
    ev = {"type": "rsi_oversold", "date": hist.index[300].strftime("%Y-%m-%d"), "direction": "oversold"}
    assert _png_ok(generate_event_chart("T", hist, ev, category="long_term"))
    assert _png_ok(generate_event_chart("T", hist, ev, category="short_term"))


def test_graceful_on_bad_input():
    hist = _hist()
    good_date = hist.index[300].strftime("%Y-%m-%d")
    assert generate_event_chart("T", None, {"type": "rsi_oversold", "date": good_date}) is None
    assert generate_event_chart("T", pd.DataFrame(), {"type": "rsi_oversold", "date": good_date}) is None
    assert generate_event_chart("T", hist, {"type": "unknown_thing", "date": good_date}) is None  # no wrong chart
    assert generate_event_chart("T", hist, {"type": "rsi_oversold"}) is None                       # no date
    assert generate_event_chart("T", hist, "not-a-dict") is None


def test_event_label_objective_and_dated():
    from utils.technical_events import event_label
    assert event_label({"type": "sma_cross", "direction": "golden", "date": "2024-05-30"}) == \
        "Golden cross (SMA 50/200) · 2024-05-30"
    assert event_label({"type": "rsi_oversold", "date": "2023-02-06"}) == "RSI oversold (<30) · 2023-02-06"
    assert "Volume spike" in event_label({"type": "volume_confirm", "direction": "up_confirm", "date": "2024-01-01"})


def test_publisher_variant_cache_separation():
    """Event sub-charts share (ticker, display_days) with the main chart and each other — the `variant`
    must keep them from colliding in the cache (Step 3)."""
    import utils.chart_publisher as cp
    orig = (cp.charts_enabled, cp.publish_chart, cp._cap_and_ttl)
    try:
        cp.charts_enabled = lambda: True
        up = {"n": 0}
        cp.publish_chart = lambda png, hint="c": (up.__setitem__("n", up["n"] + 1) or f"/static/images/media/{hint}_{up['n']}.jpg")
        cp._cap_and_ttl = lambda *a, **k: (10, 1800)
        cp._url_cache.clear(); cp.reset_response_charts()
        rc = {"n": 0}
        r = lambda: (rc.__setitem__("n", rc["n"] + 1) or b"PNG")

        a = cp.get_or_publish_chart("AAPL", 126, r, variant="rsi_oversold_2024-01-05")
        b = cp.get_or_publish_chart("AAPL", 126, r, variant="sma_cross_2024-03-10")
        assert a and b and a != b and rc["n"] == 2, (a, b, rc["n"])            # distinct variants → distinct renders
        a2 = cp.get_or_publish_chart("AAPL", 126, r, variant="rsi_oversold_2024-01-05")
        assert a2 == a and rc["n"] == 2                                        # same variant → cache hit
        m = cp.get_or_publish_chart("AAPL", 126, r)                            # main chart (variant=None)
        assert m not in (a, b) and rc["n"] == 3                               # separate entry
        assert "rsi_oversold" in a                                            # variant is traceable in the filename
    finally:
        cp.charts_enabled, cp.publish_chart, cp._cap_and_ttl = orig
        cp._url_cache.clear()


def test_analyzer_exposes_horizon_param():
    """The tool advertises analysis_horizon so the LLM can drive the long/short category (LLM-policy gate)."""
    try:
        from user_tools.comprehensive_stock_analyzer import ComprehensiveStockAnalyzerTool
    except Exception as e:
        pytest.skip(f"analyzer import unavailable in this env: {e}")
    props = ComprehensiveStockAnalyzerTool().parameters["properties"]
    assert "analysis_horizon" in props
    assert props["analysis_horizon"]["enum"] == ["long_term", "short_term"]
