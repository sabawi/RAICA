"""
src/ui/app.py

This module serves as the User Interface for the Stock Charting Application.
It utilizes Streamlit for the interactive web interface and Plotly for financial charting.
It integrates with the StockMarketService to fetch real-time data via Yahoo Finance.
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Third-party imports
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add root directory to path to ensure project modules can be imported
# This allows the script to run as standalone or as part of the package
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    # Project specific imports based on the provided architecture
    from src.services.stock_market_service import StockMarketService
    from src.config.config import Config
except ImportError as e:
    logger.error(f"Failed to import project modules: {e}")
    # We allow the app to load to display an error message in the UI rather than crashing immediately
    StockMarketService = None
    Config = None


class StockChartingApp:
    """
    Main class handling the UI logic, state management, and data visualization.
    """

    def __init__(self):
        self.service: Optional[StockMarketService] = None
        self._initialize_service()
        
        # Page Configuration
        st.set_page_config(
            page_title="ProTrade | Real-Time Analytics",
            page_icon="📈",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # Custom CSS for professional look
        self._apply_custom_styles()

    def _initialize_service(self):
        """Initialize the stock market service with error handling."""
        if StockMarketService is None:
            st.error("🚨 System Error: Backend services are unavailable. Check imports.")
            st.stop()
        
        try:
            self.service = StockMarketService()
            logger.info("StockMarketService initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing StockMarketService: {e}")
            st.error(f"Failed to initialize data service: {e}")

    def _apply_custom_styles(self):
        """Inject custom CSS for a dark-themed, professional financial dashboard."""
        st.markdown("""
        <style>
            .main {
                background-color: #0e1117;
                color: #ffffff;
            }
            h1 {
                color: #ffffff;
                font-size: 2.5rem;
                font-weight: 700;
            }
            .stMetric {
                background-color: #1e2129;
                border: 1px solid #2b303b;
                border-radius: 5px;
                padding: 10px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            }
            .stMetric label {
                color: #a0a0a0;
                font-size: 0.9rem;
            }
            .stMetric [data-testid="stMetricValue"] {
                color: #ffffff;
                font-size: 1.5rem;
                font-weight: 600;
            }
            /* Scrollbar customization */
            ::-webkit-scrollbar {
                width: 8px;
            }
            ::-webkit-scrollbar-track {
                background: #0e1117; 
            }
            ::-webkit-scrollbar-thumb {
                background: #262730; 
                border-radius: 4px;
            }
            ::-webkit-scrollbar-thumb:hover {
                background: #3d3f4b; 
            }
        </style>
        """, unsafe_allow_html=True)

    def render_sidebar(self) -> Dict[str, Any]:
        """Render the sidebar controls and return user inputs."""
        with st.sidebar:
            st.header("⚙️ Configuration")
            
            # Ticker Input
            default_ticker = st.session_state.get('ticker', 'AAPL')
            ticker = st.text_input(
                "Stock Ticker Symbol", 
                value=default_ticker, 
                max_chars=5, 
                upper=True,
                help="Enter the stock symbol (e.g., AAPL, TSLA, MSFT)"
            ).strip().upper()
            
            st.session_state['ticker'] = ticker

            # Timeframe Selection
            timeframe_options = {
                "1 Day": "1d",
                "5 Days": "5d",
                "1 Month": "1mo",
                "3 Months": "3mo",
                "6 Months": "6mo",
                "1 Year": "1y",
                "5 Years": "5y",
                "Max": "max"
            }
            
            selected_period_label = st.selectbox(
                "Time Period",
                options=list(timeframe_options.keys()),
                index=2 # Default to 1 Month
            )
            period = timeframe_options[selected_period_label]

            # Interval Selection
            interval_options = {
                "1 Minute": "1m",
                "5 Minutes": "5m",
                "15 Minutes": "15m",
                "30 Minutes": "30m",
                "1 Hour": "1h",
                "1 Day": "1d",
                "1 Week": "1wk"
            }
            
            # Logic to restrict interval based on period (Yahoo Finance limitations)
            available_intervals = ["1d"] 
            if period in ["1d", "5d"]:
                available_intervals = ["1m", "5m", "15m", "30m", "1h", "1d"]
            elif period in ["1mo", "3mo"]:
                available_intervals = ["5m", "15m", "30m", "1h", "1d", "1wk"]
            elif period in ["6mo", "1y"]:
                available_intervals = ["30m", "1h", "1d", "1wk"]
            elif period in ["5y", "max"]:
                available_intervals = ["1d", "1wk"]

            # Filter options based on availability
            valid_interval_labels = [k for k, v in interval_options.items() if v in available_intervals]
            
            selected_interval_label = st.selectbox(
                "Candlestick Interval",
                options=valid_interval_labels,
                index=len(valid_interval_labels) - 1
            )
            interval = interval_options[selected_interval_label]

            st.divider()
            
            # Action Buttons
            col_a, col_b = st.columns(2)
            with col_a:
                refresh_btn = st.button("🔄 Refresh", use_container_width=True, type="primary")
            with col_b:
                if st.button("🗑️ Reset", use_container_width=True):
                    st.session_state.clear()
                    st.rerun()

        return {
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "refresh": refresh_btn
        }

    def fetch_data(self, ticker: str, period: str, interval: str):
        """
        Fetch historical and quote data using the StockMarketService.
        Includes robust error handling for network issues and invalid tickers.
        """
        if not self.service:
            return None, None, "Service unavailable"

        try:
            with st.spinner(f"Fetching real-time data for {ticker}..."):
                # 1. Get Historical Data
                df = self.service.get_historical_data(ticker, period, interval)
                
                if df is None or df.empty:
                    return None, None, f"No historical data found for ticker '{ticker}'. It may be delisted or invalid."

                # 2. Get Current Quote (Live Price)
                quote = self.service.get_current_quote(ticker)
                
                if quote is None:
                    # Fallback to last row of historical data if live quote fails
                    logger.warning(f"Live quote failed for {ticker}, using last close.")
                    last_row = df.iloc[-1]
                    quote = {
                        'regularMarketPrice': last_row['Close'],
                        'previousClose': last_row['Close'] * 0.99, # Rough estimate for delta calculation
                        'regularMarketVolume': last_row['Volume']
                    }

            return df, quote, None

        except Exception as e:
            logger.exception(f"Error fetching data for {ticker}")
            return None, None, str(e)

    def render_metrics(self, quote: Dict[str, Any], ticker: str):
        """Render the key metrics cards at the top of the dashboard."""
        current_price = quote.get('regularMarketPrice', 0)
        prev_close = quote.get('previousClose', 0)
        
        # Calculate change
        change = current_price - prev_close
        percent_change = (change / prev_close) * 100 if prev_close != 0 else 0
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="Current Price", 
                value=f"{current_price:.2f}", 
                delta=f"{change:+.2f} ({percent_change:+.2f}%)"
            )
            
        with col2:
            st.metric(
                label="Previous Close", 
                value=f"{prev_close:.2f}"
            )
            
        with col3:
            st.metric(
                label="Volume", 
                value=f"{quote.get('regularMarketVolume', 0):,}"
            )
            
        with col4:
            market_cap = quote.get('marketCap', 0)
            if market_cap > 1e12:
                mc_display = f"{market_cap/1e12:.2f}T"
            elif market_cap > 1e9:
                mc_display = f"{market_cap/1e9:.2f}B"
            elif market_cap > 1e6:
                mc_display = f"{market_cap/1e6:.2f}M"
            else:
                mc_display = f"{market_cap:,.0f}"
                
            st.metric(
                label="Market Cap", 
                value=mc_display
            )

    def render_chart(self, df: pd.DataFrame, ticker: str):
        """
        Render an interactive financial chart using Plotly.
        Includes Candlesticks, Volume, and Moving Averages.
        """
        # Technical Indicators (Simple Moving Averages)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA50'] = df['Close'].rolling(window=50).mean()

        # Create Subplots
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.03, 
            row_heights=[0.7, 0.3],
            subplot_titles=(f'{ticker} Price Action', 'Volume')
        )

        # Candlestick
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name='OHLC',
                increasing_line_color='#26a69a',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

        # Moving Averages
        if not df['MA20'].dropna().empty:
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=df['MA20'],
                    mode='lines', name='MA 20',
                    line=dict(color='orange', width=1)
                ), row=1, col=1
            )
        
        if not df['MA50'].dropna().empty:
            fig.add_trace(
                go.Scatter(
                    x=df.index, y=df['MA50'],
                    mode='lines', name='MA 50',
                    line=dict(color='blue', width=1)
                ), row=1, col=1
            )

        # Volume Bar Chart
        colors = ['#26a69a' if row['Open'] < row['Close'] else '#ef5350' for index, row in df.iterrows()]
        
        fig.add_trace(
            go.Bar(
                x=df.index, y=df['Volume'],
                name='Volume',
                marker_color=colors,
                opacity=0.7
            ),
            row=2, col=1
        )

        # Layout Styling
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            template='plotly_dark',
            height=800,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1
            )
        )
        
        fig.update_xaxes(
            title_text="Date",
            rangeselector=dict(
                buttons=list([
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(step="all")
                ])
            ),
            row=2, col=1
        )
        
        fig.update_yaxes(title_text="Price ($)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)

        st.plotly_chart(fig, use_container_width=True)

    def run(self):
        """Main execution loop for the Streamlit app."""
        params = self.render_sidebar()
        
        # Header
        st.title(f"📊 {params['ticker']} Real-Time Analysis")
        st.caption(f"Data Source: Yahoo Finance | Interval: {params['interval']} | Period: {params['period']}")
        
        # Fetch Data
        df, quote, error = self.fetch_data(
            ticker=params['ticker'], 
            period=params['period'], 
            interval=params['interval']
        )
        
        if error:
            st.error(error)
            st.info("Please check the Ticker Symbol or try again later.")
        elif df is not None and quote is not None:
            # Render Dashboard
            self.render_metrics(quote, params['ticker'])
            st.divider()
            self.render_chart(df, params['ticker'])
            
            # Data Table Toggle
            with st.expander("View Raw Data"):
                st.dataframe(df.sort_index(ascending=False), height=300)

if __name__ == "__main__":
    app = StockChartingApp()
    app.run()