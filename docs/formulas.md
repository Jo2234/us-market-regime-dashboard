# Formula notes

## Prices and returns

`price` is the unadjusted Yahoo daily `close`: the actual last completed close, in USD for ETFs or index points for VIX/DXY. `adjusted_close` is Yahoo's split/distribution-adjusted close. The legacy `value` field remains adjusted close for compatibility. The frontend uses `price`.

Returns are `adjusted_close_at_observation / adjusted_close_at_baseline - 1`, as decimal fractions in the API and percentages in the UI. No raw-close substitution is made when Yahoo adjusted history is missing. All windows end at the actual last observation on or before the requested date:

| Window | Baseline |
| --- | --- |
| 1D | Previous available daily close |
| 1W | Close on or before the date 7 calendar days earlier |
| 1M | Close on or before the same date 1 calendar month earlier |
| 3M | Close on or before the same date 3 calendar months earlier |
| YTD | Last available close on or before December 31 of the preceding year |
| 1Y | Close on or before the same date 1 calendar year earlier |

Month/year offsets clamp to the last valid day (March 31 → February 28/29; February 29 → February 28 in a non-leap year). Holidays/weekends choose the preceding observation. A missing baseline returns null, not a shortened-window return. Indexed charts start at that same baseline, rebased to 100. Calendar windows align with common quote-app conventions, but providers using price-only returns can differ from these adjusted returns.

Moving averages use 50/200 observed sessions of adjusted close. Rolling volatility is the sample standard deviation of daily adjusted returns over 20/60 sessions, annualized by sqrt(252). `drawdown_52w` retains its historical meaning: the worst peak-to-trough adjusted drawdown in the last 252 observations, not today's drawdown. Sector relative performance is sector return minus SPY return; either missing input produces null.

## Yield curve

Yahoo `^IRX`, `^FVX`, `^TNX`, `^TYX`, and `2YY=F` are already in percent: **5.24 means 5.24%, with no factor-of-ten or factor-of-100 conversion**. Daily values use the bar close, with the documented same-session metadata repair when the last completed bar is null. Intraday quotes use timestamped `regularMarketPrice`. The curve covers 3M, 2Y*, 5Y, 10Y and 30Y.

- 3M is the `^IRX` discount-yield index, not a Treasury par yield.
- 2Y* is `2YY=F`, the front-contract 2-year yield future. It is futures-implied, not a cash Treasury index or the price-based `ZT=F` future.
- `10y_2y` remains the API key for compatibility, but is explicitly **10Y Treasury minus 2Y futures-implied yield**. It is not the conventional cash 10Y–2Y recession spread. Contract rolls, liquidity and differing observation dates can affect it; API spread metadata exposes that distinction and both dates.
- `10y_3m` and `30y_10y` are differences of the corresponding available observations.

Spreads are percentage points in the API; the UI multiplies by 100 for basis points. Rates-pressure changes currently retain their 21-observation definition. Macro inputs are supplied separately by FRED.

## FRED macro inputs

`FEDFUNDS` retains its API key but now means the latest daily effective rate from **DFF**, in percent. `FEDFUNDS_MONTHLY` supplies the separate monthly average. `UNRATE` is FRED's seasonally adjusted unemployment rate in percent. Monthly observations are not interpolated into daily synthetic readings.

Headline `CPI_YOY` uses CPIAUCSL and additive `CORE_CPI_YOY` uses CPILFESL. Both are seasonally adjusted index series. For observation month t:

`YoY_percent[t] = 100 * (index[t] / index[t minus 12 calendar months] - 1)`.

The denominator must be the exact year-ago month, not the twelfth preceding row if months are missing. No match means no derived observation for that month. API values are percentages, rounded to four decimal places; the UI shows two. These seasonally adjusted calculations can differ slightly from published unadjusted headline YoY figures. The raw snapshot retains the indices and full precision. Values dated `2026-08-01` mean **Aug 2026**, not a reading published on August 1.

The existing `cpi_above_target` rule adds one inflation point when **headline CPI YoY > 2.5%**. The threshold and all classification precedence remain unchanged. Core CPI, DFF and unemployment are displayed but do not enter the scores. Missing CPI contributes no point and caps otherwise-high confidence at medium. With the September 28, 2026 market inputs held fixed, restoring August headline CPI (3.3530%) increases raw inflation score from 1 to 2 (UI 65 → 80); Rates pressure remains the label, with medium confidence. Risk 0, growth 0 and rates pressure 2 are unchanged.

FRED returns the latest revised vintage, not ALFRED's point-in-time release history. Historical selections filter observation dates on or before the selected market date, but can include revisions and data published after the observation month. They are descriptive historical views, not valid point-in-time backtests.

## Observation dates and freshness

