# FRED macro verification — September 29, 2026

The macro panel previously showed unavailable/null for Fed funds, CPI and unemployment because the live path only covered Yahoo instruments. It now supplies daily DFF 3.88% (September 25), headline CPI YoY 3.3530%, core CPI YoY 2.4462%, unemployment 4.10%, and secondary monthly Fed funds 3.63% (all monthly observations: August 2026).

Daily DFF is the most current effective-rate reading, while FEDFUNDS is an older month's average. The retained `FEDFUNDS` API key therefore maps to DFF, and `FEDFUNDS_MONTHLY` carries the monthly comparison. Formula definitions and release-cadence grace windows are in [formulas.md](formulas.md). FRED dates are never restamped as market dates.

## Production and runner evidence

At implementation commit `2bd8659a03a6b17e33eb1655dc57d8760b4feaec`, the canonical production API returned Yahoo `data_mode: live` and FRED `mode: live` on every macro series. The first observed request completed in 2,470 ms; the FRED CSV batch took 796.18 ms. All five upstream status codes were 200 with zero retries, 429s, 401s or 5xx responses. Thus macro snapshots remain fallbacks; they are not the primary data path. No Vercel project settings were changed.

| FRED series | Vercel fetch ms | HTTP |
| --- | ---: | ---: |
| DFF | 751.73 | 200 |
| CPIAUCSL | 786.60 | 200 |
| UNRATE | 456.62 | 200 |
| CPILFESL | 766.30 | 200 |
| FEDFUNDS | 725.42 | 200 |

The [scheduled-workflow manual run](https://github.com/Jo2234/us-market-regime-dashboard/actions/runs/36582075846) passed. Its FRED batch took 431.28 ms, five HTTP 200s and no retries. FRED observations were unchanged, so the macro file was retained. Changed Yahoo observations produced bot commit `21feac7`. Both providers are refreshed independently; a failed series retains its prior snapshot and the workflow reports failure.

## Regime impact

Holding September 28 Yahoo observations fixed, the label remains **Rates Pressure**, medium confidence. CPI's existing >2.5% condition is now available and true. Raw inflation score is 1 → 2 (UI 65 → 80); risk 0, growth 0, and rates pressure 2 are unchanged. Core CPI, Fed funds and unemployment do not enter scores. No weights, thresholds or label precedence were changed. Historical macro values use the latest revised FRED vintage, not a point-in-time release dataset.

## Tests and visual checks

- 52 backend tests pass, using recorded CSV/JSON fixtures with network access blocked. Coverage includes exact year-ago CPI months, missing data, daily/monthly freshness, API-key selection, retries, cancellation, single-flight caching, corrupt snapshots, partial outages and unchanged regime thresholds.
- 35 frontend tests and the TypeScript/Vite production build pass, including dated macro cards, source links, unavailable cards and background refresh.
- Initial integration CI: [successful run](https://github.com/Jo2234/us-market-regime-dashboard/actions/runs/36581913802).
- Desktop and 375 px checks confirm dated macro values, FRED attribution, source links and snapshot notices. Production values match the API; the Yahoo chip remains Live. The browser console has no application errors.
- Local kill-test with `MARKET_REGIME_FORCE_FRED_FAILURE=1` preserves all five real macro values and original dates, labels them Snapshot, and never emits `demo_seed`. Tests with an absent/corrupt macro snapshot leave the affected card null without dropping the Yahoo feed. No production failure flag was set.

## Independent production comparison

The script downloads Yahoo/FRED directly and computes returns/YoY independently of application analytics. All 14 rows pass. Small differences below are API rounding and Yahoo floating-point storage, within the documented tolerances.

```text
Macro delivery: FEDFUNDS=live, CPI_YOY=live, UNRATE=live, CORE_CPI_YOY=live, FEDFUNDS_MONTHLY=live
API mode: live | as of 2026-09-28 | completed-session cutoff 2026-09-28
Series     Metric    Source date API date    API         Source      Check
SPY        price     2026-09-28  2026-09-28   765.61000   765.60999  PASS
SPY        1M %      2026-09-28  2026-09-28    -0.23900    -0.23901  PASS
QQQ        price     2026-09-28  2026-09-28   736.53000   736.53003  PASS
QQQ        1M %      2026-09-28  2026-09-28     2.91270     2.91270  PASS
^IRX       yield %   2026-09-28  2026-09-28     4.05700     4.05700  PASS
retired_yield_future      yield %   2026-09-28  2026-09-28     4.50000     4.50000  PASS
^FVX       yield %   2026-09-28  2026-09-28     5.06800     5.06800  PASS
^TNX       yield %   2026-09-28  2026-09-28     5.24000     5.24000  PASS
^TYX       yield %   2026-09-28  2026-09-28     5.56100     5.56100  PASS
DFF        rate %    2026-09-25  2026-09-25     3.88000     3.88000  PASS
CPIAUCSL   YoY %     2026-08-01  2026-08-01     3.35300     3.35302  PASS
CPILFESL   YoY %     2026-08-01  2026-08-01     2.44620     2.44616  PASS
UNRATE     rate %    2026-08-01  2026-08-01     4.10000     4.10000  PASS
FEDFUNDS   rate %    2026-08-01  2026-08-01     3.63000     3.63000  PASS
```
