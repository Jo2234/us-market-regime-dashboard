from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentDefinition:
    symbol: str
    name: str
    asset_class: str
    source: str
    frequency: str = "daily"


INSTRUMENTS: tuple[InstrumentDefinition, ...] = (
    InstrumentDefinition("SPY", "SPDR S&P 500 ETF Trust", "equity_index", "demo_seed"),
    InstrumentDefinition("QQQ", "Invesco QQQ Trust", "equity_index", "demo_seed"),
    InstrumentDefinition("IWM", "iShares Russell 2000 ETF", "equity_index", "demo_seed"),
    InstrumentDefinition("DIA", "SPDR Dow Jones Industrial Average ETF", "equity_index", "demo_seed"),
    InstrumentDefinition("XLK", "Technology Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLF", "Financial Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLE", "Energy Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLV", "Health Care Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLY", "Consumer Discretionary Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLP", "Consumer Staples Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLI", "Industrial Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLB", "Materials Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLU", "Utilities Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLRE", "Real Estate Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("XLC", "Communication Services Select Sector SPDR Fund", "sector_etf", "demo_seed"),
    InstrumentDefinition("USO", "United States Oil Fund", "commodity", "demo_seed"),
    InstrumentDefinition("GLD", "SPDR Gold Shares", "commodity", "demo_seed"),
    InstrumentDefinition("CPER", "United States Copper Index Fund", "commodity", "demo_seed"),
    InstrumentDefinition("VIX", "CBOE Volatility Index", "volatility", "demo_seed"),
    InstrumentDefinition("DXY", "US Dollar Index Proxy", "currency", "demo_seed"),
    InstrumentDefinition("DGS3MO", "3-Month Treasury Yield", "rates", "demo_seed"),
    InstrumentDefinition("DGS2", "2-Year Treasury Yield", "rates", "demo_seed"),
    InstrumentDefinition("DGS10", "10-Year Treasury Yield", "rates", "demo_seed"),
    InstrumentDefinition("DGS30", "30-Year Treasury Yield", "rates", "demo_seed"),
    InstrumentDefinition("FEDFUNDS", "Effective Federal Funds Rate", "macro", "demo_seed", "monthly"),
    InstrumentDefinition("CPI_YOY", "Consumer Price Index YoY", "macro", "demo_seed", "monthly"),
    InstrumentDefinition("UNRATE", "Unemployment Rate", "macro", "demo_seed", "monthly"),
)

SECTOR_SYMBOLS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC")
INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
COMMODITY_SYMBOLS = ("USO", "GLD", "CPER")
RATE_SYMBOLS = ("DGS3MO", "DGS2", "DGS10", "DGS30")
MACRO_SYMBOLS = ("FEDFUNDS", "CPI_YOY", "UNRATE")
PRICE_SYMBOLS = (
    INDEX_SYMBOLS
    + SECTOR_SYMBOLS
    + COMMODITY_SYMBOLS
    + ("VIX", "DXY")
)
