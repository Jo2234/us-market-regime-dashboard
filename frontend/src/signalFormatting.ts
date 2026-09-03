// API values remain unrounded. These units describe the existing model inputs.
const units: Record<string, "usd_difference" | "return_difference" | "return" | "percent" | "percentage_points" | "index_points" | "ratio"> = {
  sp500_above_50d_ma: "usd_difference",
  nasdaq_outperforming_sp500_1m: "return_difference",
  vix_below_3m_average: "index_points",
  defensives_outperform_cyclicals_1m: "return_difference",
  russell_underperforming_sp500_1m: "return_difference",
  gold_outperforming_equities_1m: "return_difference",
  oil_up_more_than_5pct_1m: "return",
  copper_up_more_than_5pct_1m: "return",
  cpi_above_target: "percent",
  ten_year_rising_sharply_1m: "percentage_points",
  two_year_rising_sharply_1m: "percentage_points",
  yield_curve_inverted: "percentage_points",
};
const signed = (value: number, places: number) => `${value > 0 ? "+" : ""}${value.toFixed(places)}`;
export function formatSignalValue(key: string, value: number | null): { display: string; rawUnit: string } {
  const unit = units[key];
  if (value === null || !Number.isFinite(value)) return { display: "n/a", rawUnit: unit ?? "unspecified" };
  switch (unit) {
    case "usd_difference": return { display: `${value >= 0 ? "+" : "−"}$${Math.abs(value).toFixed(2)}`, rawUnit: "USD (adjusted price minus MA)" };
    case "return_difference": return { display: `${signed(value * 100, 2)} pp`, rawUnit: "return fraction difference (×100 for pp)" };
    case "return": return { display: `${signed(value * 100, 1)}%`, rawUnit: "return fraction (×100 for %)" };
    case "percent": return { display: `${value.toFixed(2)}%`, rawUnit: "percent" };
    case "percentage_points": return { display: `${signed(value, 2)} pp`, rawUnit: "percentage points" };
    case "index_points": return { display: `${signed(value, 2)} points`, rawUnit: "index points" };
    case "ratio": return { display: `${value.toFixed(2)}×`, rawUnit: "ratio" };
    default: return { display: value.toLocaleString("en-US", { maximumFractionDigits: 3 }), rawUnit: "unspecified" };
  }
}
