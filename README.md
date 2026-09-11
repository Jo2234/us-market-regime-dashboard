# Johan's Dashboard

Descriptive US market research software, not investment advice. Real Yahoo Finance prices, official FRED Treasury yields and macro observations, with a deterministic Growth/Inflation regime and an independent stress overlay.

[Live dashboard](https://market-regime-dashboard-mu.vercel.app) · [Methodology](docs/methodology.md) · [Formulas](docs/formulas.md)

## Data sources

The canonical instrument and source mapping is `backend/app/data/instruments.py`.

| Measurement | Provider and tickers/series |
| --- | --- |
| Major equity ETFs | Yahoo Finance: SPY, QQQ, IWM, DIA |
| Sector ETFs | Yahoo Finance: XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLU, XLRE, XLC |
| Commodity proxies | Yahoo Finance: USO, GLD, CPER, DBC |
| Credit and participation | Yahoo Finance: HYG, LQD, RSP |
| Volatility and dollar | Yahoo Finance: `^VIX`, `^VIX3M`, `DX-Y.NYB` |
| Official Treasury curve | FRED: DGS3MO, DGS2, DGS5, DGS10, DGS30 |
| Official curve spreads | FRED: T10Y2Y, T10Y3M |
| Fed funds | FRED: DFF (headline), FEDFUNDS (secondary monthly average) |
| Headline/core inflation | FRED: CPIAUCSL, CPILFESL (seasonally adjusted index levels; derive YoY) |
| Unemployment/claims | FRED: UNRATE, ICSA |
| Breakeven, real yield, financial conditions | FRED: T10YIE, DFII10, NFCI |

The Treasury curve uses **same-date official constant-maturity yields**, quoted in percent. Its 10Y–2Y and 10Y–3M spreads use the official FRED series on that date; if an official spread is missing, the API identifies a difference calculated from those same-date FRED yields. One business day of publication lag is normal. Yahoo live quotes never enter the official curve or spreads.

The retained `FEDFUNDS` API key uses **daily effective DFF**, which is more current than a monthly average. `FEDFUNDS_MONTHLY` provides the monthly average separately. Neither is a target-range midpoint. CPI YoY is derived from the corresponding index and the same month one year earlier. Each macro value includes its source, FRED series ID/link, observation date, frequency and transformation. Missing values remain unavailable.

Daily `price` is the unadjusted completed-session close; `adjusted_close` and the legacy `value` field are adjusted. Returns use adjusted history. During NYSE hours, additive `live_quotes` supply timestamped regular-market prices and live-endpoint returns. A null final daily bar can be repaired only by a same-session Yahoo quote timestamped at/after the official NYSE close; it is tagged `close_source: yahoo_meta`, with provisional adjusted close equal to raw close. The next filled Yahoo bar takes precedence. See the exact [return definitions](docs/formulas.md).

## Regime model

Growth and Inflation are equal-weight composites of distinct continuous signals, standardized against their own preceding 756 daily observations. They define Goldilocks, Reflation, Stagflation and Slowdown. Stress uses volatility, credit, financial conditions and drawdown; Rates and the dollar remain context. A new official quadrant needs five consecutive trading observations, except the fixed strong-evidence override. The page exposes emerging candidates, agreement/magnitude confidence and arithmetic single-input boundary scenarios. These are not forecasts or calibrated probabilities.

All parameters were documented before calculation. [Methodology](docs/methodology.md) records sources, publication-lag approximations, fixed thresholds and sensitivity counts. Historical macro uses latest revised vintage, **not point-in-time release data**. Phase 2 transition odds and forward-return statistics are out of scope.

`regime_v2` and `historical_regimes_v2` are additive. Legacy `regime` and `historical_regimes` remain populated for one release and are deprecated; their scores are the old rule model with the new persistence rule, not v2 scores. Johan's personal-site repository was searched for this dashboard URL: it links to the dashboard but does not consume its API. CORS and existing API keys remain intact.

## Refresh, caching and failures

Daily research is precomputed in GitHub Actions. The [independent RP watchdog](docs/refresh-watchdog.md), when installed and awake, requests builds **30 and 90 minutes after the official NYSE close** and at **14:07 UTC on weekdays**. It respects NYSE DST, holidays and early closes. Fixed GitHub fallback schedules remain at 14:07, 21:17 and 22:37 UTC on weekdays; they are best effort. The workflow fetches at least six years of Yahoo daily history (from January six years ago) and seven-plus years of FRED observations, computes full baselines and 252-session histories, and bundles `backend/app/data/dashboard_artifact.json.gz` (schema version 1). Warm-up is separate from the displayed year. Snapshot commits use `github-actions[bot]` and occur only when data/artifacts change. Failed providers retain their prior real observations; regressing observation dates are rejected. GitHub schedules may be delayed.

The visitor path loads that artifact once per instance and assembles the response. It does **no daily-history downloads or model calculation**. During NYSE hours, two Yahoo spark batches (at most 20 symbols each) refresh quotes with a two-second overall budget. Quotes cache for 60 seconds; 429/401/failures double the interval up to 15 minutes, and successes decay toward 60 seconds. One instance lock coalesces concurrent refreshes. The minimal `Mozilla/5.0` User-Agent is retained. Closed markets use completed daily observations and cache for up to 15 minutes.

CDN caching is 60 seconds open / up to 900 seconds closed, with 15/60 seconds of stale revalidation, capped at session boundaries. Simultaneous regions/instances can each refresh; this is not a global distributed quota. An active month with 21 full sessions needs roughly 8,190 open-market refresh invocations per continuously active CDN region/cache key (390 × 21), plus about 2,334 closed-market windows, cold starts, distinct queries and deployments. Actual traffic and cache reuse determine billing; two quote requests per open refresh means about 16,380 upstream spark requests in that scenario.

`artifact_delivery.status` distinguishes **current**, **pending** (awaiting delivery within two hours after the official NYSE close), and **overdue**. Pending does not mean a job is running. Actual source dates/stale flags remain unchanged; additive source `delivery_state` explains their pending/overdue state. Legacy `fresh` means the delivery deadline has not been missed. Live quotes cannot turn overdue research green. Historical views are labeled explicitly.

Pending/overdue artifacts probe the small `dashboard_artifact.meta.json`, at most once per 15 minutes per instance, then retrieve the precomputed artifact only if newer. Hash/coverage/research-block validation protects against corrupt, older or incomplete remote data; failure retains true dates. No daily provider/model work runs in a visitor request. A missing/corrupt bundled artifact returns 503. Current same-session updates normally arrive with the snapshot deployment, so current visitors do not repeatedly poll GitHub.

Five observed GitHub scheduled starts were 2h45m–4h55m late, beyond the unchanged delivery window. The independent trigger is a concrete additional route, not a timeliness guarantee: RP must be logged in, awake and online, and GitHub runners/providers/publication must succeed. Code tests do not prove deployment. See the watchdog guide for installation/status/uninstall, bounded ledger/retry/catch-up behavior, API economy, operational checks and resource tradeoffs.

The offline HTTPX chart client uses eight workers, one shared session, 8-second per-request timeouts, two retries with exponential backoff/jitter for transport/429/5xx, and an 18-second batch deadline. This avoids heavy runtime dependencies and preserves complete adjusted-history revisions. FRED uses its observations JSON API when `FRED_API_KEY` exists, otherwise the no-key graph CSV endpoint, five connections and bounded retries. Yahoo is unofficial and can rate-limit or change its endpoints; FRED can also delay/block requests. No keys are logged. Per-series provenance and observed dates remain visible.

NYSE holidays, DST and early closes use a checked-in exchange calendar (2020–2031). Regenerate with `scripts/refresh_calendar.py` before expiry and after exceptional closure announcements. FRED has separate daily/monthly/weekly freshness grace windows. Research uses approximate release dates documented in the methodology, not the equity close as a macro publication timestamp.

## Loading and visibility

Initial loading always fetches, even in a hidden tab. The responsive skeleton announces loading and a longer delay after four seconds; reduced-motion disables shimmer. A verified matching browser snapshot renders immediately during background refresh. Current and pending scheduled artifacts are normal delivery states and do not trigger rapid failure retries. Overdue research retains its warning while live quotes continue polling at their own interval. Cached browser data is labeled as a saved snapshot until current status returns. Failures retain real values and dates, offer Refresh, and retry with backoff. Without real data the page shows “Live data unavailable”. Visible pages poll at the server interval; hidden tabs pause recurring polls and the age clock, then refresh if overdue when visible again.

Telemetry includes `fetch_ms`, `cache`, `fetched_at`, `fetch_diagnostics`, quote status and `Server-Timing`. `X-Market-Revision`, `X-Market-Instance` and `X-Market-Request` distinguish deployed revisions and cold/warm invocations. CDN hits replay the original response: inspect `X-Vercel-Cache` and `Age`. No Vercel project settings were required for this redesign.

## Run

Use Python 3.11+ and Node.js 22.12+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
PYTHONPATH=backend python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```sh
npm ci --prefix frontend
VITE_API_BASE_URL=/api npm run dev --prefix frontend -- --port 5173
```

The API loads the committed real artifact locally. Explicit offline demo mode is opt-in (`MARKET_REGIME_DEMO_MODE=1`, `VITE_USE_DEMO_DATA=true`) and is blocked in production. The seed exists only for tests/that legacy local demo; the v2 model never invents missing inputs. Existing local QA flags require `VITE_ENABLE_QA=true`; `?qa=skeleton`, `?qa=background`, `?qa=stale`, `?qa=error` exercise timing/failure states with real snapshots. `MARKET_REGIME_CLOCK` is only accepted locally/preview, never production.

## Tests and verification

```sh
PYTHONPATH=backend python -m pytest backend/tests
npm test --prefix frontend
npm run build --prefix frontend
python scripts/verify_live_data.py
node scripts/verify_dashboard_browser.mjs
python scripts/check_model_sensitivity.py
```

CI uses recorded Yahoo/FRED fixtures and forbids network access. The live verification script independently compares deployed prices, calendar 1M returns, FRED Treasury yields/spreads and macro readings. Headless Playwright checks hidden initial loading, the API/UI values, responsive charts, slider/touch/smoothing behavior, overflow and console errors at 1440×900 and 375×812. Screenshots go in gitignored `artifacts/`.

`python scripts/refresh_snapshot.py` refreshes real observations and builds the artifact; `python scripts/build_daily_artifact.py` rebuilds offline from committed observations. Historical dashboard snapshots cover the precomputed 252 trading dates; older dashboard dates return 404, while full source history remains accessible through `/api/series/{symbol}` and CSV exports. `POST /regime/recalculate` returns the precomputed result in production and writes no request-time rows.

Dated migration checks are preserved in [performance](docs/performance.md) and [macro verification](docs/macro-verification.md) reports. Yahoo and FRED both worked from Vercel during those checks. Current daily provider work runs on the scheduler by design.
