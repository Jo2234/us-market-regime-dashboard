import { afterEach, describe, expect, it, vi } from "vitest";
import type { adaptBackendSummary } from "./api";

type Summary = Parameters<typeof adaptBackendSummary>[0];

function summary(): Summary {
  return {
    as_of: "2025-01-15",
    regime: {
      regime_label: "mixed_transition", confidence: "low", risk_score: 0, growth_score: 1,
      inflation_score: 0, rates_pressure_score: 0,
      signals: { top_positive: [], top_negative: [], all: [], what_changed: "No prior snapshot", data_limitations: [] }
    },
    major_indices: [], sector_leaders: [], sector_laggards: [],
    rates_summary: { maturities: [], spreads: {} }, commodities_summary: [],
    volatility_summary: { symbol: "VIX", available: false, value: 0, returns: {}, volatility: {}, drawdown_52w: null },
    analyst_summary: "Computed note",
    data_freshness: { generated_at: "2025-01-16T00:00:00Z", freshness_policy: "Daily observations", instruments: [] }
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function productionApi(base = "", demo = "false") {
  vi.stubEnv("PROD", true);
  vi.stubEnv("VITE_API_BASE_URL", base);
  vi.stubEnv("VITE_USE_DEMO_DATA", demo);
  vi.stubEnv("VITE_DISABLE_DEMO_FALLBACK", "false");
  return import("./api");
}

describe("production request routing", () => {
  it("resolves the default same-origin /api route and supplies the selected window", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => summary() });
    vi.stubGlobal("fetch", fetch);
    const api = await productionApi();
    const result = await api.fetchDashboardData("2025-01-15", "1W");
    const url = new URL(fetch.mock.calls[0][0]);
    expect(url.origin).toBe(window.location.origin);
    expect(url.pathname).toBe("/api/dashboard/summary");
    expect(url.searchParams.get("date")).toBe("2025-01-15");
    expect(url.searchParams.get("range")).toBe("1w");
    expect(result.sourceMode).toBe("api");
  });

  it("keeps an absolute API base working", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => summary() });
    vi.stubGlobal("fetch", fetch);
    const api = await productionApi("https://api.example.test/v1/");
    await api.fetchDashboardData("", "1M");
    expect(fetch.mock.calls[0][0]).toBe("https://api.example.test/v1/dashboard/summary?range=1m");
  });

  it("rejects network and URL failures without synthetic fallback", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    let api = await productionApi();
    await expect(api.fetchDashboardData("", "1M")).rejects.toThrow("Live data unavailable");
    vi.resetModules();
    api = await productionApi("http://[");
    await expect(api.fetchDashboardData("", "1M")).rejects.toThrow("Live data unavailable");
  });
});

