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

Yahoo `^IRX`, `^FVX`, `^TNX`, `^TYX`, and `2YY=F` are already in percent: **5.24 means 5.24%, with no factor-of-ten or factor-of-100 conversion**. Values come from daily `close`, not `regularMarketPrice`. The curve covers 3M, 2Y*, 5Y, 10Y and 30Y.

- 3M is the `^IRX` discount-yield index, not a Treasury par yield.
- 2Y* is `2YY=F`, the front-contract 2-year yield future. It is futures-implied, not a cash Treasury index or the price-based `ZT=F` future.
- `10y_2y` remains the API key for compatibility, but is explicitly **10Y Treasury minus 2Y futures-implied yield**. It is not the conventional cash 10Y−2Y recession spread. Contract rolls, liquidity and differing observation dates can affect it; API spread metadata exposes that distinction and both dates.
- `10y_3m` and `30y_10y` are differences of the corresponding available observations.

Spreads are percentage points in the API; the UI multiplies by 100 for basis points. Rates-pressure changes currently retain their 21-observation definition. CPI, unemployment and Fed funds have no supported Yahoo series here and return null. The unavailable CPI rule is neutral, contributes no point, and caps otherwise-high regime confidence at medium. This makes inflation coverage incomplete and is disclosed in the UI.

## Observation dates and freshness

`as_of` is the last SPY observation present at the requested cutoff, never today's date. Each series includes its own `date`/`observation_date`, Yahoo ticker and source. Yahoo's unfinished current daily bar is excluded until 30 minutes after the NYSE close. The exchange calendar handles US equity holidays, weekends, DST, exceptional closures and early closes. This conservative common cutoff also excludes same-day yield/futures/FX bars until the equity session is complete; futures settlement conventions may differ.

Freshness compares actual series dates with that latest completed NYSE session; one or more missing completed sessions is stale. Missing macro coverage is marked unavailable/partial. `age_days` is retained as informational calendar age; legacy `stale_after_days` is retained for compatibility but no longer drives status. Aggregate source status uses the oldest supplied observation. `generated_at` is response generation time, `fetched_at` is the original Yahoo fetch time, and `as_of_date` is the latest actual observation. A historical selection remains labelled by its selected observation date while freshness describes the feed's latest stored observations.

## Regime and storage

Regime labels remain deterministic rule outputs. All price signals use adjusted history. Rules expose availability; missing CPI is not described as a failed observation. The note does not infer causality. Scores are descriptive, not probabilities or trading advice.

Production requests construct an isolated in-memory database from the validated cached Yahoo dataset, so an old demo SQLite database cannot leak into responses. Historical selections recompute from roughly two years of available bars. `/regime/recalculate` computes a requested backfill, but its database is request-local; it does not create durable serverless history. The default summary therefore contains its current computed classification, not invented historical scores.
