# US Market Regime Dashboard Backend

FastAPI backend for Project 2. It provides seeded demo data, optional public ingestion hooks, analytics, regime classification, and freshness APIs.

## Setup

```bash
cd projects/us-market-regime-dashboard/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload
```

The API seeds a deterministic SQLite demo database at `../data/market_regime.sqlite3` on startup.

## API

- `GET /dashboard/summary?date=YYYY-MM-DD`
- `GET /series/{symbol}?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /sectors/performance?windows=1d,1w,1m,3m,ytd,1y`
- `GET /rates/yield-curve?date=YYYY-MM-DD`
- `POST /regime/recalculate`
- `GET /data/freshness`
- `GET /export/sectors.csv?windows=1d,1m`
- `GET /export/series/{symbol}.csv?start=YYYY-MM-DD&end=YYYY-MM-DD`

`../main.py` is a compatibility entrypoint for root-level smoke tests and legacy `backend.main:app` imports. New backend code should import from the `app` package.

## Formulas

- Returns use adjusted close when available, otherwise close.
- 1D, 1W, 1M, 3M, and 1Y use 1, 5, 21, 63, and 252 trading-day offsets.
- YTD return uses the first available trading observation in the current calendar year.
- Rolling volatility is annualized as `std(daily returns) * sqrt(252)`.
- Drawdown is the minimum percentage decline from the cumulative high over the selected lookback.
- Yield spread is the difference between Treasury yield observations in percentage points.

## Tests

```bash
cd projects/us-market-regime-dashboard/backend
PYTHONPATH=. pytest
```
