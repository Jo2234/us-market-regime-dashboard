import type { DashboardData, FreshnessSource, RangeKey, RegimeSignal, ChartPoint } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  (import.meta.env.PROD ? "/api" : "http://localhost:8000");
const USE_DEMO_DATA = !import.meta.env.PROD && import.meta.env.DEV && import.meta.env.VITE_USE_DEMO_DATA === "true";

type BackendInstrument = {
  symbol: string;
  available?: boolean;
  value: number;
  price?: number;
  returns: Record<string, number | null>;
  volatility: Record<string, number | null>;
  drawdown_52w: number | null;
};

type BackendSignal = {
  name: string;
  passed: boolean;
  available?: boolean;
  value: number | null;
  evidence: string;
};

type BackendSummary = {
  as_of: string;
  data_mode?: "live" | "snapshot" | "demo";
  fetched_at?: string;
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
  performance_series?: ChartPoint[];
  historical_regimes?: Array<{
    date: string; regime_label: string; risk_score: number; growth_score: number;
    inflation_score: number; rates_pressure_score: number;
  }>;
  sectors?: Array<{ symbol: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  macro_summary?: Record<string, { value: number } | null>;
  sector_leaders: Array<{ symbol: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  sector_laggards: Array<{ symbol: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  rates_summary: {
    maturities: Array<{ symbol: string; value: number; yahoo_ticker?: string; date?: string }>;
    spreads: Record<string, number | null>;
  };
  commodities_summary: BackendInstrument[];
  volatility_summary: BackendInstrument;
  analyst_summary: string;
  data_freshness: {
    generated_at: string;
    freshness_policy: string;
    sources?: Array<{ source: string }>;
    instruments: Array<{
      asset_class: string;
      symbol?: string;
      yahoo_ticker?: string | null;
      source?: string;
      latest_date: string | null;
      age_days: number | null;
      is_stale: boolean;
    }>;
  };
};

export async function fetchDashboardData(date: string, range: RangeKey): Promise<DashboardData> {
  if (USE_DEMO_DATA) {
    const { demoDashboardData } = await import("./demoData");
    return markDemo(demoDashboardData, "Demo mode enabled with VITE_USE_DEMO_DATA=true.");
  }

  try {
    const url = new URL(`${API_BASE_URL}/dashboard/summary`, window.location.origin);
    if (date) url.searchParams.set("date", date);
    url.searchParams.set("range", range.toLowerCase());
    const response = await fetch(url.toString(), {
      headers: { Accept: "application/json" }
    });

    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }

    const payload = (await response.json()) as BackendSummary;
    const sources = [...(payload.data_freshness.sources ?? []), ...payload.data_freshness.instruments];
    if (import.meta.env.PROD && (payload.data_mode === "demo" || sources.some(item => item.source === "demo_seed"))) {
      throw new Error("The API returned synthetic data; production requires real market observations");
    }
    return adaptBackendSummary(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown API error";
    throw new Error(`Live data unavailable (${message}). Please retry later.`);
  }
}

function markDemo(data: DashboardData, message: string): DashboardData {
  return {
    ...data,
    sourceMode: "demo",
    apiBaseUrl: API_BASE_URL,
    provenance: {
      ...data.provenance,
      mode: "demo",
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
  const sources = sourceLabels([
    ...(payload.data_freshness.sources ?? []),
    ...payload.data_freshness.instruments
  ]);
  const hasDemoSource = sources.some(source => source.toLowerCase() === "demo_seed");
  const onlyDemoSources = hasDemoSource && sources.every(source => source.toLowerCase() === "demo_seed");
  const sectorUpdates = payload.sectors ?? [...payload.sector_leaders, ...payload.sector_laggards];
  const sectorNames: Record<string, string> = {
    XLK: "Technology", XLF: "Financials", XLE: "Energy", XLV: "Health Care", XLY: "Cons. Disc.",
    XLP: "Staples", XLI: "Industrials", XLB: "Materials", XLU: "Utilities", XLRE: "Real Estate", XLC: "Comm. Svcs."
  };
  const names: Record<string, string> = { SPY: "S&P 500", QQQ: "Nasdaq 100", IWM: "Russell 2000", DIA: "Dow Industrials" };
  const maturities: Record<string, [string, number]> = {
    DGS3MO: ["3M", 0.25],
    DGS2: ["2Y*", 2],
    DGS5: ["5Y", 5],
    DGS10: ["10Y", 10],
    DGS30: ["30Y", 30]
  };

  return {
    performanceSeries: payload.performance_series ?? [],
    historicalRegimes: (payload.historical_regimes ?? []).map((point) => ({
      date: point.date, displayLabel: titleCase(point.regime_label),
      riskScore: scorePercent(point.risk_score), growthScore: scorePercent(point.growth_score),
      inflationScore: scorePercent(point.inflation_score), ratesPressureScore: scorePercent(point.rates_pressure_score),
      note: "Computed from stored regime classifications."
    })),
    breadth: [],
    generatedAt: payload.data_freshness.generated_at,
    selectedDate: payload.as_of,
    sourceMode: "api",
    apiBaseUrl: API_BASE_URL,
    stale: freshness.some((item) => item.status === "stale"),
    partial: true,
    optionalProvidersMissing: ["Market breadth feed", "CPI, unemployment and Fed funds (no Yahoo equivalent)"],
    errors: [],
    freshness,
    provenance: {
      mode: payload.data_mode === "snapshot" ? "snapshot" : payload.data_mode === "live" ? "live" : onlyDemoSources ? "demo" : hasDemoSource ? "mixed" : "api",
      description: payload.data_mode === "snapshot"
        ? "Yahoo could not be refreshed. Showing a last-known-good Yahoo snapshot with its original observation dates."
        : payload.data_mode === "live"
          ? "Daily closes fetched from Yahoo Finance. Prices are unadjusted closes; returns use adjusted closes. Live describes the feed, not intraday quotes."
          : onlyDemoSources
        ? "Deterministic demo_seed observations served by the API. Values are generated examples, not live market data."
        : hasDemoSource
          ? "API observations include demo_seed examples alongside other reported sources."
          : sources.length
            ? "API observations from the reported sources below. See source dates for freshness."
            : "API observations; source metadata was not supplied. Live market provenance is unverified.",
      generatedAt: payload.data_freshness.generated_at,
      selectedDate: payload.as_of,
      sources,
      observations: payload.data_freshness.instruments.filter(item => item.yahoo_ticker).map(item => ({ symbol: item.symbol ?? "", ticker: item.yahoo_ticker!, date: item.latest_date })),
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
    indices: payload.major_indices.filter((item) => item.available !== false).map((item) => ({
      symbol: item.symbol,
      name: names[item.symbol] ?? item.symbol,
      price: item.price ?? item.value,
      dayReturn: percent(item.returns["1d"]),
      monthReturn: percent(item.returns["1m"]),
      ytdReturn: percent(item.returns.ytd),
      oneYearReturn: percent(item.returns["1y"]),
      drawdown52w: percent(item.drawdown_52w),
      volatility20d: percent(item.volatility["20d"])
    })),
    sectors: sectorUpdates.map((item) => ({
      symbol: item.symbol,
      name: sectorNames[item.symbol] ?? item.symbol,
      relativeToSpy1m: percent(item.relative_to_spy["1m"]),
      returns: {
        "1D": percent(item.returns["1d"]), "1W": percent(item.returns["1w"]),
        "1M": percent(item.returns["1m"]), "3M": percent(item.returns["3m"]),
        YTD: percent(item.returns.ytd), "1Y": percent(item.returns["1y"])
      }
    })),
    rates: {
      fedFundsRate: payload.macro_summary?.FEDFUNDS?.value ?? null,
      cpiYoY: payload.macro_summary?.CPI_YOY?.value ?? null,
      unemploymentRate: payload.macro_summary?.UNRATE?.value ?? null,
      tenTwoSpread: payload.rates_summary.spreads["10y_2y"] ?? null,
      points: payload.rates_summary.maturities.flatMap((item) => {
        const maturity = maturities[item.symbol];
        return maturity ? [{ maturity: maturity[0], years: maturity[1], yield: item.value, date: item.date, ticker: item.yahoo_ticker }] : [];
      })
    },
    commodities: payload.commodities_summary.filter((item) => item.available !== false).map((item) => ({
      symbol: item.symbol,
      name: ({ USO: "Crude oil proxy", GLD: "Gold", CPER: "Copper" } as Record<string, string>)[item.symbol] ?? item.symbol,
      value: item.price ?? item.value,
      dayChange: percent(item.returns["1d"]),
      monthReturn: percent(item.returns["1m"]),
      signal: "Yahoo Finance daily ETF close"
    })),
    volatility: payload.volatility_summary.available === false ? [] : [{
      symbol: payload.volatility_summary.symbol,
      name: "CBOE Volatility Index",
      value: payload.volatility_summary.price ?? payload.volatility_summary.value,
      dayChange: percent(payload.volatility_summary.returns["1d"]),
      monthReturn: percent(payload.volatility_summary.returns["1m"]),
      signal: "Yahoo Finance · ^VIX daily close"
    }],
    signals: payload.regime.signals.all.map(adaptSignal),
    analystNote: {
      title: titleCase(payload.regime.regime_label),
      bullets: [payload.analyst_summary],
      watchItems: payload.regime.signals.top_negative.slice(0, 3).map((signal) => signal.evidence)
    }
  };
}

function sourceLabels(rows: Array<{ source?: string }>): string[] {
  return [...new Set(rows.map(row => row.source)
    .filter((source): source is string => typeof source === "string" && source.trim().length > 0)
    .map(source => source.trim()))];
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
    const sources = sourceLabels(items);
    return {
      name: labels[assetClass] ?? titleCase(assetClass),
      latestDate: dates[0] ?? null,
      status: dates.length < items.length ? "partial" : stale ? "stale" : "fresh",
      lagDays,
      note: sources.length ? `Reported sources: ${sources.join(", ")}.` : "Source metadata was not supplied by the API."
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
    direction: signal.available === false || signal.value === null ? "neutral" : signal.passed ? "positive" : "negative",
    weight: 1,
    evidence: signal.evidence
  };
}

function percent(value: number | null | undefined): number | null {
  return value == null ? null : Math.round(value * 10_000) / 100;
}

function scorePercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(50 + value * 15)));
}

function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}
