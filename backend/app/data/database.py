from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.core.config import get_settings
from app.data.instruments import INSTRUMENTS, InstrumentDefinition


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = path or get_settings().database_path
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path: Path | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            source TEXT NOT NULL,
            frequency TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS market_prices (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL NOT NULL,
            adjusted_close REAL,
            volume INTEGER,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(instrument_id, date, source)
        );

        CREATE TABLE IF NOT EXISTS macro_observations (
            id TEXT PRIMARY KEY,
            instrument_id TEXT NOT NULL REFERENCES instruments(id),
            date TEXT NOT NULL,
            value REAL NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(instrument_id, date, source)
        );

        CREATE TABLE IF NOT EXISTS computed_metrics (
            id TEXT PRIMARY KEY,
            instrument_id TEXT REFERENCES instruments(id),
            metric_name TEXT NOT NULL,
            date TEXT NOT NULL,
            value REAL NOT NULL,
            window TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS regime_snapshots (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL UNIQUE,
            regime_label TEXT NOT NULL,
            confidence TEXT NOT NULL,
            risk_score REAL NOT NULL,
            growth_score REAL NOT NULL,
            inflation_score REAL NOT NULL,
            rates_pressure_score REAL NOT NULL,
            signals TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def upsert_instruments(conn: sqlite3.Connection, instruments: Iterable[InstrumentDefinition] = INSTRUMENTS) -> None:
    for item in instruments:
        conn.execute(
            """
            INSERT INTO instruments (id, symbol, name, asset_class, source, frequency)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name,
                asset_class=excluded.asset_class,
                source=excluded.source,
                frequency=excluded.frequency
            """,
            (item.symbol, item.symbol, item.name, item.asset_class, item.source, item.frequency),
        )


def instrument_map(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {row["symbol"]: row for row in conn.execute("SELECT * FROM instruments")}


def insert_price_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO market_prices
                (id, instrument_id, date, open, high, low, close, adjusted_close, volume, source)
            VALUES
                (:id, :instrument_id, :date, :open, :high, :low, :close, :adjusted_close, :volume, :source)
            ON CONFLICT(instrument_id, date, source) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                adjusted_close=excluded.adjusted_close,
                volume=excluded.volume
            """,
            row,
        )
        count += 1
    return count


def insert_macro_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO macro_observations (id, instrument_id, date, value, source)
            VALUES (:id, :instrument_id, :date, :value, :source)
            ON CONFLICT(instrument_id, date, source) DO UPDATE SET value=excluded.value
            """,
            row,
        )
        count += 1
    return count


def latest_available_date(conn: sqlite3.Connection, symbol: str, as_of: date | None = None) -> str | None:
    query = """
        SELECT MAX(p.date) AS date
        FROM market_prices p
        JOIN instruments i ON i.id = p.instrument_id
        WHERE i.symbol = ?
    """
    params: tuple[Any, ...] = (symbol,)
    if as_of:
        query += " AND p.date <= ?"
        params = (symbol, as_of.isoformat())
    row = conn.execute(query, params).fetchone()
    if row and row["date"]:
        return row["date"]
    row = conn.execute(
        """
        SELECT MAX(m.date) AS date
        FROM macro_observations m
        JOIN instruments i ON i.id = m.instrument_id
        WHERE i.symbol = ?
        """ + (" AND m.date <= ?" if as_of else ""),
        params,
    ).fetchone()
    return row["date"] if row and row["date"] else None


def save_regime_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> None:
    payload = dict(snapshot)
    payload["signals"] = json.dumps(payload["signals"], sort_keys=True)
    conn.execute(
        """
        INSERT INTO regime_snapshots
            (id, date, regime_label, confidence, risk_score, growth_score, inflation_score,
             rates_pressure_score, signals, summary)
        VALUES
            (:id, :date, :regime_label, :confidence, :risk_score, :growth_score, :inflation_score,
             :rates_pressure_score, :signals, :summary)
        ON CONFLICT(date) DO UPDATE SET
            regime_label=excluded.regime_label,
            confidence=excluded.confidence,
            risk_score=excluded.risk_score,
            growth_score=excluded.growth_score,
            inflation_score=excluded.inflation_score,
            rates_pressure_score=excluded.rates_pressure_score,
            signals=excluded.signals,
            summary=excluded.summary
        """,
        payload,
    )


def load_latest_regime(conn: sqlite3.Connection, as_of: date | None = None) -> dict[str, Any] | None:
    if as_of:
        row = conn.execute(
            "SELECT * FROM regime_snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (as_of.isoformat(),),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM regime_snapshots ORDER BY date DESC LIMIT 1").fetchone()
    if not row:
        return None
    data = dict(row)
    data["signals"] = json.loads(data["signals"])
    return data


def load_previous_regime(conn: sqlite3.Connection, before: date) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM regime_snapshots WHERE date < ? ORDER BY date DESC LIMIT 1",
        (before.isoformat(),),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["signals"] = json.loads(data["signals"])
    return data
