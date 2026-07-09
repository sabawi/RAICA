"""
Financial Ratio Calculator

Calculates comprehensive financial ratios from financial statements.

Part of: FUNDAMENTAL_ANALYSIS_DCF_IMPLEMENTATION_PLAN.md - Day 3 Implementation
"""

import pandas as pd
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class FinancialRatioCalculator:
    """
    Calculate comprehensive financial ratios.

    Categories:
    - Profitability: Gross Margin, Operating Margin, Net Margin, ROA, ROE, ROIC
    - Liquidity: Current Ratio, Quick Ratio, Cash Ratio
    - Leverage: Debt/Equity, Debt/Assets, Interest Coverage
    - Efficiency: Asset Turnover, Inventory Turnover, Receivables Turnover
    - Valuation: P/E, P/B, P/S, EV/EBITDA, P/FCF
    """

    def __init__(self):
        """Initialize the calculator."""
        pass

    def _safe_divide(self, numerator, denominator, default=None):
        """Safely divide two numbers, handling None and zero cases."""
        try:
            if numerator is None or denominator is None:
                return default
            if pd.isna(numerator) or pd.isna(denominator):
                return default
            if denominator == 0:
                return default
            return numerator / denominator
        except:
            return default

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

    def _freshest_balance_sheet(self, financials: Dict):
        """Return (DataFrame, label) for the most-recent balance sheet available.

        v1.0.0.160 — prefer the QUARTERLY balance sheet (column 0 = most-recent quarter) over the
        annual statement, which can be a full fiscal year stale. yfinance returns columns most-recent
        first, so column 0 is always the freshest period.
        """
        bs = financials.get('balance_sheet', {}) or {}
        quarterly = bs.get('quarterly')
        if quarterly is not None and not quarterly.empty:
            return quarterly, 'quarterly'
        return bs.get('annual'), 'annual'

    def _freshest_income_stmt(self, financials: Dict):
        """Return (DataFrame, label) for the most-recent income statement available (quarterly→annual)."""
        is_data = financials.get('income_statement', {}) or {}
        quarterly = is_data.get('quarterly')
        if quarterly is not None and not quarterly.empty:
            return quarterly, 'quarterly'
        return is_data.get('annual'), 'annual'

    def _avg_value(self, df: pd.DataFrame, key: str, n: int = 2):
        """Average of the n most-recent column values (for balance-sheet stock items).

        Averaging the two most-recent quarters smooths quarter-end noise (e.g. buyback-driven equity
        dips) that a single ending balance would amplify. Falls back to a single value if fewer columns.
        """
        try:
            if df is None or df.empty or key not in df.index:
                return None
            cols = list(df.columns)[:n]
            vals = [df.loc[key, c] for c in cols]
            vals = [v for v in vals if v is not None and not pd.isna(v)]
            if not vals:
                return None
            return sum(vals) / len(vals)
        except Exception:
            return None

    def _ttm_value(self, df: pd.DataFrame, key: str, n: int = 4):
        """Sum of the n most-recent quarterly column values (trailing-twelve-month for flow items)."""
        try:
            if df is None or df.empty or key not in df.index:
                return None
            cols = list(df.columns)[:n]
            vals = [df.loc[key, c] for c in cols]
            vals = [v for v in vals if v is not None and not pd.isna(v)]
            if not vals:
                return None
            return sum(vals)
        except Exception:
            return None

    def calculate_profitability_ratios(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame,
                                       ticker_info: Dict = None, quarterly_income: pd.DataFrame = None) -> Dict[str, Any]:
        """Calculate profitability ratios.

        v1.0.0.160 — ROE/ROA/ROIC freshness + NOPAT fix. Previously these used ending ANNUAL balances
        and net income, which (a) was a full fiscal year stale and (b) understated ROIC vs trackers
        because net income < NOPAT. Now: TTM net income (``info['netIncomeToCommon']``) over averaged
        most-recent quarterly balance-sheet figures; ROIC uses NOPAT (TTM operating income × (1−tax)).
        Margins remain on the annual statement (full-year ratios are representative; no TTM gross/operating
        field exists in yfinance info).
        """
        ratios = {}
        ticker_info = ticker_info or {}

        # Margins — from the annual income statement (full-year ratios, stable/representative)
        revenue = self._get_value(income_stmt, 'Total Revenue')
        gross_profit = self._get_value(income_stmt, 'Gross Profit')
        operating_income = self._get_value(income_stmt, 'Operating Income')
        net_income = self._get_value(income_stmt, 'Net Income')

        if revenue and gross_profit:
            ratios['gross_margin'] = (gross_profit / revenue) * 100
        if revenue and operating_income:
            ratios['operating_margin'] = (operating_income / revenue) * 100
        if revenue and net_income:
            ratios['net_margin'] = (net_income / revenue) * 100

        # ROE/ROA — TTM net income (numerator) over averaged most-recent quarterly balances (denominator)
        ttm_ni = ticker_info.get('netIncomeToCommon')
        ni_for_return = float(ttm_ni) if ttm_ni else net_income
        ni_source = 'TTM (info.netIncomeToCommon)' if ttm_ni else ('annual net income (stale)' if net_income else None)

        avg_assets = self._avg_value(balance_sheet, 'Total Assets')
        avg_equity = self._avg_value(balance_sheet, 'Stockholders Equity')

        if avg_assets and ni_for_return:
            ratios['roa'] = (ni_for_return / avg_assets) * 100
        if avg_equity and ni_for_return:
            ratios['roe'] = (ni_for_return / avg_equity) * 100

        # ROIC = NOPAT / Invested Capital, where NOPAT = Operating Income × (1 − tax rate)
        # and Invested Capital = Total Debt + Stockholders Equity (averaged). NOPAT (not net income)
        # is the economic return on invested capital — this is why the old net-income ROIC understated
        # vs trackers (e.g. META 20.08% vs 31.38%).
        op_income_ttm = self._ttm_value(quarterly_income, 'Operating Income') if quarterly_income is not None else None
        if not op_income_ttm:
            op_income_ttm = operating_income  # annual fallback
        pretax = self._get_value(income_stmt, 'Pretax Income')
        tax_prov = self._get_value(income_stmt, 'Tax Provision')
        tax_rate = (tax_prov / pretax) if (pretax and tax_prov and pretax > 0) else 0.21

        total_debt = self._avg_value(balance_sheet, 'Total Debt')
        if not total_debt:
            long_term_debt = self._avg_value(balance_sheet, 'Long Term Debt') or 0
            current_debt = self._avg_value(balance_sheet, 'Current Debt') or 0
            total_debt = long_term_debt + current_debt if (long_term_debt or current_debt) else None

        if op_income_ttm and total_debt is not None and avg_equity:
            invested_capital = total_debt + avg_equity
            if invested_capital > 0:
                nopat = op_income_ttm * (1 - tax_rate)
                ratios['roic'] = (nopat / invested_capital) * 100
                ratios['roic_basis'] = 'NOPAT (TTM operating income × (1−tax)) / avg invested capital'

        if ni_source and 'stale' in (ni_source or ''):
            ratios['profitability_note'] = (
                "⚠️ ROE/ROA use last fiscal-year net income (TTM netIncomeToCommon unavailable); "
                "balance-sheet denominators are averaged most-recent quarterly. Treat as directional."
            )

        return ratios

    def calculate_liquidity_ratios(self, balance_sheet: pd.DataFrame) -> Dict[str, Any]:
        """Calculate liquidity ratios."""
        ratios = {}

        current_assets = self._get_value(balance_sheet, 'Current Assets')
        current_liabilities = self._get_value(balance_sheet, 'Current Liabilities')
        cash = self._get_value(balance_sheet, 'Cash And Cash Equivalents')
        inventory = self._get_value(balance_sheet, 'Inventory')
        accounts_receivable = self._get_value(balance_sheet, 'Accounts Receivable')

        # Current Ratio
        if current_assets and current_liabilities:
            ratios['current_ratio'] = current_assets / current_liabilities

        # Quick Ratio (exclude inventory)
        if current_assets and inventory is not None and current_liabilities:
            quick_assets = current_assets - inventory
            ratios['quick_ratio'] = quick_assets / current_liabilities

        # Cash Ratio
        if cash and current_liabilities:
            ratios['cash_ratio'] = cash / current_liabilities

        return ratios

    def calculate_leverage_ratios(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame,
                                   quarterly_income: pd.DataFrame = None) -> Dict[str, Any]:
        """Calculate leverage ratios.

        v1.0.0.160 — Interest coverage now uses TTM (4-quarter sum) operating income / abs(TTM interest
        expense), falling back to the annual statement. yfinance's annual Interest Expense can be a tiny
        residual (e.g. GOOGL carries far more interest income than expense), so dividing a stale annual
        operating income by a tiny stale denominator printed an outsized ratio (175x) matching no live
        source. A note is emitted when the denominator is negligible rather than silently printing a
        misleading multiple.
        """
        ratios = {}

        total_assets = self._get_value(balance_sheet, 'Total Assets')
        stockholders_equity = self._get_value(balance_sheet, 'Stockholders Equity')

        # Calculate total debt
        total_debt = self._get_value(balance_sheet, 'Total Debt')
        if not total_debt:
            long_term_debt = self._get_value(balance_sheet, 'Long Term Debt') or 0
            current_debt = self._get_value(balance_sheet, 'Current Debt') or 0
            total_debt = long_term_debt + current_debt if (long_term_debt or current_debt) else None

        # Debt to Equity
        if total_debt and stockholders_equity:
            ratios['debt_to_equity'] = total_debt / stockholders_equity

        # Debt to Assets
        if total_debt and total_assets:
            ratios['debt_to_assets'] = (total_debt / total_assets) * 100

        # Interest Coverage — TTM (4-quarter sum); annual fallback
        op_income_ttm = self._ttm_value(quarterly_income, 'Operating Income') if quarterly_income is not None else None
        int_exp_ttm = self._ttm_value(quarterly_income, 'Interest Expense') if quarterly_income is not None else None
        cov_source = 'TTM (4-quarter sum)'
        if op_income_ttm is None:
            op_income_ttm = self._get_value(income_stmt, 'Operating Income')
            cov_source = 'annual (stale)'
        if int_exp_ttm is None:
            int_exp_ttm = self._get_value(income_stmt, 'Interest Expense')

        if op_income_ttm and int_exp_ttm and int_exp_ttm != 0:
            ratios['interest_coverage'] = op_income_ttm / abs(int_exp_ttm)
            # Negligible interest expense → the multiple is not a meaningful coverage figure
            if op_income_ttm > 0 and (op_income_ttm / abs(int_exp_ttm)) > 100:
                ratios['interest_coverage_note'] = (
                    f"⚠️ Interest coverage {ratios['interest_coverage']:.1f}x is very high because interest "
                    f"expense is negligible relative to operating income (interest income ≫ expense). "
                    f"Treat as 'effectively no interest burden', not a precise multiple. [{cov_source}]"
                )
            elif 'stale' in cov_source:
                ratios['interest_coverage_note'] = (
                    "⚠️ Interest coverage based on last fiscal-year figures (quarterly unavailable); "
                    "treat as directional."
                )

        return ratios

    def calculate_efficiency_ratios(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> Dict[str, Any]:
        """Calculate efficiency ratios."""
        ratios = {}

        revenue = self._get_value(income_stmt, 'Total Revenue')
        cost_of_revenue = self._get_value(income_stmt, 'Cost Of Revenue')
        total_assets = self._get_value(balance_sheet, 'Total Assets')
        inventory = self._get_value(balance_sheet, 'Inventory')
        accounts_receivable = self._get_value(balance_sheet, 'Accounts Receivable')

        # Asset Turnover
        if revenue and total_assets:
            ratios['asset_turnover'] = revenue / total_assets

        # Inventory Turnover
        if cost_of_revenue and inventory:
            ratios['inventory_turnover'] = cost_of_revenue / inventory

        # Receivables Turnover
        if revenue and accounts_receivable:
            ratios['receivables_turnover'] = revenue / accounts_receivable
            # Days Sales Outstanding
            ratios['days_sales_outstanding'] = 365 / ratios['receivables_turnover']

        return ratios

    def calculate_valuation_ratios(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame,
                                   cash_flow: pd.DataFrame, market_data: Dict,
                                   ticker_info: Dict = None) -> Dict[str, Any]:
        """Calculate valuation ratios.

        v1.0.0.159 — TTM-FIRST sourcing. yfinance's ``info`` carries trailing-twelve-month fields
        (``trailingEps``, ``trailingPE``, ``forwardPE``, ``freeCashflow``, ``totalRevenue``,
        ``ebitda``) that are internally consistent with the live price. The last ANNUAL fiscal-year
        statement can be months stale, so computing P/E = live_price / (annual_net_income / shares)
        mixes a stale denominator with a live numerator and massively distorts P/E & DCF for any
        stock whose TTM earnings diverge from the last fiscal year (e.g. a cyclical in a turning
        cycle — see MU: annual NI $8.54B vs TTM NI $50.47B → computed P/E 125 vs true 21).

        Policy here: prefer TTM (``ticker_info``) for EPS, P/E, forward P/E, P/S, P/FCF, EV/EBITDA;
        fall back to the annual statement only when a TTM field is absent; and emit a staleness
        note whenever the live price is being compared against a stale annual figure so the
        synthesis can never silently cite a distorted ratio as "current".
        """
        ratios = {}
        ticker_info = ticker_info or {}

        # Extract market data
        current_price = market_data.get('current_price')
        market_cap = market_data.get('market_cap')
        shares_outstanding = market_data.get('shares_outstanding')

        # Extract financial data (annual statement — used as FALLBACK only)
        net_income = self._get_value(income_stmt, 'Net Income')
        revenue = self._get_value(income_stmt, 'Total Revenue')
        stockholders_equity = self._get_value(balance_sheet, 'Stockholders Equity')
        operating_cash_flow = self._get_value(cash_flow, 'Operating Cash Flow')
        capex = self._get_value(cash_flow, 'Capital Expenditure')

        # Prefer yfinance's authoritative TTM shares outstanding over derived
        ttm_shares = ticker_info.get('sharesOutstanding')
        if ttm_shares:
            shares_outstanding = ttm_shares

        # Calculate shares outstanding from market cap and price if still not provided
        if not shares_outstanding and market_cap and current_price and current_price > 0:
            shares_outstanding = market_cap / current_price

        # --- Earnings per share: TTM-first ---
        trailing_eps = ticker_info.get('trailingEps')
        eps = None
        eps_source = None
        if trailing_eps and trailing_eps > 0:
            eps = float(trailing_eps)
            eps_source = 'TTM (trailingEps)'
        elif net_income and shares_outstanding and shares_outstanding > 0:
            eps = net_income / shares_outstanding
            eps_source = 'annual net income / shares (stale)'
        if eps is not None:
            ratios['eps'] = eps
            ratios['eps_source'] = eps_source

        # --- P/E Ratio: TTM-first, with annual cross-check + staleness note ---
        trailing_pe = ticker_info.get('trailingPE')
        pe_computed_annual = None
        if current_price and net_income and shares_outstanding and shares_outstanding > 0:
            eps_annual = net_income / shares_outstanding
            if eps_annual and eps_annual > 0:
                pe_computed_annual = current_price / eps_annual

        if trailing_pe and trailing_pe > 0:
            ratios['pe_ratio'] = float(trailing_pe)
            ratios['pe_source'] = 'TTM (trailingPE)'
        elif current_price and eps and eps > 0:
            ratios['pe_ratio'] = current_price / eps
            ratios['pe_source'] = eps_source or 'computed'

        # Staleness flag: live price vs annual-figure P/E diverges > 20% from TTM
        if (trailing_pe and pe_computed_annual and trailing_pe > 0
                and abs(pe_computed_annual - trailing_pe) / trailing_pe > 0.20):
            ratios['pe_note'] = (
                f"⚠️ P/E staleness: live price vs annual-figure P/E = {pe_computed_annual:.1f} "
                f"diverges {abs(pe_computed_annual-trailing_pe)/trailing_pe*100:.0f}% from TTM P/E "
                f"{trailing_pe:.1f}. The annual income statement is stale; USE the TTM P/E "
                f"{trailing_pe:.1f}."
            )

        # --- Forward P/E (v1.0.0.159 TTM-first; v1.0.0.160 relabel) ---
        # yfinance's forwardPE is typically based on the next fiscal-year EPS estimate; for non-calendar
        # fiscal-year stocks (META/AMZN/ORCL/MU) that can be ~FY+2 and UNDERSTATE the true next-12-month
        # forward P/E. No clean NTM EPS is exposed, so relay it with an explicit approximation note rather
        # than presenting it as a precise forward multiple.
        forward_pe = ticker_info.get('forwardPE')
        if forward_pe and forward_pe > 0:
            ratios['forward_pe'] = float(forward_pe)
            ratios['forward_pe_note'] = (
                "⚠️ Forward P/E is yfinance's forwardPE — typically next-fiscal-year EPS, which for "
                "non-calendar fiscal-year stocks can be ~FY+2 and understate the true next-12-month "
                "forward P/E. Treat as approximate; do not present as a precise NTM multiple."
            )

        # --- P/B Ratio: prefer yfinance TTM priceToBook; fall back to quarterly equity / shares ---
        # v1.0.0.160 — previously divided a live price by STALE ANNUAL equity (with TTM shares),
        # distorting P/B (e.g. MU 19.78 vs ~10.9, GOOGL 5.11 vs ~9.2). priceToBook is yfinance's
        # authoritative TTM ratio; the equity fallback now uses the most-recent quarterly balance sheet.
        pb = ticker_info.get('priceToBook')
        if pb and pb > 0:
            ratios['pb_ratio'] = float(pb)
            ratios['pb_source'] = 'TTM (info.priceToBook)'
        elif current_price and stockholders_equity and shares_outstanding and shares_outstanding > 0:
            book_value_per_share = stockholders_equity / shares_outstanding
            if book_value_per_share > 0:
                ratios['pb_ratio'] = current_price / book_value_per_share
                ratios['pb_source'] = 'price / (most-recent equity per share)'
                ratios['pb_note'] = (
                    "⚠️ P/B computed from the most-recent balance-sheet equity (priceToBook unavailable). "
                    "If the balance sheet is stale, P/B may be distorted."
                )

        # --- P/S Ratio: TTM revenue first ---
        ttm_revenue = ticker_info.get('totalRevenue')
        ps_revenue = None
        if ttm_revenue and ttm_revenue > 0:
            ps_revenue = float(ttm_revenue)
        elif revenue and revenue > 0:
            ps_revenue = revenue
        if market_cap and ps_revenue:
            ratios['ps_ratio'] = market_cap / ps_revenue

        # --- P/FCF Ratio: TTM freeCashflow first ---
        ttm_fcf = ticker_info.get('freeCashflow')
        if ttm_fcf and ttm_fcf > 0 and market_cap:
            ratios['pfcf_ratio'] = market_cap / float(ttm_fcf)
        elif operating_cash_flow and capex is not None:
            fcf = operating_cash_flow + capex  # capex is negative
            if fcf > 0 and market_cap:
                ratios['pfcf_ratio'] = market_cap / fcf

        # EV/EBITDA — prefer yfinance TTM ebitda; fall back to annual operating-income proxy
        ttm_ebitda = ticker_info.get('ebitda')
        total_debt = self._get_value(balance_sheet, 'Total Debt')
        if not total_debt:
            long_term_debt = self._get_value(balance_sheet, 'Long Term Debt') or 0
            current_debt = self._get_value(balance_sheet, 'Current Debt') or 0
            total_debt = long_term_debt + current_debt if (long_term_debt or current_debt) else 0
        cash = self._get_value(balance_sheet, 'Cash And Cash Equivalents') or 0

        if market_cap and total_debt is not None:
            enterprise_value = market_cap + total_debt - cash
            if ttm_ebitda and ttm_ebitda > 0:
                ratios['ev_ebitda'] = enterprise_value / float(ttm_ebitda)
            else:
                operating_income = self._get_value(income_stmt, 'Operating Income')
                if operating_income and operating_income > 0:
                    ratios['ev_ebitda'] = enterprise_value / operating_income

        return ratios

    def calculate_all_ratios(self, financials: Dict, market_data: Dict) -> Dict[str, Any]:
        """
        Calculate all financial ratios.

        Args:
            financials: Financial statements from extractor
            market_data: Market data (price, shares, market cap)

        Returns:
            Dictionary of all calculated ratios by category
        """
        logger.info("Calculating comprehensive financial ratios")

        if not financials:
            logger.warning("No financial data available for ratio calculation")
            return {
                'profitability': {},
                'liquidity': {},
                'leverage': {},
                'efficiency': {},
                'valuation': {}
            }

        # Extract financial statements
        income_stmt = financials.get('income_statement', {}).get('annual')
        cash_flow = financials.get('cash_flow', {}).get('annual')
        ticker_info = financials.get('ticker_info', {}) or {}

        # v1.0.0.160 — freshest balance sheet & income statement: prefer QUARTERLY (most-recent column)
        # over the annual statement, which can be a full fiscal year stale. Quarterly is already fetched
        # by the extractor but was never consumed before this version.
        balance_sheet, _ = self._freshest_balance_sheet(financials)
        quarterly_income, _ = self._freshest_income_stmt(financials)

        return {
            'profitability': self.calculate_profitability_ratios(income_stmt, balance_sheet, ticker_info, quarterly_income),
            'liquidity': self.calculate_liquidity_ratios(balance_sheet),
            'leverage': self.calculate_leverage_ratios(income_stmt, balance_sheet, quarterly_income),
            'efficiency': self.calculate_efficiency_ratios(income_stmt, balance_sheet),
            'valuation': self.calculate_valuation_ratios(income_stmt, balance_sheet, cash_flow, market_data, ticker_info)
        }

    def _format_source_block(self, source_num: int, title: str, url: str, date: str, content: str) -> str:
        """
        Format content into standardized SOURCE block format for LLM context.

        This follows the Context Engineering Citation Mastery format.

        Args:
            source_num: Sequential source number
            title: Title of the analysis
            url: URL to the source
            date: Analysis date
            content: Formatted ratio data

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

    def format_ratios_for_llm(self, ratios: Dict, ticker: str = None) -> str:
        """
        Format calculated ratios for LLM consumption in SOURCE block format.

        Args:
            ratios: Dictionary of calculated ratios
            ticker: Stock ticker for URL attribution

        Returns:
            Formatted string in SOURCE block format
        """
        if not ticker:
            ticker = "UNKNOWN"

        # Check if we have any ratios
        has_ratios = any(ratios.get(category) for category in ratios.keys())
        if not has_ratios:
            return "\n⚠️ **FINANCIAL RATIOS ANALYSIS** - Data not available\n"

        output = []
        source_num = 1
        current_date = pd.Timestamp.now().strftime('%Y-%m-%d')

        # Format each category as a separate SOURCE block

        # Profitability Ratios
        if ratios.get('profitability'):
            content = self._format_profitability_ratios(ratios['profitability'])
            source_block = self._format_source_block(
                source_num=source_num,
                title=f"{ticker} Profitability Ratios Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/key-statistics",
                date=current_date,
                content=content
            )
            output.append(source_block)
            source_num += 1

        # Liquidity Ratios
        if ratios.get('liquidity'):
            content = self._format_liquidity_ratios(ratios['liquidity'])
            source_block = self._format_source_block(
                source_num=source_num,
                title=f"{ticker} Liquidity Ratios Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/key-statistics",
                date=current_date,
                content=content
            )
            output.append(source_block)
            source_num += 1

        # Leverage Ratios
        if ratios.get('leverage'):
            content = self._format_leverage_ratios(ratios['leverage'])
            source_block = self._format_source_block(
                source_num=source_num,
                title=f"{ticker} Leverage Ratios Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/key-statistics",
                date=current_date,
                content=content
            )
            output.append(source_block)
            source_num += 1

        # Efficiency Ratios
        if ratios.get('efficiency'):
            content = self._format_efficiency_ratios(ratios['efficiency'])
            source_block = self._format_source_block(
                source_num=source_num,
                title=f"{ticker} Efficiency Ratios Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/key-statistics",
                date=current_date,
                content=content
            )
            output.append(source_block)
            source_num += 1

        # Valuation Ratios
        if ratios.get('valuation'):
            content = self._format_valuation_ratios(ratios['valuation'])
            source_block = self._format_source_block(
                source_num=source_num,
                title=f"{ticker} Valuation Ratios Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/key-statistics",
                date=current_date,
                content=content
            )
            output.append(source_block)
            source_num += 1

        return "\n".join(output)

    def _format_profitability_ratios(self, ratios: Dict) -> str:
        """Format profitability ratios."""
        lines = ["PROFITABILITY METRICS:"]

        if 'gross_margin' in ratios:
            lines.append(f"  Gross Margin: {ratios['gross_margin']:.2f}%")
        if 'operating_margin' in ratios:
            lines.append(f"  Operating Margin: {ratios['operating_margin']:.2f}%")
        if 'net_margin' in ratios:
            lines.append(f"  Net Margin: {ratios['net_margin']:.2f}%")
        if 'roa' in ratios:
            lines.append(f"  Return on Assets (ROA): {ratios['roa']:.2f}%")
        if 'roe' in ratios:
            lines.append(f"  Return on Equity (ROE): {ratios['roe']:.2f}%")
        if 'roic' in ratios:
            lines.append(f"  Return on Invested Capital (ROIC): {ratios['roic']:.2f}%")
        if 'roic_basis' in ratios:
            lines.append(f"  [ROIC basis: {ratios['roic_basis']}]")
        if 'profitability_note' in ratios:
            lines.append(f"  {ratios['profitability_note']}")

        return "\n".join(lines)

    def _format_liquidity_ratios(self, ratios: Dict) -> str:
        """Format liquidity ratios."""
        lines = ["LIQUIDITY METRICS:"]

        if 'current_ratio' in ratios:
            lines.append(f"  Current Ratio: {ratios['current_ratio']:.2f}")
        if 'quick_ratio' in ratios:
            lines.append(f"  Quick Ratio: {ratios['quick_ratio']:.2f}")
        if 'cash_ratio' in ratios:
            lines.append(f"  Cash Ratio: {ratios['cash_ratio']:.2f}")

        return "\n".join(lines)

    def _format_leverage_ratios(self, ratios: Dict) -> str:
        """Format leverage ratios."""
        lines = ["LEVERAGE METRICS:"]

        if 'debt_to_equity' in ratios:
            lines.append(f"  Debt to Equity: {ratios['debt_to_equity']:.2f}")
        if 'debt_to_assets' in ratios:
            lines.append(f"  Debt to Assets: {ratios['debt_to_assets']:.2f}%")
        if 'interest_coverage' in ratios:
            lines.append(f"  Interest Coverage: {ratios['interest_coverage']:.2f}x")
        if 'interest_coverage_note' in ratios:
            lines.append(f"  {ratios['interest_coverage_note']}")

        return "\n".join(lines)

    def _format_efficiency_ratios(self, ratios: Dict) -> str:
        """Format efficiency ratios."""
        lines = ["EFFICIENCY METRICS:"]

        if 'asset_turnover' in ratios:
            lines.append(f"  Asset Turnover: {ratios['asset_turnover']:.2f}x")
        if 'inventory_turnover' in ratios:
            lines.append(f"  Inventory Turnover: {ratios['inventory_turnover']:.2f}x")
        if 'receivables_turnover' in ratios:
            lines.append(f"  Receivables Turnover: {ratios['receivables_turnover']:.2f}x")
        if 'days_sales_outstanding' in ratios:
            lines.append(f"  Days Sales Outstanding: {ratios['days_sales_outstanding']:.1f} days")

        return "\n".join(lines)

    def _format_valuation_ratios(self, ratios: Dict) -> str:
        """Format valuation ratios."""
        lines = ["VALUATION METRICS:"]

        if 'eps' in ratios:
            src = ratios.get('eps_source')
            src_tag = f"  [{src}]" if src and 'TTM' not in (src or '') else ""
            lines.append(f"  Earnings Per Share (EPS): ${ratios['eps']:.2f}{src_tag}")
        if 'pe_ratio' in ratios:
            src = ratios.get('pe_source')
            src_tag = f"  [{src}]" if src else ""
            lines.append(f"  Price to Earnings (P/E): {ratios['pe_ratio']:.2f}{src_tag}")
        if 'forward_pe' in ratios:
            lines.append(f"  Forward P/E: {ratios['forward_pe']:.2f}")
        if 'forward_pe_note' in ratios:
            lines.append(f"  {ratios['forward_pe_note']}")
        if 'pb_ratio' in ratios:
            src = ratios.get('pb_source')
            src_tag = f"  [{src}]" if src else ""
            lines.append(f"  Price to Book (P/B): {ratios['pb_ratio']:.2f}{src_tag}")
        if 'pb_note' in ratios:
            lines.append(f"  {ratios['pb_note']}")
        if 'ps_ratio' in ratios:
            lines.append(f"  Price to Sales (P/S): {ratios['ps_ratio']:.2f}")
        if 'pfcf_ratio' in ratios:
            lines.append(f"  Price to Free Cash Flow (P/FCF): {ratios['pfcf_ratio']:.2f}")
        if 'ev_ebitda' in ratios:
            lines.append(f"  EV/EBITDA: {ratios['ev_ebitda']:.2f}")
        if 'pe_note' in ratios:
            lines.append(f"  {ratios['pe_note']}")

        return "\n".join(lines)
