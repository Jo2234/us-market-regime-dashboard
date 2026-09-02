#!/usr/bin/env python3
"""Build the small runtime NYSE schedule; exchange_calendars stays a dev dependency."""
import json
from pathlib import Path
import exchange_calendars as xcals

calendar = xcals.get_calendar("XNYS", start="2020-01-01", end="2031-12-31")
payload = {"calendar": "XNYS", "library_version": xcals.__version__, "valid_through": "2031-12-31",
           "sessions": [[day.date().isoformat(), int(row["close"].timestamp())] for day, row in calendar.schedule.iterrows()]}
path = Path(__file__).resolve().parents[1] / "backend/app/data/nyse_sessions.json"
path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
print(f"Wrote {len(payload['sessions'])} sessions to {path.name}")

# A separate Globex schedule supplies futures trading dates and shortened sessions.
calendar = xcals.get_calendar("CMES", start="2020-01-01", end="2031-12-31")
payload = {"calendar": "CMES", "library_version": xcals.__version__, "valid_through": "2031-12-31",
           "sessions": [[day.date().isoformat(), int(row["close"].timestamp())] for day, row in calendar.schedule.iterrows()]}
path = path.with_name("cme_sessions.json")
path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
print(f"Wrote {len(payload['sessions'])} sessions to {path.name}")
