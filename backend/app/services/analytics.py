from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd

from app.data.instruments import COMMODITY_SYMBOLS, INDEX_SYMBOLS, RATE_SYMBOLS, SECTOR_SYMBOLS


WINDOW_TRADING_DAYS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "1y": 252}


def parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _price_frame(conn, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    query = """
        SELECT p.date, p.open, p.high, p.low, p.close, p.adjusted_close, p.volume, p.source
        FROM market_prices p
        JOIN instruments i ON i.id = p.instrument_id
        WHERE i.symbol = ?
    """
    params: list[Any] = [symbol.upper()]
    if start:
        query += " AND p.date >= ?"
        params.append(start.isoformat())
    if end:
        query += " AND p.date <= ?"
        params.append(end.isoformat())
    query += " ORDER BY p.date"
    frame = pd.read_sql_query(query, conn, params=params, parse_dates=["date"])
    if frame.empty:
        return frame
    frame["value"] = frame["adjusted_close"].fillna(frame["close"])
    frame["daily_return"] = frame["value"].pct_change()
    return frame


def _macro_frame(conn, symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    query = """
        SELECT m.date, m.value, m.source
        FROM macro_observations m
        JOIN instruments i ON i.id = m.instrument_id
        WHERE i.symbol = ?
    """
    params: list[Any] = [symbol.upper()]
    if start:
        query += " AND m.date >= ?"
        params.append(start.isoformat())
    if end:
        query += " AND m.date <= ?"
        params.append(end.isoformat())
    query += " ORDER BY m.date"
    return pd.read_sql_query(query, conn, params=params, parse_dates=["date"])


def latest_date(conn, symbol: str = "SPY", as_of: date | None = None) -> date | None:
    frame = _price_frame(conn, symbol, end=as_of)
    if frame.empty:
        frame = _macro_frame(conn, symbol, end=as_of)
    if frame.empty:
        return None
    return frame.iloc[-1]["date"].date()


def price_series(conn, symbol: str, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    frame = _price_frame(conn, symbol, start, end)
    if not frame.empty:
        return [
            {
                "date": row.date.date().isoformat(),
                "open": _rounded(row.open),
                "high": _rounded(row.high),
                "low": _rounded(row.low),
                "close": _rounded(row.close),
                "adjusted_close": _rounded(row.adjusted_close),
                "value": _rounded(row.value),
                "daily_return": _rounded(row.daily_return, 6),
                "volume": None if pd.isna(row.volume) else int(row.volume),
                "source": row.source,
            }
            for row in frame.itertuples()
        ]
    macro = _macro_frame(conn, symbol, start, end)
    return [
        {
            "date": row.date.date().isoformat(),
            "value": _rounded(row.value),
            "source": row.source,
        }
        for row in macro.itertuples()
    ]


def _rounded(value: Any, digits: int = 4) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    return round(float(value), digits)


def period_return(frame: pd.DataFrame, window: str, as_of: date | None = None) -> float | None:
    if frame.empty:
        return None
    work = frame
    if as_of:
        work = frame[frame["date"].dt.date <= as_of]
    if work.empty:
        return None
    current = float(work.iloc[-1]["value"])
    if window == "ytd":
        year = work.iloc[-1]["date"].year
        year_rows = work[work["date"].dt.year == year]
        if year_rows.empty:
            return None
        base = float(year_rows.iloc[0]["value"])
    else:
        offset = WINDOW_TRADING_DAYS[window]
        if len(work) <= offset:
            return None
        base = float(work.iloc[-offset - 1]["value"])
    if base == 0:
        return None
    return current / base - 1.0


def moving_average(frame: pd.DataFrame, window: int, as_of: date | None = None) -> float | None:
    work = frame if as_of is None else frame[frame["date"].dt.date <= as_of]
    if len(work) < window:
        return None
    return float(work["value"].tail(window).mean())


def rolling_volatility(frame: pd.DataFrame, window: int = 20, as_of: date | None = None) -> float | None:
    """Annualized rolling volatility: std(daily returns) * sqrt(252)."""
    work = frame if as_of is None else frame[frame["date"].dt.date <= as_of]
    returns = work["value"].pct_change().dropna().tail(window)
    if len(returns) < max(2, min(window, 5)):
        return None
    return float(returns.std(ddof=1) * math.sqrt(252))


def max_drawdown(frame: pd.DataFrame, as_of: date | None = None, lookback: int = 252) -> float | None:
    """Current drawdown from the rolling high in the selected lookback window."""
    work = frame if as_of is None else frame[frame["date"].dt.date <= as_of]
    if work.empty:
        return None
    values = work["value"].tail(lookback)
    peak = values.cummax()
    drawdowns = values / peak - 1.0
    return float(drawdowns.min())


def returns_by_windows(conn, symbol: str, windows: tuple[str, ...], as_of: date | None = None) -> dict[str, float | None]:
    frame = _price_frame(conn, symbol, end=as_of)
    return {window: _rounded(period_return(frame, window, as_of), 6) for window in windows}


def instrument_snapshot(conn, symbol: str, as_of: date | None = None) -> dict[str, Any]:
    frame = _price_frame(conn, symbol, end=as_of)
    if frame.empty:
        return {"symbol": symbol, "available": False}
    latest = frame.iloc[-1]
    windows = ("1d", "1w", "1m", "3m", "ytd", "1y")
    return {
        "symbol": symbol,
        "date": latest["date"].date().isoformat(),
        "value": _rounded(latest["value"]),
        "returns": {window: _rounded(period_return(frame, window, as_of), 6) for window in windows},
        "volatility": {
            "20d": _rounded(rolling_volatility(frame, 20, as_of), 6),
            "60d": _rounded(rolling_volatility(frame, 60, as_of), 6),
        },
        "drawdown_52w": _rounded(max_drawdown(frame, as_of, 252), 6),
        "moving_averages": {
            "50d": _rounded(moving_average(frame, 50, as_of)),
            "200d": _rounded(moving_average(frame, 200, as_of)),
        },
        "source": latest["source"],
    }


def sector_performance(conn, windows: tuple[str, ...], as_of: date | None = None) -> list[dict[str, Any]]:
    spy = _price_frame(conn, "SPY", end=as_of)
    rows = []
    for symbol in SECTOR_SYMBOLS:
        frame = _price_frame(conn, symbol, end=as_of)
        returns = {window: _rounded(period_return(frame, window, as_of), 6) for window in windows}
        relative = {
            window: _rounded(
                (period_return(frame, window, as_of) or 0.0) - (period_return(spy, window, as_of) or 0.0),
                6,
            )
            for window in windows
        }
        rows.append({"symbol": symbol, "returns": returns, "relative_to_spy": relative})
    primary_window = "1m" if "1m" in windows else windows[0]
    rows.sort(key=lambda item: item["returns"].get(primary_window) if item["returns"].get(primary_window) is not None else -999)
    return list(reversed(rows))


def latest_macro_value(conn, symbol: str, as_of: date | None = None) -> dict[str, Any] | None:
    frame = _macro_frame(conn, symbol, end=as_of)
    if frame.empty:
        return None
    row = frame.iloc[-1]
    return {"symbol": symbol, "date": row["date"].date().isoformat(), "value": _rounded(row["value"]), "source": row["source"]}


def macro_change(conn, symbol: str, periods: int = 21, as_of: date | None = None) -> float | None:
    frame = _macro_frame(conn, symbol, end=as_of)
    if len(frame) <= periods:
        return None
    return float(frame.iloc[-1]["value"] - frame.iloc[-periods - 1]["value"])


def yield_curve(conn, as_of: date | None = None) -> dict[str, Any]:
    maturities = []
    values: dict[str, float] = {}
    for symbol in RATE_SYMBOLS:
        latest = latest_macro_value(conn, symbol, as_of)
        if latest:
            values[symbol] = float(latest["value"])
            maturities.append(latest)
    spreads = {}
    if "DGS10" in values and "DGS2" in values:
        spreads["10y_2y"] = _rounded(values["DGS10"] - values["DGS2"])
    if "DGS10" in values and "DGS3MO" in values:
        spreads["10y_3m"] = _rounded(values["DGS10"] - values["DGS3MO"])
    if "DGS30" in values and "DGS10" in values:
        spreads["30y_10y"] = _rounded(values["DGS30"] - values["DGS10"])
    latest_curve_date = max((item["date"] for item in maturities), default=None)
    return {"date": latest_curve_date, "maturities": maturities, "spreads": spreads}


def dashboard_market_blocks(conn, as_of: date | None = None) -> dict[str, Any]:
    sectors = sector_performance(conn, ("1d", "1w", "1m", "3m", "ytd", "1y"), as_of)
    sector_with_1m = [row for row in sectors if row["returns"].get("1m") is not None]
    return {
        "indices": [instrument_snapshot(conn, symbol, as_of) for symbol in INDEX_SYMBOLS],
        "sector_leaders": sector_with_1m[:3],
        "sector_laggards": list(reversed(sector_with_1m[-3:])),
        "commodities": [instrument_snapshot(conn, symbol, as_of) for symbol in COMMODITY_SYMBOLS],
        "volatility": instrument_snapshot(conn, "VIX", as_of),
        "rates": yield_curve(conn, as_of),
    }
