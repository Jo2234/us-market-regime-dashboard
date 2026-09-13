import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDashboardData } from "./api";
import App from "./App";
import { demoDashboardData } from "./demoData";

vi.mock("./api", () => ({
  fetchDashboardData: vi.fn(),
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
    { mode: "mixed" as const, label: "Mixed sources" },
  ])(
    "renders $label independently of API transport",
    async ({ mode, label }) => {
      mockedFetchDashboardData.mockResolvedValue({
        ...demoDashboardData,
        sourceMode: "api",
        apiBaseUrl: "/api",
        provenance: { ...demoDashboardData.provenance!, mode },
      });
      render(<App />);
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
      expect(screen.getByText("API: /api")).toBeInTheDocument();
      expect(screen.queryByText(/^live$/i)).not.toBeInTheDocument();
    },
  );

  it("renders stale, partial, and optional-provider status states", async () => {
    mockedFetchDashboardData.mockResolvedValue(demoDashboardData);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Mixed Transition" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Partial freshness")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Partial snapshot: at least one feed is delayed or missing latest observations.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Optional provider not configured: CBOE VIX direct feed.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Optional provider not configured: premium options sentiment.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Data provenance")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Historical Regime Scores" }),
    ).toBeInTheDocument();
  });

  it("shows an explicit fallback when freshness metadata is missing", async () => {
    mockedFetchDashboardData.mockResolvedValue({
      ...demoDashboardData,
      freshness: [],
      errors: [],
      optionalProvidersMissing: [],
      stale: false,
      partial: false,
    });

    render(<App />);

    expect(
      await screen.findByText("No source dates returned"),
    ).toBeInTheDocument();
  });

  it("renders a fatal source error and recovers on retry", async () => {
    mockedFetchDashboardData.mockRejectedValueOnce(
      new Error("API returned 500"),
    );
    mockedFetchDashboardData.mockResolvedValue(demoDashboardData);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Data source error" }),
    ).toBeInTheDocument();
    expect(screen.getByText("API returned 500")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(
      await screen.findByRole("heading", { name: "Mixed Transition" }),
    ).toBeInTheDocument();
  });
});

it("renders unavailable measurements and does not invent a previous yield curve", async () => {
  mockedFetchDashboardData.mockResolvedValue({
    ...demoDashboardData,
    sourceMode: "api",
    performanceSeries: [],
    historicalRegimes: [],
    breadth: [],
    sectors: [],
    indices: [],
    volatility: [],
    rates: {
      fedFundsRate: null,
      cpiYoY: null,
      unemploymentRate: null,
      tenTwoSpread: null,
      points: [{ maturity: "10Y", years: 10, yield: 3.33 }],
    },
  });
  render(<App />);
  expect(
    await screen.findByText("Performance chart unavailable"),
  ).toBeInTheDocument();
  expect(screen.getByText("Regime history unavailable")).toBeInTheDocument();
  expect(screen.getByText("Sector heatmap unavailable")).toBeInTheDocument();
  expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  const yieldChart = screen.getByRole("img", { name: "Treasury yield curve" });
  expect(yieldChart.querySelectorAll("polyline")).toHaveLength(1);
});

it("keeps period and series controls available when chart observations are missing", async () => {
  mockedFetchDashboardData.mockImplementation(async (_date, range) => ({
    ...demoDashboardData,
    performanceSeries:
      range === "1M" ? [] : demoDashboardData.performanceSeries,
  }));
  render(<App />);
  expect(
    await screen.findByText("Performance chart unavailable"),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "3M" }));
  expect(
    await screen.findByRole("img", { name: "Indexed performance chart" }),
  ).toBeInTheDocument();
  expect(mockedFetchDashboardData).toHaveBeenLastCalledWith(
    demoDashboardData.selectedDate,
    "3M",
  );
  for (const name of ["QQQ", "IWM", "DIA"]) {
    await userEvent.click(screen.getByRole("button", { name }));
  }
  await userEvent.click(screen.getByRole("button", { name: "SPY" }));
  expect(screen.getByRole("button", { name: "SPY" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(
    screen
      .getByRole("img", { name: "Indexed performance chart" })
      .querySelectorAll("polyline"),
  ).toHaveLength(1);
});

it("filters rule evidence by category and restores every signal", async () => {
  mockedFetchDashboardData.mockResolvedValue(demoDashboardData);
  render(<App />);
  const category = await screen.findByRole("combobox", { name: "Category" });
  await userEvent.selectOptions(category, "rates");
  expect(document.querySelectorAll(".signal-table tbody tr")).toHaveLength(
    demoDashboardData.signals.filter((signal) => signal.category === "rates")
      .length,
  );
  await userEvent.selectOptions(category, "all");
  expect(document.querySelectorAll(".signal-table tbody tr")).toHaveLength(
    demoDashboardData.signals.length,
  );
});

it("makes a single stored history observation visible without implying a trend", async () => {
  mockedFetchDashboardData.mockResolvedValue({
    ...demoDashboardData,
    historicalRegimes: demoDashboardData.historicalRegimes!.slice(0, 1),
  });
  render(<App />);
  const chart = await screen.findByRole("img", {
    name: "Historical regime scores chart",
  });
  expect(chart.querySelectorAll("circle")).toHaveLength(4);
  expect(
    screen.getByText(/a trend needs at least two observations/i),
  ).toBeInTheDocument();
});
