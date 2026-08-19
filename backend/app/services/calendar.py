"""Completed US equity sessions, including holidays, DST and early closes."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd


@lru_cache(maxsize=8)
def market_calendar(year: int):
    return xcals.get_calendar("XNYS", start=f"{year - 6}-01-01", end=f"{year + 1}-12-31")


def latest_completed_session(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    calendar = market_calendar(now.year)
    # Allow 30 minutes after the exchange close for final daily bars to settle.
    cutoff = pd.Timestamp(now - timedelta(minutes=30))
    completed = calendar.schedule[calendar.schedule["close"] <= cutoff]
    return completed.index[-1].date()


def missed_sessions(observed, expected) -> int:
    if observed >= expected:
        return 0
    sessions = market_calendar(expected.year).sessions_in_range(
        max(pd.Timestamp(observed), pd.Timestamp(f"{expected.year - 6}-01-01")), pd.Timestamp(expected)
    )
    return sum(day.date() > observed for day in sessions)
