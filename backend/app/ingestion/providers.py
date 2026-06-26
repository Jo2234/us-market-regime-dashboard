from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable


@dataclass(frozen=True)
class NormalizedPriceBar:
    symbol: str
    date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adjusted_close: float | None
    volume: int | None
    source: str


@dataclass(frozen=True)
class NormalizedMacroObservation:
    symbol: str
    date: date
    value: float
    source: str


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", ".", "null", "None", "nan"}:
        return None
    return float(text)


def normalize_price_rows(symbol: str, rows: Iterable[dict[str, object]], source: str) -> list[NormalizedPriceBar]:
    """Normalize public OHLCV rows.

    Returns use adjusted close when supplied by the provider. Rows without a valid
    date or close are skipped so market holidays and sparse downloads do not
    create false zero-price observations.
    """
    bars: dict[date, NormalizedPriceBar] = {}
    for row in rows:
        date_value = row.get("date") or row.get("Date")
        close_value = row.get("close") or row.get("Close")
        if not date_value or _float_or_none(close_value) is None:
            continue
        observed_date = _parse_date(str(date_value))
        close = float(_float_or_none(close_value))
        adjusted_close = _float_or_none(row.get("adjusted_close") or row.get("Adj Close") or row.get("adj_close"))
        bars[observed_date] = NormalizedPriceBar(
            symbol=symbol.upper(),
            date=observed_date,
            open=_float_or_none(row.get("open") or row.get("Open")),
            high=_float_or_none(row.get("high") or row.get("High")),
            low=_float_or_none(row.get("low") or row.get("Low")),
            close=close,
            adjusted_close=adjusted_close,
            volume=int(_float_or_none(row.get("volume") or row.get("Volume")) or 0) or None,
            source=source,
        )
    return [bars[key] for key in sorted(bars)]


def normalize_macro_rows(symbol: str, rows: Iterable[dict[str, object]], source: str) -> list[NormalizedMacroObservation]:
    observations: dict[date, NormalizedMacroObservation] = {}
    for row in rows:
        date_value = row.get("date") or row.get("DATE")
        value = _float_or_none(row.get("value") or row.get("VALUE") or row.get(symbol))
        if not date_value or value is None:
            continue
        observed_date = _parse_date(str(date_value))
        observations[observed_date] = NormalizedMacroObservation(symbol.upper(), observed_date, value, source)
    return [observations[key] for key in sorted(observations)]


def fetch_stooq_daily(symbol: str) -> list[NormalizedPriceBar]:
    """Optional public price hook.

    Stooq symbols are mapped by the caller when needed, for example ``spy.us``.
    The dashboard never requires this network hook for demo mode.
    """
    query = urllib.parse.urlencode({"s": symbol.lower(), "i": "d"})
    url = f"https://stooq.com/q/d/l/?{query}"
    with urllib.request.urlopen(url, timeout=20) as response:
        text = response.read().decode("utf-8")
    return normalize_price_rows(symbol.split(".")[0].upper(), csv.DictReader(io.StringIO(text)), "stooq")


def fetch_fred_series(series_id: str, api_key: str | None = None) -> list[NormalizedMacroObservation]:
    """Optional FRED hook for macro and rates series.

    If no API key is provided, this uses FRED's CSV download endpoint where
    available. With an API key, it uses FRED's observations JSON endpoint.
    """
    if api_key:
        query = urllib.parse.urlencode(
            {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
            }
        )
        url = f"https://api.stlouisfed.org/fred/series/observations?{query}"
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = [{"date": item["date"], "value": item["value"]} for item in payload.get("observations", [])]
        return normalize_macro_rows(series_id.upper(), rows, "fred")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series_id)}"
    with urllib.request.urlopen(url, timeout=20) as response:
        text = response.read().decode("utf-8")
    return normalize_macro_rows(series_id.upper(), csv.DictReader(io.StringIO(text)), "fred")
