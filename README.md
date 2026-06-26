# US Market Regime Dashboard

Compact market dashboard API with seeded market data, return calculations, volatility, yield curve, freshness checks, and transparent regime classification.

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
