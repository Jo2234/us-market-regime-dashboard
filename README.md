# US Market Regime Dashboard

Daily US market dashboard with Yahoo Finance prices, FRED macro observations, adjusted returns, a labelled yield curve and deterministic regime rules.

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

Macro data comes from [FRED, Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org/). The retained API keys and new additive fields are:

| API macro key | FRED series | Measurement |
| --- | --- | --- |
| FEDFUNDS | [DFF](https://fred.stlouisfed.org/series/DFF) | Daily effective Fed funds rate, percent |
| FEDFUNDS_MONTHLY | [FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS) | Monthly average, secondary context |
| CPI_YOY | [CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL) | Headline CPI YoY, derived from the seasonally adjusted index |
| CORE_CPI_YOY | [CPILFESL](https://fred.stlouisfed.org/series/CPILFESL) | Core CPI YoY, derived from the seasonally adjusted index |
| UNRATE | [UNRATE](https://fred.stlouisfed.org/series/UNRATE) | Seasonally adjusted unemployment rate, percent |

**Fed funds uses daily DFF for the headline**, preserving the `FEDFUNDS` API key. A monthly average can lag a policy change: the September 25, 2026 DFF observation is 3.88%, while August's monthly average is 3.63%. Both are labelled separately; neither is a target-range midpoint. Each macro value supplies `source: fred`, `fred_series_id`, `source_url`, `frequency`, `observation_date`, `observation_label`, `mode`, and `fetched_at`. Null means unavailable. DXY remains accessible through `/series/DXY` and `currency_summary`.

The backward-compatible daily API **price** is the actual unadjusted last completed daily close. Additive `live_quotes` carry regular-market prices, timestamps and intraday returns; the UI displays current-session quotes while NYSE is open. If Yahoo leaves the latest completed daily bar null, its same-session regular-market quote may supply the close only when the quote timestamp is at or after the official NYSE close (including early closes). The normalized bar is tagged `close_source: yahoo_meta`. Its adjusted close temporarily equals that unadjusted close, tagged as provisional; the next history refresh prefers Yahoo’s filled bar and adjustment. Older-day or pre-close metadata cannot repair a bar. Returns and indexed charts use Yahoo **adjusted close**. The legacy `value` field remains adjusted close for compatibility. Every market series identifies `source: yahoo_finance`, `yahoo_ticker`, and its observation date. Calendar return windows and YTD are defined precisely in [docs/formulas.md](docs/formulas.md) and the UI source section.

## Refresh, caching and failures

The server uses a direct HTTPX chart client instead of yfinance to keep serverless dependencies and request behavior small and predictable. It fetches two years per symbol, eight requests at a time through one shared HTTPX session, with a browser User-Agent, 8-second request timeouts, at most two retries for transport failures/429/5xx with exponential backoff and jitter, and an 18-second total batch deadline inside the 30-second Vercel function budget. Yahoo's unfinished daily bars are excluded until the official NYSE close. A checked-in NYSE schedule generated with `exchange_calendars` handles holidays, weekends, DST and early closes. The runtime uses standard-library analytics; pandas, NumPy and exchange_calendars are development dependencies only. The schedule covers 2020–2031 and fails closed after expiry. Run `python scripts/refresh_calendar.py` annually and after exceptional exchange closure announcements; update its date bounds before expiry.

Daily-history batches are cached per instance for 15 minutes, invalidated when a new session completes. CDN caching is 60 seconds during NYSE hours (15-second stale revalidation) and up to 900 seconds when closed (60-second stale revalidation), capped at the next session boundary. CDN responses can therefore be older during revalidation; check observation dates. Cold instances fetch Yahoo and build a request-local in-memory SQLite database. No persistent `/tmp` database or startup seed is used.

If Yahoo fails, the API serves the newest validated last-known-good dataset from instance memory or `backend/app/data/yahoo_snapshot.json`, explicitly marked `data_mode: snapshot`. Original dates and fetch time are preserved. Successful and failed refreshes both have a 15-minute per-instance cooldown, including failures with no snapshot. A single-flight lock coalesces concurrent requests. Query/date/range changes and manual Refresh cannot bypass this cooldown. If no valid snapshot exists, the API returns 503 and the UI shows **Live data unavailable**, with automatic backoff and a Retry button. Successful direct Yahoo requests are labelled **Live · Yahoo Finance · as of DATE**; quotes are intraday during NYSE hours and completed daily closes when closed. Snapshot responses say **Snapshot · as of DATE**.

FRED has an independent one-hour, single-flight per-instance cache. `FRED_API_KEY`, when set, selects the official observations JSON API; otherwise the no-key FRED graph CSV endpoint is used. Five series fetch concurrently in one lightweight HTTPX session, with 3.5-second request timeouts, up to two retries for transport/429/5xx errors, and a six-second total deadline. The existing normalization code handles CSV `observation_date`, missing values and zero rates. FRED uses the Python client's User-Agent: the Yahoo browser string timed out against FRED in local checks. No heavy analytics dependency is added. Yahoo and FRED fetch concurrently; the larger 18-second budget plus the five-second quote budget stays within the 30-second function limit.

Each macro series independently falls back to its last real observations in memory or `backend/app/data/fred_snapshot.json`, preserving dates and fetch times; failed refreshes cool down for 15 minutes. A failed CPI request does not remove DFF, unemployment or Yahoo prices. A missing/corrupt series shows Unavailable only on its card. `macro_delivery` exposes per-series mode/cache and upstream timing/status diagnostics without keys. `?cached_only=true` also returns macro snapshots without contacting FRED. `MARKET_REGIME_FORCE_FRED_FAILURE=1` provides a local kill-test. CDN caching is shared with the summary response.

`.github/workflows/refresh-market-data.yml` refreshes both committed snapshots on weekdays at 22:35 UTC, after the US close in both EST and EDT. It can also be dispatched manually. It commits as `github-actions[bot]` only if observations changed, rejects regressing dates, and retains prior data for any failed provider/series. It can commit successful provider updates even when the other fails; the failed workflow remains visible. The optional repository secret `FRED_API_KEY` selects JSON on the runner; otherwise it uses CSV. GitHub schedules may be delayed and Yahoo may rate-limit or change its undocumented endpoint. An unchanged holiday dataset does not produce a timestamp-only commit. The snapshot is bundled in the Vercel Python function. `MARKET_REGIME_SNAPSHOT_ONLY=1` can explicitly select snapshots if a hosting network cannot reach Yahoo.

## Deployment verification

On 2026-09-29, the production Vercel function successfully fetched Yahoo directly (`data_mode: live`); the initial migration needed no Vercel settings change or snapshot-primary switch. The subsequent performance audit temporarily added two encrypted diagnostics environment variables; both were removed after measurement. See the dated [performance audit](docs/performance.md). `scripts/verify_live_data.py` matched SPY 765.61, QQQ 736.53, calendar 1M adjusted returns −0.2390% / +2.9127%, and all five yields for the completed 2026-09-28 session. GitHub Actions also successfully refreshed the snapshot. These are dated checks, not a promise of future Yahoo availability.

FRED CSV was also verified directly from Vercel on September 29: five HTTP 200 responses, no retries/429s, 796 ms for the parallel macro batch. GitHub Actions fetched the same five series in 431 ms and retained the unchanged macro snapshot. No Vercel settings changed for the FRED integration. See the [macro verification report](docs/macro-verification.md) for values, regime impact and test evidence.

## Loading and refresh behavior

The initial layout is a responsive skeleton with a polite loading announcement; after four seconds it acknowledges the delay. Motion respects `prefers-reduced-motion`. The client immediately displays its last verified real response (one bounded localStorage entry matching date/window), or asks `?cached_only=true` for the bundled/instance snapshot. That bootstrap path never contacts Yahoo/FRED or waits for a refresh lock. A normal request runs alongside it; data stays visible with an Updating indicator until it completes. Failure retains the last real values, dates and fetch time, and offers Refresh. Without real data, the error page contains no example values. Retries use 5, 10, 20, … seconds, capped at 15 minutes, respecting the API snapshot cooldown; successful pages poll every 60 seconds during NYSE hours and up to 15 minutes otherwise. Hidden tabs pause polling and refresh on visibility; historical date selections keep daily values. Quote failures double the 60-second interval up to 15 minutes and successful batches halve it toward 60 seconds. The default date stays “latest” internally so a new trading session is picked up automatically.

`fetch_ms`, `cache` (`hit`, `miss`, `stale`), `fetched_at`, `retry_after_seconds` and `fetch_diagnostics` are additive summary fields. `fetched_at` is the successful upstream fetch time, never the render time. Logs include each ticker's elapsed time/attempts/retries and 429/401/5xx totals. `Server-Timing` reports app, import and Yahoo time. On instance hits, `fetch_ms=0`; diagnostics describe the last refresh. A CDN hit replays the original JSON/headers: use `X-Vercel-Cache`/`Age` to distinguish it from a new function execution. `X-Market-Revision`, `X-Market-Instance` and `X-Market-Request` make cold/warm measurements auditable.

All dashboard tabs share one two-year dataset: the displayed 1D/1W chart still accompanies 1Y returns, 200-day averages and regime calculations. Separate series/rates endpoints reuse that same cache, so switching views does not trigger more downloads. Five-day refreshes were benchmarked against two years; see [production measurements](docs/performance.md) for the decision. Splitting adjusted histories without refetching corporate-action revisions would risk incorrect returns. Cache protection is per warm instance plus the CDN; simultaneous new instances/regions can each refresh once. This is not a global distributed quota, and Yahoo remains an unofficial, rate-limited upstream.

For visual QA only, run the frontend with `VITE_ENABLE_QA=true` and the backend with `MARKET_REGIME_FORCE_YAHOO_FAILURE=1`. The local URLs `?qa=skeleton`, `?qa=background`, `?qa=stale`, and `?qa=error` delay/fail requests while using the real committed snapshot. These switches are excluded from production builds.

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

Unit tests block network access and use recorded Yahoo chart responses and FRED CSV responses in `backend/tests/fixtures`. They cover raw/adjusted prices, calendar return anchors, missing data, units, holidays, production demo guards, caching, retries, snapshot fallback and 503 failure. The separate verification script fetches Yahoo independently, calculates the 1M return without importing application analytics, compares SPY/QQQ prices, all five yields, and all five macro measurements with production, checks dates/provenance, prints a table and exits nonzero on mismatch. Tolerances are 0.00011 price/yield units and 0.000051 percentage points for returns and macro values. FRED YoY is independently calculated from exact year-ago months.

Refresh the committed fallback manually:

```bash
python scripts/refresh_snapshot.py
```

For a local failure test, start a fresh backend process with `MARKET_REGIME_FORCE_YAHOO_FAILURE=1`; responses must be labelled snapshots. With the snapshot file unavailable too, expect HTTP 503. Never remove the production snapshot to test this; unit tests use a temporary missing path.

## Explicit offline demos

Synthetic fixtures are restricted to tests and opt-in local demos. Set `MARKET_REGIME_DEMO_MODE=1` for a local backend demo with a fixed historical end date. This flag is ignored on Vercel and when `ENVIRONMENT=production`. `VITE_USE_DEMO_DATA=true` works only in Vite development mode; production builds omit the embedded demo module entirely. No API error silently enables it.

## Known limits

Yahoo is unofficial, may rate-limit, revise adjusted history or omit bars, and offers no availability guarantee. The UI labels stale observations and unsupported breadth coverage. FRED may delay releases, rate-limit downloads, and revise historical values. Monthly observation dates are not release dates; historical views use the latest revised vintage and are not point-in-time backtests. ETF proxies, futures and yield indices have different economic meanings. The rule-based regime is an explanation of these inputs, not a predictive guarantee. Historical regime backfills are request-local on serverless hosting; they are not persistently stored. The interface shows unavailable measurements as `n/a`.

## License

[MIT License](LICENSE). Third-party data and dependencies retain their own terms.

### Intraday quotes

Yahoo's unauthenticated **v7 spark** endpoint returns metadata for batches of at most 20 symbols; all 25 instruments use two concurrent requests through one HTTPX client with minimal `Mozilla/5.0` User-Agent. The v8 spark response tested here is flat and lacks `regularMarketTime`, so v7 spark is used to verify quote observation times. The crumb-protected v7 **quote** endpoint is not used. Quotes have a separate single-flight cache, four-second request timeout and five-second total deadline. On 401/429 or transport failure, preserve the last good observations and back off the next batch (60 → 120 → … → 900 seconds); do not immediately retry and amplify a rate limit. Telemetry is additive in `quote_delivery`; `market_status` reports the exchange clock. Older-session/stale quotes never replace a current daily close in the UI. Futures and FX follow the same NYSE refresh schedule; overnight trading is intentionally not polled.

Daily classifications and the legacy daily fields remain based on completed sessions. `live_quotes` alone supplies the intraday endpoint: 1D uses Yahoo's previous regular close (or the prior daily bar if missing); calendar returns use live price over adjusted historical close. Yahoo may delay quotes or corporate-action adjustments, especially on an ex-dividend day. FRED remains daily/monthly, cached for one hour. `MARKET_REGIME_CLOCK=<ISO timestamp>` allows local/preview calendar verification and is ignored in production. `MARKET_REGIME_FORCE_QUOTE_FAILURE=1` exercises fallback without deliberately triggering upstream rate limits.

For one continuously visited CDN cache key/location in a 30-day month with 22 full trading sessions: 22 × 390 = 8,580 open-market refreshes, plus 34,620 closed minutes / 15 = 2,308, approximately **10,888 origin invocations/month** before bootstrap requests, revalidation and cold-instance effects. Each open quote refresh uses two spark calls. Visitors sharing a CDN key share cached responses; different ranges/dates/locations and evicted instances increase totals. This is a traffic model, not a billing guarantee.

### Historical regimes

The trailing 12 months of daily classifications (about 252 sessions) are derived from the two-year price history, not request-time SQLite rows. Normalized price frames are reused across dates. A bounded, single-flight per-instance cache keys the result by observed price/macro values and model version, so unchanged requests and quote refreshes do not recompute it. `history_delivery` reports cache status, calculation time and point count. The scheduled snapshot job also commits `backend/app/data/regime_history.json`; a matching input fingerprint lets cold fallback instances load it directly. Production summary requests do not write `regime_snapshots`.

Historical CPI is available from approximately the 15th of the following month; unemployment from the first Friday of the following month; daily effective Fed funds from the next NYSE business day (a holiday-aware approximation to publication, not an official release calendar). Only headline CPI enters the current model; unemployment and Fed funds remain display context. All FRED values use the latest revised vintage, so this history is explanatory and **not a point-in-time backtest**. The chart shows four normalized score lines, regime bands, and a date slider/hover/tap inspector with a View snapshot action.
