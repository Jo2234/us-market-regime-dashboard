from __future__ import annotations

import calendar
import bisect
import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any

from app.data.instruments import COMMODITY_SYMBOLS, INDEX_SYMBOLS, RATE_SYMBOLS, SECTOR_SYMBOLS, provenance


def parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def calendar_anchor(observed: date, window: str) -> date:
    if window == "1w":
        return observed - timedelta(days=7)
    if window == "ytd":
        return date(observed.year - 1, 12, 31)
    months = {"1m": 1, "3m": 3, "1y": 12}[window]
    index = observed.year * 12 + observed.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(observed.day, calendar.monthrange(year, month + 1)[1]))


def _records(frame):
    # Existing callers/tests may supply a DataFrame. Runtime paths use plain rows
    # and never import pandas/numpy to compute a few hundred daily observations.
    if hasattr(frame, "to_dict"):
        return [{**row, "date": parse_date(row["date"])} for row in frame.to_dict("records")]
    return frame


def _select(rows, start=None, end=None):
    return [row for row in _records(rows) if (not start or row["date"] >= start) and (not end or row["date"] <= end)]


class MarketHistory:
    """Load once per request; use standard-library arithmetic for daily history."""
    def __init__(self, conn):
        self.prices, self.macro = {}, {}
        for table, target in [("market_prices", self.prices), ("macro_observations", self.macro)]:
            for record in conn.execute(f"SELECT i.symbol, p.* FROM {table} p JOIN instruments i ON i.id=p.instrument_id ORDER BY p.date"):
                row = dict(record)
                symbol = row.pop("symbol")
                row["date"] = parse_date(row["date"])
                target.setdefault(symbol, []).append(row)
        self.price_frames = {}
        self.date_indexes = {}
        for symbol, rows in self.prices.items():
            result, previous = [], None
            for row in rows:
                value = row["adjusted_close"] if row["adjusted_close"] is not None else row["close"]
                result.append({**row, "value": value, "daily_return": value / previous - 1 if previous else None})
                previous = value
            self.price_frames[symbol] = result
        for table, series in (("market_prices", self.prices), ("macro_observations", self.macro)):
            for symbol, rows in series.items():
                self.date_indexes[(table, symbol)] = [r["date"] for r in rows]

    def select(self, symbol, table, start=None, end=None, prices=False):
        symbol = symbol.upper()
        rows = (self.price_frames if prices else self.prices if table == "market_prices" else self.macro).get(symbol, [])
        dates = self.date_indexes.get((table, symbol), [])
        return rows[bisect.bisect_left(dates, start) if start else 0:bisect.bisect_right(dates, end) if end else len(rows)]


def _frame(conn, symbol, table, start=None, end=None):
    if isinstance(conn, MarketHistory):
        return conn.select(symbol, table, start, end)
    records = conn.execute(f"SELECT p.* FROM {table} p JOIN instruments i ON i.id=p.instrument_id WHERE i.symbol=? ORDER BY p.date", (symbol.upper(),))
    return _select([{**dict(row), "date": parse_date(row["date"])} for row in records], start, end)


def _price_frame(conn, symbol, start=None, end=None):
    if isinstance(conn, MarketHistory):
        rows = conn.select(symbol, "market_prices", start, end, prices=True)
        if start and rows:
            rows = [{**rows[0], "daily_return": None}, *rows[1:]]
        return rows
    rows = _frame(conn, symbol, "market_prices", start, end)
    result, previous = [], None
    for row in rows:
        value = row["adjusted_close"] if row["adjusted_close"] is not None else row["close"]
        result.append({**row, "value": value, "daily_return": value / previous - 1 if previous else None})
        previous = value
    return result


def _macro_frame(conn, symbol, start=None, end=None):
    return _frame(conn, symbol, "macro_observations", start, end)


