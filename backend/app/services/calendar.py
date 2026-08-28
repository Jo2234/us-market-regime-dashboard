"""Completed US equity sessions from a checked-in exchange_calendars schedule."""
import bisect
import os
import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def _schedule():
    payload = json.loads((Path(__file__).resolve().parents[1] / "data/nyse_sessions.json").read_text())
    return ([date.fromisoformat(row[0]) for row in payload["sessions"]],
            [row[1] for row in payload["sessions"]], date.fromisoformat(payload["valid_through"]))


def latest_completed_session(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    dates, closes, valid_through = _schedule()
    if now.date() > valid_through:
        raise ValueError("NYSE schedule expired; run scripts/refresh_calendar.py")
    index = bisect.bisect_right(closes, now.timestamp()) - 1
    if index < 0:
        raise ValueError("No completed session in the supported calendar")
    return dates[index]


def missed_sessions(observed, expected) -> int:
    dates, _, _ = _schedule()
    return max(0, bisect.bisect_right(dates, expected) - bisect.bisect_right(dates, observed))


def session_close(day: date) -> datetime | None:
    """Official close, including early closes; None for weekends/holidays."""
    dates, closes, _ = _schedule()
    index = bisect.bisect_left(dates, day)
    if index >= len(dates) or dates[index] != day:
        return None
    return datetime.fromtimestamp(closes[index], timezone.utc)


def market_now():
    """Clock override is restricted to local/preview verification, never production."""
    override = os.getenv("MARKET_REGIME_CLOCK")
    if override and os.getenv("ENVIRONMENT", "").lower() != "production" and (not os.getenv("VERCEL") or os.getenv("VERCEL_ENV") == "preview"):
        return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def market_status(now=None):
    now = now or market_now()
    ny = ZoneInfo("America/New_York")
    day = now.astimezone(ny).date()
    close = session_close(day)
    opening = datetime.combine(day, datetime.min.time(), ny).replace(hour=9, minute=30)
    is_open = bool(close and opening <= now < close)
    dates, _, _ = _schedule()
    if close and now < opening:
        next_open = opening
    else:
        index = bisect.bisect_right(dates, day)
        next_open = datetime.combine(dates[index], datetime.min.time(), ny).replace(hour=9, minute=30)
    boundary = close if is_open else next_open
    ttl = max(1, min(60 if is_open else 900, int((boundary - now).total_seconds())))
    return {"is_open": is_open, "session_date": day.isoformat(),
            "completed_session": latest_completed_session(now).isoformat(),
            "session_close": close.isoformat() if close else None,
            "next_open": next_open.isoformat(), "server_time": now.isoformat(),
            "refresh_seconds": ttl, "model_basis": "completed_daily_closes"}
