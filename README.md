# US Market Regime Dashboard

Compact market dashboard API with seeded market data, return calculations, volatility, yield curve, freshness checks, and transparent regime classification.

## What It Demonstrates

- Market-regime classification with visible inputs instead of opaque labels.
- Seeded deterministic data for repeatable local demos and tests.
- API endpoints for sector returns, volatility, yield curve state, data freshness, and CSV exports.
- A small frontend surface that makes the regime, market internals, and freshness state easy to inspect.

## Quick Proof

- `GET /data/freshness` exposes whether the demo data is current enough for the dashboard.
- `GET /export/sectors.csv` and `GET /export/series/{symbol}.csv` make the underlying data downloadable.
- Backend tests cover the API and seeded data behavior; root tests cover broader project behavior.

## Run

```bash
cd projects/us-market-regime-dashboard
PYTHONPATH=backend uvicorn app.main:app --reload --port 8002
```

Open `frontend/index.html` directly in a browser or serve it with:

```bash
python3 -m http.server 5174 -d frontend
```

## Test

```bash
cd projects/us-market-regime-dashboard
PYTHONPATH=.:backend pytest backend/tests tests
```

For backend-only work, this shorter command is equivalent:

```bash
cd projects/us-market-regime-dashboard/backend
PYTHONPATH=. pytest
```

## Data And Exports

The API seeds deterministic demo history into `data/market_regime.sqlite3` on startup when the database is empty. Freshness is exposed at `GET /data/freshness`, and CSV downloads are available at `GET /export/sectors.csv` and `GET /export/series/{symbol}.csv`.
