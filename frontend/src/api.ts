import { demoDashboardData } from "./demoData";
import type { DashboardData, RangeKey } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";
const USE_DEMO_DATA = import.meta.env.VITE_USE_DEMO_DATA === "true";
const DISABLE_DEMO_FALLBACK = import.meta.env.VITE_DISABLE_DEMO_FALLBACK === "true";

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

    const data = (await response.json()) as DashboardData;
    return withLiveProvenance({
      ...data,
      sourceMode: "api",
      apiBaseUrl: API_BASE_URL,
      errors: data.errors ?? []
    });
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

function withLiveProvenance(data: DashboardData): DashboardData {
  if (data.provenance) return data;

  const sourceNames = data.freshness.map((source) => `${source.name}${source.latestDate ? ` (${source.latestDate})` : ""}`);
  return {
    ...data,
    provenance: {
      mode: "live",
      description: "Live API response assembled from backend market, macro, rates, volatility, and regime analytics endpoints.",
      generatedAt: data.generatedAt,
      selectedDate: data.selectedDate,
      sources: sourceNames,
      freshnessPolicy: "Freshness is reported per source by the backend; stale/partial flags are surfaced without hiding delayed feeds."
    }
  };
}