def latest_date(conn, symbol="SPY", as_of=None):
    rows = _price_frame(conn, symbol, end=as_of) or _macro_frame(conn, symbol, end=as_of)
    return rows[-1]["date"] if rows else None


def _rounded(value: Any, digits: int = 4):
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def price_series(conn, symbol, start=None, end=None):
    rows = _price_frame(conn, symbol, start, end)
    if rows:
        return [{"date": row["date"].isoformat(),
                 **{key: _rounded(row[key], 6 if key == "daily_return" else 4) for key in ("open", "high", "low", "close", "adjusted_close", "value", "daily_return")},
                 "volume": int(row["volume"]) if row["volume"] is not None else None,
                 "source": row["source"], "observation_date": row["date"].isoformat(), **provenance(symbol)} for row in rows]
    return [{"date": row["date"].isoformat(), "value": _rounded(row["value"]), "source": row["source"],
             "observation_date": row["date"].isoformat(), **provenance(symbol)} for row in _macro_frame(conn, symbol, start, end)]


def period_return(frame, window, as_of=None):
    rows = _select(frame, end=as_of)
    if not rows:
        return None
    bases = rows[:-1] if window == "1d" else [row for row in rows if row["date"] <= calendar_anchor(rows[-1]["date"], window)]
    if not bases or not bases[-1]["value"]:
        return None
    return rows[-1]["value"] / bases[-1]["value"] - 1


def moving_average(frame, window, as_of=None):
    rows = _select(frame, end=as_of)
    return statistics.fmean(row["value"] for row in rows[-window:]) if len(rows) >= window else None


def rolling_volatility(frame, window=20, as_of=None):
    rows = _select(frame, end=as_of)
    returns = [b["value"] / a["value"] - 1 for a, b in zip(rows, rows[1:])][-window:]
    return statistics.stdev(returns) * math.sqrt(252) if len(returns) >= max(2, min(window, 5)) else None


def max_drawdown(frame, as_of=None, lookback=252):
    rows = _select(frame, end=as_of)[-lookback:]
    if not rows:
        return None
    peak, drawdown = rows[0]["value"], 0.0
    for row in rows:
        peak = max(peak, row["value"])
        drawdown = min(drawdown, row["value"] / peak - 1)
    return drawdown


def returns_by_windows(conn, symbol, windows, as_of=None):
    frame = _price_frame(conn, symbol, end=as_of)
    return {window: _rounded(period_return(frame, window, as_of), 6) for window in windows}


def instrument_snapshot(conn, symbol, as_of=None):
    frame = _price_frame(conn, symbol, end=as_of)
    if not frame:
        return {"symbol": symbol, "available": False}
    latest = frame[-1]
    return {"symbol": symbol, "date": latest["date"].isoformat(), "value": _rounded(latest["value"]),
            "price": _rounded(latest["close"]), "adjusted_close": _rounded(latest["value"]),
            "price_basis": "unadjusted_close", "return_basis": "adjusted_close", "observation_date": latest["date"].isoformat(),
            **provenance(symbol),
            "returns": {w: _rounded(period_return(frame, w, as_of), 6) for w in ("1d", "1w", "1m", "3m", "ytd", "1y")},
            "volatility": {f"{w}d": _rounded(rolling_volatility(frame, w, as_of), 6) for w in (20, 60)},
            "drawdown_52w": _rounded(max_drawdown(frame, as_of, 252), 6),
            "moving_averages": {f"{w}d": _rounded(moving_average(frame, w, as_of)) for w in (50, 200)}, "source": latest["source"]}


