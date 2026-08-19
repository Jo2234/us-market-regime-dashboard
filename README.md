# US Market Regime Dashboard

Daily US market dashboard with Yahoo Finance prices, adjusted returns, a labelled yield curve, observation-level provenance and deterministic regime rules.

[Live dashboard](https://market-regime-dashboard-mu.vercel.app) · [Formula definitions](docs/formulas.md)

## Data sources

All 25 supported market series come from Yahoo Finance's unofficial v8 chart endpoint. The canonical mapping is in `backend/app/data/instruments.py`:

| Instruments / retained API IDs | Yahoo ticker(s) |
| --- | --- |
| Major indices | SPY, QQQ, IWM, DIA |
| Sector SPDRs | XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC |
| Commodity ETFs | USO, GLD, CPER |
| VIX / DXY | `^VIX` / `DX-Y.NYB` |
| DGS3MO / DGS5 / DGS10 / DGS30 | `^IRX` / `^FVX` / `^TNX` / `^TYX` |
| DGS2 | `2YY=F` (2-year yield futures, futures-implied) |

DGS identifiers are retained to avoid breaking API consumers; they no longer imply FRED or constant-maturity Treasury data. The curve uses 3M, 2Y*, 5Y, 10Y and 30Y, all quoted directly in percent (5.24 = 5.24%). 3M is a discount yield. Yahoo has no equivalent cash 2Y index. We chose its [CME 2-year yield future](https://www.cmegroup.com/education/articles-and-reports/introducing-yield-futures) to keep the market feed Yahoo-only, with explicit API/UI labels. **The 10Y−2Y* spread mixes a Treasury index and a futures-implied yield; it is not the standard cash recession spread.** Futures rolls, liquidity and settlement timing can affect it. `ZT=F` is not used because it is a price-based Treasury future, not a quoted yield.

CPI YoY, unemployment and Fed funds have no equivalent Yahoo instrument in this feed. Their existing API fields remain null, their coverage is marked unavailable, and the CPI model input is neutral with reduced confidence. Nothing replaces them with synthetic values. DXY remains accessible through `/series/DXY` and the additive `currency_summary` field.

Displayed **price** is the actual unadjusted last completed daily close. Returns and indexed charts use Yahoo **adjusted close**. The legacy `value` field remains adjusted close for compatibility. Every market series identifies `source: yahoo_finance`, `yahoo_ticker`, and its observation date. Calendar return windows and YTD are defined precisely in [docs/formulas.md](docs/formulas.md) and the UI source section.

## Refresh, caching and failures

The server uses a direct HTTPX chart client instead of yfinance to keep serverless dependencies and request behavior small and predictable. It fetches two years per symbol, four requests at a time, with a browser User-Agent, 4-second request timeouts, three attempts with exponential backoff, and an 18-second total batch deadline inside the 30-second Vercel function budget. Yahoo's unfinished daily bars are excluded until 30 minutes after the NYSE close. Exchange calendars handle holidays, weekends, DST and early closes.

Successful batches are cached in memory per instance for 15 minutes. Successful GET responses send `Cache-Control: public, max-age=0, s-maxage=900, stale-while-revalidate=3600`. CDN responses can therefore be older during revalidation; check observation dates. Cold instances fetch Yahoo and build a request-local in-memory SQLite database. No persistent `/tmp` database or startup seed is used.

If Yahoo fails, the API serves the newest validated last-known-good dataset from instance memory or `backend/app/data/yahoo_snapshot.json`, explicitly marked `data_mode: snapshot`. Original dates and fetch time are preserved. Failed refreshes retry after 60 seconds per instance. If no valid snapshot exists, the API returns 503 and the UI shows **Live data unavailable**. Successful direct Yahoo requests are labelled **Live · Yahoo Finance · as of DATE**; this means a live data source, not intraday quotes. Snapshot responses say **Snapshot · as of DATE**.

`.github/workflows/refresh-market-data.yml` refreshes the committed snapshot on weekdays at 22:35 UTC, after the US close in both EST and EDT. It can also be dispatched manually. It commits as `github-actions[bot]` only if observations changed, rejects regressing dates, and leaves the previous file intact if Yahoo fails. GitHub schedules may be delayed and Yahoo may rate-limit or change its undocumented endpoint. An unchanged holiday dataset does not produce a timestamp-only commit. The snapshot is bundled in the Vercel Python function. `MARKET_REGIME_SNAPSHOT_ONLY=1` can explicitly select snapshots if a hosting network cannot reach Yahoo.

## Run

Use Python 3.11+ and Node.js 22.12+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
npm ci --prefix frontend
VITE_API_BASE_URL=/api npm run dev --prefix frontend -- --port 5173
```

The Vite development proxy defaults to port 8000 (`DEV_API_TARGET` overrides it). Production builds call same-origin `/api`. Existing CORS access for Johan's personal site is preserved. Open `/docs` on the local backend for the API, including series, sector, freshness and CSV endpoints. API fields are additive; historical prices and selected-date analytics are available within the roughly two-year downloaded range.

## Tests and live verification

```bash
PYTHONPATH=backend python -m pytest backend/tests
npm test --prefix frontend
npm run build --prefix frontend
python scripts/verify_live_data.py --base-url https://market-regime-dashboard-mu.vercel.app
```

Unit tests block network access and use recorded Yahoo chart responses in `backend/tests/fixtures`. They cover raw/adjusted prices, calendar return anchors, missing data, units, holidays, production demo guards, caching, retries, snapshot fallback and 503 failure. The separate verification script fetches Yahoo independently, calculates the 1M return without importing application analytics, compares SPY/QQQ prices and all five yields with production, checks dates/provenance, prints a table and exits nonzero on mismatch. Tolerances are 0.00011 price/yield units and 0.000051 percentage points for returns.

Refresh the committed fallback manually:

```bash
python scripts/refresh_snapshot.py
```

For a local failure test, start a fresh backend process with `MARKET_REGIME_FORCE_YAHOO_FAILURE=1`; responses must be labelled snapshots. With the snapshot file unavailable too, expect HTTP 503. Never remove the production snapshot to test this; unit tests use a temporary missing path.

## Explicit offline demos

Synthetic fixtures are restricted to tests and opt-in local demos. Set `MARKET_REGIME_DEMO_MODE=1` for a local backend demo with a fixed historical end date. This flag is ignored on Vercel and when `ENVIRONMENT=production`. `VITE_USE_DEMO_DATA=true` works only in Vite development mode; production builds omit the embedded demo module entirely. No API error silently enables it.

## Known limits

Yahoo is unofficial, may rate-limit, revise adjusted history or omit bars, and offers no availability guarantee. The UI labels stale observations and unsupported breadth/macro coverage. ETF proxies, futures and yield indices have different economic meanings. The rule-based regime is an explanation of these inputs, not a predictive guarantee. Historical regime backfills are request-local on serverless hosting; they are not persistently stored. The interface shows unavailable measurements as `n/a`.

## License

[MIT License](LICENSE). Third-party data and dependencies retain their own terms.