describe("API provenance", () => {
  it.each([
    { sources: ["demo_seed"], mode: "demo" },
    { sources: ["fred", "yahoo_finance"], mode: "api" },
    { sources: ["demo_seed", "fred"], mode: "mixed" },
    { sources: [], mode: "api" }
  ])("classifies $sources without confusing API transport with live data", async ({ sources, mode }) => {
    const api = await productionApi();
    const input = summary();
    input.data_freshness.sources = sources.map(source => ({ source }));
    input.data_freshness.instruments = sources.map(source => ({
      source, asset_class: "macro", latest_date: input.as_of, age_days: 0, is_stale: false
    }));
    const data = api.adaptBackendSummary(input);
    expect(data.sourceMode).toBe("api");
    expect(data.provenance?.mode).toBe(mode);
    expect(data.provenance?.sources).toEqual(sources.map(source => ({ demo_seed: "Local demo", fred: "FRED", yahoo_finance: "Yahoo Finance" })[source]));
    if (!sources.length) expect(data.provenance?.description).toContain("source metadata was not supplied");
    if (!sources.includes("demo_seed")) {
      expect(data.freshness.map(item => item.note).join(" ")).not.toContain("demo_seed");
    }
    // Older API responses may omit the aggregate list but still identify each instrument.
    delete input.data_freshness.sources;
    expect(api.adaptBackendSummary(input).provenance?.mode).toBe(mode);
  });

  it("never fills missing API sections or measurements with demo data", async () => {
    const api = await productionApi();
    const data = api.adaptBackendSummary(summary());
    expect(data.selectedDate).toBe("2025-01-15");
    expect(data.performanceSeries).toEqual([]);
    expect(data.historicalRegimes).toEqual([]);
    expect(data.breadth).toEqual([]);
    expect(data.sectors).toEqual([]);
    expect(data.volatility).toEqual([]);
    expect(data.rates).toEqual({ points: [], fedFundsRate: null, cpiYoY: null, unemploymentRate: null, tenTwoSpread: null });
    expect(data.optionalProvidersMissing).toContain("Market breadth feed");
  });

  it("uses every API sector and actual macro/series values", async () => {
    const api = await productionApi();
    const input = summary();
    input.sectors = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"].map((symbol, i) => ({
      symbol, returns: { "1m": i / 100 }, relative_to_spy: { "1m": null }
    }));
    input.macro_summary = { FEDFUNDS: { value: 2.22 }, CPI_YOY: { value: 1.11 }, UNRATE: { value: 5.55 } };
    input.performance_series = [{ date: input.as_of, SPY: 100, QQQ: 100, IWM: 100, DIA: 100 }];
    input.rates_summary.maturities = [{ symbol: "DGS10", value: 3.33 }];
    const data = api.adaptBackendSummary(input);
    expect(data.sectors).toHaveLength(11);
    expect(data.sectors.map((sector) => sector.returns["1M"])).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(data.sectors[0].returns["1Y"]).toBeNull();
    expect(data.sectors[0].relativeToSpy1m).toBeNull();
    expect(data.rates.cpiYoY).toBe(1.11);
    expect(data.rates.points[0].previousYield).toBeUndefined();
    expect(data.performanceSeries).toEqual(input.performance_series);
  });
});

it("uses raw close as price and keeps the labelled snapshot and 5Y maturity", async () => {
  const api = await productionApi();
  const input = summary();
  Object.assign(input, { data_mode: "snapshot" });
  input.major_indices = [{ symbol: "SPY", value: 98, price: 100, returns: { "1m": 0.02 }, volatility: {}, drawdown_52w: null }];
  input.rates_summary.maturities = [{ symbol: "DGS2", value: 4.5 }, { symbol: "DGS5", value: 5.068 }];
  const data = api.adaptBackendSummary(input);
  expect(data.indices[0].price).toBe(100);
  expect(data.indices[0].monthReturn).toBe(2);
  expect(data.provenance?.mode).toBe("snapshot");
  expect(data.rates.points.map(point => point.maturity)).toEqual(["2Y", "5Y"]);
});

it("does not enable embedded demo data in a production build", async () => {
  const api = await productionApi("", "true");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(api.fetchDashboardData("", "1M")).rejects.toThrow("Live data unavailable");
});

it("rejects synthetic API observations in production", async () => {
  const input = summary();
  input.data_freshness.sources = [{ source: "demo_seed" }];
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => input }));
  const api = await productionApi();
  await expect(api.fetchDashboardData("", "1M")).rejects.toThrow("synthetic data");
});

it("delivers the persisted real snapshot without a second bootstrap request", async () => {
  const snapshot = { ...summary(), data_mode: "snapshot" as const, fetched_at: "2025-01-16T00:00:00Z", cache: "stale" as const };
  const live = { ...snapshot, data_mode: "live" as const, cache: "miss" as const };
  let finish!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => url.includes("cached_only=true")
    ? Promise.resolve({ ok: true, json: async () => snapshot })
    : new Promise(resolve => { finish = resolve; })));
  localStorage.setItem("market-regime-real-snapshot-v1", JSON.stringify({ key: ":1M", payload: snapshot }));
  const api = await productionApi();
  const cached = vi.fn();
  const request = api.fetchDashboardData("", "1M", { onCached: cached });
  await vi.waitFor(() => expect(cached).toHaveBeenCalledTimes(1));
  expect(cached.mock.calls[0][0].provenance.mode).toBe("snapshot");
  finish({ ok: true, json: async () => live });
  expect((await request).provenance?.mode).toBe("live");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(localStorage.getItem("market-regime-real-snapshot-v1")!).payload.data_mode).toBe("live");
  localStorage.clear();
});

