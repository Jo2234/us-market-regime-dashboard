from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid5, NAMESPACE_URL

import pytest

from app.data.database import init_schema, insert_macro_rows, insert_price_rows, instrument_map, upsert_instruments


@pytest.fixture()
def seeded_conn():
    from app.data.database import connect
    from app.data.seed import seed_demo_data

    conn = connect(":memory:")
    init_schema(conn)
    seed_demo_data(conn, today=date(2026, 6, 25))
    yield conn
    conn.close()


@pytest.fixture()
def empty_conn():
    from app.data.database import connect

    conn = connect(":memory:")
    init_schema(conn)
    upsert_instruments(conn)
    yield conn
    conn.close()


def stable_id(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(str(part) for part in parts)))


def business_days(start: date, count: int) -> list[date]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def insert_price_path(conn, symbol: str, values: list[float], start: date = date(2025, 1, 2), source: str = "test") -> None:
    instruments = instrument_map(conn)
    rows = []
    for observed_date, value in zip(business_days(start, len(values)), values):
        rows.append(
            {
                "id": stable_id("price", symbol, observed_date, source),
                "instrument_id": instruments[symbol]["id"],
                "date": observed_date.isoformat(),
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "adjusted_close": value,
                "volume": 100,
                "source": source,
            }
        )
    insert_price_rows(conn, rows)


def insert_macro_path(conn, symbol: str, values: list[float], start: date = date(2025, 1, 2), source: str = "test") -> None:
    instruments = instrument_map(conn)
    rows = []
    for observed_date, value in zip(business_days(start, len(values)), values):
        rows.append(
            {
                "id": stable_id("macro", symbol, observed_date, source),
                "instrument_id": instruments[symbol]["id"],
                "date": observed_date.isoformat(),
                "value": value,
                "source": source,
            }
        )
    insert_macro_rows(conn, rows)
