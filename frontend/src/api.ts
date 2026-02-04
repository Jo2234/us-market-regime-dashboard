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
    return {
      ...data,
      sourceMode: "api",
      apiBaseUrl: API_BASE_URL,
      errors: data.errors ?? []
    };
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
    errors: [message, ...data.errors.filter((item) => item !== message)]
  };
}
