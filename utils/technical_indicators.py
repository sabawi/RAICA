"""
Technical indicators for the stock analyzer (v1.0.0.168).

Computes a curated set of standard technical indicators from ~2y of daily OHLCV history via
``pandas-ta-classic`` (pure pandas/numpy — no Numba/C; verified compatible with RAICA's pinned
numpy 2.3.2 / pandas 2.3.1) and emits a TECHNICAL ANALYSIS SOURCE block of VALUES + OBJECTIVE STATES
for the LLM to interpret.

CLAUDE.md compliance: this NEVER emits a hardcoded buy/sell signal. It reports the readings and their
standard objective zones/regimes (e.g. "RSI 72 → overbought zone (>70)", "50-day SMA above 200-day
= golden-cross regime", "price at 88% of the 52-week range") and the LLM reasons about what they mean
for the thesis. Every indicator is wrapped defensively; missing/short history → empty block, never a
crash or a half-rendered SOURCE.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
import pandas_ta_classic as pta
import yfinance as yf

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    def _last(self, series) -> Optional[float]:
        """Last non-NaN float of a Series, or None."""
        try:
            s = series.dropna()
            return float(s.iloc[-1]) if len(s) else None
        except Exception:
            return None

    def _pct_return(self, close: pd.Series, days: int) -> Optional[float]:
        """Simple price return over `days` trailing sessions, as a percentage."""
        try:
            if len(close) <= days:
                return None
            prev = close.iloc[-1 - days]
            if prev and prev != 0:
                return (close.iloc[-1] / prev - 1.0) * 100.0
        except Exception:
            pass
        return None

    def get_indicators(self, ticker: str, ticker_obj=None, history: pd.DataFrame = None) -> Dict[str, Any]:
        """Compute the curated indicator set. Never raises; missing pieces are simply absent."""
        data: Dict[str, Any] = {"symbol": ticker}
        try:
            if history is None:
                # P1 (v1.0.0.173): retry the transient-prone history fetch (shared bounded retry).
                from utils.yf_retry import configured_fetch
                t = ticker_obj or yf.Ticker(ticker)
                history = configured_fetch(lambda: t.history(period="2y"),
                                           label=f"{ticker} 2y history", log=logger)  # ≥200 sessions for 200-SMA + 12-mo return + ADX warmup
            if history is None or getattr(history, "empty", True) or len(history) < 40:
                return data
            df = history.copy()
            df.columns = [str(c).lower() for c in df.columns]
            if "close" not in df.columns:
                return data
            close, high, low = df["close"], df.get("high"), df.get("low")
            data["price"] = self._last(close)
            data["history_days"] = int(len(df))

            # ---- Trend: 50/200-day SMA + cross regime ----
            sma50 = self._last(pta.sma(close, length=50))
            sma200 = self._last(pta.sma(close, length=200))
            data["sma50"], data["sma200"] = sma50, sma200
            if data["price"] and sma50:
                data["price_vs_sma50_pct"] = (data["price"] / sma50 - 1.0) * 100.0
            if data["price"] and sma200:
                data["price_vs_sma200_pct"] = (data["price"] / sma200 - 1.0) * 100.0
            if sma50 and sma200:
                data["cross_regime"] = "golden" if sma50 > sma200 else "death"

            # ---- Momentum: RSI-14, MACD ----
            data["rsi14"] = self._last(pta.rsi(close, length=14))
            try:
                macd = pta.macd(close)
                if macd is not None and not macd.empty:
                    data["macd"] = self._last(macd.iloc[:, 0])       # MACD line
                    data["macd_hist"] = self._last(macd.iloc[:, 1])  # histogram
                    data["macd_signal"] = self._last(macd.iloc[:, 2])
            except Exception:
                pass

            # ---- Trend strength: ADX-14 (+DI / -DI) ----
            try:
                if high is not None and low is not None:
                    adx = pta.adx(high, low, close, length=14)
                    if adx is not None and not adx.empty:
                        data["adx14"] = self._last(adx.iloc[:, 0])   # ADX
                        data["di_plus"] = self._last(adx.iloc[:, 1])  # +DI
                        data["di_minus"] = self._last(adx.iloc[:, 2])  # -DI
            except Exception:
                pass

            # ---- Volatility: ATR (as % of price) + annualized realized vol ----
            try:
                if high is not None and low is not None:
                    atr = self._last(pta.atr(high, low, close, length=14))
                    if atr and data["price"]:
                        data["atr_pct"] = atr / data["price"] * 100.0
            except Exception:
                pass
            try:
                rets = close.pct_change().dropna()
                if len(rets) >= 20:
                    data["realized_vol_pct"] = float(rets.std() * np.sqrt(252) * 100.0)
            except Exception:
                pass

            # ---- Bollinger %B (position within the 20/2 bands) ----
            try:
                bb = pta.bbands(close, length=20, std=2)
                if bb is not None and not bb.empty:
                    bbp_col = [c for c in bb.columns if c.upper().startswith("BBP")]
                    if bbp_col:
                        data["bb_percent_b"] = self._last(bb[bbp_col[0]])
            except Exception:
                pass

            # ---- 52-week range position ----
            try:
                window = min(len(df), 252)
                hi = float(df["high"].tail(window).max()) if "high" in df.columns else float(close.tail(window).max())
                lo = float(df["low"].tail(window).min()) if "low" in df.columns else float(close.tail(window).min())
                data["wk52_high"], data["wk52_low"] = hi, lo
                if hi > lo and data["price"] is not None:
                    data["wk52_position_pct"] = (data["price"] - lo) / (hi - lo) * 100.0
            except Exception:
                pass

            # ---- Momentum returns: 1 / 3 / 6 / 12 months ----
            for label, d in (("ret_1m", 21), ("ret_3m", 63), ("ret_6m", 126), ("ret_12m", 252)):
                r = self._pct_return(close, d)
                if r is not None:
                    data[label] = r

            return data
        except Exception as e:  # noqa: BLE001 — technical block must never break the analyzer
            logger.info(f"TechnicalIndicators: unavailable for {ticker}: {e}")
            return data

    def _format_source_block(self, source_num: int, title: str, url: str, date: str, content: str) -> str:
        CAP = 1200
        if len(content) > CAP:
            content = content[:CAP - 3] + "..."
        return f"""SOURCE {source_num}:
