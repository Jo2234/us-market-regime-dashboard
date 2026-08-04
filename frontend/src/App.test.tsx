import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDashboardData } from "./api";
import App from "./App";
import { demoDashboardData } from "./demoData";

vi.mock("./api", () => ({
  fetchDashboardData: vi.fn()
}));

const mockedFetchDashboardData = vi.mocked(fetchDashboardData);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("App dashboard states", () => {
  it.each([
    { mode: "demo" as const, label: "Demo data" },
    { mode: "api" as const, label: "API data" },
    { mode: "mixed" as const, label: "Mixed sources" }
  ])("renders $label independently of API transport", async ({ mode, label }) => {
    mockedFetchDashboardData.mockResolvedValue({
      ...demoDashboardData,
      sourceMode: "api",
      apiBaseUrl: "/api",
      provenance: { ...demoDashboardData.provenance!, mode }
    });
    render(<App />);
    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(screen.getByText("API: /api")).toBeInTheDocument();
    expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument();
  });

  it("renders stale, partial, and optional-provider status states", async () => {
    mockedFetchDashboardData.mockResolvedValue(demoDashboardData);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Mixed Transition" })).toBeInTheDocument();
    expect(screen.getByText("Partial freshness")).toBeInTheDocument();
    expect(screen.getByText("Partial snapshot: at least one feed is delayed or missing latest observations.")).toBeInTheDocument();
    expect(screen.getByText("Optional provider not configured: CBOE VIX direct feed.")).toBeInTheDocument();
    expect(screen.getByText("Optional provider not configured: premium options sentiment.")).toBeInTheDocument();
    expect(screen.getByText("Data provenance")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Historical Regime Scores" })).toBeInTheDocument();
  });

  it("shows an explicit fallback when freshness metadata is missing", async () => {
    mockedFetchDashboardData.mockResolvedValue({
      ...demoDashboardData,
      freshness: [],
      errors: [],
      optionalProvidersMissing: [],
      stale: false,
      partial: false
    });

    render(<App />);

    expect(await screen.findByText("No source dates returned")).toBeInTheDocument();
  });

  it("renders a fatal source error and recovers on retry", async () => {
    mockedFetchDashboardData.mockRejectedValueOnce(new Error("API returned 500"));
    mockedFetchDashboardData.mockResolvedValue(demoDashboardData);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Data source error" })).toBeInTheDocument();
    expect(screen.getByText("API returned 500")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByRole("heading", { name: "Mixed Transition" })).toBeInTheDocument();
  });
});

it("renders unavailable measurements and does not invent a previous yield curve", async () => {
  mockedFetchDashboardData.mockResolvedValue({
    ...demoDashboardData,
    sourceMode: "api",
    performanceSeries: [], historicalRegimes: [], breadth: [], sectors: [], indices: [], volatility: [],
    rates: { fedFundsRate: null, cpiYoY: null, unemploymentRate: null, tenTwoSpread: null,
      points: [{ maturity: "10Y", years: 10, yield: 3.33 }] }
  });
  render(<App />);
  expect(await screen.findByText("Performance chart unavailable")).toBeInTheDocument();
  expect(screen.getByText("Regime history unavailable")).toBeInTheDocument();
  expect(screen.getByText("Sector heatmap unavailable")).toBeInTheDocument();
  expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  const yieldChart = screen.getByRole("img", { name: "Treasury yield curve" });
  expect(yieldChart.querySelectorAll("polyline")).toHaveLength(1);
});