`as_of` is the last SPY observation present at the requested cutoff, never today's date. Each series includes its own `date`/`observation_date`, Yahoo ticker and source. Yahoo's unfinished current daily bar is excluded until the official NYSE close. The exchange calendar handles US equity holidays, weekends, DST, exceptional closures and early closes. Yield indices and FX retain the equity cutoff. 2YY=F uses its own CME yield-futures settlement boundary (14:00 America/Chicago), independent of NYSE hours. A checked-in CMES schedule handles futures dates, DST and shortened sessions; a matching Yahoo currentTradingPeriod end can shorten, but never extend, the boundary. Holiday schedules are a conservative proxy for instrument-specific settlement publication and should be refreshed when exchanges announce changes.

Freshness compares actual series dates with that latest completed NYSE session; one or more missing completed sessions is stale. 2YY=F is compared with its completed CME settlement date. A one-session delay retains is_stale=true on that row with affects_group_freshness=false; two or more missing sessions, or missing coverage, affect group/page freshness. FRED has separate cadence-aware policies. Daily DFF allows two completed NYSE sessions of publication lag; this holiday-aware proxy is not an exact FRED release calendar. Monthly CPI allows the previous month, or the month before that through day 20 of the current month. Unemployment and monthly Fed funds use day 10 instead. These conservative grace windows avoid treating naturally lagged monthly observations as stale; they can flag delays later than the exact release calendar. Missing macro coverage is unavailable/partial. September 29 with August CPI/UNRATE and September 25 DFF is fresh. `age_days` is retained as informational calendar age; legacy `stale_after_days` is retained for compatibility but no longer drives status. Aggregate source dates retain the oldest supplied observation; status aggregates the cadence-aware statuses of individual instruments, not their raw calendar ages. `generated_at` is response generation time, `fetched_at` is the original Yahoo fetch time, and `as_of_date` is the latest actual observation. A historical selection remains labelled by its selected observation date while freshness describes the feed's latest stored observations.

## Regime and storage

Regime labels remain deterministic rule outputs. All price signals use adjusted history. Rules expose availability; missing CPI is not described as a failed observation. The note does not infer causality. Scores are descriptive, not probabilities or trading advice.

Production requests construct an isolated in-memory database from the validated cached Yahoo and FRED datasets, so an old demo SQLite database cannot leak into responses. Historical selections recompute from roughly two years of available bars. `/regime/recalculate` computes a requested backfill, but its database is request-local; it does not create durable serverless history. The default summary includes the cached, deterministic trailing-year history and previous-session change note; the snapshot workflow persists the same derived history.

## Intraday endpoints

The daily API fields and regime scores use completed sessions. Additive `live_quotes` use timestamped Yahoo regular-market prices during NYSE hours. Intraday 1D = live price / previous raw close − 1; 1W/1M/3M/YTD/1Y = live price / the adjusted historical close at the same calendar baseline defined above − 1. Indexed charts append that live endpoint. Each quote carries its own observation time and stale flag. A stale or older-session quote does not override daily values in the UI; intraday values are explicitly labelled.

## Historical regime reconstruction

Classify each available SPY session in the trailing calendar year, with at least 63 preceding price observations for warm-up. Reuse the same thresholds and precedence as the current classifier. Cache by source observation values plus model version and retain a matching derived snapshot; quote-only refreshes leave this history unchanged. The preceding daily classification supplies change notes even on a new serverless instance.

For model inputs on historical date D, select the latest FRED observation whose approximate release date is on/before D: CPI month M on the 15th of M+1, unemployment on the first Friday of M+1, DFF on the next NYSE business day. These are date-level approximations, not exact release timestamps; the data are latest revised vintage. CPI is the only macro variable affecting this model. Fed funds/unemployment do not alter scores. Display scores retain the existing mapping `clamp(50 + 15 × raw score, 0, 100)`; no thresholds were tuned for the resulting labels.

A null final futures bar may use `meta.regularMarketPrice` only when `regularMarketTime` falls on that bar's observation date at or after its settlement boundary. Yahoo's exchange timezone determines the observation date. Older quotes are never re-dated. This is a post-settlement Yahoo trade quote, not a claim to reproduce CME's official VWAP settlement; the filled row carries `close_source: yahoo_meta`. A supplied daily bar always wins. See [CME's yield-futures daily settlement procedure](https://www.cmegroup.com/market-regulation/rule-filings/2021/7/21-245_1.pdf).

## Historical score display

The chart uses four aligned 0–100 panels and a categorical regime ribbon. Raw daily scores use a step curve by default, preserving the discrete model decisions. The optional 5-day smoothing switch draws the trailing mean of five trading observations (or available observations at the start of the window). It affects display only: daily labels, regime changes, raw inspector scores, API history and snapshot selection are unchanged. The date slider provides keyboard access to the same synchronized inspector as pointer hover/tap/drag.
