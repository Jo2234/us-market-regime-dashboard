import type { DashboardData, RangeKey } from "./types";

export const ranges: RangeKey[] = ["1D", "1W", "1M", "3M", "YTD", "1Y"];

export function formatPercent(value: number, precision = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(precision)}%`;
}

export function formatNumber(value: number, precision = 2): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision
  });
}

export function formatDate(value: string | null): string {
  if (!value) return "n/a";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(new Date(`${value}T12:00:00`));
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function scoreClass(value: number): string {
  if (value >= 66) return "score-high";
  if (value >= 45) return "score-mid";
  return "score-low";
}

export function performanceClass(value: number): string {
  if (value > 0.05) return "positive";
  if (value < -0.05) return "negative";
  return "neutral";
}

export function heatColor(value: number): string {
  const clipped = Math.max(-8, Math.min(8, value));
  const intensity = Math.abs(clipped) / 8;
  if (clipped > 0.05) {
    return `color-mix(in srgb, var(--positive) ${18 + intensity * 62}%, transparent)`;
  }
  if (clipped < -0.05) {
    return `color-mix(in srgb, var(--negative) ${18 + intensity * 62}%, transparent)`;
  }
  return "color-mix(in srgb, var(--faint) 14%, transparent)";
}

export function downloadDashboardCsv(data: DashboardData): void {
  const rows: string[][] = [
    ["section", "name", "symbol", "metric", "value", "as_of"],
    ...data.indices.flatMap((item) => [
      ["index", item.name, item.symbol, "day_return_pct", String(item.dayReturn), data.selectedDate],
      ["index", item.name, item.symbol, "month_return_pct", String(item.monthReturn), data.selectedDate],
      ["index", item.name, item.symbol, "ytd_return_pct", String(item.ytdReturn), data.selectedDate],
      ["index", item.name, item.symbol, "drawdown_52w_pct", String(item.drawdown52w), data.selectedDate]
    ]),
    ...data.sectors.flatMap((item) =>
      Object.entries(item.returns).map(([window, value]) => [
        "sector",
        item.name,
        item.symbol,
        `${window.toLowerCase()}_return_pct`,
        String(value),
        data.selectedDate
      ])
    ),
    ...data.rates.points.map((item) => ["yield_curve", item.maturity, "", "yield_pct", String(item.yield), data.selectedDate]),
    ...data.commodities.map((item) => ["commodity", item.name, item.symbol, "month_return_pct", String(item.monthReturn), data.selectedDate]),
    ...data.volatility.map((item) => ["volatility", item.name, item.symbol, "value", String(item.value), data.selectedDate]),
    ...data.signals.map((item) => ["signal", item.name, item.category, item.direction, item.value, data.selectedDate])
  ];

  const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `market-regime-dashboard-${data.selectedDate}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeCsv(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