it("never accepts a synthetic persisted snapshot when the network fails", async () => {
  localStorage.setItem("market-regime-real-snapshot-v1", JSON.stringify({ key: ":1M", payload: { ...summary(), data_mode: "demo" } }));
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  const api = await productionApi();
  const cached = vi.fn();
  await expect(api.fetchDashboardData("", "1M", { onCached: cached })).rejects.toThrow("Live data unavailable");
  expect(cached).not.toHaveBeenCalled();
  localStorage.clear();
});

it("preserves FRED provenance, observation cadence and per-card fallback", async () => {
  const api = await productionApi();
  const input = summary();
  input.macro_summary = { FEDFUNDS: { value: 3.88, source: "fred", fred_series_id: "DFF", frequency: "daily", observation_date: "2026-09-25", mode: "snapshot" } };
  input.data_freshness.instruments = [{ symbol: "FEDFUNDS", asset_class: "macro", source: "fred", fred_series_id: "DFF", source_url: "https://fred.stlouisfed.org/series/DFF", latest_date: "2026-09-25", age_days: 4, is_stale: false }];
  const result = api.adaptBackendSummary(input);
  expect(result.macro?.FEDFUNDS).toEqual(input.macro_summary.FEDFUNDS);
  expect(result.freshness[0].status).toBe("fresh");
  expect(result.provenance?.observations?.[0].url).toBe("https://fred.stlouisfed.org/series/DFF");
  expect(result.optionalProvidersMissing).not.toContain("CPI, unemployment and Fed funds (no Yahoo equivalent)");
});

it("displays current quotes with their dates while preserving completed regime inputs", async () => {
  const api = await productionApi();
  const input = summary();
  input.market_status = { is_open: true, session_date: "2025-01-16", refresh_seconds: 60, next_open: "2025-01-17" };
  input.major_indices = [{ symbol: "SPY", date: "2025-01-15", value: 100, price: 101, returns: { "1m": .02 }, volatility: {}, drawdown_52w: 0 }];
  input.live_quotes = { SPY: { price: 102, observation_date: "2025-01-16", observed_at: "2025-01-16T15:00:00Z", is_current_session: true, is_stale: false, returns: { "1m": .03 } } };
  const result = api.adaptBackendSummary(input);
  expect(result.indices[0].price).toBe(102);
  expect(result.indices[0].monthReturn).toBe(3);
  expect(result.indices[0].observationDate).toBe("2025-01-16");
  expect(result.regime.asOf).toBe("2025-01-15");
  expect(input.major_indices[0].price).toBe(101);
  input.live_quotes.SPY.is_stale = true;
  expect(api.adaptBackendSummary(input).indices[0].price).toBe(101);
});


it("keeps unrounded signal values while exposing display units and support names", async () => {
  const { adaptBackendSummary } = await import("./api");
  const data = summary();
  const signal = { name: "nasdaq_outperforming_sp500_1m", value: 0.035311, passed: true, evidence: "QQQ outperformed SPY by 3.53 percentage points." };
  data.regime.signals.all = [signal]; data.regime.signals.top_positive = [signal];
  const result = adaptBackendSummary(data);
  expect(result.signals[0].value).toBe("0.035311");
  expect(result.signals[0].displayValue).toBe("+3.53 pp");
  expect(result.regime.positiveSignals[0]).toBe("Nasdaq 100 outperforming S&P 500 (1M)");
  expect(result.partial).toBe(false);
});
