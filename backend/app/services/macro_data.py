"""Independent FRED cache, per-series fallback and calendar-month transformations."""
from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from app.core.telemetry import log_event
from app.data import database
from app.data.instruments import FRED_SERIES, MONTHLY_FRED, provenance
from app.ingestion.fred import fetch_batch
from app.services.calendar import latest_completed_session, missed_sessions

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "fred_snapshot.json"
CACHE_SECONDS = 3600
FAILURE_SECONDS = 900
_cached: dict = {}
_expires: dict = {}
_modes: dict = {}
_lock = threading.Lock()


def validate_series(series_id: str, series: dict) -> dict:
    if not isinstance(series, dict) or series.get("source") != "fred" or series.get("fred_series_id") != series_id or series_id not in FRED_SERIES.values():
        raise ValueError("Invalid FRED provenance")
    datetime.fromisoformat(series["fetched_at"])
    observations = series["observations"]
    if not observations:
        raise ValueError("Empty FRED series")
    dates = [date.fromisoformat(r["date"]) for r in observations]
    if dates != sorted(set(dates)) or dates[-1] > datetime.now(timezone.utc).date():
        raise ValueError("Invalid FRED observation dates")
    if series_id in MONTHLY_FRED and any(d.day != 1 for d in dates):
        raise ValueError("Monthly FRED dates must denote the observation month")
    for row in observations:
        value = row["value"]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Invalid FRED value")
        if series_id in {"CPIAUCSL", "CPILFESL"} and value <= 0:
            raise ValueError("Invalid CPI index")
    if series_id in {"CPIAUCSL", "CPILFESL"} and not yoy_observations(observations):
        raise ValueError("CPI requires a matching year-ago month")
    if series_id in {"CPIAUCSL", "CPILFESL"} and yoy_observations(observations)[-1]["date"] != observations[-1]["date"]:
        raise ValueError("Latest CPI index has no matching year-ago month")
    return series


def yoy_observations(observations: list[dict]) -> list[dict]:
    levels = {r["date"]: r["value"] for r in observations}
    result = []
    for row in observations:
        day = date.fromisoformat(row["date"])
        baseline = levels.get(day.replace(year=day.year - 1).isoformat())
        if baseline is not None and baseline > 0:
            result.append({"date": row["date"], "value": (row["value"] / baseline - 1) * 100})
    return result


def read_snapshot() -> dict:
    try:
        raw = json.loads(SNAPSHOT_PATH.read_text())
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("series"), dict):
            return {}
    except (OSError, ValueError):
        return {}
    result = {}
    for series_id, series in raw.get("series", {}).items():
        try:
            result[series_id] = validate_series(series_id, series)
        except (ValueError, KeyError, TypeError):
            continue  # A corrupt macro card cannot remove the other real series.
    return result


def get_snapshot(*, cached_only=False) -> tuple[dict, dict]:
    if cached_only:
        # Bootstrap never waits for a FRED refresh or contacts a provider.
        return _delivered({**read_snapshot(), **_cached}, {}, bootstrap=True)
    with _lock:
        fallbacks = read_snapshot()
        for series_id, series in fallbacks.items():
            if series_id not in _cached or series["observations"][-1]["date"] > _cached[series_id]["observations"][-1]["date"]:
                _cached[series_id] = series
                _modes[series_id] = "snapshot"
        due = [s for s in FRED_SERIES.values() if time.monotonic() >= _expires.get(s, 0)]
        stats = {"fetch_ms": 0.0}
        if due:
            results, stats = asyncio.run(fetch_batch(due))
            for series_id in due:
                try:
                    series = validate_series(series_id, results[series_id])
                    if series_id in _cached and series["observations"][-1]["date"] < _cached[series_id]["observations"][-1]["date"]:
                        raise ValueError("Refusing older FRED observations")
                    _cached[series_id], _modes[series_id] = series, "live"
                    _expires[series_id] = time.monotonic() + CACHE_SECONDS
                except (KeyError, ValueError, TypeError):
                    _modes[series_id] = "snapshot" if series_id in _cached else "unavailable"
                    _expires[series_id] = time.monotonic() + FAILURE_SECONDS
        result, delivery = _delivered(_cached, stats, refreshed=due)
        log_event("fred_cache", **delivery)
        return result, delivery


