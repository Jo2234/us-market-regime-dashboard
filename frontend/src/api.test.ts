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

async function productionApi(base = "") {
  vi.stubEnv("PROD", true);
  vi.stubEnv("VITE_API_BASE_URL", base);
  vi.stubEnv("VITE_USE_DEMO_DATA", "false");
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

  it("falls back on network and URL configuration failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    let api = await productionApi();
    expect((await api.fetchDashboardData("", "1M")).provenance?.mode).toBe("fallback");
    vi.resetModules();
    api = await productionApi("http://[");
    expect((await api.fetchDashboardData("", "1M")).provenance?.mode).toBe("fallback");
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
    expect(data.provenance?.sources).toEqual(sources);
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
