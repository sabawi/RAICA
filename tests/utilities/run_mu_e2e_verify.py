"""E2E re-verification of the v1.0.0.159 TTM fix + v1.0.0.160 data-quality fixes on the 5-stock
audit regression set (META/AMZN/GOOGL/ORCL/MU). Runs the REAL analyzer tool (the code path RAICA
invokes) — no mocking — and greps the formatted output for the key figures that must have flipped.

v1.0.0.160 markers to confirm in the output:
  - "RAICA MODEL ESTIMATE" on the DCF block (not cited as Yahoo-sourced)
  - "N/M" instead of a >100% "DOWNSIDE" for high-debt names (ORCL)
  - "Historical CAGR (raw, uncapped)" + "not analyst consensus" on projection blocks
  - "Price to Book" sourced from priceToBook (or a ⚠️ note on equity fallback)
  - "Dividend Yield" computed as dividendRate/price (MU ~0.06%, NOT 6.00%)
  - "ROIC" with a NOPAT basis note
  - Interest coverage with a negligible-denominator note (GOOGL)
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from user_tools.comprehensive_stock_analyzer import ComprehensiveStockAnalyzerTool

KEYS = ["P/E", "EPS", "P/S", "EV/EBITDA", "Forward P/E", "Price/FCF",
        "Intrinsic Value", "Current FCF", "FCF Source", "fcf_source",
        "Current Revenue", "Current Net Income", "Current FCF",
        "[TTM", "[annual", "NOTE", "⚠️", "staleness", "Trailing P/E",
        "Revenue (TTM)", "Net Income (TTM)", "Free Cash Flow",
        # v1.0.0.160 markers
        "RAICA MODEL ESTIMATE", "N/M", "Historical CAGR", "not analyst consensus",
        "Price to Book", "Price/Book", "Dividend Yield", "ROIC", "NOPAT",
        "Interest Coverage", "Projected growth", "Historical-CAGR Extrapolation"]

async def main():
    tool = ComprehensiveStockAnalyzerTool()
    for ticker in ["MU", "META", "AMZN", "GOOGL", "ORCL"]:
        print(f"\n{'='*70}\n{ticker}\n{'='*70}")
        res = await tool.execute(ticker=ticker, detailed=True)
        if not res.get("success"):
            print("ERROR:", res.get("error")); continue
        text = res.get("result", "")
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(k in s for k in KEYS):
                print(" ", s[:200])

asyncio.run(main())