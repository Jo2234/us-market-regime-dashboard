import { demoDashboardData } from "./demoData";
import type { DashboardData, FreshnessSource, RangeKey, RegimeSignal } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  (import.meta.env.PROD ? "/api" : "http://localhost:8000");
const USE_DEMO_DATA = import.meta.env.VITE_USE_DEMO_DATA === "true";
const DISABLE_DEMO_FALLBACK = import.meta.env.VITE_DISABLE_DEMO_FALLBACK === "true";

type BackendInstrument = {
  symbol: string;
  value: number;
  returns: Record<string, number | null>;
  volatility: Record<string, number | null>;
  drawdown_52w: number | null;
};

type BackendSignal = {
  name: string;
  passed: boolean;
  value: number | null;
  evidence: string;
};

type BackendSummary = {
  as_of: string;
  regime: {
    regime_label: string;
    confidence: "low" | "medium" | "high";
    risk_score: number;
    growth_score: number;
    inflation_score: number;
    rates_pressure_score: number;
    signals: {
      top_positive: BackendSignal[];
      top_negative: BackendSignal[];
      all: BackendSignal[];
      what_changed: string;
      data_limitations: string[];
    };
  };
  major_indices: BackendInstrument[];
  sector_leaders: Array<{ symbol: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  sector_laggards: Array<{ symbol: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  rates_summary: {
    maturities: Array<{ symbol: string; value: number }>;
    spreads: Record<string, number | null>;
  };
  commodities_summary: BackendInstrument[];
  volatility_summary: BackendInstrument;
  analyst_summary: string;
  data_freshness: {
    generated_at: string;
    freshness_policy: string;
    instruments: Array<{
      asset_class: string;
      latest_date: string | null;
      age_days: number | null;
      is_stale: boolean;
    }>;
  };
};

export async function fetchDashboardData(date: string, range: RangeKey): Promise<DashboardData> {
  if (USE_DEMO_DATA) {
    return markDemo(demoDashboardData, "Demo mode enabled with VITE_USE_DEMO_DATA=true.");
  }

  const url = new URL(`${API_BASE_URL}/dashboard/summary`);
  if (date) url.searchParams.set("date", date);
  url.searchParams.set("range", range.toLowerCase());

  try {
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json" }
    });

    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }

    return adaptBackendSummary((await response.json()) as BackendSummary);
  } catch (error) {
    if (DISABLE_DEMO_FALLBACK) {
      throw error;
    }

    const message = error instanceof Error ? error.message : "Unknown API error";
    return markDemo(demoDashboardData, `Backend API unavailable (${message}); demo fallback rendered.`);
  }
}

function markDemo(data: DashboardData, message: string): DashboardData {
  return {
    ...data,
    sourceMode: "demo",
    apiBaseUrl: API_BASE_URL,
    provenance: {
      ...data.provenance,
      mode: message.startsWith("Backend API unavailable") ? "fallback" : "demo",
      description: data.provenance?.description ?? "Deterministic demo snapshot.",
      generatedAt: data.generatedAt,
      selectedDate: data.selectedDate,
      sources: data.provenance?.sources ?? [],
      freshnessPolicy: data.provenance?.freshnessPolicy ?? "Demo freshness is derived from embedded source dates."
    },
    errors: [message, ...data.errors.filter((item) => item !== message)]
  };
}

