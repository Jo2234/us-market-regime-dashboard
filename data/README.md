# Data Directory

The backend creates `market_regime.sqlite3` here on startup and seeds it with deterministic demo market history when empty. The seeded history ends on the latest local business day at startup, so `GET /data/freshness` should read fresh in demo mode during normal weekday development.

Provider ingestors can upsert public Stooq and FRED data over the demo source without changing API contracts. Upserts are keyed by instrument, date, and source, which lets real public observations coexist with or replace demo rows without duplicate records.

CSV export endpoints:

- `GET /export/sectors.csv?windows=1d,1m,3m`
- `GET /export/series/SPY.csv?start=YYYY-MM-DD&end=YYYY-MM-DD`

The CSV endpoints export computed API data, not separate static files in this directory.
