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

The API seeds deterministic demo history into `data/market_regime.sqlite3` on startup when the database is empty. Freshness is exposed at `GET /data/freshness`, including `generated_at`, `as_of_date`, per-source `status`, and the stale-age policy. CSV downloads are available at `GET /export/sectors.csv` and `GET /export/series/{symbol}.csv`.

The frontend now labels the current source mode explicitly:

- `api` means the dashboard came from the configured FastAPI backend.
- `demo` means `VITE_USE_DEMO_DATA=true` loaded the deterministic embedded snapshot.
- `fallback` means the API request failed and demo data was rendered instead.

Each mode includes provenance text, source labels, generated/selected dates, and a freshness policy. Demo source dates are intentionally fixed so test and product-demo screenshots are reproducible; the dashboard marks stale, partial, and missing optional providers instead of hiding those gaps.

## Historical Regime Explainability

The demo UI includes a historical regime score chart covering risk, growth, inflation, and rates-pressure components. It is a compact explainability aid: the score paths show why a label moved toward risk-on, mixed-transition, or defensive-tilt instead of presenting only the latest label. When the live API later returns backfilled regime classifications, the optional `historicalRegimes` field can be populated without changing existing dashboard sections.
