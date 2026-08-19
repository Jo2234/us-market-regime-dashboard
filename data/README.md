# Data

Production does not store data in this directory or persist a SQLite database. The committed Yahoo fallback is `backend/app/data/yahoo_snapshot.json`, refreshed by `scripts/refresh_snapshot.py` and the scheduled GitHub workflow. It retains real provider observation dates and is bundled with the serverless function. Recorded provider fixtures for offline tests live in `backend/tests/fixtures`.
