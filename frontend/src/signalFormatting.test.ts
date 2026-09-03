import { expect, it } from "vitest";
import { formatSignalValue } from "./signalFormatting";
it.each([
  ["sp500_above_50d_ma", 3.329834, "+$3.33"],
  ["nasdaq_outperforming_sp500_1m", 0.035311, "+3.53 pp"],
  ["defensives_outperform_cyclicals_1m", -0.0199, "-1.99 pp"],
  ["russell_underperforming_sp500_1m", -0.035311, "-3.53 pp"],
  ["gold_outperforming_equities_1m", 0.02, "+2.00 pp"],
  ["oil_up_more_than_5pct_1m", 0.10523, "+10.5%"],
  ["copper_up_more_than_5pct_1m", -0.0753, "-7.5%"],
  ["cpi_above_target", 3.353, "3.35%"],
  ["ten_year_rising_sharply_1m", 0.535, "+0.54 pp"],
  ["two_year_rising_sharply_1m", 0.032, "+0.03 pp"],
  ["yield_curve_inverted", -0.51, "-0.51 pp"],
  ["vix_below_3m_average", -2.93776, "-2.94 points"],
  ["cpi_above_target", null, "n/a"],
] as const)("formats %s by its actual model unit", (key, raw, display) => {
  expect(formatSignalValue(key, raw).display).toBe(display);
});
