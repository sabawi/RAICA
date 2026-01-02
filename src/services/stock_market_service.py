import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Union

import pandas as pd

# Assuming the project structure includes these interfaces and implementations
from src.data.repositories.istock_repository import IStockRepository
from src.data.repositories.yahoo_finance_repository import YahooFinanceRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StockMarketService:
    """
    Service layer responsible for handling business logic related to stock market data.
    It acts as an intermediary between the UI and the Data Repository.
    """

    def __init__(self, repository: Optional[IStockRepository] = None):
        """
        Initialize the StockMarketService.

        Args:
            repository (Optional[IStockRepository]): The data repository instance. 
                                                   Defaults to YahooFinanceRepository if None.
        """
        if repository is None:
            logger.info("No repository provided. Defaulting to YahooFinanceRepository.")
            self._repository = YahooFinanceRepository()
        else:
            self._repository = repository
        
        self._current_ticker: Optional[str] = None

    @property
    def current_ticker(self) -> Optional[str]:
        """Gets the currently active ticker symbol."""
        return self._current_ticker

    def get_ticker_info(self, ticker: str) -> Dict[str, Any]:
        """
        Retrieves general information and real-time quote for a specific ticker.

        Args:
            ticker (str): The stock symbol (e.g., 'AAPL').

        Returns:
            Dict[str, Any]: A dictionary containing stock details (price, volume, etc).

        Raises:
            ValueError: If the ticker is invalid or data cannot be retrieved.
        """
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")

        ticker = ticker.upper().strip()
        logger.info(f"Fetching info for ticker: {ticker}")

        try:
            # Delegating to the repository to fetch real-time data
            info = self._repository.get_stock_info(ticker)
            
            # Normalize data for UI consumption
            normalized_info = {
                "symbol": info.get("symbol", ticker),
                "company_name": info.get("longName", "N/A"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "open_price": info.get("open"),
                "day_high": info.get("dayHigh"),
                "day_low": info.get("dayLow"),
                "volume": info.get("volume"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "currency": info.get("currency", "USD"),
                "market_cap": info.get("marketCap"),
                "last_update": datetime.now().isoformat()
            }
            return normalized_info

        except Exception as e:
            logger.error(f"Failed to retrieve info for {ticker}: {e}")
            raise ValueError(f"Could not retrieve data for {ticker}. Please check the symbol.") from e

    def get_historical_data(
        self, 
        ticker: str, 
        period: str = "1mo", 
        interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Retrieves historical stock data for charting.

        Args:
            ticker (str): The stock symbol.
            period (str): The range of data (e.g., '1d', '5d', '1mo', '1y', 'max').
            interval (str): The data granularity (e.g., '1m', '5m', '1h', '1d').

        Returns:
            pd.DataFrame: A DataFrame containing OHLCV data. 
                          Columns: Date, Open, High, Low, Close, Volume.

        Raises:
            ValueError: If data retrieval fails.
        """
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")

        ticker = ticker.upper().strip()
        self._current_ticker = ticker
        
        logger.info(f"Fetching historical data for {ticker} | Period: {period} | Interval: {interval}")

        try:
            # Fetch raw data from Yahoo Finance via repository
            df = self._repository.get_historical_data(ticker, period, interval)

            if df.empty:
                raise ValueError("No data returned for the given parameters.")

            # Data Cleaning and Normalization
            # Ensure index is a datetime object
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)

            # Reset index to make 'Date' a column for easier UI consumption
            df.reset_index(inplace=True)
            
            # Rename columns to be generic and consistent
            df.rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume"
            }, inplace=True)

            # Handle missing values (forward fill is common for stock gaps, or drop)
            df.fillna(method='ffill', inplace=True)
            
            # Round numeric columns to 2 decimals for cleaner display
            numeric_cols = ["open", "high", "low", "close", "adj_close"]
            df[numeric_cols] = df[numeric_cols].round(2)

            logger.info(f"Successfully retrieved {len(df)} data points for {ticker}")
            return df

        except Exception as e:
            logger.error(f"Failed to retrieve historical data for {ticker}: {e}")
            raise ValueError(f"Error fetching historical data: {str(e)}") from e

    def search_symbols(self, query: str) -> List[Dict[str, str]]:
        """
        Searches for stock symbols based on a query string.

        Args:
            query (str): The search term (company name or ticker).

        Returns:
            List[Dict[str, str]]: A list of matching symbols with metadata.
        """
        if not query or len(query) < 2:
            return []

        logger.info(f"Searching for symbols matching: {query}")
        try:
            results = self._repository.search_ticker(query)
            return results
        except Exception as e:
            logger.warning(f"Search failed for query '{query}': {e}")
            return []

    def get_intraday_data(self, ticker: str) -> Dict[str, Any]:
        """
        Fetches up-to-the-minute data for day trading views.
        
        Args:
            ticker (str): The stock symbol.

        Returns:
            Dict[str, Any]: Real-time quote and recent mini-tick data.
        """
        try:
            # For intraday, we typically use 1m interval for 1d or 5d period
            df = self.get_historical_data(ticker, period="5d", interval="1m")
            
            # Get current quote
            info = self.get_ticker_info(ticker)
            
            return {
                "historical_intraday": df,
                "quote": info
            }
        except Exception as e:
            logger.error(f"Error fetching intraday data for {ticker}: {e}")
            raise