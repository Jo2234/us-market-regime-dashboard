# Regime methodology

This dashboard is descriptive research software, not investment advice or a forecast. Parameters below are fixed before the redesign's results are calculated. Sensitivity results will be reported, not used to select a preferred current label.

## Sources and information dates

Completed-session Treasury curves use FRED DGS3MO, DGS2, DGS5, DGS10 and DGS30. Spreads use FRED T10Y2Y and T10Y3M on the same common observation date as the curve. No mixed-source or mixed-date spread is permitted. Treasury observations become eligible on the next exchange business day, a conservative publication proxy; one business day of feed lag is normal. All dates remain observation dates. Sources: [H.15/DGS2](https://fred.stlouisfed.org/series/DGS2) and [official spread definition](https://fred.stlouisfed.org/series/T10Y2Y).

Historical macro uses latest revised vintage with approximate release lags, not point-in-time data: CPI on the 15th of the following month (moved to the next business day); unemployment on the first Friday of the following month; daily Fed funds, Treasury yields, breakevens and real yields on the next business day; ICSA for a Saturday-ending week on the following Thursday; NFCI for a Friday-ending week on the following Wednesday. Monthly Fed funds use the seventh of the following month. Delayed releases and revisions are a research limitation. Actual observation and assumed availability dates are exposed.

## Stability chosen in advance

A candidate quadrant must persist for five consecutive trading observations before becoming official. Returning to the official label cancels the candidate; a different candidate restarts at one. Five sessions represent one trading week. Stress is an independent daily overlay and is not delayed by quadrant persistence.

For the legacy model, immediate shock overrides require risk-off with risk score at most -4 and SPY 1M return at most -10%, or a commodity-shock raw label with oil above 20% and copper above 16% over 1M (twice the original commodity thresholds). For v2, an immediate quadrant change requires both axes at least 25 points from neutral and at least 75% of the Growth/Inflation signals agreeing with the candidate. Those strong-evidence criteria are fixed, not fitted. N=3/5/10 change counts and stricter/looser strong-margin variants will be reported. Initial labels are initialized from the first valid warm-up observation; days-in-regime may be left-censored there.

## Phase 1 measurement chosen in advance

Five years of Yahoo adjusted daily history supplies warm-up, three-year baselines and the displayed trailing 252 trading sessions. A feature is standardized against its preceding 756 valid daily observations using the empirical midrank: 100 × (count below + half the count equal) / 756. The current observation is excluded from the baseline. A constant series ranks 50. Unavailable inputs stay unavailable; they are not replaced by 50. A complete signal family is required for its composite and quadrant classification.

Trend features blend calendar 1M/3M/6M returns with weights 0.25/0.50/0.25. These are conventional short/intermediate horizons; the emphasis on the middle horizon is a design choice, not an estimated optimum. Sector breadth uses 200 trading-day moving averages, and claims use four weekly observations. Percentiles of slowly published series are computed on the daily information set, so held observations repeat until their next approximate release. Percentiles measure historical position, not probabilities of a future outcome.

Each derived input belongs to exactly one family. Within each family, signals have equal weight; differing family sizes do not cross-weight the axes. Shared underlying instruments can support distinct features, but the same feature is never counted in multiple composites.

| Family | Inputs; high oriented percentile means |
|---|---|
| Growth | RSP/SPY trend; share of 11 sectors above 200-day MA; CPER/GLD trend; cyclical/defensive trend; IWM/SPY trend; inverted four-week initial claims average. High means stronger growth proxies. |
| Inflation | CPI acceleration (three-month annualized less YoY, percentage points); 10Y breakeven level; equal blend of USO and DBC trend. High means more inflation pressure. |
| Stress | VIX level; VIX/VIX3M level; inverted HYG/LQD trend; NFCI level; magnitude of SPY drawdown from its trailing 252-session high. High means more stress. |
| Rates context | 10Y real yield level; 10Y nominal yield level; inverted 10Y–2Y curve slope. High means tighter conditions relative to history. Does not determine the quadrant. |
| Dollar context | DXY trend. No quadrant or stress weight. |

Cyclicals are XLK, XLY, XLI and XLF; defensives are XLU and XLP, continuing the existing proxy baskets. Their equal-weight blended-return difference is one Growth feature. Breadth measures participation rather than an exchange-wide advance/decline series.

## Classification and confidence chosen in advance

Growth and Inflation composites range from 0 to 100; 50 divides rising/stronger from falling/weaker relative to historical distributions. Growth ≥50 and Inflation <50 is Goldilocks; both ≥50 is Reflation; Growth <50 and Inflation ≥50 is Stagflation; both <50 is Slowdown. Equality belongs to the high side. Stress is Calm below 60, Elevated from 60 to below 80, and Stressed from 80. These labels describe proxies, not realized GDP growth or an inflation forecast.

Axis magnitude = 2 × min(|Growth−50|, |Inflation−50|), expressed on 0–100. Agreement = the percentage of Growth/Inflation signals on the same side of 50 as the official quadrant. Confidence score is the equal average of magnitude and agreement; High ≥70, Medium ≥40, otherwise Low. If the official and raw quadrants differ, magnitude is set to zero until the official quadrant is supported again. Confidence is descriptive model agreement, not a calibrated probability.

## What would change the call

Hold other signal percentiles, weights and the historical reference distribution fixed. Solve the composite equation for each input's required percentile to cross the nearest axis/stress boundary, then invert the empirical rank distribution to an attainable raw value. Report up to three feasible single-input changes with the smallest percentile distances. Ratio and price trend changes are translated back into endpoint percentage changes; claims changes refer to the four-week average. Quantized breadth reports the next attainable sector count. An unattainable single-input flip is disclosed rather than extrapolated. These are arithmetic counterfactuals, not forecasts; a raw quadrant flip still requires the stability rule.

## Sensitivity protocol

Report change counts on a common eligible sample for persistence N=3/5/10; percentile baselines 504/630/756; equal horizon weights versus 0.25/0.50/0.25; breadth MAs 150/200/250; claims averages 3/4/5 weeks; stress cut-offs 55/75, 60/80 and 65/85; strong margins 20/25/30 with agreement 2/3, 0.75 and 0.80; and confidence cut-offs 30/60, 40/70 and 50/80. These checks are descriptive and do not choose parameters. No forward-return fitting, transition odds or Phase 2 statistics are included.