def _delivered(series, stats, *, bootstrap=False, refreshed=()):
    delivery = {**stats, "series": {}}
    for symbol, series_id in FRED_SERIES.items():
        item = series.get(series_id)
        mode = _modes.get(series_id, "snapshot") if item else "unavailable"
        if bootstrap and time.monotonic() >= _expires.get(series_id, 0):
            mode = "snapshot" if item else "unavailable"
        delivery["series"][symbol] = {
            "mode": mode, "cache": ("miss" if series_id in refreshed else "hit") if mode == "live" else "stale",
            "fetched_at": item["fetched_at"] if item else None,
            "retry_after_seconds": max(0, math.ceil(_expires.get(series_id, 0) - time.monotonic())) if mode != "live" else 0,
        }
    return dict(series), delivery


def populate_database(conn, series, delivery):
    database.upsert_instruments(conn)
    rows = []
    for symbol, series_id in FRED_SERIES.items():
        item = series.get(series_id)
        if not item:
            continue
        observations = yoy_observations(item["observations"]) if symbol.endswith("CPI_YOY") else item["observations"]
        rows.extend({"id": f"{symbol}:{r['date']}", "instrument_id": symbol, "date": r["date"],
                     "value": r["value"], "source": "fred"} for r in observations)
    database.insert_macro_rows(conn, rows)
    conn.execute("CREATE TABLE macro_delivery (payload TEXT)")
    conn.execute("INSERT INTO macro_delivery VALUES (?)", (json.dumps(delivery),))


def delivery_metadata(conn):
    exists = conn.execute("SELECT name FROM sqlite_master WHERE name='macro_delivery'").fetchone()
    return json.loads(conn.execute("SELECT payload FROM macro_delivery").fetchone()[0]) if exists else {}


def freshness(symbol: str, latest: date | None, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    if FRED_SERIES.get(symbol) not in MONTHLY_FRED:
        lag = missed_sessions(latest, latest_completed_session()) if latest else None
        stale = lag is not None and lag > (2 if symbol == "FEDFUNDS" else 1)
        policy = "Daily FRED: allow one completed business session of publication lag (two for DFF); exchange-calendar proxy."
    else:
        # Conservative publication windows: first ten days for jobs/monthly funds,
        # first twenty for CPI. No invented publication dates or daily resampling.
        deadline = 20 if symbol.endswith("CPI_YOY") else 10
        allowed_months = 2 if today.day <= deadline else 1
        lag = (today.year - latest.year) * 12 + today.month - latest.month if latest else None
        stale = lag is not None and lag > allowed_months
        policy = f"Monthly: allow previous month; through day {deadline}, also allow the month before it for publication lag. Dates denote observation months."
    return {"is_stale": stale, "status": "unavailable" if latest is None else "stale" if stale else "fresh",
            "freshness_policy": policy, "missing_sessions": None}


def summary(conn, history, as_of):
    from app.services.analytics import latest_macro_value
    delivery = delivery_metadata(conn).get("series", {})
    result = {}
    for symbol in FRED_SERIES:
        value = latest_macro_value(history, symbol, as_of)
        if value:
            day = date.fromisoformat(value["date"])
            value.update(delivery.get(symbol, {}))
            value.update(freshness(symbol, day))
            value["observation_label"] = day.isoformat() if FRED_SERIES.get(symbol) not in MONTHLY_FRED else day.strftime("%b %Y")
        result[symbol] = value
    return result


def available_on(symbol, observed):
    """Approximate release date, using revised vintage; not a point-in-time feed."""
    from datetime import timedelta
    from app.services.calendar import session_close
    if FRED_SERIES.get(symbol) not in MONTHLY_FRED:
        day = observed + timedelta(days=1)
        while session_close(day) is None:
            day += timedelta(days=1)
        return day
    month = date(observed.year + (observed.month == 12), observed.month % 12 + 1, 1)
    if symbol.endswith("CPI_YOY"):
        return month.replace(day=15)
    if symbol == "UNRATE":
        return month + timedelta(days=(4 - month.weekday()) % 7)
    return month + timedelta(days=6)  # Monthly average: conservative first-week proxy.
