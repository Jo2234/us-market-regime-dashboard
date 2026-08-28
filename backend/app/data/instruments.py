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
    InstrumentDefinition("SPY", "SPDR S&P 500 ETF Trust", "equity_index", "yahoo_finance"),
    InstrumentDefinition("QQQ", "Invesco QQQ Trust", "equity_index", "yahoo_finance"),
    InstrumentDefinition("IWM", "iShares Russell 2000 ETF", "equity_index", "yahoo_finance"),
    InstrumentDefinition("DIA", "SPDR Dow Jones Industrial Average ETF", "equity_index", "yahoo_finance"),
    InstrumentDefinition("XLK", "Technology Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLF", "Financial Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLE", "Energy Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLV", "Health Care Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLY", "Consumer Discretionary Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLP", "Consumer Staples Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLI", "Industrial Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLB", "Materials Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLU", "Utilities Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLRE", "Real Estate Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("XLC", "Communication Services Select Sector SPDR Fund", "sector_etf", "yahoo_finance"),
    InstrumentDefinition("USO", "United States Oil Fund", "commodity", "yahoo_finance"),
    InstrumentDefinition("GLD", "SPDR Gold Shares", "commodity", "yahoo_finance"),
    InstrumentDefinition("CPER", "United States Copper Index Fund", "commodity", "yahoo_finance"),
    InstrumentDefinition("VIX", "CBOE Volatility Index", "volatility", "yahoo_finance"),
    InstrumentDefinition("DXY", "US Dollar Index", "currency", "yahoo_finance"),
    InstrumentDefinition("DGS3MO", "3-month Treasury", "rates", "yahoo_finance"),
    InstrumentDefinition("DGS2", "2-year yield futures (futures-implied)", "rates", "yahoo_finance"),
    InstrumentDefinition("DGS5", "5-year Treasury", "rates", "yahoo_finance"),
    InstrumentDefinition("DGS10", "10-year Treasury", "rates", "yahoo_finance"),
    InstrumentDefinition("DGS30", "30-year Treasury", "rates", "yahoo_finance"),
    InstrumentDefinition("FEDFUNDS", "Effective Fed funds rate, daily", "macro", "fred", "daily"),
    InstrumentDefinition("CPI_YOY", "Headline CPI YoY", "macro", "fred", "monthly"),
    InstrumentDefinition("CORE_CPI_YOY", "Core CPI YoY", "macro", "fred", "monthly"),
    InstrumentDefinition("FEDFUNDS_MONTHLY", "Fed funds monthly average", "macro", "fred", "monthly"),
    InstrumentDefinition("UNRATE", "Unemployment rate", "macro", "fred", "monthly"),
)

SECTOR_SYMBOLS = ("XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC")
INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")
COMMODITY_SYMBOLS = ("USO", "GLD", "CPER")
RATE_SYMBOLS = ("DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30")
MACRO_SYMBOLS = ("FEDFUNDS", "CPI_YOY", "UNRATE", "CORE_CPI_YOY", "FEDFUNDS_MONTHLY")
FRED_SERIES = {"FEDFUNDS": "DFF", "CPI_YOY": "CPIAUCSL", "UNRATE": "UNRATE",
               "CORE_CPI_YOY": "CPILFESL", "FEDFUNDS_MONTHLY": "FEDFUNDS"}
PRICE_SYMBOLS = (
    INDEX_SYMBOLS
    + SECTOR_SYMBOLS
    + COMMODITY_SYMBOLS
    + ("VIX", "DXY")
)

# Canonical internal ID -> Yahoo symbol. DGS IDs are retained for API compatibility;
# they do not imply FRED/constant-maturity data. Macro IDs have no Yahoo equivalent.
YAHOO_TICKERS = {
    **{symbol: symbol for symbol in INDEX_SYMBOLS + SECTOR_SYMBOLS + COMMODITY_SYMBOLS},
    "VIX": "^VIX", "DXY": "DX-Y.NYB", "DGS3MO": "^IRX",
    "DGS2": "2YY=F", "DGS5": "^FVX", "DGS10": "^TNX", "DGS30": "^TYX",
}

def provenance(symbol: str) -> dict:
    if symbol in FRED_SERIES:
        series_id = FRED_SERIES[symbol]
        return {"yahoo_ticker": None, "fred_series_id": series_id,
                "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
                "unit": "percent", "instrument_type": "macro",
                "frequency": "daily" if series_id == "DFF" else "monthly",
                "transformation": "year_over_year_percent" if symbol.endswith("CPI_YOY") else "level",
                "label": next(item.name for item in INSTRUMENTS if item.symbol == symbol)}
    return {
        "yahoo_ticker": YAHOO_TICKERS.get(symbol),
        "unit": "percent" if symbol in RATE_SYMBOLS else "index_points" if symbol in {"VIX", "DXY"} else "USD",
        "instrument_type": "yield_futures" if symbol == "DGS2" else "yield_index" if symbol in RATE_SYMBOLS else "market_price",
        "label": next((item.name for item in INSTRUMENTS if item.symbol == symbol), symbol),
    }
