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
- Backend tests cover the application entrypoint, API, seeded data, analytics and regime behavior.

## Run

Use Python 3.11+ and Node.js 22 LTS (22.12 or newer). Start from the repository root.

Install the backend dependencies and start the API:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend python -m uvicorn app.main:app --reload --port 8000
```

In a second terminal, start the Vite/React/TypeScript frontend:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev -- --port 5173
```

Open <http://localhost:5173>. The example frontend environment selects the API at
<http://localhost:8000>, with embedded demo mode disabled. The API documentation is
available at <http://localhost:8000/docs>. If you use another API address, update
`VITE_API_BASE_URL` in `frontend/.env.local` and restart Vite.

To verify a production build locally, stop the frontend dev server and run from
`frontend/`:

```bash
npm run build
npm run preview -- --port 5173
```

Vite writes the built site to `frontend/dist`. Keep the API running when viewing
this local preview. Production deployment uses `vercel.json`; without a local
`VITE_API_BASE_URL` override, the built frontend calls the same-origin `/api` routes.

## Test

With the backend virtual environment active, run from the repository root:

```bash
PYTHONPATH=backend python -m pytest backend/tests
```

Run frontend tests from `frontend/`:

```bash
npm test
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

## API snapshot consistency

The summary resolves the selected date to the latest available SPY observation and recomputes the regime from current stored inputs on every request. Other summary blocks use that same observation cutoff; an older saved snapshot is never reused as the current regime. Saved classifications remain available as history. After revising historical input observations, rerun `/regime/recalculate` to refresh that stored history.

The API now supplies all eleven sectors, actual stored macro observations, indexed major-index performance for the selected return range, and available saved regime history. The frontend constructs its API view solely from these response fields. Missing measurements display `n/a`, unsupported breadth is marked unavailable, and a previous yield curve is drawn only when supplied. Embedded fixtures are used only in explicit demo or fallback mode. The default production `/api` base resolves against the page origin; absolute API base overrides continue to work.

Regime backfills load market and macro history once per request, then apply the same classification rules with a date cutoff for each snapshot. Prior-snapshot change notes remain sequential and deterministic.

## License

Project code is available under the [MIT License](LICENSE). Third-party dependencies retain their own licenses.
