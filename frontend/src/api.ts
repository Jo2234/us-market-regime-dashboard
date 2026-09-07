import displayLabels from "../../backend/app/data/display_labels.json";
import { sentenceCase } from "./utils";
import { formatSignalValue } from "./signalFormatting";
import type { DashboardData, FreshnessSource, RangeKey, RegimeSignal, ChartPoint, MacroValue } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  (import.meta.env.PROD ? "/api" : "http://localhost:8000");
const USE_DEMO_DATA = !import.meta.env.PROD && import.meta.env.DEV && import.meta.env.VITE_USE_DEMO_DATA === "true";

type BackendInstrument = {
  date?: string;
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
  display_name?: string;
  passed: boolean;
  available?: boolean;
  value: number | null;
  evidence: string;
};

type LiveQuote = { price: number; observation_date: string; observed_at: string; is_current_session: boolean; is_stale: boolean; returns?: Record<string, number | null> };
type BackendSummary = {
  market_status?: DashboardData["marketStatus"];
  quote_delivery?: DashboardData["quoteStatus"];
  live_quotes?: Record<string, LiveQuote>;
  as_of: string;
  artifact_delivery?: { scheduled?: boolean; fresh?: boolean };
  data_mode?: "live" | "snapshot" | "demo";
  fetched_at?: string;
  cache?: "hit" | "miss" | "stale";
  retry_after_seconds?: number;
  regime: {
    days_in_regime?: number; raw_label?: string; official_label?: string; emerging_label?: string | null; emerging_days?: number;
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
    inflation_score: number; rates_pressure_score: number; note?: string;
  }>;
  sectors?: Array<{ symbol: string; date?: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  macro_summary?: Record<string, MacroValue | null>;
  sector_leaders: Array<{ symbol: string; date?: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
  sector_laggards: Array<{ symbol: string; date?: string; returns: Record<string, number | null>; relative_to_spy: Record<string, number | null> }>;
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
      name?: string;
      frequency?: string;
      symbol?: string;
      yahoo_ticker?: string | null;
      fred_series_id?: string;
      source_url?: string;
      source?: string;
      latest_date: string | null;
      age_days: number | null;
      is_stale: boolean;
      affects_group_freshness?: boolean;
    }>;
  };
};

type FetchOptions = { signal?: AbortSignal; onCached?: (data: DashboardData) => void };
const STORAGE_KEY = "market-regime-real-snapshot-v1";

function verified(payload: BackendSummary): DashboardData {
  const sources = [...(payload.data_freshness.sources ?? []), ...payload.data_freshness.instruments];
  if (payload.data_mode === "demo" || sources.some(item => item.source === "demo_seed")) {
    throw new Error("The API returned synthetic data; real market observations are required");
  }
  return adaptBackendSummary(payload);
}

