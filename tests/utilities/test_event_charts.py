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
