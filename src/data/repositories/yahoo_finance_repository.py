"""
Yahoo Finance Repository
Provides real-time and historical stock data by integrating with the Yahoo Finance API via yfinance.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Union

import pandas as pd
import yfinance as yf

# Attempt to import the interface to adhere to the project's architecture.
# If the file structure hasn't been fully created by the user yet, we define a fallback ABC
# to ensure this file remains syntactically valid and functional for testing.
try:
    from src.data.repositories.istock_repository import IStockRepository
except ImportError:
    from abc import ABC, abstractmethod
    
    # Fallback Interface Definition
    class IStockRepository(ABC):
        @abstractmethod
        def get_historical_data(self, symbol: str, period: str, interval: str) -> List[Dict[str, Any]]:
            """Fetches historical OHLCV data."""
            pass

        @abstractmethod
        def get_current_price(self, symbol: str) -> Optional[float]:
            """Fetches the latest available market price."""
            pass
        
        @abstractmethod
        def get_stock_info(self, symbol: str) -> Dict[str, Any]:
            """Fetches metadata about the stock."""
            pass

# Configure logger for this module
logger = logging.getLogger(__name__)


class YahooFinanceRepository(IStockRepository):
    """
    Concrete implementation of IStockRepository using Yahoo Finance (yfinance).
    
    This class handles the complexity of fetching data, cleaning DataFrames,
    and handling common API edge cases such as empty results or multi-index columns.
    """

    def __init__(self) -> None:
        """
        Initializes the YahooFinanceRepository.
        """
        logger.info("Initializing YahooFinanceRepository")
        # Note: yfinance does not require explicit API keys for standard usage,
        # but it relies on underlying Yahoo Finance URLs which may change.
        # This library is actively maintained to handle such changes.

    def get_historical_data(
        self, 
        symbol: str, 
        period: str = "1y", 
        interval: str = "1d"
    ) -> List[Dict[str, Any]]:
        """
        Retrieves historical stock data for the given symbol.

        Args:
            symbol (str): The stock ticker (e.g., 'AAPL', 'MSFT').
            period (str): Data range to download. 
                          Options: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'.
            interval (str): Data interval. 
                           Options: '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo'.
                           Note: Intraday data (<1d) is typically limited to the last 729 days (60 days for 1m).

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, where each dictionary represents a time point
                                  with keys: 'date', 'open', 'high', 'low', 'close', 'volume'.
                                  Returns an empty list if data cannot be retrieved.
        """
        try:
            logger.debug(f"Fetching historical data for {symbol} | Period: {period} | Interval: {interval}")
            
            # Fetch data using yfinance
            # auto_adjust=True adjusts OHLC prices for splits and dividends automatically
            # prepost=True includes Pre-market and After-hours data
            df = yf.download(
                tickers=symbol,
                period=period,
                interval=interval,
                group_by='ticker',
                auto_adjust=True,
                prepost=True,
                threads=True
            )

            # Check if DataFrame is empty
            if df.empty:
                logger.warning(f"No data returned for {symbol} with period={period} and interval={interval}")
                return []

            # Handling MultiIndex columns (occurs if fetching multiple tickers or specific yfinance versions)
            if isinstance(df.columns, pd.MultiIndex):
                if symbol in df.columns.levels[0]:
                    df = df[symbol]
                else:
                    # Fallback: select the first ticker column if symbol match fails
                    df = df.iloc[:, 0]

            # Reset index to make Date/Datetime a column
            df.reset_index(inplace=True)

            # Standardize column names
            # yfinance usually returns 'Date' for daily and 'Datetime' for intraday
            date_col = 'Date' if 'Date' in df.columns else 'Datetime'
            
            required_cols_mapping = {
                date_col: 'date',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }

            # Filter to only existing columns to prevent KeyError
            cols_to_rename = {k: v for k, v in required_cols_mapping.items() if k in df.columns}
            
            if not cols_to_rename:
                logger.error(f"Expected columns not found in data for {symbol}. Columns found: {df.columns}")
                return []

            df = df[list(cols_to_rename.keys())].copy()
            df.rename(columns=cols_to_rename, inplace=True)

            # Data Cleaning
            # Convert date to ISO format string for JSON serialization
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                # Remove timezone info for simpler serialization if desired, or keep it. 
                # Here we convert to UTC then ISO to ensure consistency.
                if df['date'].dt.tz is None:
                    df['date'] = df['date'].dt.tz_localize('UTC')
                else:
                    df['date'] = df['date'].dt.tz_convert('UTC')
                    
                df['date'] = df['date'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Convert numeric types to handle NaNs and ensure float/int types
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Drop rows with NaN in critical columns (Close)
            df.dropna(subset=['close'], inplace=True)

            # Convert to list of dictionaries
            result = df.to_dict(orient='records')
            
            logger.info(f"Successfully retrieved {len(result)} data points for {symbol}")
            return result

        except Exception as e:
            logger.error(f"Exception in get_historical_data for {symbol}: {str(e)}", exc_info=True)
            return []

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Retrieves the most recent price for the given symbol.
        This attempts to get real-time data during market hours or the last closing price.

        Args:
            symbol (str): The stock ticker.

        Returns:
            Optional[float]: The current price or None if unavailable.
        """
        try:
            logger.debug(f"Fetching current price for {symbol}")
            ticker = yf.Ticker(symbol)

            # Strategy 1: Use fast_info for real-time data (lightweight)
            # Note: fast_info properties might not be available immediately after instantiation
            if hasattr(ticker, 'fast_info'):
                try:
                    price = ticker.fast_info.last_price
                    if price is not None:
                        return float(price)
                except Exception:
                    pass # Fallback to standard history fetch

            # Strategy 2: Fetch the most recent 1 minute candle
            # We fetch 1 day of 1m data to get the very last tick
            # prepost=True is important for extended hours trading
            df = ticker.history(period="1d", interval="1m", prepost=True)
            
            if not df.empty:
                # The last row represents the most recent completed minute
                last_row = df.iloc[-1]
                
                # Prefer 'Close' if available, otherwise 'Last' or fallback
                price = last_row.get('Close')
                
                if pd.notna(price):
                    return float(price)
                
                # Some variations of yfinance or index types might use different keys
                if 'Open' in last_row and pd.notna(last_row['Open']):
                    # As a last resort, use Open if Close is missing (rare)
                    return float(last_row['Open'])

            # Strategy 3: Fallback to previous day's close if no intraday data
            # (e.g., market is closed and extended hours data isn't available)
            df_prev = ticker.history(period="5d", interval="1d")
            if not df_prev.empty:
                last_close = df_prev['Close'].iloc[-1]
                if pd.notna(last_close):
                    return float(last_close)

            logger.warning(f"Could not determine current price for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Exception in get_current_price for {symbol}: {str(e)}", exc_info=True)
            return None

    def get_stock_info(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieves metadata about the stock.

        Args:
            symbol (str): The stock ticker.

        Returns:
            Dict[str, Any]: Dictionary containing company details.
        """
        try:
            logger.debug(f"Fetching stock info for {symbol}")
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Normalize and extract relevant fields to avoid sending massive payloads
            # or sensitive/irrelevant data
            extracted_info = {
                'symbol': symbol.upper(),
                'longName': info.get('longName'),
                'shortName': info.get('shortName'),
                'exchange': info.get('exchange'),
                'market': info.get('market'),
                'currency': info.get('currency'),
                'industry': info.get('industry'),
                'sector': info.get('sector'),
                'website': info.get('website'),
                'logo_url': info.get('logo_url'),
                'type': info.get('quoteType'), # e.g. EQUITY, ETF
                'timezone': info.get('timeZoneFullName')
            }
            
            return extracted_info

        except Exception as e:
            logger.error(f"Exception in get_stock_info for {symbol}: {str(e)}", exc_info=True)
            # Return a minimal structure on error to prevent UI crashes
            return {
                'symbol': symbol.upper(),
                'error': 'Could not retrieve stock info',
                'details': str(e)
            }