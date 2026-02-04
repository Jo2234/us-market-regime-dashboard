# Formula Notes

## Price Metrics

- Returns use adjusted close when available, otherwise close.
- `1d`, `1w`, `1m`, `3m`, and `1y` use 1, 5, 21, 63, and 252 trading-day offsets.
- `ytd` uses the first available trading observation in the current calendar year.
- Rolling volatility is annualized as `std(daily returns) * sqrt(252)`.
- Drawdown is `price / prior_running_max - 1` over the selected lookback window.
- Sector relative performance is sector return minus SPY return for the same window.

## Rates And Macro

- Yield spreads are simple differences between the latest available Treasury observations in percentage points.
- Monthly macro series use the latest observation on or before the requested date, so sparse CPI, unemployment, and Fed funds rows do not create false daily gaps.
- Data freshness compares each instrument's latest stored date with the current local date and marks it stale after the configured threshold.

## Regime Notes

Regime labels are deterministic rule outputs. The analyst note uses only computed signals, the current 10Y-2Y spread, and the previous stored snapshot before the observed date. It does not infer causality beyond those dashboard metrics.
