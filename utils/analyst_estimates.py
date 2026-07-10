"""
Analyst consensus estimates from yfinance (Yahoo-aggregated).

v1.0.0.166 — Structured analyst data: 12-month price targets, the buy/hold/sell recommendation
distribution, and FORWARD EPS/revenue consensus with growth rates. This is REAL analyst consensus,
deliberately DISTINCT from the RAICA historical-CAGR projections (which are labeled "not analyst
consensus"). It replaces web-scraped analyst targets — those were unreliable AND the first thing to
degrade when the live server's web search gets rate-limited, yet they drive the Buy/Hold/Sell ranking.

All fields are pulled defensively (each yfinance endpoint wrapped) so a single missing field or a
flaky endpoint never breaks the block. yfinance growth fields are FRACTIONS (0.4225 = 42.25%) and are
rendered ×100 — same field-scale gotcha as dividendYield/revenueGrowth.
"""
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class AnalystEstimates:
    def _num(self, v) -> Optional[float]:
        """Coerce to float, mapping None/NaN/garbage → None (NaN != NaN)."""
        try:
            if v is None:
                return None
            f = float(v)
            return None if f != f else f
        except Exception:
            return None

    def _pct(self, v) -> Optional[float]:
        """yfinance growth fields are FRACTIONS (0.4225 → 42.25%). Render as a percentage number."""
        f = self._num(v)
        return f * 100.0 if f is not None else None

    def _row(self, df, idx):
        try:
            if isinstance(df, pd.DataFrame) and not df.empty and idx in df.index:
                return df.loc[idx]
        except Exception:
            pass
        return None

    def get_estimates(self, ticker: str, ticker_obj=None, ticker_info: Dict = None) -> Dict[str, Any]:
        """Return a dict of analyst-consensus fields. Never raises; missing pieces are simply absent."""
        data: Dict[str, Any] = {"symbol": ticker}
        try:
            t = ticker_obj or yf.Ticker(ticker)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AnalystEstimates: could not create Ticker for {ticker}: {e}")
            return data

        # ---- price targets + recommendation (from info; already fetched by the analyzer) ----
        info = ticker_info
        if info is None:
            try:
                info = t.info or {}
            except Exception:
                info = {}
        cp = self._num(info.get("currentPrice"))
        tm = self._num(info.get("targetMeanPrice"))
        data.update({
            "current_price": cp,
            "target_mean": tm,
            "target_median": self._num(info.get("targetMedianPrice")),
            "target_high": self._num(info.get("targetHighPrice")),
            "target_low": self._num(info.get("targetLowPrice")),
            "num_analysts": self._num(info.get("numberOfAnalystOpinions")),
            "recommendation_mean": self._num(info.get("recommendationMean")),
            "recommendation_key": info.get("recommendationKey"),
        })
        if tm is not None and cp:
            data["upside_to_mean_pct"] = (tm / cp - 1.0) * 100.0

        # ---- forward consensus: next fiscal year EPS + revenue (separate endpoints) ----
        try:
            ee = self._row(t.get_earnings_estimate(), "+1y")
            if ee is not None:
                data["fwd_eps_avg"] = self._num(ee.get("avg"))
                data["fwd_eps_growth_pct"] = self._pct(ee.get("growth"))
                data["fwd_eps_n"] = self._num(ee.get("numberOfAnalysts"))
        except Exception as e:  # noqa: BLE001
            logger.info(f"AnalystEstimates: earnings estimate unavailable for {ticker}: {e}")
        try:
            rev = self._row(t.get_revenue_estimate(), "+1y")
            if rev is not None:
                data["fwd_rev_avg"] = self._num(rev.get("avg"))
                data["fwd_rev_growth_pct"] = self._pct(rev.get("growth"))
                data["fwd_rev_n"] = self._num(rev.get("numberOfAnalysts"))
        except Exception as e:  # noqa: BLE001
            logger.info(f"AnalystEstimates: revenue estimate unavailable for {ticker}: {e}")

        # ---- long-term growth estimate (often absent) ----
        try:
            ltg = self._row(t.get_growth_estimates(), "LTG")
            if ltg is not None:
                data["ltg_pct"] = self._pct(ltg.get("stockTrend"))
        except Exception:
            pass

        # ---- recommendation distribution (most recent period) ----
        try:
            rs = t.get_recommendations_summary()
            if isinstance(rs, pd.DataFrame) and not rs.empty:
                r0 = rs.iloc[0]
                data["rec_dist"] = {k: int(self._num(r0.get(k)) or 0)
                                    for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        except Exception:
            pass

        return data

    def _format_source_block(self, source_num: int, title: str, url: str, date: str, content: str) -> str:
        CAP = 1000
        if len(content) > CAP:
            content = content[:CAP - 3] + "..."
        return f"""SOURCE {source_num}:
Title: {title}
URL: {url}
Date: {date}
{content}

"""

    def format_for_llm(self, data: Dict[str, Any], ticker: str) -> str:
        """Render the analyst-consensus SOURCE block, or '' when no usable data was retrieved."""
        if not data or (data.get("target_mean") is None and data.get("fwd_eps_avg") is None):
            return ""
        lines = [
            "ANALYST CONSENSUS (Yahoo-aggregated analyst estimates via yfinance — REAL forward-looking "
            "market consensus; DISTINCT from the RAICA historical-CAGR projections and NOT web-scraped):"
        ]
        tm, cp = data.get("target_mean"), data.get("current_price")
        if tm is not None:
            extra = ""
            if data.get("target_low") is not None and data.get("target_high") is not None:
                med = f"median ${data['target_median']:.2f}, " if data.get("target_median") is not None else ""
                extra = f" ({med}range ${data['target_low']:.2f}–${data['target_high']:.2f})"
            n = f" from {int(data['num_analysts'])} analysts" if data.get("num_analysts") else ""
            lines.append(f"  Price target (12-mo): mean ${tm:.2f}{extra}{n}")
        if data.get("upside_to_mean_pct") is not None and cp:
            lines.append(f"  Implied move to mean target: {data['upside_to_mean_pct']:+.1f}% from ${cp:.2f}")
        if data.get("recommendation_key") or data.get("recommendation_mean") is not None:
            rm = (f" (mean rating {data['recommendation_mean']:.2f}; scale 1=Strong Buy … 5=Strong Sell)"
                  if data.get("recommendation_mean") is not None else "")
            lines.append(f"  Recommendation: {data.get('recommendation_key', 'n/a')}{rm}")
        rd = data.get("rec_dist")
        if rd:
            lines.append(f"  Rating distribution: {rd['strongBuy']} Strong Buy, {rd['buy']} Buy, "
                         f"{rd['hold']} Hold, {rd['sell']} Sell, {rd['strongSell']} Strong Sell")
        if data.get("fwd_rev_avg") is not None:
            g = f" ({data['fwd_rev_growth_pct']:+.1f}% YoY)" if data.get("fwd_rev_growth_pct") is not None else ""
            n = f", {int(data['fwd_rev_n'])} analysts" if data.get("fwd_rev_n") else ""
            lines.append(f"  Forward revenue consensus (next FY): ${data['fwd_rev_avg'] / 1e9:.2f}B{g}{n}")
        if data.get("fwd_eps_avg") is not None:
            g = f" ({data['fwd_eps_growth_pct']:+.1f}% YoY)" if data.get("fwd_eps_growth_pct") is not None else ""
            n = f", {int(data['fwd_eps_n'])} analysts" if data.get("fwd_eps_n") else ""
            lines.append(f"  Forward EPS consensus (next FY): ${data['fwd_eps_avg']:.2f}{g}{n}")
        if data.get("ltg_pct") is not None:
            lines.append(f"  Long-term growth estimate (analyst): {data['ltg_pct']:+.1f}%")
        return self._format_source_block(
            source_num=1,
            title=f"{ticker} Analyst Consensus (yfinance / Yahoo Finance)",
            url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
            date=datetime.now().strftime("%Y-%m-%d"),
            content="\n".join(lines),
        )
