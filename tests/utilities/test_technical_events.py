"""
Deterministic accuracy tests for utils/technical_events.py (inline chart cards — Phase 5).

The accuracy claim: a detected event's date IS the real crossing date. These tests prove it by
independently recomputing the crossings (same pandas-ta indicators, crossing logic re-derived here)
and asserting detect_events() matches — plus determinism, display-window filtering, config wiring,
and graceful empties. No network, no LLM. Run:  venv/bin/python -m pytest tests/utilities/test_technical_events.py -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pandas_ta_classic as pta
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utils import technical_events as te


def _make_history(n=520, seed=7):
    """Deterministic OHLCV that CONTAINS a golden cross, an RSI<30 dip, and MACD crosses.
    Three clean phases: gentle decline → sharp crash (RSI oversold) → strong recovery (golden cross).
    Jitter is per-bar (NOT cumulative) so it wiggles MACD without drifting the trend that defines events."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    a_end, b_end = 260, 282
    close = np.empty(n)
    for k in range(n):
        if k < a_end:
            close[k] = 100.0 - 0.10 * k                              # decline 100 → ~74
        elif k < b_end:
            close[k] = (100.0 - 0.10 * a_end) - 1.15 * (k - a_end)   # crash ~74 → ~49 (RSI < 30)
        else:
            base = (100.0 - 0.10 * a_end) - 1.15 * (b_end - a_end)
            close[k] = base + 0.36 * (k - b_end)                     # recovery → ~135 (golden cross)
    close = pd.Series(np.clip(close + rng.normal(0, 0.25, n), 5, None), index=idx)
    return pd.DataFrame(
        {"Open": close, "High": close + 1.0, "Low": close - 1.0, "Close": close,
         "Volume": pd.Series(1_000_000.0, index=idx)},
        index=idx,
    )


def _independent_sign_flip_up(diff):
    diff = diff.dropna(); prev = diff.shift(1)
    return [d.strftime("%Y-%m-%d") for d in diff.index[((prev <= 0) & (diff > 0)).fillna(False)]]


def _independent_cross_down(s, level):
    s = s.dropna(); prev = s.shift(1)
    return [d.strftime("%Y-%m-%d") for d in s.index[((prev > level) & (s <= level)).fillna(False)]]


def _within_window(dates, index, disp):
    start = index[max(0, len(index) - disp)]
    return [d for d in dates if pd.Timestamp(d) >= start]


def test_sma_golden_cross_detected_on_exact_date():
    hist = _make_history()
    disp = te.trend_category("long_term")["display_sessions"]
    fast = pta.sma(hist["Close"].astype(float), length=50)
    slow = pta.sma(hist["Close"].astype(float), length=200)
    expected = _within_window(_independent_sign_flip_up(fast - slow), hist.index, disp)
    assert len(expected) >= 1, "test fixture must contain a golden cross"

    ev = te.detect_events(hist, category="long_term")
    got = sorted(e["date"] for e in ev if e["type"] == "sma_cross" and e["direction"] == "golden")
    assert got == sorted(expected), (got, expected)


def test_rsi_oversold_detected_on_exact_date():
    hist = _make_history()
    disp = te.trend_category("long_term")["display_sessions"]
    rsi = pta.rsi(hist["Close"].astype(float), length=14)
    expected = _within_window(_independent_cross_down(rsi, 30), hist.index, disp)
    assert len(expected) >= 1, "test fixture must push RSI below 30"

    ev = te.detect_events(hist, category="long_term")
    got = sorted(e["date"] for e in ev if e["type"] == "rsi_oversold")
    assert got == sorted(expected), (got, expected)


def test_volume_spike_only_confirms_when_near_another_event():
    hist = _make_history()
    base = te.detect_events(hist, category="long_term")
    assert not any(e["type"] == "volume_confirm" for e in base)  # flat volume → no spikes yet

    # Place a spike ON an existing event date → must be detected as a confirmation there.
    anchor = next(e["date"] for e in base if e["type"] in ("rsi_oversold", "macd_cross", "sma_cross"))
    h2 = hist.copy()
    h2.loc[pd.Timestamp(anchor), "Volume"] = 6_000_000.0
    ev2 = te.detect_events(h2, category="long_term")
    confirms = [e for e in ev2 if e["type"] == "volume_confirm"]
    assert any(e["date"] == anchor for e in confirms), (anchor, [e["date"] for e in confirms])

    # NEGATIVE: a lone spike in a DEAD-FLAT, event-free series → nothing nearby to confirm.
    idx = pd.date_range("2023-01-02", periods=300, freq="B")
    flat_close = pd.Series(100.0, index=idx)
    flat = pd.DataFrame({"Open": flat_close, "High": flat_close, "Low": flat_close,
                         "Close": flat_close, "Volume": pd.Series(1_000_000.0, index=idx)}, index=idx)
    flat.iloc[150, flat.columns.get_loc("Volume")] = 6_000_000.0
    ev_flat = te.detect_events(flat, category="long_term")
    assert not any(e["type"] == "volume_confirm" for e in ev_flat)