Title: {title}
URL: {url}
Date: {date}
{content}

"""

    def format_for_llm(self, data: Dict[str, Any], ticker: str) -> str:
        """Render the TECHNICAL ANALYSIS SOURCE block, or '' when no usable data was computed."""
        if not data or data.get("price") is None or data.get("rsi14") is None:
            return ""
        lines = [
            "TECHNICAL ANALYSIS (price-action indicators computed by RAICA from ~2y daily history — "
            "OBJECTIVE readings/states, NOT a buy/sell signal; interpret them for the thesis):"
        ]
        px = data["price"]
        lines.append(f"  Price: ${px:.2f}  (over {data.get('history_days', '?')} sessions)")

        # Trend
        if data.get("sma50") is not None and data.get("sma200") is not None:
            regime = data.get("cross_regime")
            regime_txt = ("50-day ABOVE 200-day = golden-cross regime" if regime == "golden"
                          else "50-day BELOW 200-day = death-cross regime" if regime == "death" else "")
            p50 = f"{data['price_vs_sma50_pct']:+.1f}% vs 50-day" if data.get("price_vs_sma50_pct") is not None else ""
            p200 = f"{data['price_vs_sma200_pct']:+.1f}% vs 200-day" if data.get("price_vs_sma200_pct") is not None else ""
            lines.append(f"  Trend: SMA50 ${data['sma50']:.2f}, SMA200 ${data['sma200']:.2f}  "
                         f"(price {p50}, {p200}); {regime_txt}")

        # Momentum
        if data.get("rsi14") is not None:
            r = data["rsi14"]
            zone = "overbought zone (>70)" if r > 70 else "oversold zone (<30)" if r < 30 else "neutral (30–70)"
            lines.append(f"  RSI(14): {r:.1f} — {zone}")
        if data.get("macd") is not None and data.get("macd_signal") is not None:
            rel = "line ABOVE signal" if data["macd"] > data["macd_signal"] else "line BELOW signal"
            lines.append(f"  MACD: {data['macd']:+.2f} vs signal {data['macd_signal']:+.2f} "
                         f"(hist {data.get('macd_hist', 0):+.2f}; {rel})")

        # Trend strength
        if data.get("adx14") is not None:
            adx = data["adx14"]
            strength = ("strong trend (ADX>25)" if adx > 25 else "weak/rangebound (ADX<20)" if adx < 20
                        else "developing trend (ADX 20–25)")
            di = ""
            if data.get("di_plus") is not None and data.get("di_minus") is not None:
                di = f"; +DI {data['di_plus']:.1f} vs −DI {data['di_minus']:.1f}"
            lines.append(f"  ADX(14): {adx:.1f} — {strength}{di}")

        # Position + volatility
        if data.get("wk52_position_pct") is not None:
            lines.append(f"  52-week range: ${data['wk52_low']:.2f}–${data['wk52_high']:.2f}, "
                         f"price at {data['wk52_position_pct']:.0f}% of range")
        if data.get("bb_percent_b") is not None:
            lines.append(f"  Bollinger %B (20,2): {data['bb_percent_b']:.2f} "
                         f"(0=lower band, 1=upper band)")
        vol_bits = []
        if data.get("realized_vol_pct") is not None:
            vol_bits.append(f"realized vol {data['realized_vol_pct']:.0f}% annualized")
        if data.get("atr_pct") is not None:
            vol_bits.append(f"ATR {data['atr_pct']:.1f}% of price")
        if vol_bits:
            lines.append("  Volatility: " + ", ".join(vol_bits))

        # Returns
        rets = [(lbl, data.get(k)) for lbl, k in (("1M", "ret_1m"), ("3M", "ret_3m"),
                                                  ("6M", "ret_6m"), ("12M", "ret_12m"))]
        rets = [(lbl, v) for lbl, v in rets if v is not None]
        if rets:
            lines.append("  Price returns: " + ", ".join(f"{lbl} {v:+.1f}%" for lbl, v in rets))

        return self._format_source_block(
            source_num=1,
            title=f"{ticker} Technical Analysis (RAICA — pandas-ta-classic indicators)",
            url=f"https://finance.yahoo.com/quote/{ticker}/chart",
            date=datetime.now().strftime("%Y-%m-%d"),
            content="\n".join(lines),
        )
