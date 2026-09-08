# Formula definitions

This is descriptive research software, not investment advice. [Methodology](methodology.md) contains the fixed parameter choices, information lags, limitations and sensitivity protocol.

## Prices and returns

Daily `price` is Yahoo's raw completed-session close; `adjusted_close` and legacy `value` include Yahoo's historical split/distribution adjustment. Return = adjusted endpoint / adjusted baseline − 1. A provisional null-bar repair uses the same-session post-close Yahoo meta price and explicitly marks that day's adjustment as pending. Once supplied, Yahoo's actual adjusted bar replaces it.

| Window | Baseline |
| --- | --- |
| 1D | Immediately preceding observed trading close |
| 1W | Close on or before seven calendar days earlier |
| 1M | Close on or before the same calendar date one month earlier |
| 3M | Close on or before the same calendar date three months earlier |
| YTD | Last close of the prior calendar year |
| 1Y | Close on or before the same calendar date one year earlier |

Month/year anchors clamp to the last valid day of the destination month. Baselines never look forward. Missing history yields null, not zero. Indexed performance = 100 × adjusted close / baseline adjusted close. Relative sector performance is sector return minus SPY return, expressed in percentage points. Annualized volatility is sample standard deviation of daily adjusted returns × √252. The market-card 52-week maximum drawdown is the worst peak-to-trough adjusted return in the trailing 252 observations.

During NYSE hours additive quotes use regular-market price and timestamp. Intraday 1D = live price / previous raw close − 1. Longer windows use the live price / historical adjusted calendar baseline − 1. A stale/older-session quote never overrides daily values. The daily regime remains on completed closes.

## Official rates and macro

All five Treasury maturities use FRED constant-maturity percent yields on the latest common observation date available by the selected model date. Official T10Y2Y and T10Y3M use that same date; a missing official spread can be calculated from those same-date FRED yields, explicitly identified. No mixed-source or mixed-date spread is permitted. Basis points = percentage-point spread × 100.

Headline/core CPI YoY = 100 × (index at month t / index at t−12 months − 1), using CPIAUCSL/CPILFESL. Missing required months yield unavailable. Daily effective Fed funds uses DFF; monthly FEDFUNDS is secondary context. UNRATE is the published percent level.

## Continuous Phase 1 model

For a raw feature x, percentile = 100 × (number of reference observations below x + ½ the number equal to x) / 756. The reference contains the **preceding** 756 valid daily observations; today is excluded. A constant feature ranks 50. Inverted features use 100 − percentile. Each feature has exactly one family, and equal weights sum to one within each family. Missing signals do not get a neutral score; a complete family is required.

Trend = 0.25 × calendar 1M return + 0.50 × 3M return + 0.25 × 6M return. Ratios use adjusted component prices on the same daily information set. Sector breadth is the fraction of the 11 sector ETFs above their 200-observation adjusted moving average. Claims use the four-week mean of published ICSA observations, inverted after standardization. CPI acceleration = 100 × [(CPI[t]/CPI[t−3])⁴ − 1] − CPI YoY. VIX term structure is VIX/VIX3M; above one means front-end volatility exceeds three-month volatility. Stress drawdown is the **current** shortfall from the trailing 252-session high, not the market card's worst historical drawdown. NFCI, breakevens and real yields enter as published levels. Full family membership is in [methodology](methodology.md).

Growth and Inflation composites split at 50: high/low = Goldilocks, high/high = Reflation, low/high = Stagflation, low/low = Slowdown. Stress <60 is Calm, 60–<80 Elevated, ≥80 Stressed. Rates context and dollar trend have no quadrant weight.

Axis magnitude = 2 × min(|Growth−50|, |Inflation−50|). Agreement is the fraction of Growth/Inflation signals on the official quadrant's side of neutral. Confidence score = (magnitude + agreement percentage)/2; High ≥70, Medium ≥40, otherwise Low. Magnitude is zero while raw and official quadrants disagree. This is not a probability.

## Persistence and information dates

The official quadrant changes only after five consecutive candidate trading observations, unless both axes are at least 25 points from neutral and ≥75% of relevant signals agree with the candidate. A different candidate restarts the count, returning to official cancels it, and a missing trading observation breaks candidate continuity. History applies the same rule after warm-up. Exposed fields include raw/official labels, days in regime, emerging label/days and strong-override status. Stress is a separate unsmoothed daily overlay.

Historical inputs respect approximate publication lags: CPI on/after the 15th of next month, unemployment first Friday, monthly Fed funds seventh, daily rates next exchange business day, ICSA observation Saturday +5 days, NFCI observation Friday +5 days. These use latest revised vintage, not point-in-time/ALFRED vintages; holidays and unusual release delays can differ. Monthly/weekly freshness is assessed by its cadence, not by counting equity sessions since the observation month/week.

## Arithmetic boundary scenarios

Holding other signal ranks and reference distributions fixed, solve `target rank = current rank + (boundary − composite) / signal weight`. Invert the empirical distribution to the nearest attainable raw value that actually crosses the boundary. Downward crossings require strictly below the threshold; upward crossings include equality. Signals whose required ranks lie outside 0–100 cannot flip that axis alone. Breadth is restricted to integer sector counts. Ratio trends translate to endpoint changes using the fixed historical denominators. Up to three feasible scenarios with the smallest percentile distances are shown; ties use the signal key. A raw flip still requires persistence. Scenarios do not estimate likelihood or future returns.

## Artifact and history display

All daily calculations run in the scheduled builder and are versioned in a bundled artifact. Visitor requests only load/assemble and optionally refresh live quotes. The 252-point chart uses Growth, Inflation and Stress panels, official-quadrant ribbon and emerging-period dots. Raw curves are steps by default. Optional trailing five-trading-day smoothing affects display only; labels, change counts and inspector values remain raw. Hover, tap/drag and the keyboard date slider inspect the same date and keep snapshot navigation available.

Legacy `regime`/`historical_regimes` remain populated for one release and are deprecated. They retain the prior binary-rule scores and `clamp(50 + 15 × score, 0, 100)` display convention plus five-day persistence. The new chart and page use `regime_v2`/`historical_regimes_v2`; they do not rescale v2 percentiles with the legacy formula.

## Provenance and formatting

`as_of` is an actual stored completed trading date. Each series keeps its own observation date, source ID/link and original fetch time. Response generation time is not observation time. UI dates use readable month/day/year text; API/CSV dates remain ISO. Percent returns, percentage-point differences, percent yields, claims counts, ratios and index points are formatted by unit; raw values remain in tooltips/CSV. The signal table shows its oriented percentile, direction and within-axis weight.
