"""
Projection Engine

Generates financial projections based on historical data and analyst estimates.

Part of: FUNDAMENTAL_ANALYSIS_DCF_IMPLEMENTATION_PLAN.md - Day 5 Implementation
"""

import pandas as pd
from typing import Dict, Any, List, Optional
import logging
import numpy as np

from utils.dcf_calculator import evidence_aware_growth_cap

logger = logging.getLogger(__name__)


class ProjectionEngine:
    """
    Generate financial projections.

    Features:
    - Historical growth rate calculations
    - Revenue projections (base/best/worst case)
    - Earnings projections
    - Free cash flow projections
    """

    def __init__(self):
        """Initialize the projection engine."""
        self.projection_years = 3  # 3-year forward projections
        self.sustainable_anchor = 0.05   # long-run growth a mature business can sustain
        self.max_growth = 0.20           # default ceiling; see evidence_aware_growth_cap

    def _blend_growth(self, historical, forward, cap=None, forward_label='analyst forward growth'):
        """Median of (historical CAGR, analyst FORWARD growth, sustainable anchor).

        See docs/PROJECTION_GROWTH_BLEND_SCOPE.md. The engine used to extrapolate a CAPPED
        HISTORICAL CAGR with NO forward signal, while the DCF next to it in the same report
        already median-blended a forward one. The two disagreed on the same page.

        For CROX the report printed a 20.0% capped projection while stating, correctly, that
        the raw 32.6% CAGR was "likely inflated by the HEYDUDE acquisition" and that analyst
        consensus implied 7.1%. RAICA detected the distortion, said so, and then used the
        distorted number anyway. A median of three signals is robust to ONE transient outlier
        in either direction — it discards CROX's acquisition spike and KO's -17.8% collapse
        alike — while actually pulling in the forward view.

        Returns (growth, signals, cap, cap_raised, cap_reason). `signals` is carried through
        to the formatter so the output can SHOW its derivation rather than assert a number.
        """
        signals = []
        if historical is not None:
            signals.append(('historical CAGR', float(historical)))
        if forward is not None:
            try:
                _f = float(forward)
                if -0.9 < _f < 3.0:          # same sanity bound the DCF applies
                    signals.append((forward_label, _f))
            except (TypeError, ValueError):
                pass
        signals.append(('sustainable anchor', self.sustainable_anchor))

        growth = float(np.median([v for _, v in signals]))
        _cap, _raised, _reason = evidence_aware_growth_cap(
            signals, self.max_growth if cap is None else cap)
        return min(growth, _cap), signals, _cap, _raised, _reason

    @staticmethod
    def _divergence_note(signals):
        """Flag when the backward and forward signals disagree enough to matter.

        The median already neutralises the outlier; this states WHY the number moved, so a
        reader is not left wondering why a 32.6% CAGR became 7.1%.
        """
        hist = next((v for lbl, v in signals if lbl == 'historical CAGR'), None)
        fwd = next((v for lbl, v in signals
                    if lbl not in ('historical CAGR', 'sustainable anchor')), None)
        if hist is None or fwd is None:
            return None
        if abs(hist - fwd) > 0.15 or (abs(fwd) > 1e-9 and abs(hist / fwd) > 2.0):
            return ("historical CAGR diverges sharply from analyst consensus — likely "
                    "reflects acquisitions or one-time items rather than organic growth")
        return None

    def _get_value(self, df: pd.DataFrame, key: str, col_index: int = 0):
        """Safely extract value from DataFrame."""
        try:
            if df is None or df.empty:
                return None
            if key not in df.index:
                return None
            value = df.loc[key, df.columns[col_index]]
            if pd.isna(value):
                return None
            return value
        except:
            return None

    def calculate_historical_cagr(self, values: List[float]) -> Optional[float]:
        """
        Calculate CAGR from a list of values.

        CAGR = (Ending Value / Beginning Value)^(1/years) - 1
        """
        try:
            if not values or len(values) < 2:
                return None

            # Filter out None and invalid values
            valid_values = [v for v in values if v is not None and v > 0]

            if len(valid_values) < 2:
                return None

            beginning_value = valid_values[-1]
            ending_value = valid_values[0]
            years = len(valid_values) - 1

            if beginning_value <= 0:
                return None

            cagr = (ending_value / beginning_value) ** (1 / years) - 1

            # Cap at reasonable levels
            cagr = max(min(cagr, 1.0), -0.5)

            return cagr
        except:
            return None

    def project_metric(self, current_value: float, growth_rate: float, years: int) -> List[float]:
        """Project a metric forward using a growth rate."""
        if current_value is None or growth_rate is None:
            return []

        projections = []
        value = current_value

        for year in range(1, years + 1):
            value = value * (1 + growth_rate)
            projections.append(value)

        return projections

    def generate_revenue_projections(self, income_stmt: pd.DataFrame, ticker_info: Dict = None,
                                     analyst_estimates: Dict = None) -> Dict[str, Any]:
        """Generate revenue projections with base/best/worst scenarios."""
        try:
            ticker_info = ticker_info or {}
            if (income_stmt is None or income_stmt.empty) and not ticker_info.get('totalRevenue'):
                return {}

            # Get historical revenue (annual — used for the growth-rate calc)
            revenue_values = []
            if income_stmt is not None and not income_stmt.empty:
                for i in range(min(4, len(income_stmt.columns))):
                    rev = self._get_value(income_stmt, 'Total Revenue', i)
                    if rev:
                        revenue_values.append(rev)

            # Current revenue base: TTM-first (v1.0.0.159). yfinance info['totalRevenue'] is the
            # trailing-twelve-month revenue, consistent with the live price; the last annual
            # statement can be months stale (e.g. MU annual rev $37.38B vs TTM $90.27B). Projecting
            # from a stale base against current context distorts the whole 3-year path.
            ttm_revenue = ticker_info.get('totalRevenue')
            current_revenue = None
            current_source = None
            if ttm_revenue and ttm_revenue > 0:
                current_revenue = float(ttm_revenue)
                current_source = 'TTM (info.totalRevenue)'
            elif revenue_values:
                current_revenue = revenue_values[0]
                current_source = 'annual statement (stale)'

            if current_revenue is None:
                return {}

            # Calculate historical growth rate (from the multi-year annual series — still legit)
            historical_growth = self.calculate_historical_cagr(revenue_values)

            # v1.0.0.163 capped the RAW historical CAGR here (a hyper-growth name projected
            # revenue DOUBLING every year → ~$2.03T in 3 years). The cap stopped the absurdity
            # but kept the model blind to the forward view; SI-022 replaces it with the same
            # median blend the DCF uses, so the two agree in the report they share.
            _fwd = (analyst_estimates or {}).get('fwd_rev_growth_pct')
            _fwd = float(_fwd) / 100.0 if isinstance(_fwd, (int, float)) else None
            base_growth, _sig, _cap, _raised, _reason = self._blend_growth(
                historical_growth, _fwd)

            # Create scenarios
            # Best case: 1.5x historical or +5%, whichever is higher
            best_growth = max(base_growth * 1.5, base_growth + 0.05)
            # SI-022: the 25% ceiling must never fall BELOW the base case. It was safe only
            # while base_growth was itself hard-capped at 20%; once a corroborated forward
            # signal can lift the base above 25% (NVDA: base 42.6%), a flat ceiling made the
            # "best case" 25% — an OPTIMISTIC scenario more pessimistic than the base one.
            best_growth = min(best_growth, max(0.25, base_growth + 0.05))

            # Worst case: 0.5x historical or -5%, whichever is lower
            worst_growth = min(base_growth * 0.5, base_growth - 0.05)
            worst_growth = max(worst_growth, -0.10)  # Floor at -10%

            return {
                'current': current_revenue,
                'current_source': current_source,
                'historical_growth': historical_growth,
                'growth_signals': _sig,
                'growth_cap': _cap,
                'growth_cap_raised': _raised,
                'growth_cap_reason': _reason,
                'divergence_note': self._divergence_note(_sig),
                'base_case': {
                    'growth_rate': base_growth,
                    'projections': self.project_metric(current_revenue, base_growth, self.projection_years)
                },
                'best_case': {
                    'growth_rate': best_growth,
                    'projections': self.project_metric(current_revenue, best_growth, self.projection_years)
                },
                'worst_case': {
                    'growth_rate': worst_growth,
                    'projections': self.project_metric(current_revenue, worst_growth, self.projection_years)
                }
            }

        except Exception as e:
            logger.error(f"Error generating revenue projections: {e}")
            return {}

    def generate_earnings_projections(self, income_stmt: pd.DataFrame, ticker_info: Dict = None,
                                      analyst_estimates: Dict = None) -> Dict[str, Any]:
        """Generate earnings projections."""
        try:
            ticker_info = ticker_info or {}

            # Get historical net income (annual — for the growth-rate calc)
            earnings_values = []
            if income_stmt is not None and not income_stmt.empty:
                for i in range(min(4, len(income_stmt.columns))):
                    earnings = self._get_value(income_stmt, 'Net Income', i)
                    if earnings:
                        earnings_values.append(earnings)

            # Current earnings base: TTM-first (v1.0.0.159). info['netIncomeToCommon'] is TTM
            # net income; the annual statement can be stale (MU annual NI $8.54B vs TTM $50.47B).
            ttm_ni = ticker_info.get('netIncomeToCommon')
            current_earnings = None
            current_source = None
            if ttm_ni and ttm_ni > 0:
                current_earnings = float(ttm_ni)
                current_source = 'TTM (info.netIncomeToCommon)'
            elif earnings_values:
                current_earnings = earnings_values[0]
                current_source = 'annual statement (stale)'

            if current_earnings is None:
                return {}

            # Calculate historical growth rate
            historical_growth = self.calculate_historical_cagr([e for e in earnings_values if e > 0])

            # SI-022: median-blend with the analyst forward EPS consensus rather than
            # extrapolating a capped historical CAGR. The 0.9 haircut on history is dropped —
            # it was a crude stand-in for the forward view we now actually have.
            _fwd = (analyst_estimates or {}).get('fwd_eps_growth_pct')
            _fwd = float(_fwd) / 100.0 if isinstance(_fwd, (int, float)) else None
            base_growth, _sig, _cap, _raised, _reason = self._blend_growth(
                historical_growth, _fwd)

            return {
                'current': current_earnings,
                'current_source': current_source,
                'historical_growth': historical_growth,
                'growth_signals': _sig,
                'growth_cap': _cap,
                'growth_cap_raised': _raised,
                'growth_cap_reason': _reason,
                'divergence_note': self._divergence_note(_sig),
                'base_case': {
                    'growth_rate': base_growth,
                    'projections': self.project_metric(current_earnings, base_growth, self.projection_years)
                }
            }

        except Exception as e:
            logger.error(f"Error generating earnings projections: {e}")
            return {}

    def _ttm_fcf_from_quarters(self, quarterly_cash_flow) -> Optional[float]:
        """TTM free cash flow as OCF + capex over the last 4 quarters.

        Deliberately the SAME formula the annual figures use, so the two are comparable.
        `info['freeCashflow']` is NOT: for CROX it implied $228.7M of capex against the
        $58.0M actually reported, turning a rising FCF ($659.2M -> $704.6M) into an
        apparent decline ($659.2M -> $533.9M). A comparison is only a comparison when
        both sides are computed the same way.

        Returns None when fewer than 4 quarters are available — a partial sum would
        understate TTM and reintroduce exactly the bug this replaces.
        """
        if quarterly_cash_flow is None or getattr(quarterly_cash_flow, 'empty', True):
            return None
        try:
            if len(quarterly_cash_flow.columns) < 4:
                return None
            total = 0.0
            for i in range(4):
                ocf = self._get_value(quarterly_cash_flow, 'Operating Cash Flow', i)
                capex = self._get_value(quarterly_cash_flow, 'Capital Expenditure', i)
                if ocf is None or capex is None:
                    return None
                total += ocf + capex  # capex is negative
            return total
        except Exception:  # noqa: BLE001 - a shape surprise must not kill the projection
            return None

    def generate_fcf_projections(self, cash_flow: pd.DataFrame, ticker_info: Dict = None,
                                 quarterly_cash_flow: pd.DataFrame = None,
                                 analyst_estimates: Dict = None) -> Dict[str, Any]:
        """Generate free cash flow projections."""
        try:
            ticker_info = ticker_info or {}

            # Get historical FCF (annual — for the growth-rate calc)
            fcf_values = []
            if cash_flow is not None and not cash_flow.empty:
                for i in range(min(4, len(cash_flow.columns))):
                    ocf = self._get_value(cash_flow, 'Operating Cash Flow', i)
                    capex = self._get_value(cash_flow, 'Capital Expenditure', i)
                    if ocf is not None and capex is not None:
                        fcf = ocf + capex  # capex is negative
                        fcf_values.append(fcf)

            # Current FCF base: TTM-first (v1.0.0.159), but computed with the SAME FORMULA as the
            # annual figures it is compared against (v1.0.0.242).
            #
            # `info['freeCashflow']` uses a DIFFERENT definition from OCF+capex, and mixing the two
            # manufactures a trend that does not exist. CROX, 2026-08-09:
            #     annual 2025 FCF (OCF 710.4 - capex  51.2) = $659.2M
            #     TTM  info.freeCashflow                    = $533.9M   -> looks like a DECLINE
            #     TTM  (4q OCF 762.6 - 4q capex 58.0)       = $704.6M   -> actually RISING
            # info.freeCashflow implied $228.7M of capex against the $58.0M actually reported. The
            # analysis then described "robust FCF with a 9.7% CAGR" beside a falling number, and a
            # reviewer flagged the contradiction — correctly, and the fault was ours.
            #
            # So: sum the last 4 QUARTERS of OCF+capex. Fall back to info.freeCashflow only when
            # quarterly data is unavailable, and SAY which definition was used either way.
            ttm_fcf_consistent = self._ttm_fcf_from_quarters(quarterly_cash_flow)
            ttm_fcf = ticker_info.get('freeCashflow')
            current_fcf = None
            current_source = None
            if ttm_fcf_consistent is not None:
                current_fcf = ttm_fcf_consistent
                current_source = 'TTM (4-quarter OCF - capex; same formula as annual)'
            elif ttm_fcf is not None:
                current_fcf = float(ttm_fcf)
                current_source = ("TTM (info.freeCashflow — NOTE: vendor definition, NOT "
                                  "comparable to the annual OCF-capex figures)")
            elif fcf_values:
                current_fcf = fcf_values[0]
                current_source = 'annual statement (stale)'

            if current_fcf is None:
                return {}

            # Calculate historical growth rate
            historical_growth = self.calculate_historical_cagr([f for f in fcf_values if f > 0])

            # SI-022: no analyst FCF consensus exists in yfinance, so EPS growth is used as
            # the forward PROXY — an explicit assumption, labelled as such in the output
            # (scope doc Q1). The alternative, two signals, is a mean not a median and loses
            # the outlier robustness that is the whole point. FCF keeps its tighter 15%
            # default ceiling.
            _fwd = (analyst_estimates or {}).get('fwd_eps_growth_pct')
            _fwd = float(_fwd) / 100.0 if isinstance(_fwd, (int, float)) else None
            base_growth, _sig, _cap, _raised, _reason = self._blend_growth(
                historical_growth, _fwd, cap=0.15,
                forward_label='analyst forward growth (EPS proxy)')

            return {
                'current': current_fcf,
                'growth_signals': _sig,
                'growth_cap': _cap,
                'growth_cap_raised': _raised,
                'growth_cap_reason': _reason,
                'divergence_note': self._divergence_note(_sig),
                'current_source': current_source,
                'historical_growth': historical_growth,
                'base_case': {
                    'growth_rate': base_growth,
                    'projections': self.project_metric(current_fcf, base_growth, self.projection_years)
                }
            }

        except Exception as e:
            logger.error(f"Error generating FCF projections: {e}")
            return {}

    def generate_projections(self, ticker: str, financials: Dict,
                             analyst_estimates: Dict = None) -> Dict[str, Any]:
        """
        Generate comprehensive financial projections.

        Args:
            ticker: Stock ticker symbol
            financials: Financial statements from extractor

        Returns:
            Dictionary with all projections
        """
        logger.info(f"Generating projections for {ticker}")

        # Extract financial statements
        income_stmt = financials.get('income_statement', {}).get('annual')
        cash_flow = financials.get('cash_flow', {}).get('annual')
        quarterly_cash_flow = financials.get('cash_flow', {}).get('quarterly')
        ticker_info = financials.get('ticker_info', {}) or {}

        # SI-022: analyst_estimates is already fetched by the caller for the DCF and simply
        # was not passed here — the wiring gap the scope doc identified as "one line".
        return {
            'revenue_projections': self.generate_revenue_projections(
                income_stmt, ticker_info, analyst_estimates),
            'earnings_projections': self.generate_earnings_projections(
                income_stmt, ticker_info, analyst_estimates),
            'fcf_projections': self.generate_fcf_projections(
                cash_flow, ticker_info, quarterly_cash_flow, analyst_estimates)
        }


    @staticmethod
    def _growth_derivation_lines(block, indent="  "):
        """Render HOW a projected growth rate was derived, not just its value.

        Non-negotiable per the scope doc §4.3: RAICA already DETECTED the CROX distortion
        and said so in prose while using the distorted number. Showing the derivation is
        what makes the corrected number auditable instead of merely different.
        """
        out = []
        sig = block.get('growth_signals')
        if sig:
            out.append(f"{indent}  [median of: "
                       + " | ".join(f"{lbl} {val*100:.1f}%" for lbl, val in sig) + "]")
        if block.get('growth_cap_raised') and block.get('growth_cap_reason'):
            out.append(f"{indent}  Growth ceiling: {block['growth_cap_reason']}")
        note = block.get('divergence_note')
        if note:
            out.append(f"{indent}  NOTE: {note}")
        return out

    def _format_source_block(self, source_num: int, title: str, url: str, date: str, content: str) -> str:
        """
        Format content into standardized SOURCE block format for LLM context.

        This follows the Context Engineering Citation Mastery format.

        Args:
            source_num: Sequential source number
            title: Title of the projection
            url: URL to the source
            date: Projection date
            content: Formatted projection data

        Returns:
            Formatted SOURCE block string
        """
        # Truncate content to 500 characters max (Context Engineering standard)
        if len(content) > 500:
            content = content[:497] + "..."

        return f"""SOURCE {source_num}:
Title: {title}
URL: {url}
Date: {date}
{content}

"""

    def format_projections_for_llm(self, projections: Dict, ticker: str = None) -> str:
        """
        Format projections for LLM consumption in SOURCE block format.

        Args:
            projections: Dictionary of projections
            ticker: Stock ticker for URL attribution

        Returns:
            Formatted string in SOURCE block format
        """
        if not ticker:
            ticker = "UNKNOWN"

        # Check if we have any projections
        has_projections = any(
            projections.get(key) for key in ['revenue_projections', 'earnings_projections', 'fcf_projections']
        )

        if not has_projections:
            return "\n⚠️ **FINANCIAL PROJECTIONS** - Data not available\n"

        output = []
        source_num = 1
        current_date = pd.Timestamp.now().strftime('%Y-%m-%d')

        # Format revenue projections
        if projections.get('revenue_projections'):
            rev_proj = projections['revenue_projections']
            content = self._format_revenue_projections(rev_proj)
            if content:
                source_block = self._format_source_block(
                    source_num=source_num,
                    title=f"{ticker} Revenue Projections (3-Year, Historical-CAGR Extrapolation — not analyst consensus)",
                    url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
                    date=current_date,
                    content=content
                )
                output.append(source_block)
                source_num += 1

        # Format earnings projections
        if projections.get('earnings_projections'):
            earn_proj = projections['earnings_projections']
            content = self._format_earnings_projections(earn_proj)
            if content:
                source_block = self._format_source_block(
                    source_num=source_num,
                    title=f"{ticker} Earnings Projections (3-Year, Historical-CAGR Extrapolation — not analyst consensus)",
                    url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
                    date=current_date,
                    content=content
                )
                output.append(source_block)
                source_num += 1

        # Format FCF projections
        if projections.get('fcf_projections'):
            fcf_proj = projections['fcf_projections']
            content = self._format_fcf_projections(fcf_proj)
            if content:
                source_block = self._format_source_block(
                    source_num=source_num,
                    title=f"{ticker} Free Cash Flow Projections (3-Year, Historical-CAGR Extrapolation — not analyst consensus)",
                    url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
                    date=current_date,
                    content=content
                )
                output.append(source_block)
                source_num += 1

        return "\n".join(output)

    def _format_revenue_projections(self, rev_proj: Dict) -> str:
        """Format revenue projections."""
        if not rev_proj:
            return ""

        lines = ["REVENUE PROJECTIONS:"]

        if 'current' in rev_proj:
            src = rev_proj.get('current_source')
            src_tag = f"  [{src}]" if src else ""
            lines.append(f"  Current Revenue: ${rev_proj['current']/1e9:.2f}B{src_tag}")

        if 'historical_growth' in rev_proj and rev_proj['historical_growth'] is not None:
            lines.append(f"  Historical CAGR (raw, uncapped): {rev_proj['historical_growth']*100:.1f}%")
        if 'base_case' in rev_proj:
            base = rev_proj['base_case']
            lines.append(f"\nBase Case (Projected growth: {base['growth_rate']*100:.1f}%):")
            lines.extend(self._growth_derivation_lines(rev_proj))
            for i, value in enumerate(base['projections'], 1):
                lines.append(f"  Year {i}: ${value/1e9:.2f}B")
        lines.append(
            "  NOTE: RAICA model estimate — the median of the historical CAGR, the analyst "
            "FORWARD consensus, and a 5% sustainable anchor. Not a pure analyst consensus, "
            "and not a pure historical extrapolation."
        )

        return "\n".join(lines)

    def _format_earnings_projections(self, earn_proj: Dict) -> str:
        """Format earnings projections."""
        if not earn_proj:
            return ""

        lines = ["EARNINGS PROJECTIONS:"]

        if 'current' in earn_proj:
            src = earn_proj.get('current_source')
            src_tag = f"  [{src}]" if src else ""
            lines.append(f"  Current Net Income: ${earn_proj['current']/1e9:.2f}B{src_tag}")

        if 'historical_growth' in earn_proj and earn_proj['historical_growth'] is not None:
            lines.append(f"  Historical CAGR (raw, uncapped): {earn_proj['historical_growth']*100:.1f}%")
        if 'base_case' in earn_proj:
            base = earn_proj['base_case']
            lines.append(f"\nProjected Growth: {base['growth_rate']*100:.1f}%")
            lines.extend(self._growth_derivation_lines(earn_proj))
            for i, value in enumerate(base['projections'], 1):
                lines.append(f"  Year {i}: ${value/1e9:.2f}B")
        lines.append(
            "  NOTE: RAICA model estimate — the median of the historical CAGR, the analyst "
            "FORWARD consensus, and a 5% sustainable anchor. Not a pure analyst consensus, "
            "and not a pure historical extrapolation."
        )

        return "\n".join(lines)

    def _format_fcf_projections(self, fcf_proj: Dict) -> str:
        """Format FCF projections."""
        if not fcf_proj:
            return ""

        lines = ["FREE CASH FLOW PROJECTIONS:"]

        if 'current' in fcf_proj:
            src = fcf_proj.get('current_source')
            src_tag = f"  [{src}]" if src else ""
            lines.append(f"  Current FCF: ${fcf_proj['current']/1e9:.2f}B{src_tag}")

        if 'historical_growth' in fcf_proj and fcf_proj['historical_growth'] is not None:
            lines.append(f"  Historical CAGR (raw, uncapped): {fcf_proj['historical_growth']*100:.1f}%")
        if 'base_case' in fcf_proj:
            base = fcf_proj['base_case']
            lines.append(f"\nProjected Growth: {base['growth_rate']*100:.1f}%")
            lines.extend(self._growth_derivation_lines(fcf_proj))
            for i, value in enumerate(base['projections'], 1):
                lines.append(f"  Year {i}: ${value/1e9:.2f}B")
        lines.append(
            "  NOTE: RAICA model estimate — the median of the historical CAGR, the analyst "
            "FORWARD consensus, and a 5% sustainable anchor. Not a pure analyst consensus, "
            "and not a pure historical extrapolation."
        )

        return "\n".join(lines)
