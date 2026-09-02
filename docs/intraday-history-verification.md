# Dashboard verification · Sep 30, 2026

Production revision: `59517d156d80765fd3347c0a2f682ff796bfbe4c`. Tests: 62 backend, 38 frontend; Vite build and [CI](https://github.com/Jo2234/us-market-regime-dashboard/actions/runs/36656145317) passed. All five manual commits are authored and committed by Johan Vaz <v.johan2234@gmail.com>. No Vercel project settings were changed.

## Changes and observed values

| Item | Before | After |
| --- | --- | --- |
| Latest equity session | Sep 28 | Sep 29 |
| SPY price | 765.61 | 764.20 |
| QQQ price | 736.53 | 737.93 |
| SPY 1M | −0.2390% | −0.4227% |
| QQQ 1M | +2.9127% | +3.1083% |
| Regime history | 1 request-time row | 252 daily points, Sep 29, 2025–Sep 29, 2026 |
| Masthead | Previous publication name | Johan’s Dashboard |
| Latest model classification | Sep 28: Rates pressure | Sep 29: Mixed transition |

Yahoo left the final ETF daily close null while its timestamped regular-market metadata already held the completed close. The parser now accepts that metadata only for the same session at/after the official NYSE close, marks it `yahoo_meta`, and prefers a subsequently filled daily bar. Its provisional adjusted close equals the raw close. Holidays and early closes use the checked-in exchange calendar.

The production freshness response flags only **2YY=F**, whose last valid daily observation is Sep 28 (4.50%). Yahoo’s older metadata is dated Sep 22 and is deliberately rejected as a Sep 29 close. Other equity, sector, commodity and Treasury index observations are Sep 29; macro freshness follows publication cadence.

## Quotes, caching and history

Daily fields remain backward-compatible. Additive `live_quotes`, `quote_delivery` and `market_status` carry timestamped intraday prices/returns, telemetry and market hours. Two v7 spark batches (20 + 5 symbols) use minimal Mozilla/5.0 and a shared HTTPX client; v8 spark was observed to lack quote timestamps, while v7 spark returned metadata without a crumb. The v7 quote endpoint is not used.

Open-session quotes cache/poll at 60 seconds, with 401/429/failure backoff to 900 seconds; hidden browser tabs pause polling. Closed-market data caches for up to 900 seconds. Daily history independently refreshes every 900 seconds and after the close; FRED caches for one hour. Daily-history and macro retrieval run concurrently. A production clock override is prohibited.

Regime history is deterministic, cached by an input fingerprint and stored in the scheduled fallback. Production summary requests no longer write regime_snapshots. CPI uses an approximate next-month 15th release date; unemployment uses the first Friday and DFF the next NYSE business day. FRED vintage is revised, not point in time. The model’s thresholds and precedence are unchanged. Latest scores are Risk 80, Growth 50, Inflation 80, Rates 80; the preceding-session note now reports Rates pressure → Mixed transition (raw risk +2).

## Timing evidence

| Measurement | Samples | Median / maximum |
| --- | ---: | ---: |
| First production request on a new instance | 1 | 4,182.58 ms / 4,182.58 ms |
| Warm origin request, in-memory hit | 5 | 788.69 ms / 864.09 ms |
| CDN hit | 5 | 14.28 ms / 25.82 ms |
| History computation in production | 1 | 2,468.13 ms |
| History computation on subsequent requests | 5 | 0 ms (cache hit) |
| Local spark batch | 1 | 94.31 ms for 25 symbols, 2 requests |

Production import was 465.66 ms, Yahoo’s 25-symbol daily batch 372.36 ms, and the parallel FRED CSV batch 404.13 ms. Yahoo returned 25/25 HTTP successes, zero retries, zero 401s and zero 429s. All five FRED requests were HTTP 200. The separate five-cold/five-warm-miss benchmark from the preceding release remains in docs/performance.md; those measurements predate this new history computation and are not substituted for current measurements.

At 22 full NYSE sessions in a 30-day month, one continuously visited CDN key/location implies about 8,580 open-minute refreshes + 2,308 closed-market refreshes = **10,888 origin invocations/month**, plus bootstrap/revalidation/cold-instance effects. Different dates, ranges and CDN locations create additional cache keys.

## Display-label pass

| Before | After |
| --- | --- | --- |
| Indexed Return / Major Indices | Indexed return / Major indices |
| Sector Rotation / Performance Heatmap | Sector rotation / Performance heatmap |
| Cross-Asset / Volatility & Breadth | Cross-asset / Volatility & breadth |
| Yield Curve / Regime Signal Table | Yield curve / Regime signal table |
| Analyst Note / Data Limits / Historical Regime Scores | Analyst note / Data limits / Historical regime scores |
| rates_pressure / medium confidence | Rates pressure / Medium confidence |
| risk / positive / negative | Risk / Positive / Negative |
| Sector Etf / yahoo_finance / fred | Sector ETFs / Yahoo Finance / FRED |
| DGS10 / CORE_CPI_YOY | 10-year Treasury · ^TNX / Core CPI YoY · FRED: CPILFESL |
| 10Y - 2Y* / 10Y−2Y / 10Y-2Y | 10Y–2Y* |
| as of 2026-09-28 / chart 08-28 | as of Sep 28, 2026 / chart Aug 28 |

Native date inputs retain the browser’s locale format; API and CSV dates remain ISO. Signal IDs stay unchanged; their display names are shared by backend prose and frontend:

| API signal key | Display label |
| --- | --- |
| `sp500_above_50d_ma` | S&P 500 above 50-day MA |
| `nasdaq_outperforming_sp500_1m` | Nasdaq 100 outperforming S&P 500 (1M) |
| `vix_below_3m_average` | VIX below 3-month average |
| `defensives_outperform_cyclicals_1m` | Defensives outperforming cyclicals (1M) |
| `russell_underperforming_sp500_1m` | Russell 2000 underperforming S&P 500 (1M) |
| `gold_outperforming_equities_1m` | Gold outperforming equities (1M) |
| `oil_up_more_than_5pct_1m` | Oil up more than 5% (1M) |
| `copper_up_more_than_5pct_1m` | Copper up more than 5% (1M) |
| `cpi_above_target` | CPI above target |
| `ten_year_rising_sharply_1m` | 10Y yield rising sharply (1M) |
| `two_year_rising_sharply_1m` | 2Y futures-implied yield rising sharply (1M) |
| `yield_curve_inverted` | Yield curve inverted |

## Verification output

```text
Market closed: live polling is paused; comparing completed-session prices and returns.
Macro delivery: FEDFUNDS=live, CPI_YOY=live, UNRATE=live, CORE_CPI_YOY=live, FEDFUNDS_MONTHLY=live
API mode: live | as of 2026-09-29 | completed-session cutoff 2026-09-29
Series     Metric    Source date API date    API         Source      Check
SPY        price     2026-09-29  2026-09-29   764.20000   764.20001  PASS
SPY        1M %      2026-09-29  2026-09-29    -0.42270    -0.42274  PASS
QQQ        price     2026-09-29  2026-09-29   737.93000   737.92999  PASS
QQQ        1M %      2026-09-29  2026-09-29     3.10830     3.10832  PASS
^IRX       yield %   2026-09-29  2026-09-29     4.06500     4.06500  PASS
2YY=F      yield %   2026-09-28  2026-09-28     4.50000     4.50000  PASS
^FVX       yield %   2026-09-29  2026-09-29     5.06300     5.06300  PASS
^TNX       yield %   2026-09-29  2026-09-29     5.25500     5.25500  PASS
^TYX       yield %   2026-09-29  2026-09-29     5.59400     5.59400  PASS
DFF        rate %    2026-09-28  2026-09-28     3.88000     3.88000  PASS
CPIAUCSL   YoY %     2026-08-01  2026-08-01     3.35300     3.35302  PASS
CPILFESL   YoY %     2026-08-01  2026-08-01     2.44620     2.44616  PASS
UNRATE     rate %    2026-08-01  2026-08-01     4.10000     4.10000  PASS
FEDFUNDS   rate %    2026-08-01  2026-08-01     3.63000     3.63000  PASS
```

## Visual checks and remaining verification

Desktop local browser checks confirmed the renamed masthead, sentence-case labels, real Sep 29 snapshot values, 252-point chart with four lines/bands/inspector, and the delayed loading skeleton. Snapshot-only Yahoo/FRED failure flags retained real dated values. Frame files are in /tmp/regime-latest-qa.

The browser tool began returning cgWindowNotFound while setting responsive width. A valid 375 px capture and final production browser/console check remain pending; the failed width-1 capture is not evidence of a mobile pass. Production HTML and its deployed bundle have the correct title, masthead and labels, but that static check is not a substitute for a browser rendering check.

The clock-override API replay and recorded spark tests pass, including intraday/daily separation, holiday/early-close boundaries, rate-limit backoff and old-quote rejection. The Page Visibility/fake-timer tests pass. Production is correctly closed; actual live-session polling and spark performance from Vercel during US trading hours are not yet observed. Overnight futures/FX polling is intentionally paused with the approved NYSE schedule.

## Commits

- 1 · Completed closes: [2682609](https://github.com/Jo2234/us-market-regime-dashboard/commit/2682609071cbb59649d11eab9837915036427122)
- 2 · Intraday quotes: [a862836](https://github.com/Jo2234/us-market-regime-dashboard/commit/a86283612a5d3ef8b5d539a7c508e9cdff285489)
- 3 · Regime history: [ba40304](https://github.com/Jo2234/us-market-regime-dashboard/commit/ba4030450ad73a254bd037fee6188a1d451d78ec)
- 4 · Masthead: [c31b26d](https://github.com/Jo2234/us-market-regime-dashboard/commit/c31b26dc79f193cb8507741455c49550c7156eea)
- 5 · Display consistency: [59517d1](https://github.com/Jo2234/us-market-regime-dashboard/commit/59517d156d80765fd3347c0a2f682ff796bfbe4c)

The scheduled [snapshot workflow](https://github.com/Jo2234/us-market-regime-dashboard/actions/runs/36656388370) also passed, refreshing both the Yahoo snapshot and derived history in bot commit [c791fab](https://github.com/Jo2234/us-market-regime-dashboard/commit/c791fab3e3b7bdf940f10124c8b246d3c4931086). FRED observations were unchanged and retained. Production value verification passed again after that deployment.

Raw evidence: [production timings](verification-2026-09-30/timings.json) and [independent verification output](verification-2026-09-30/live-verification.txt).