def sector_performance(conn, windows, as_of=None):
    spy_frame = _price_frame(conn, "SPY", end=as_of)
    spy = {w: period_return(spy_frame, w, as_of) for w in windows}
    rows = []
    for symbol in SECTOR_SYMBOLS:
        frame = _price_frame(conn, symbol, end=as_of)
        returns = {w: _rounded(period_return(frame, w, as_of), 6) for w in windows}
        observed = frame[-1]["date"].isoformat() if frame else None
        relative = {w: _rounded(returns[w] - spy[w], 6)
                    if returns[w] is not None and spy[w] is not None else None for w in windows}
        rows.append({"symbol": symbol, "returns": returns, "relative_to_spy": relative, "date": observed,
                     "observation_date": observed, "source": frame[-1]["source"] if frame else None,
                     "return_basis": "adjusted_close", **provenance(symbol)})
    primary = "1m" if "1m" in windows else windows[0]
    rows.sort(key=lambda row: row["returns"].get(primary) if row["returns"].get(primary) is not None else -999)
    return list(reversed(rows))


def latest_macro_value(conn, symbol, as_of=None, published=False):
    rows = _macro_frame(conn, symbol, end=as_of)
    if published and as_of:
        from app.services.macro_data import available_on
        rows = [r for r in rows if r["source"] != "fred" or available_on(symbol, r["date"]) <= as_of]
    if not rows:
        return None
    row = rows[-1]
    return {"symbol": symbol, "date": row["date"].isoformat(), "value": _rounded(row["value"]), "source": row["source"],
            "observation_date": row["date"].isoformat(), **provenance(symbol)}


def macro_change(conn, symbol, periods=21, as_of=None):
    rows = _macro_frame(conn, symbol, end=as_of)
    return rows[-1]["value"] - rows[-periods - 1]["value"] if len(rows) > periods else None


def yield_curve(conn, as_of=None):
    maturities = [row for s in RATE_SYMBOLS if (row := latest_macro_value(conn, s, as_of))]
    values = {row["symbol"]: row["value"] for row in maturities}
    spreads = {name: _rounded(values[a] - values[b]) for name, a, b in
               [("10y_2y", "DGS10", "DGS2"), ("10y_3m", "DGS10", "DGS3MO"), ("30y_10y", "DGS30", "DGS10")]
               if a in values and b in values}
    return {"date": max((r["date"] for r in maturities), default=None), "maturities": maturities, "spreads": spreads,
            "units": "percent", "spread_metadata": {
                "10y_2y": {"label": "10Y Treasury minus 2Y futures-implied yield", "unit": "percentage_points", "is_cash_treasury_spread": False,
                           "observation_dates": {s: next((m["date"] for m in maturities if m["symbol"] == s), None) for s in ("DGS10", "DGS2")}},
                "10y_3m": {"label": "10Y Treasury minus 3M discount yield", "unit": "percentage_points"}}}


def dashboard_market_blocks(conn, as_of=None):
    sectors = sector_performance(conn, ("1d", "1w", "1m", "3m", "ytd", "1y"), as_of)
    ranked = [row for row in sectors if row["returns"].get("1m") is not None]
    return {"indices": [instrument_snapshot(conn, s, as_of) for s in INDEX_SYMBOLS], "sectors": sectors,
            "sector_leaders": ranked[:3], "sector_laggards": list(reversed(ranked[-3:])),
            "commodities": [instrument_snapshot(conn, s, as_of) for s in COMMODITY_SYMBOLS],
            "volatility": instrument_snapshot(conn, "VIX", as_of), "rates": yield_curve(conn, as_of)}


def indexed_performance(conn, as_of, window="1m"):
    columns = {s: {row["date"]: row["value"] for row in _price_frame(conn, s, end=as_of)} for s in INDEX_SYMBOLS}
    dates = sorted(set.intersection(*(set(column) for column in columns.values())))
    if not dates:
        return []
    if window == "1d":
        dates = dates[-2:]
    else:
        anchor = calendar_anchor(dates[-1], window)
        bases = [day for day in dates if day <= anchor]
        if not bases:
            return []
        dates = [day for day in dates if day >= bases[-1]]
    return [{"date": day.isoformat(), **{s: round(column[day] / column[dates[0]] * 100, 4) for s, column in columns.items()}} for day in dates]
