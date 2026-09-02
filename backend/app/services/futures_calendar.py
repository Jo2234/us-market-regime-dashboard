"""Yield futures settlement cadence, independent of the NYSE close.

CME 2YY daily settlement window ends at 14:00 America/Chicago. Globex
session ends are not settlement times. Short sessions cap that boundary;
Yahoo's current period may further shorten it, never extend it.
"""
import bisect
import json
from datetime import date, datetime, time, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
from app.services.calendar import market_now


@lru_cache(maxsize=1)
def _schedule():
    payload = json.loads((Path(__file__).resolve().parents[1] / "data/cme_sessions.json").read_text())
    days, settlements = [], []
    for day, close in payload["sessions"]:
        day = date.fromisoformat(day)
        days.append(day)
        settlements.append(min(datetime.combine(day, time(14), ZoneInfo("America/Chicago")).timestamp(), close))
    return days, settlements, date.fromisoformat(payload["valid_through"])


def settlement_time(day, meta=None):
    days, times, _ = _schedule()
    index = bisect.bisect_left(days, day)
    if index == len(days) or days[index] != day:
        return None
    boundary = times[index]
    if meta:
        end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end")
        tz = ZoneInfo(meta.get("exchangeTimezoneName", "America/New_York"))
        if isinstance(end, (int, float)) and datetime.fromtimestamp(end, tz).date() == day:
            boundary = min(boundary, end)
    return datetime.fromtimestamp(boundary, timezone.utc)


def latest_completed_settlement(now=None):
    now = now or market_now()
    days, times, valid_through = _schedule()
    if now.date() > valid_through:
        raise ValueError("CME schedule expired; run scripts/refresh_calendar.py")
    index = bisect.bisect_right(times, now.timestamp()) - 1
    if index < 0:
        raise ValueError("No supported completed futures session")
    return days[index]


def freshness(observed, now=None):
    expected = latest_completed_settlement(now)
    days, _, _ = _schedule()
    missed = max(0, bisect.bisect_right(days, expected) - bisect.bisect_right(days, observed)) if observed else None
    return {"expected_session_date": expected.isoformat(), "missing_sessions": missed,
            "is_stale": missed is not None and missed > 0,
            "status": "unavailable" if observed is None else "stale" if missed else "fresh",
            "affects_group_freshness": missed != 1,
            "freshness_policy": "CME yield futures: 14:00 CT settlement, with shortened Globex sessions. A one-session lag is flagged on this instrument only; longer lags affect the group."}
