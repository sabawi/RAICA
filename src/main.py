"""
src/main.py
Entry point for the Stock Charting Application.
This script initializes the application, configures dependency injection,
and launches the UI with the real-time Yahoo Finance data repository.
"""

import sys
import logging
import asyncio
from typing import Optional

# Context-aware imports based on project structure
from src.config.config import Config
from src.data.repositories.istock_repository import IStockRepository
from src.data.repositories.yahoo_finance_repository import YahooFinanceRepository
from src.services.stock_market_service import StockMarketService
from src.ui.app import App

# Configure global logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('stocks_charting.log')
    ]
)

logger = logging.getLogger(__name__)


def setup_logging():
    """Sets up advanced logging configuration."""
    logger.setLevel(logging.DEBUG)
    # Prevent overly verbose logs from external libraries if necessary
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def initialize_application() -> App:
    """
    Initializes the core application components using Dependency Injection.
    
    Returns:
        App: The fully configured application instance ready to run.
    """
    try:
        logger.info("Loading application configuration...")
        config = Config()
        
        logger.info("Initializing Data Repository...")
        # CRITICAL FIX: Switching from Fake/Mock Repository to Yahoo Finance
        # This ensures real-time prices and volumes are fetched.
        stock_repository: IStockRepository = YahooFinanceRepository(config)
        logger.info("Successfully connected to Yahoo Finance data source.")

        logger.info("Initializing Business Logic Layer...")
        market_service = StockMarketService(stock_repository)

        logger.info("Initializing User Interface...")
        app = App(service=market_service, config=config)
        
        return app

    except ImportError as e:
        logger.critical(f"Import Error: {e}. Please ensure all project modules exist.")
        raise
    except Exception as e:
        logger.critical(f"Failed to initialize application: {e}", exc_info=True)
        raise


def main():
    """
    Main execution function. Handles the lifecycle of the application.
    """
    setup_logging()
    logger.info("=" * 50)
    logger.info("Starting Stock Charting Software")
    logger.info("=" * 50)

    app: Optional[App] = None

    try:
        # Initialize the application stack
        app = initialize_application()

        # Start the application loop
        # Using asyncio check to support both sync and async UI frameworks
        if asyncio.iscoroutinefunction(app.run):
            logger.info("Starting Async Event Loop...")
            asyncio.run(app.run())
        else:
            logger.info("Starting Main Event Loop...")
            app.run()

    except KeyboardInterrupt:
        logger.info("Shutdown signal received (Ctrl+C). Closing application...")
    except Exception as e:
        logger.exception("Unhandled critical error in main execution loop.")
        sys.exit(1)
    finally:
        logger.info("Application terminated.")
        if app:
            # Perform any cleanup if the app supports it
            if hasattr(app, 'cleanup'):
                app.cleanup()


if __name__ == "__main__":
    main()