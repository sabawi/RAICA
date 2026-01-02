"""
src/config/config.py

This module manages the configuration settings for the fully functional stocks charting software.
It centralizes settings for data sources, API interactions (Yahoo Finance), caching, and UI defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    """
    Configuration class for the Stock Charting Application.
    
    Attributes:
        DATA_SOURCE_PROVIDER (str): The specific data provider to use (e.g., 'yahoo_finance').
        DEFAULT_SYMBOLS (List[str]): List of stock tickers to load on startup.
        DEFAULT_TIME_INTERVAL (str): The default chart interval (1m, 5m, 1h, 1d).
        YAHOO_USER_AGENT (str): User-Agent string required by Yahoo Finance to avoid blocking.
        REQUEST_TIMEOUT (int): Timeout in seconds for network requests to the data provider.
        ENABLE_LOGGING (bool): Flag to enable or disable detailed logging.
        REFRESH_INTERVAL_MS (int): Frequency in milliseconds to refresh the data/UI.
    """

    # ------------------------------------------------------------------
    # Data Source Configuration
    # ------------------------------------------------------------------
    # We are explicitly setting this to yahoo_finance as per requirements
    DATA_SOURCE_PROVIDER: str = "yahoo_finance"

    # List of default stocks to display. 
    # Can be overridden by environment variable 'DEFAULT_SYMBOLS' (comma-separated).
    DEFAULT_SYMBOLS: List[str] = field(default_factory=lambda: [
        s.strip().upper() 
        for s in os.getenv("DEFAULT_SYMBOLS", "AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA").split(",")
        if s.strip()
    ])

    # Default chart interval. Valid Yahoo intervals: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
    DEFAULT_TIME_INTERVAL: str = os.getenv("DEFAULT_TIME_INTERVAL", "1m")

    # ------------------------------------------------------------------
    # API / Network Configuration
    # ------------------------------------------------------------------
    # Yahoo Finance requires a valid User-Agent header to prevent 403/429 errors.
    # We use a standard Chrome user agent string.
    YAHOO_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )

    # Timeout for network requests (in seconds)
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))

    # Maximum retries for failed requests
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

    # ------------------------------------------------------------------
    # Application UI & Behavior
    # ------------------------------------------------------------------
    APP_TITLE: str = "RAICA Stock Charting Pro"
    WINDOW_WIDTH: int = 1200
    WINDOW_HEIGHT: int = 800

    # How often the UI attempts to update with new data (milliseconds)
    # Note: Yahoo free API has rate limits, so 1000ms might be too aggressive.
    # 5000ms (5 seconds) is a safer default for real-time-ish updates without banning.
    REFRESH_INTERVAL_MS: int = int(os.getenv("REFRESH_INTERVAL_MS", "5000"))

    # ------------------------------------------------------------------
    # Caching & Performance
    # ------------------------------------------------------------------
    # Enable in-memory caching to reduce API calls
    ENABLE_CACHE: bool = os.getenv("ENABLE_CACHE", "True").lower() == "true"
    
    # Time to live for cached data (seconds)
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "5"))

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def validate(self) -> bool:
        """
        Validates the current configuration settings.
        
        Returns:
            bool: True if configuration is valid, raises ValueError otherwise.
        """
        if not self.DEFAULT_SYMBOLS:
            raise ValueError("At least one default symbol must be configured.")
        
        valid_intervals = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
        if self.DEFAULT_TIME_INTERVAL not in valid_intervals:
            raise ValueError(f"Invalid time interval: {self.DEFAULT_TIME_INTERVAL}. Must be one of {valid_intervals}")

        return True


# Global configuration instance
# This instance is imported by other modules (services, repositories, ui)
settings = Config()

# Validate configuration on import to fail fast if there are issues
try:
    settings.validate()
except ValueError as e:
    print(f"Configuration Error: {e}")
    # Depending on the severity, we might want to exit or revert to safe defaults.
    # For now, we will log it, but the application will handle the error state.