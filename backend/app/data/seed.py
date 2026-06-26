from __future__ import annotations

import math
from datetime import date, timedelta
from uuid import uuid5, NAMESPACE_URL

from app.core.config import get_settings
from app.data.database import insert_macro_rows, insert_price_rows, instrument_map, upsert_instruments
from app.data.instruments import INSTRUMENTS, MACRO_SYMBOLS, PRICE_SYMBOLS, RATE_SYMBOLS


BASE_PRICES = {
    "SPY": 420.0,
    "QQQ": 340.0,
    "IWM": 190.0,
    "DIA": 330.0,
    "XLK": 170.0,
    "XLF": 38.0,
    "XLE": 80.0,
    "XLV": 130.0,
    "XLY": 150.0,
    "XLP": 72.0,
    "XLI": 105.0,
    "XLB": 82.0,
    "XLU": 68.0,
    "XLRE": 40.0,
    "XLC": 70.0,
    "USO": 68.0,
    "GLD": 178.0,
    "CPER": 25.0,
    "VIX": 21.0,
    "DXY": 103.0,
}


def _stable_id(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _latest_business_day(today: date | None = None) -> date:
    current = today or date.today()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _phase(index: int, total: int) -> str:
    ratio = index / max(total - 1, 1)
    if ratio < 0.22:
        return "risk_off"
    if ratio < 0.48:
        return "growth"
    if ratio < 0.72:
        return "broadening"
    if ratio < 0.9:
        return "rates_pressure"
    return "mixed"


def _daily_return(symbol: str, phase: str, day_index: int) -> float:
    cycle = math.sin(day_index / 13.0) * 0.0018 + math.cos(day_index / 29.0) * 0.0011
    base = {
        "risk_off": -0.00055,
        "growth": 0.00072,
        "broadening": 0.00048,
        "rates_pressure": -0.00012,
        "mixed": 0.00018,
    }[phase]
    tilts = {
        "QQQ": {"risk_off": -0.00025, "growth": 0.00045, "rates_pressure": -0.00035},
        "IWM": {"risk_off": -0.00045, "broadening": 0.00035, "mixed": -0.0001},
        "XLK": {"growth": 0.00055, "rates_pressure": -0.00025},
        "XLF": {"broadening": 0.00022, "rates_pressure": 0.00012},
        "XLE": {"risk_off": 0.0007, "mixed": 0.00035},
        "XLV": {"risk_off": 0.0002},
        "XLP": {"risk_off": 0.00025, "growth": -0.00012},
        "XLU": {"risk_off": 0.0003, "rates_pressure": -0.00025},
        "XLY": {"growth": 0.00025, "rates_pressure": -0.00025},
        "USO": {"risk_off": 0.00075, "mixed": 0.00055, "growth": -0.00005},
        "GLD": {"risk_off": 0.00035, "rates_pressure": -0.00018, "mixed": 0.00025},
        "CPER": {"growth": 0.00028, "mixed": 0.00042},
        "DXY": {"risk_off": 0.00022, "rates_pressure": 0.00028},
    }
    if symbol == "VIX":
        return {
            "risk_off": 0.00035,
            "growth": -0.00045,
            "broadening": -0.00018,
            "rates_pressure": 0.00032,
            "mixed": -0.00012,
        }[phase] + math.sin(day_index / 7.0) * 0.005
    return base + tilts.get(symbol, {}).get(phase, 0.0) + cycle


def _rate_value(symbol: str, phase: str, day_index: int, total: int) -> float:
    trend = day_index / max(total - 1, 1)
    seasonal = math.sin(day_index / 31.0) * 0.05
    ten_year = 3.0 + trend * 1.25 + seasonal
    two_year = 3.25 + trend * 1.05 + math.cos(day_index / 37.0) * 0.06
    if phase == "risk_off":
        ten_year -= 0.55
        two_year -= 0.15
    elif phase == "rates_pressure":
        ten_year += 0.45
        two_year += 0.55
    elif phase == "mixed":
        ten_year += 0.2
        two_year += 0.15
    values = {
        "DGS3MO": two_year - 0.25,
        "DGS2": two_year,
        "DGS10": ten_year,
        "DGS30": ten_year + 0.35,
    }
    return round(values[symbol], 3)


def seed_demo_data(conn, today: date | None = None) -> None:
    """Populate deterministic demo history if the database is empty.

    The generated data intentionally contains risk-off, growth-led, broadening,
    rates-pressure, and mixed periods so regime tests and UI states are useful in
    local demo mode. Ingestion from public providers can upsert over this data.
    """
    upsert_instruments(conn, INSTRUMENTS)
    existing = conn.execute("SELECT COUNT(*) AS count FROM market_prices").fetchone()["count"]
    if existing:
        return

    end = _latest_business_day(today)
    start = end - timedelta(days=365 * 4)
    dates = _business_days(start, end)
    source = get_settings().demo_source
    instruments = instrument_map(conn)

    current_prices = dict(BASE_PRICES)
    price_rows = []
    macro_rows = []
    for idx, observed_date in enumerate(dates):
        phase = _phase(idx, len(dates))
        for symbol in PRICE_SYMBOLS:
            previous = current_prices[symbol]
            close = max(previous * (1.0 + _daily_return(symbol, phase, idx)), 1.0)
            intraday = 0.004 + abs(math.sin(idx / 11.0)) * 0.006
            adjusted_close = close * (0.998 if symbol not in {"VIX", "DXY"} else 1.0)
            price_rows.append(
                {
                    "id": _stable_id("price", symbol, observed_date, source),
                    "instrument_id": instruments[symbol]["id"],
                    "date": observed_date.isoformat(),
                    "open": round(previous, 4),
                    "high": round(max(previous, close) * (1 + intraday), 4),
                    "low": round(min(previous, close) * (1 - intraday), 4),
                    "close": round(close, 4),
                    "adjusted_close": round(adjusted_close, 4),
                    "volume": int(1_000_000 + (idx % 37) * 25_000),
                    "source": source,
                }
            )
            current_prices[symbol] = close
        for symbol in RATE_SYMBOLS:
            value = _rate_value(symbol, phase, idx, len(dates))
            macro_rows.append(
                {
                    "id": _stable_id("macro", symbol, observed_date, source),
                    "instrument_id": instruments[symbol]["id"],
                    "date": observed_date.isoformat(),
                    "value": value,
                    "source": source,
                }
            )
        if idx == 0 or observed_date.month != dates[idx - 1].month:
            cpi = 2.4 + math.sin(idx / 80.0) * 0.45
            if phase in {"risk_off", "mixed"}:
                cpi += 0.9
            unemployment = 3.7 + math.cos(idx / 100.0) * 0.25
            fed_funds = max(_rate_value("DGS2", phase, idx, len(dates)) - 0.35, 0.0)
            monthly_values = {"CPI_YOY": cpi, "UNRATE": unemployment, "FEDFUNDS": fed_funds}
            for symbol in MACRO_SYMBOLS:
                macro_rows.append(
                    {
                        "id": _stable_id("macro", symbol, observed_date, source),
                        "instrument_id": instruments[symbol]["id"],
                        "date": observed_date.isoformat(),
                        "value": round(monthly_values[symbol], 3),
                        "source": source,
                    }
                )

    insert_price_rows(conn, price_rows)
    insert_macro_rows(conn, macro_rows)
