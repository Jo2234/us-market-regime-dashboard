"""Per-instance cache with a validated, committed last-known-good fallback."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from datetime import date
from pathlib import Path

from app.core.telemetry import log_event
from app.data import database
from app.data.instruments import YAHOO_TICKERS, PRICE_SYMBOLS
from app.ingestion.yahoo import fetch_snapshot
from app.services.calendar import latest_completed_session

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "yahoo_snapshot.json"
_lock = threading.Lock()
_cached: dict | None = None
_cached_mode = "snapshot"
_expires = 0.0
_last_good: dict | None = None


class DataUnavailable(RuntimeError):
    pass


def validate_snapshot(snapshot: dict) -> dict:
    if snapshot.get("version") != 1 or set(snapshot.get("series", {})) != set(YAHOO_TICKERS):
        raise ValueError("Snapshot has incomplete instrument coverage")
    cutoff = latest_completed_session()
    for symbol, series in snapshot["series"].items():
        if series.get("source") != "yahoo_finance" or series.get("yahoo_ticker") != YAHOO_TICKERS[symbol]:
            raise ValueError(f"Invalid provenance for {symbol}")
        bars = series["bars"]
        if len(bars) < 260:
            raise ValueError(f"Insufficient history for {symbol}")
        dates = [bar["date"] for bar in bars]
        if dates != sorted(set(dates)) or date.fromisoformat(dates[-1]) > cutoff:
            raise ValueError(f"Invalid observation dates for {symbol}")
        for bar in bars:
            for field in (["close", "adjusted_close"] if symbol in PRICE_SYMBOLS else ["close"]):
                value = bar[field]
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"Invalid {field} for {symbol}")
    return snapshot


def _fallback():
    candidates = [_last_good] if _last_good else []
    try:
        candidates.append(validate_snapshot(json.loads(SNAPSHOT_PATH.read_text())))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not candidates:
        raise DataUnavailable("Live data unavailable; no valid Yahoo snapshot is available")
    return max(candidates, key=lambda item: min(s["bars"][-1]["date"] for s in item["series"].values()))


def get_snapshot(*, cached_only=False) -> tuple[dict, str]:
    global _cached, _cached_mode, _expires, _last_good
    # Bootstrap must not wait behind a slow refresh holding the single-flight lock.
    if cached_only:
        snapshot = _cached or _fallback()
        mode = _cached_mode if _cached and time.monotonic() < _expires else "snapshot"
        return {**snapshot, "_delivery": {"cache": "hit" if mode == "live" else "stale", "fetch_ms": 0.0,
                "refresh_pending": True, "retry_after_seconds": 0}}, mode
    with _lock:
        remaining = max(0, math.ceil(_expires - time.monotonic()))
        if remaining:
            if _cached is None:
                raise DataUnavailable("Live data unavailable; retry after the refresh cooldown")
            cache = "hit" if _cached_mode == "live" else "stale"
            log_event("market_cache", cache=cache, mode=_cached_mode)
            return {**_cached, "_delivery": {"cache": cache, "fetch_ms": 0.0,
                    "retry_after_seconds": remaining if _cached_mode == "snapshot" else 0}}, _cached_mode
        stats = {}
        try:
            if os.getenv("MARKET_REGIME_SNAPSHOT_ONLY") == "1":
                raise DataUnavailable("Snapshot-only mode enabled")
            snapshot = validate_snapshot(asyncio.run(fetch_snapshot()))
            stats = snapshot.get("_telemetry", {})
            _last_good = snapshot
            mode = "live"
        except Exception as exc:
            logging.getLogger(__name__).warning("Live Yahoo data unavailable (%s)", type(exc).__name__)
            stats = getattr(exc, "telemetry", {})
            # Failed refreshes have the SAME cooldown as successful ones, even if
            # there is no usable fallback. Visitors cannot bypass it with a query.
            _expires = time.monotonic() + 900
            snapshot = _fallback()
            mode = "snapshot"
        _cached, _cached_mode = {**snapshot, "_telemetry": stats}, mode
        _expires = time.monotonic() + 900
        cache = "miss" if mode == "live" else "stale"
        log_event("market_cache", cache=cache, mode=mode)
        return {**snapshot, "_telemetry": stats, "_delivery": {"cache": cache,
                "fetch_ms": stats.get("fetch_ms", 0.0), "retry_after_seconds": 900 if mode == "snapshot" else 0}}, mode


def populate_database(conn, snapshot: dict, mode: str):
    database.upsert_instruments(conn)
    prices, rates = [], []
    for symbol, series in snapshot["series"].items():
        for bar in series["bars"]:
            common = {"id": f"{symbol}:{bar['date']}", "instrument_id": symbol, "date": bar["date"], "source": series["source"]}
            if symbol in PRICE_SYMBOLS:
                prices.append({**bar, **common})
            else:
                rates.append({**common, "value": bar["close"]})
    database.insert_price_rows(conn, prices)
    database.insert_macro_rows(conn, rates)
    conn.execute("CREATE TABLE delivery_metadata (mode TEXT, fetched_at TEXT, telemetry TEXT)")
    conn.execute("INSERT INTO delivery_metadata VALUES (?, ?, ?)", (mode, snapshot["fetched_at"], json.dumps({**snapshot.get("_telemetry", {}), **snapshot.get("_delivery", {})})))


def delivery_metadata(conn):
    exists = conn.execute("SELECT name FROM sqlite_master WHERE name = 'delivery_metadata'").fetchone()
    if exists:
        metadata = dict(conn.execute("SELECT * FROM delivery_metadata").fetchone())
        stats = json.loads(metadata.pop("telemetry"))
        return {**metadata, **stats}
    return {"mode": "demo", "fetched_at": None}


def demo_enabled() -> bool:
    # Vercel (including previews) and explicit production environments fail closed.
    return os.getenv("MARKET_REGIME_DEMO_MODE") == "1" and not os.getenv("VERCEL") and os.getenv("ENVIRONMENT", "").lower() != "production"
