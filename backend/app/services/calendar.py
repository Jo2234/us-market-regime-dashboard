"""Completed US equity sessions from a checked-in exchange_calendars schedule."""
import bisect
import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path


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
    index = bisect.bisect_right(closes, (now - timedelta(minutes=30)).timestamp()) - 1
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
