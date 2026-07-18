"""
Event-anchored technical events (inline chart cards — Phase 5).
See docs/DESIGN_event_anchored_subcharts.md (in the NewX repo).

Detects DATED technical events (crossings/threshold/spike occurrences) from a daily OHLCV history,
deterministically — pure math over the indicator SERIES (sign-flips, threshold crossings, volume
z-spikes), never a buy/sell judgment. Each event carries the EXACT trading date it occurred, so the
same event can drive BOTH a zoomed sub-chart's crop window AND what the LLM narrates — text and chart
stay bound to the one ground-truth occurrence (the accuracy principle in §2 of the design).

CLAUDE.md compliance:
  • LLM-policy gate (§A): detection is deterministic data — it decides no meaning/intent. The LLM
    later interprets, selects by trend, and places. No hardcoded keyword→signal routing here.
  • This module mirrors ``technical_indicators``'s "OBJECTIVE readings, NOT a buy/sell signal"
    discipline — it reports OBJECTIVE *dated states*, nothing more.

All thresholds and the long/short-term category boundaries live in ``config/llm_config.yaml``
(``charts.detection`` and ``charts.trend_categories``) — tweak them there, no code change.
Never raises: missing/short/garbled history → [].
"""
import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import pandas_ta_classic as pta

logger = logging.getLogger(__name__)


class ChartConfigError(RuntimeError):
    """Required ``charts.*`` config is missing/incomplete. Per RAICA's ZERO-TOLERANCE config directive
    (CLAUDE.md) we FAIL FAST here — config/llm_config.yaml is the single source of truth and we NEVER
    silently substitute hardcoded values. ``detect_events()`` catches this, logs it, and returns [] so
    the analyzer degrades to 'no charts' instead of crashing."""


# All values live in config/llm_config.yaml (charts.trend_categories / charts.detection). These are
# only the REQUIRED-KEY manifests used to fail fast on a missing/partial config — NOT default values.
_CATEGORY_KEYS = ("display_sessions", "fetch_sessions", "prior_sessions", "event_zoom_sessions")
_DETECTION_KEYS = ("rsi_length", "rsi_oversold", "rsi_overbought", "adx_length", "adx_strong",
                   "adx_weak", "sma_fast", "sma_slow", "volume_avg_length", "volume_spike_mult",
                   "volume_confirm_window")


def _charts_cfg() -> Dict[str, Any]:
    from utils.config_loader import config_loader
    return (config_loader.load_config().get("charts", {}) or {})


def _require_keys(d: Any, keys, ctx: str) -> Dict[str, Any]:
    if not isinstance(d, dict):
        raise ChartConfigError(f"missing config: charts.{ctx} (config/llm_config.yaml)")
    missing = [k for k in keys if d.get(k) is None]
    if missing:
        raise ChartConfigError(f"missing config keys: charts.{ctx}{{{', '.join(missing)}}} (config/llm_config.yaml)")
    return d


def default_category() -> str:
    """Fallback category for an ambiguous horizon — config/llm_config.yaml charts.trend_categories.default."""
    tc = _charts_cfg().get("trend_categories")
    if not isinstance(tc, dict) or tc.get("default") is None:
        raise ChartConfigError("missing config: charts.trend_categories.default (config/llm_config.yaml)")
    return str(tc["default"]).strip().lower()


def trend_category(name: Optional[str] = None) -> Dict[str, Any]:
    """Resolved boundaries for a trend category ('long_term'|'short_term'), STRICTLY from config.
    Unknown/empty name → the configured default. Fails fast if the config or its keys are missing.
    Returns the category dict plus a 'name' key."""
    tc = _charts_cfg().get("trend_categories")
    if not isinstance(tc, dict) or not tc:
        raise ChartConfigError("missing config: charts.trend_categories (config/llm_config.yaml)")
    name = (name or "").strip().lower()
    if name not in ("long_term", "short_term"):
        name = default_category()
    resolved = dict(_require_keys(tc.get(name), _CATEGORY_KEYS, f"trend_categories.{name}."))
    resolved["name"] = name
    return resolved


def detection_cfg() -> Dict[str, Any]:
    """Detection thresholds — STRICTLY from config/llm_config.yaml charts.detection; fails fast if missing."""
    return dict(_require_keys(_charts_cfg().get("detection"), _DETECTION_KEYS, "detection."))


# ── deterministic detection primitives ──────────────────────────────────────
def _cross_dates(s: pd.Series, level: float, up: bool) -> List[pd.Timestamp]:
    """Dates where ``s`` crosses ``level``. up=True: prev<level and now>=level. up=False: prev>level and now<=level."""
    s = s.dropna()
    if len(s) < 2:
        return []
    prev = s.shift(1)
    mask = ((prev < level) & (s >= level)) if up else ((prev > level) & (s <= level))
    return list(s.index[mask.fillna(False)])


def _sign_flip_dates(diff: pd.Series) -> List:
    """(date, 'up'|'down') where ``diff`` changes sign. up: prev<=0 and now>0; down: prev>=0 and now<0."""
    diff = diff.dropna()
    if len(diff) < 2:
        return []
    prev = diff.shift(1)
    up = (prev <= 0) & (diff > 0)
    down = (prev >= 0) & (diff < 0)
    out = [(d, "up") for d in diff.index[up.fillna(False)]] + \
          [(d, "down") for d in diff.index[down.fillna(False)]]
    return sorted(out, key=lambda x: x[0])


def _normalize(history: pd.DataFrame) -> Optional[pd.DataFrame]:
    if history is None or getattr(history, "empty", True):
        return None
    df = history.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "close" not in df.columns:
        return None
    try:
        df.index = pd.to_datetime(df.index)
    except Exception:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df if len(df) >= 40 else None