export async function fetchDashboardData(date: string, range: RangeKey, options: FetchOptions = {}): Promise<DashboardData> {
  if (USE_DEMO_DATA) {
    const { demoDashboardData } = await import("./demoData");
    return markDemo(demoDashboardData, "Demo mode enabled with VITE_USE_DEMO_DATA=true.");
  }
  let finished = false;
  let bootstrap: Promise<void> | undefined;
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) abort();
  const timeout = window.setTimeout(abort, 25_000);
  try {
    const url = new URL(`${API_BASE_URL}/dashboard/summary`, window.location.origin);
    if (date) url.searchParams.set("date", date);
    url.searchParams.set("range", range.toLowerCase());
    const read = async (target: URL) => {
      const response = await fetch(target.toString(), { headers: { Accept: "application/json" }, signal: controller.signal });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const payload = await response.json() as BackendSummary;
      verified(payload);
      return payload;
    };
    // Development-only visual checks use the real local snapshot, never example numbers.
    const qa = import.meta.env.DEV && import.meta.env.VITE_ENABLE_QA === "true"
      ? new URLSearchParams(window.location.search).get("qa") : null;
    if (qa === "error") throw new Error("Local failure simulation: the data service is unavailable");
    if (qa === "skeleton") await new Promise(resolve => window.setTimeout(resolve, 60_000));
    if (options.onCached) {
      let stored = false;
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
        if (saved?.key === `${date}:${range}` && ["live", "snapshot"].includes(saved.payload.data_mode)) {
          options.onCached(verified(saved.payload));
          stored = true;
        }
      } catch { /* Storage is optional; blocked/quota/corrupt storage cannot break live data. */ }
      if (!stored && (qa === "background" || qa === "stale")) {
        const cachedUrl = new URL(url); cachedUrl.searchParams.set("cached_only", "true");
        bootstrap = read(cachedUrl).then(payload => {
          if (!finished && !controller.signal.aborted) options.onCached?.(verified(payload));
        }).catch(() => { /* The normal request below owns the error state. */ });
      }
    }
    if (qa === "background" || qa === "stale") {
      await bootstrap;
      if (qa === "stale") throw new Error("Local failure simulation: live refresh unavailable");
      await new Promise(resolve => window.setTimeout(resolve, 60_000));
    }
    const payload = await read(url);
    finished = true;
    if (["live", "snapshot"].includes(payload.data_mode ?? "")) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ key: `${date}:${range}`, payload })); } catch { /* Optional cache. */ }
    }
    return verified(payload);
  } catch (error) {
    await bootstrap;
    const message = error instanceof Error ? error.message : "Unknown API error";
    throw new Error(`Live data unavailable (${message}). Please retry later.`);
  } finally {
    finished = true;
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
    controller.abort();
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

function withLiveQuotes(raw: BackendSummary): BackendSummary {
  if (!raw.market_status?.is_open) return raw;
  const quotes = raw.live_quotes ?? {};
  const usable = (symbol: string) => quotes[symbol]?.is_current_session && !quotes[symbol]?.is_stale ? quotes[symbol] : undefined;
  const overlay = (item: BackendInstrument) => {
    const quote = usable(item.symbol);
    return quote ? { ...item, date: quote.observation_date, price: quote.price, returns: quote.returns ?? item.returns } : item;
  };
  const sectors = raw.sectors?.map(item => {
    const returns = usable(item.symbol)?.returns ?? item.returns;
    const spy = usable("SPY")?.returns ?? raw.major_indices.find(i => i.symbol === "SPY")?.returns ?? {};
    return { ...item, date: usable(item.symbol)?.observation_date ?? item.date, returns, relative_to_spy: Object.fromEntries(Object.entries(returns).map(([key, value]) => [key, value != null && spy[key] != null ? value - spy[key]! : null])) };
  });
  const performance = [...(raw.performance_series ?? [])];
  const last = performance[performance.length - 1];
  if (last && ["SPY", "QQQ", "IWM", "DIA"].every(symbol => usable(symbol))) {
    const point = { ...last, date: raw.market_status.session_date };
    for (const symbol of ["SPY", "QQQ", "IWM", "DIA"] as const) {
      const daily = raw.major_indices.find(item => item.symbol === symbol);
      if (daily?.value) point[symbol] = last[symbol] * usable(symbol)!.price / daily.value;
    }
    performance.push(point);
  }
  return { ...raw, major_indices: raw.major_indices.map(overlay), sectors,
    commodities_summary: raw.commodities_summary.map(overlay), volatility_summary: overlay(raw.volatility_summary),
    rates_summary: raw.rates_summary, performance_series: performance };
}

export function adaptBackendSummary(raw: BackendSummary): DashboardData {
  const payload = withLiveQuotes(raw);
  const freshness = adaptFreshness(payload.data_freshness.instruments);
  const sources = sourceLabels([
    ...(payload.data_freshness.sources ?? []),
    ...payload.data_freshness.instruments
  ]);
  const hasDemoSource = sources.some(source => source.toLowerCase() === "demo_seed");
  const onlyDemoSources = hasDemoSource && sources.every(source => source.toLowerCase() === "demo_seed");
  const sectorUpdates = payload.sectors ?? [...payload.sector_leaders, ...payload.sector_laggards];
  const sectorNames: Record<string, string> = {
    XLK: "Technology", XLF: "Financials", XLE: "Energy", XLV: "Health care", XLY: "Consumer discretionary",
    XLP: "Staples", XLI: "Industrials", XLB: "Materials", XLU: "Utilities", XLRE: "Real estate", XLC: "Communications"
  };
  const names: Record<string, string> = { SPY: "S&P 500", QQQ: "Nasdaq 100", IWM: "Russell 2000", DIA: "Dow Jones" };
  const maturities: Record<string, [string, number]> = {
    DGS3MO: ["3M", 0.25],
    DGS2: ["2Y", 2],
    DGS5: ["5Y", 5],
    DGS10: ["10Y", 10],
    DGS30: ["30Y", 30]
  };

  return {
    scheduledFresh: Boolean(payload.artifact_delivery?.scheduled && payload.artifact_delivery?.fresh),
    marketStatus: payload.market_status,
    quoteStatus: payload.quote_delivery,
    intraday: Boolean(payload.market_status?.is_open && Object.values(payload.live_quotes ?? {}).some(q => q.is_current_session && !q.is_stale)),
    performanceSeries: payload.performance_series ?? [],
    historicalRegimes: (payload.historical_regimes ?? []).map((point) => ({
      date: point.date, displayLabel: regimeLabel(point.regime_label),
      riskScore: scorePercent(point.risk_score), growthScore: scorePercent(point.growth_score),
      inflationScore: scorePercent(point.inflation_score), ratesPressureScore: scorePercent(point.rates_pressure_score),
      note: point.note ?? "Computed from completed daily closes with approximate macro release lags."
    })),
    breadth: [],
    fetchedAt: payload.quote_delivery?.fetched_at ?? payload.fetched_at,
    cache: payload.cache,
    retryAfterSeconds: payload.retry_after_seconds,
    generatedAt: payload.data_freshness.generated_at,
    selectedDate: payload.as_of,
    sourceMode: "api",
    apiBaseUrl: API_BASE_URL,
    stale: freshness.some((item) => item.status === "stale"),
    partial: freshness.some(item => item.status === "stale" || item.status === "partial" || item.status === "error"),
    optionalProvidersMissing: ["Market breadth feed"],
    macro: payload.macro_summary ?? {},
    errors: [],
    freshness,
    provenance: {
      mode: payload.data_mode === "snapshot" ? "snapshot" : payload.data_mode === "live" ? "live" : onlyDemoSources ? "demo" : hasDemoSource ? "mixed" : "api",
      description: payload.data_mode === "snapshot"
        ? payload.artifact_delivery?.fresh ? "Scheduled daily research snapshot from Yahoo Finance and FRED, with original observation dates. Live quotes refresh during NYSE hours." : "Saved real observations; the scheduled update is overdue."
        : payload.data_mode === "live"
          ? "Yahoo Finance quotes refresh every 60 seconds during NYSE hours; closed markets show completed daily closes. Longer returns use adjusted history with a live endpoint intraday. The regime model uses completed daily closes."
          : onlyDemoSources
        ? "Deterministic demo_seed observations served by the API. Values are generated examples, not live market data."
        : hasDemoSource
          ? "API observations include demo_seed examples alongside other reported sources."
          : sources.length
            ? "API observations from the reported sources below. See source dates for freshness."
            : "API observations; source metadata was not supplied. Live market provenance is unverified.",
      generatedAt: payload.data_freshness.generated_at,
      selectedDate: payload.as_of,
      sources: sources.map(source => displayLabels.sources[source as keyof typeof displayLabels.sources] ?? sentenceCase(source)),
      observations: payload.data_freshness.instruments.filter(item => item.yahoo_ticker || item.fred_series_id).map(item => ({ symbol: item.symbol ?? "", name: item.name ?? item.symbol ?? "", ticker: item.fred_series_id ? `FRED: ${item.fred_series_id}` : item.yahoo_ticker!, date: item.latest_date, url: item.source_url, isStale: item.is_stale })),
      freshnessPolicy: payload.data_freshness.freshness_policy
    },
    regime: {
      label: payload.regime.regime_label,
      daysInRegime: payload.regime.days_in_regime,
      rawLabel: payload.regime.raw_label,
      emergingLabel: payload.regime.emerging_label ? regimeLabel(payload.regime.emerging_label) : null,
      emergingDays: payload.regime.emerging_days,
      displayLabel: regimeLabel(payload.regime.regime_label),
      confidence: payload.regime.confidence,
      asOf: payload.as_of,
      riskScore: scorePercent(payload.regime.risk_score),
      growthScore: scorePercent(payload.regime.growth_score),
      inflationScore: scorePercent(payload.regime.inflation_score),
      ratesPressureScore: scorePercent(payload.regime.rates_pressure_score),
      changedSincePrevious: payload.regime.signals.what_changed,
      positiveSignals: payload.regime.signals.top_positive.map((signal) => adaptSignal(signal).name),
      negativeSignals: payload.regime.signals.top_negative.map((signal) => adaptSignal(signal).name),
      limitations: payload.regime.signals.data_limitations
    },
    indices: payload.major_indices.filter((item) => item.available !== false).map((item) => ({
      symbol: item.symbol,
      observationDate: item.date ?? payload.as_of,
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
      observationDate: item.date ?? payload.as_of,
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
        const observation = payload.data_freshness.instruments.find(row => row.symbol === item.symbol);
        const isStale = observation?.is_stale && observation.latest_date === item.date;
        return maturity ? [{ maturity: maturity[0], years: maturity[1], yield: item.value, date: item.date, ticker: item.yahoo_ticker, isStale }] : [];
      })
    },
    commodities: payload.commodities_summary.filter((item) => item.available !== false).map((item) => ({
      symbol: item.symbol,
      observationDate: item.date ?? payload.as_of,
      name: ({ USO: "Crude oil proxy", GLD: "Gold", CPER: "Copper" } as Record<string, string>)[item.symbol] ?? item.symbol,
      value: item.price ?? item.value,
      dayChange: percent(item.returns["1d"]),
      monthReturn: percent(item.returns["1m"]),
      signal: payload.market_status?.is_open && payload.live_quotes?.[item.symbol]?.is_current_session && !payload.live_quotes?.[item.symbol]?.is_stale ? "Yahoo Finance · Intraday quote" : "Yahoo Finance · Daily ETF close"
    })),
    volatility: payload.volatility_summary.available === false ? [] : [{
      symbol: payload.volatility_summary.symbol,
      observationDate: payload.volatility_summary.date ?? payload.as_of,
      name: "CBOE Volatility Index",
      value: payload.volatility_summary.price ?? payload.volatility_summary.value,
      dayChange: percent(payload.volatility_summary.returns["1d"]),
      monthReturn: percent(payload.volatility_summary.returns["1m"]),
      signal: payload.market_status?.is_open && payload.live_quotes?.VIX?.is_current_session && !payload.live_quotes?.VIX?.is_stale ? "Yahoo Finance · ^VIX intraday quote" : "Yahoo Finance · ^VIX daily close"
    }],
    signals: payload.regime.signals.all.map(adaptSignal),
    analystNote: {
      title: regimeLabel(payload.regime.regime_label),
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
    sector_etf: "Sector ETFs",
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
    const stale = items.some((item) => item.is_stale && item.affects_group_freshness !== false);
    const sources = sourceLabels(items);
    return {
      name: labels[assetClass] ?? sentenceCase(assetClass),
      latestDate: dates[0] ?? null,
      status: dates.length < items.length ? "partial" : stale ? "stale" : "fresh",
      lagDays,
      note: sources.length ? `Reported sources: ${sources.map(source => displayLabels.sources[source as keyof typeof displayLabels.sources] ?? sentenceCase(source)).join(", ")}.` : "Source metadata was not supplied by the API."
    };
  });
}

function adaptSignal(signal: BackendSignal): RegimeSignal {
  const formatted = formatSignalValue(signal.name, signal.value);
  const name = signal.name.replace(/_/g, " ");
  const category = name.includes("yield") || name.includes("year rising") ? "rates"
    : name.includes("vix") ? "volatility"
      : name.includes("oil") || name.includes("copper") || name.includes("cpi") ? "inflation"
        : name.includes("nasdaq") || name.includes("russell") ? "growth" : "risk";
  return {
    name: signal.display_name ?? displayLabels.signals[signal.name as keyof typeof displayLabels.signals] ?? sentenceCase(name),
    category,
    value: signal.value === null ? "n/a" : String(signal.value),
    displayValue: formatted.display,
    rawUnit: formatted.rawUnit,
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

function regimeLabel(value: string): string {
  return displayLabels.regimes[value as keyof typeof displayLabels.regimes] ?? sentenceCase(value);
}
