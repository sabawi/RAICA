"""
Stock chart generation for inline chart cards (v1.0.0.170).

Renders the enriched "main" per-stock chart — candlesticks + SMA 50/200 + volume overlay, with RSI /
MACD / ADX in shorter stacked panels, h+v gridlines on ticks, real date axis — from ~2y of daily OHLCV
via pandas-ta-classic, displaying the query window (default 6 mo) so the moving averages are already
warmed up across the whole visible range (no edge artifacts). Returns PNG bytes.

Thread-safe: uses the matplotlib OO API (Figure + Agg canvas), NOT pyplot global state, because the
stock analyzer runs inside a thread pool. Never raises — returns None on any failure so a chart problem
can never break the analysis.
"""
import io
import logging
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta_classic as pta
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

logger = logging.getLogger(__name__)

_BG = "#0f141c"; _AX = "#151b26"; _GRID = "#2a3340"; _TXT = "#e1e7f0"; _SP = "#2d3748"
_UP = "#26a69a"; _DN = "#ef5350"


def _style(ax):
    ax.set_facecolor(_AX)
    ax.grid(True, which='major', axis='both', color=_GRID, ls=':', alpha=.7)
    ax.tick_params(colors=_TXT, labelsize=8)
    for s in ax.spines.values():
        s.set_color(_SP)


def generate_main_chart(ticker: str, history: pd.DataFrame, display_days: int = 126) -> Optional[bytes]:
    """Return PNG bytes for the enriched main chart, or None if it can't be built.

    `history` is a yfinance-style daily OHLCV DataFrame (DatetimeIndex, columns Open/High/Low/Close/Volume);
    pass ≥ ~1.5y so the 200-day SMA is warmed up across the `display_days` window.
    """
    try:
        if history is None or getattr(history, "empty", True) or len(history) < 60:
            return None
        df = history.copy()
        df.columns = [str(c).capitalize() for c in df.columns]  # normalize (open->Open, etc.)
        need = {"Open", "High", "Low", "Close"}
        if not need.issubset(set(df.columns)):
            return None
        c, h, l = df["Close"], df["High"], df["Low"]
        df["SMA50"] = pta.sma(c, length=50)
        df["SMA200"] = pta.sma(c, length=200)
        df["RSI"] = pta.rsi(c, length=14)
        macd = pta.macd(c)
        adx = pta.adx(h, l, c, length=14)
        if macd is None or adx is None:
            return None
        df = df.join(macd).join(adx)
        mc, mh, ms = macd.columns[0], macd.columns[1], macd.columns[2]
        ac, dp, dn = adx.columns[0], adx.columns[1], adx.columns[2]
        has_vol = "Volume" in df.columns

        win = df.tail(display_days)
        if len(win) < 20:
            return None
        xd = mdates.date2num(win.index.to_pydatetime())
        bw = 0.6

        fig = Figure(figsize=(9, 7), facecolor=_BG)
        FigureCanvasAgg(fig)
        p, rax, max_, aax = fig.subplots(4, 1, sharex=True,
                                         gridspec_kw={'height_ratios': [3.2, 1, 1, 1], 'hspace': 0.12})
        # candles + SMAs
        for dt, o, hi, lo, cl in zip(xd, win["Open"], win["High"], win["Low"], win["Close"]):
            col = _UP if cl >= o else _DN
            p.vlines(dt, lo, hi, color=col, lw=.7)
            p.add_patch(Rectangle((dt - bw / 2, min(o, cl)), bw, max(abs(cl - o), .01), color=col, ec=col))
        p.plot(xd, win["SMA50"], color="#f2ca30", lw=1.1, label="SMA 50")
        p.plot(xd, win["SMA200"], color="#ab7df8", lw=1.1, label="SMA 200")
        p.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=8)
        p.set_title(f"{ticker} — Daily · Candles · SMA 50/200 · RSI · MACD · ADX",
                    color=_TXT, fontsize=11, fontweight="bold")
        if has_vol:
            pv = p.twinx()
            pv.bar(xd, win["Volume"], width=bw,
                   color=[_UP if cl >= o else _DN for o, cl in zip(win["Open"], win["Close"])], alpha=.38)
            pv.set_ylim(0, float(win["Volume"].max()) * 2.5)  # bars fill bottom ~40% (was *4 ≈ 25%)
            pv.axis("off")
        # RSI
        rax.plot(xd, win["RSI"], color="#7ee787", lw=1.4)
        rax.axhline(70, color=_DN, ls=":", alpha=.6); rax.axhline(30, color=_UP, ls=":", alpha=.6)
        rax.set_ylim(0, 100); rax.set_ylabel("RSI", color=_TXT, fontsize=9)
        # MACD
        max_.bar(xd, win[mh], width=bw, color=[_UP if v >= 0 else _DN for v in win[mh]], alpha=.6)
        max_.plot(xd, win[mc], color="#58a6ff", lw=1.1); max_.plot(xd, win[ms], color="#ff8b3d", lw=1.1)
        max_.axhline(0, color=_SP, lw=.8); max_.set_ylabel("MACD", color=_TXT, fontsize=9)
        # ADX
        aax.plot(xd, win[ac], color="#e1e7f0", lw=1.4, label="ADX")
        aax.plot(xd, win[dp], color=_UP, lw=1, label="+DI"); aax.plot(xd, win[dn], color=_DN, lw=1, label="-DI")
        aax.axhline(25, color="#8899a6", ls=":", alpha=.5); aax.set_ylabel("ADX", color=_TXT, fontsize=9)
        aax.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=7, ncol=3)
        for a in (p, rax, max_, aax):
            _style(a)
        aax.xaxis_date()
        aax.xaxis.set_major_locator(mdates.AutoDateLocator())
        aax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        fig.autofmt_xdate()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=_BG, dpi=130, bbox_inches="tight")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — a chart failure must never break the analysis
        logger.info(f"chart_generator: main chart unavailable for {ticker}: {e}")
        return None