def test_deterministic_same_input_same_events():
    hist = _make_history()
    assert te.detect_events(hist, category="long_term") == te.detect_events(hist, category="long_term")


def test_display_window_filters_old_events():
    hist = _make_history()
    long_ev = te.detect_events(hist, category="long_term")    # 504-session window → sees the whole series
    short_ev = te.detect_events(hist, category="short_term")  # 126-session window → only the recent tail
    start = hist.index[max(0, len(hist) - te.trend_category("short_term")["display_sessions"])]
    assert all(pd.Timestamp(e["date"]) >= start for e in short_ev)
    assert len(short_ev) <= len(long_ev)


def test_config_boundaries_are_adjustable_and_loaded():
    # These come from config/llm_config.yaml charts.trend_categories — proving the one-edit knob is wired.
    lt = te.trend_category("long_term")
    st = te.trend_category("short_term")
    assert lt["display_sessions"] == 504 and lt["event_zoom_sessions"] == 25
    assert st["display_sessions"] == 126 and st["event_zoom_sessions"] == 12
    # unknown name → configured default
    assert te.trend_category("nonsense")["name"] in ("short_term", "long_term")


def test_event_window_crop_bounds():
    hist = _make_history()
    z = te.trend_category("long_term")["event_zoom_sessions"]
    mid = hist.index[300]
    lo, hi = te.event_window(hist.index, mid, category="long_term")
    lo_pos, hi_pos = hist.index.get_loc(lo), hist.index.get_loc(hi)
    assert hi_pos - lo_pos == 2 * z            # symmetric crop, full width away from the edges
    assert lo_pos <= 300 <= hi_pos


def test_graceful_on_empty_and_short():
    assert te.detect_events(None) == []
    assert te.detect_events(pd.DataFrame()) == []
    short = _make_history(n=20)
    assert te.detect_events(short) == []       # < 40 sessions → no detection


def test_select_featured_events_dedup_and_priority():
    """One card per indicator family (no duplicate MACD), structural SMA guaranteed, rest by recency."""
    from utils.technical_events import select_featured_events
    events = sorted([
        {"type": "macd_zero_cross", "date": "2026-06-10"},
        {"type": "sma_cross",       "date": "2026-01-15"},   # oldest, but structural → must be featured
        {"type": "adx_weakening",   "date": "2026-06-02"},
        {"type": "macd_cross",      "date": "2026-07-14"},   # same family as zero_cross, more recent
        {"type": "rsi_oversold",    "date": "2026-05-01"},
    ], key=lambda e: e["date"])
    sel = select_featured_events(events, 3, ["sma"])
    types = [e["type"] for e in sel]
    assert len(sel) == 3
    assert sum(1 for t in types if t.startswith("macd")) == 1   # MACD family de-duped
    assert "macd_cross" in types                                # kept the more-recent MACD
    assert "sma_cross" in types                                 # structural guaranteed despite being oldest
    assert [e["date"] for e in sel] == sorted(e["date"] for e in sel)   # chronological


def test_select_featured_events_cap_priority_and_empty():
    from utils.technical_events import select_featured_events
    assert select_featured_events([], 3, ["sma"]) == []
    assert select_featured_events([{"type": "macd_cross", "date": "2026-07-14"}], 0, []) == []
    evs = sorted([{"type": "macd_cross", "date": "2026-07-14"},
                  {"type": "rsi_oversold", "date": "2026-06-01"},
                  {"type": "adx_weakening", "date": "2026-05-01"}], key=lambda e: e["date"])
    assert len(select_featured_events(evs, 2, [])) == 2          # capped at max_n
    assert len(select_featured_events(evs, 5, [])) == 3          # only 3 families available
    # priority family absent → just recency, no crash
    assert len(select_featured_events(evs, 3, ["sma"])) == 3


def test_missing_config_fails_fast(monkeypatch):
    """RAICA config directive: no hardcoded fallbacks — a missing charts.* config must FAIL FAST,
    never silently use defaults. detect_events() still degrades gracefully (logs + []) so the
    analyzer never crashes."""
    monkeypatch.setattr(te, "_charts_cfg", lambda: {})           # simulate missing charts config
    with pytest.raises(te.ChartConfigError):
        te.trend_category("long_term")
    with pytest.raises(te.ChartConfigError):
        te.detection_cfg()
    # analyzer-facing entry point never raises — degrades to no events
    assert te.detect_events(_make_history()) == []