def event_window(df_index, date, category: Optional[str] = None):
    """(start_ts, end_ts) crop bounds for a sub-chart: event ± category.event_zoom_sessions, clamped to data.
    Positions by NEAREST index so a non-trading date still resolves. Returns (None, None) on empty index."""
    idx = pd.DatetimeIndex(pd.to_datetime(df_index))
    if len(idx) == 0:
        return None, None
    z = int(trend_category(category)["event_zoom_sessions"])
    pos = int(idx.get_indexer([pd.Timestamp(date)], method="nearest")[0])
    lo = max(0, pos - z)
    hi = min(len(idx) - 1, pos + z)
    return idx[lo], idx[hi]


def detect_events(history: pd.DataFrame, category: Optional[str] = None,
                  detection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Deterministic dated technical events within the category's display window.

    Each event: {type, date 'YYYY-MM-DD', value, direction, magnitude, timeframe_nature, category}.
    Indicators are computed over the FULL series (so they're warmed) then events are filtered to the
    visible display window (the last ``display_sessions`` bars). Never raises → [] on any failure.
    """
    try:
        cat = trend_category(category)
        det = detection or detection_cfg()
        df = _normalize(history)
        if df is None:
            return []
        close = df["close"].astype(float)
        high = df["high"].astype(float) if "high" in df.columns else None
        low = df["low"].astype(float) if "low" in df.columns else None
        volume = df["volume"].astype(float) if "volume" in df.columns else None

        disp = int(cat["display_sessions"])
        window_start = df.index[max(0, len(df) - disp)]
        pos = {ts: i for i, ts in enumerate(df.index)}
        events: List[Dict[str, Any]] = []

        def _add(etype, date, value, direction, nature, magnitude=None):
            ts = pd.Timestamp(date)
            if ts < window_start:
                return
            events.append({
                "type": etype,
                "date": ts.strftime("%Y-%m-%d"),
                "_ts": ts,
                "value": None if value is None else round(float(value), 4),
                "direction": direction,
                "magnitude": None if magnitude is None else round(float(magnitude), 4),
                "timeframe_nature": nature,
                "category": cat["name"],
            })

        # 1) RSI oversold / overbought crossings (tactical)
        try:
            rsi = pta.rsi(close, length=int(det["rsi_length"]))
            for d in _cross_dates(rsi, det["rsi_oversold"], up=False):
                _add("rsi_oversold", d, rsi.loc[d], "oversold", "tactical")
            for d in _cross_dates(rsi, det["rsi_overbought"], up=True):
                _add("rsi_overbought", d, rsi.loc[d], "overbought", "tactical")
        except Exception:
            pass

        # 2) MACD signal-line + zero-line crossings (tactical)
        try:
            macd = pta.macd(close)
            if macd is not None and not macd.empty:
                macd_line, signal = macd.iloc[:, 0], macd.iloc[:, 2]
                for d, dr in _sign_flip_dates(macd_line - signal):
                    _add("macd_cross", d, macd_line.loc[d], "bullish" if dr == "up" else "bearish", "tactical")
                for d, dr in _sign_flip_dates(macd_line):
                    _add("macd_zero_cross", d, macd_line.loc[d], "bullish" if dr == "up" else "bearish", "tactical")
        except Exception:
            pass

        # 3) ADX strengthening / weakening (structural)
        try:
            if high is not None and low is not None:
                adx_df = pta.adx(high, low, close, length=int(det["adx_length"]))
                if adx_df is not None and not adx_df.empty:
                    adx = adx_df.iloc[:, 0]
                    for d in _cross_dates(adx, det["adx_strong"], up=True):
                        _add("adx_strengthening", d, adx.loc[d], "strengthening", "structural")
                    for d in _cross_dates(adx, det["adx_weak"], up=False):
                        _add("adx_weakening", d, adx.loc[d], "weakening", "structural")
        except Exception:
            pass

        # 4) SMA fast/slow golden / death cross (structural)
        try:
            fast = pta.sma(close, length=int(det["sma_fast"]))
            slow = pta.sma(close, length=int(det["sma_slow"]))
            for d, dr in _sign_flip_dates(fast - slow):
                _add("sma_cross", d, close.loc[d], "golden" if dr == "up" else "death", "structural")
        except Exception:
            pass

        # 5) Volume-spike confirmation — a spike within ±window of any #1-4 event (confirms_signal)
        try:
            if volume is not None:
                vavg = volume.rolling(int(det["volume_avg_length"]), min_periods=5).mean()
                ratio = (volume / vavg)
                spikes = list(ratio.index[(ratio >= float(det["volume_spike_mult"])).fillna(False)])
                win = int(det["volume_confirm_window"])
                other_pos = [pos[e["_ts"]] for e in events if e["_ts"] in pos]  # already-added #1-4 events
                ret = close.pct_change()
                for d in spikes:
                    if d < window_start or d not in pos:
                        continue
                    di = pos[d]
                    if not any(abs(op - di) <= win for op in other_pos):
                        continue
                    dr = "up_confirm" if float(ret.get(d, 0.0) or 0.0) >= 0 else "down_confirm"
                    _add("volume_confirm", d, float(ratio.loc[d]), dr, "confirms_signal",
                         magnitude=float(ratio.loc[d]))
        except Exception:
            pass

        events.sort(key=lambda e: e["_ts"])
        for e in events:
            e.pop("_ts", None)
        return events
    except Exception as e:  # noqa: BLE001 — an events failure must never break the analyzer
        logger.info(f"detect_events error: {e}")
        return []