export function adaptBackendSummary(payload: BackendSummary): DashboardData {
  const freshness = adaptFreshness(payload.data_freshness.instruments);
  const sectorUpdates = [...payload.sector_leaders, ...payload.sector_laggards];
  const names: Record<string, string> = { SPY: "S&P 500", QQQ: "Nasdaq 100", IWM: "Russell 2000", DIA: "Dow Industrials" };
  const maturities: Record<string, [string, number]> = {
    DGS3MO: ["3M", 0.25],
    DGS2: ["2Y", 2],
    DGS10: ["10Y", 10],
    DGS30: ["30Y", 30]
  };

  return {
    ...demoDashboardData,
    generatedAt: payload.data_freshness.generated_at,
    selectedDate: payload.as_of,
    sourceMode: "api",
    apiBaseUrl: API_BASE_URL,
    stale: freshness.some((item) => item.status === "stale"),
    partial: freshness.some((item) => item.status === "stale"),
    optionalProvidersMissing: [],
    errors: [],
    freshness,
    provenance: {
      mode: "live",
      description: "API response computed from deterministic market, macro, rates, volatility, and regime analytics data.",
      generatedAt: payload.data_freshness.generated_at,
      selectedDate: payload.as_of,
      sources: freshness.map((source) => `${source.name}${source.latestDate ? ` (${source.latestDate})` : ""}`),
      freshnessPolicy: payload.data_freshness.freshness_policy
    },
    regime: {
      label: payload.regime.regime_label,
      displayLabel: titleCase(payload.regime.regime_label),
      confidence: payload.regime.confidence,
      asOf: payload.as_of,
      riskScore: scorePercent(payload.regime.risk_score),
      growthScore: scorePercent(payload.regime.growth_score),
      inflationScore: scorePercent(payload.regime.inflation_score),
      ratesPressureScore: scorePercent(payload.regime.rates_pressure_score),
      changedSincePrevious: payload.regime.signals.what_changed,
      positiveSignals: payload.regime.signals.top_positive.map((signal) => signal.evidence),
      negativeSignals: payload.regime.signals.top_negative.map((signal) => signal.evidence),
      limitations: payload.regime.signals.data_limitations
    },
    indices: payload.major_indices.map((item) => ({
      symbol: item.symbol,
      name: names[item.symbol] ?? item.symbol,
      price: item.value,
      dayReturn: percent(item.returns["1d"]),
      monthReturn: percent(item.returns["1m"]),
      ytdReturn: percent(item.returns.ytd),
      oneYearReturn: percent(item.returns["1y"]),
      drawdown52w: percent(item.drawdown_52w),
      volatility20d: percent(item.volatility["20d"])
    })),
    sectors: demoDashboardData.sectors.map((sector) => {
      const update = sectorUpdates.find((item) => item.symbol === sector.symbol);
      if (!update) return sector;
      return {
        ...sector,
        relativeToSpy1m: percent(update.relative_to_spy["1m"]),
        returns: {
          "1D": percent(update.returns["1d"]),
          "1W": percent(update.returns["1w"]),
          "1M": percent(update.returns["1m"]),
          "3M": percent(update.returns["3m"]),
          YTD: percent(update.returns.ytd),
          "1Y": percent(update.returns["1y"])
        }
      };
    }),
    rates: {
      ...demoDashboardData.rates,
      tenTwoSpread: payload.rates_summary.spreads["10y_2y"] ?? 0,
      points: payload.rates_summary.maturities.flatMap((item) => {
        const maturity = maturities[item.symbol];
        return maturity ? [{ maturity: maturity[0], years: maturity[1], yield: item.value, previousYield: item.value }] : [];
      })
    },
    commodities: payload.commodities_summary.map((item) => ({
      symbol: item.symbol,
      name: demoDashboardData.commodities.find((value) => value.symbol === item.symbol)?.name ?? item.symbol,
      value: item.value,
      dayChange: percent(item.returns["1d"]),
      monthReturn: percent(item.returns["1m"]),
      signal: "Deterministic API market proxy"
    })),
    volatility: [{
      symbol: payload.volatility_summary.symbol,
      name: "CBOE VIX proxy",
      value: payload.volatility_summary.value,
      dayChange: percent(payload.volatility_summary.returns["1d"]),
      monthReturn: percent(payload.volatility_summary.returns["1m"]),
      signal: "Deterministic API volatility proxy"
    }],
    signals: payload.regime.signals.all.map(adaptSignal),
    analystNote: {
      title: titleCase(payload.regime.regime_label),
      bullets: [payload.analyst_summary],
      watchItems: payload.regime.signals.top_negative.slice(0, 3).map((signal) => signal.evidence)
    }
  };
}

function adaptFreshness(rows: BackendSummary["data_freshness"]["instruments"]): FreshnessSource[] {
  const labels: Record<string, string> = {
    equity_index: "Equity indices",
    sector: "Sector ETFs",
    rates: "Treasury rates",
    macro: "Macro indicators",
    commodity: "Commodities",
    volatility: "Volatility"
  };
  const groups = new Map<string, typeof rows>();
  for (const row of rows) groups.set(row.asset_class, [...(groups.get(row.asset_class) ?? []), row]);
  return [...groups].map(([assetClass, items]) => {
    const dates = items.flatMap((item) => item.latest_date ? [item.latest_date] : []).sort();
    const lagDays = items.reduce<number | null>((largest, item) => item.age_days === null ? largest : Math.max(largest ?? 0, item.age_days), null);
    const stale = items.some((item) => item.is_stale);
    return {
      name: labels[assetClass] ?? titleCase(assetClass),
      latestDate: dates[dates.length - 1] ?? null,
      status: stale ? "stale" : "fresh",
      lagDays,
      note: "Deterministic demo_seed observations served by FastAPI."
    };
  });
}

function adaptSignal(signal: BackendSignal): RegimeSignal {
  const name = signal.name.replace(/_/g, " ");
  const category = name.includes("yield") || name.includes("year rising") ? "rates"
    : name.includes("vix") ? "volatility"
      : name.includes("oil") || name.includes("copper") || name.includes("cpi") ? "inflation"
        : name.includes("nasdaq") || name.includes("russell") ? "growth" : "risk";
  return {
    name: titleCase(name),
    category,
    value: signal.value === null ? "n/a" : String(signal.value),
    direction: signal.passed ? "positive" : "negative",
    weight: 1,
    evidence: signal.evidence
  };
}

function percent(value: number | null | undefined): number {
  return Math.round((value ?? 0) * 10_000) / 100;
}

function scorePercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(50 + value * 15)));
}

function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}