# ── Event-anchored sub-charts (Phase 5) — see docs/DESIGN_event_anchored_subcharts.md (NewX repo) ──
# A compact, single-indicator card ZOOMED to the exact window of one detected event (from
# technical_events.detect_events), with the occurrence annotated. Which indicator a given event
# type renders is deterministic PRESENTATION of a structured event (like the main chart's fixed
# panels / technical_indicators.format_for_llm's per-indicator rendering) — not meaning classification.

def _human_event(event: dict) -> str:
    """Objective, dated label for the card title/annotation — a STATE, never a buy/sell call.
    Shared with the analyzer's dated-event list via technical_events.event_label (one source)."""
    from utils.technical_events import event_label
    return event_label(event)


def _mark_event(ax, xnum, label=None):
    ax.axvline(xnum, color="#ffd54f", ls="--", lw=1.2, alpha=.9)
    if label:
        ax.annotate(label, xy=(xnum, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(4, -10), textcoords="offset points", color="#ffd54f",
                    fontsize=8, fontweight="bold", ha="left", va="top")


def generate_event_chart(ticker: str, history: pd.DataFrame, event: dict,
                         category: str = None) -> Optional[bytes]:
    """PNG bytes for a compact sub-chart zoomed to ONE event's window, or None if it can't be built.

    `history` = daily OHLCV (≥ warmup + span). `event` = a dict from technical_events.detect_events
    ({type, date, value, direction, ...}). Crops to event ± the category's event_zoom_sessions (config).
    Thread-safe OO API; never raises → None so a chart problem can't break the analysis.
    """
    try:
        if history is None or getattr(history, "empty", True) or not isinstance(event, dict):
            return None
        etype = str(event.get("type", "")); edate = event.get("date")
        if not etype or not edate:
            return None
        df = history.copy()
        df.columns = [str(c).capitalize() for c in df.columns]
        if "Close" not in df.columns:
            return None
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        c = df["Close"]; h = df.get("High"); l = df.get("Low")

        # Crop window = event ± zoom (reuse the Step-1 config-driven helper for one source of truth).
        from utils.technical_events import event_window
        lo, hi = event_window(df.index, edate, category)
        if lo is None:
            return None
        win = df.loc[lo:hi]
        if len(win) < 5:
            return None
        xd = mdates.date2num(win.index.to_pydatetime())
        ev_x = mdates.date2num(pd.Timestamp(edate).to_pydatetime())
        bw = 0.6

        fig = Figure(figsize=(5.4, 3.4), facecolor=_BG)
        FigureCanvasAgg(fig)
        ax = fig.subplots(1, 1)
        title = f"{ticker} — {_human_event(event)}"

        fam = etype.split("_")[0]
        if etype == "sma_cross":
            sma_f = pta.sma(c, length=50).reindex(df.index)
            sma_s = pta.sma(c, length=200).reindex(df.index)
            ax.plot(xd, win["Close"], color=_TXT, lw=1.2, label="Close")
            ax.plot(xd, sma_f.loc[win.index], color="#f2ca30", lw=1.3, label="SMA 50")
            ax.plot(xd, sma_s.loc[win.index], color="#ab7df8", lw=1.3, label="SMA 200")
            ax.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=7)
        elif fam == "rsi":
            rsi = pta.rsi(c, length=14).reindex(df.index)
            ax.plot(xd, rsi.loc[win.index], color="#7ee787", lw=1.6)
            ax.axhspan(70, 100, color=_DN, alpha=.10); ax.axhspan(0, 30, color=_UP, alpha=.10)
            ax.axhline(70, color=_DN, ls=":", alpha=.6); ax.axhline(30, color=_UP, ls=":", alpha=.6)
            ax.set_ylim(0, 100)
        elif fam == "macd":
            macd = pta.macd(c)
            if macd is None or macd.empty:
                return None
            mc, mh, ms = macd.columns[0], macd.columns[1], macd.columns[2]
            m = macd.reindex(df.index).loc[win.index]
            ax.bar(xd, m[mh], width=bw, color=[_UP if v >= 0 else _DN for v in m[mh]], alpha=.6)
            ax.plot(xd, m[mc], color="#58a6ff", lw=1.3, label="MACD")
            ax.plot(xd, m[ms], color="#ff8b3d", lw=1.3, label="signal")
            ax.axhline(0, color=_SP, lw=.8)
            ax.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=7)
        elif fam == "adx":
            if h is None or l is None:
                return None
            adx = pta.adx(h, l, c, length=14)
            if adx is None or adx.empty:
                return None
            ac, dp, dn = adx.columns[0], adx.columns[1], adx.columns[2]
            a = adx.reindex(df.index).loc[win.index]
            ax.plot(xd, a[ac], color=_TXT, lw=1.6, label="ADX")
            ax.plot(xd, a[dp], color=_UP, lw=1, label="+DI"); ax.plot(xd, a[dn], color=_DN, lw=1, label="-DI")
            ax.axhline(25, color="#8899a6", ls=":", alpha=.6)
            ax.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=7, ncol=3)
        elif etype == "volume_confirm":
            if "Volume" not in win.columns:
                return None
            ax.plot(xd, win["Close"], color=_TXT, lw=1.3, label="Close")
            pv = ax.twinx()
            cols = [_UP if cl >= o else _DN for o, cl in zip(win.get("Open", win["Close"]), win["Close"])]
            pv.bar(xd, win["Volume"], width=bw, color=cols, alpha=.35)
            pv.set_ylim(0, float(win["Volume"].max()) * 1.6); pv.axis("off")
            ax.legend(loc="upper left", framealpha=.3, facecolor=_AX, edgecolor=_SP, labelcolor=_TXT, fontsize=7)
        else:
            return None  # unknown event type → no card (fail closed, never a wrong chart)

        _mark_event(ax, ev_x, _human_event(event))
        ax.set_title(title, color=_TXT, fontsize=9.5, fontweight="bold")
        _style(ax)
        ax.xaxis_date()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
        fig.autofmt_xdate()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=_BG, dpi=130, bbox_inches="tight")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — a chart failure must never break the analysis
        logger.info(f"chart_generator: event chart unavailable for {ticker} ({event.get('type') if isinstance(event, dict) else '?'}): {e}")
        return None
