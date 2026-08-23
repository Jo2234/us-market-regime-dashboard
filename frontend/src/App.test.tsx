import { act, cleanup, render, screen } from "@testing-library/react";
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
  vi.useRealTimers();
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
      await screen.findByRole("heading", { name: "Live data unavailable" }),
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
    "",
    "3M",
    expect.objectContaining({ signal: expect.any(AbortSignal), onCached: expect.any(Function) }),
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

it.each(["live", "snapshot"] as const)("renders the %s chip with the real date", async mode => {
  mockedFetchDashboardData.mockResolvedValue({
    ...demoDashboardData,
    sourceMode: "api",
    selectedDate: "2026-09-28",
    provenance: { ...demoDashboardData.provenance!, mode },
  });
  render(<App />);
  const label = mode === "live" ? "Live · Yahoo Finance · as of 2026-09-28" : "Snapshot · as of 2026-09-28";
  expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
  expect(screen.getByText(/2Y is futures-implied/)).toBeInTheDocument();
});

// Deferred responses exercise the visible intermediate states, not just final HTML.
it("shows the dashboard skeleton and changes the status after four seconds", async () => {
  vi.useFakeTimers();
  mockedFetchDashboardData.mockImplementation(() => new Promise(() => {}));
  render(<App />);
  expect(screen.getByLabelText("Loading market dashboard")).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("status")).toHaveTextContent("Fetching the latest market data from Yahoo Finance");
  await act(async () => { vi.advanceTimersByTime(4000); });
  expect(screen.getByRole("status")).toHaveTextContent("Still fetching, Yahoo can be slow at times");
  expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  vi.useRealTimers();
});

it("renders a real cached snapshot immediately and replaces it after background refresh", async () => {
  let finish!: (value: typeof demoDashboardData) => void;
  const cached = { ...demoDashboardData, sourceMode: "api" as const, fetchedAt: "2026-09-29T13:00:00Z", selectedDate: "2026-09-28", provenance: { ...demoDashboardData.provenance!, mode: "snapshot" as const } };
  mockedFetchDashboardData.mockImplementation((_date, _range, options) => {
    options?.onCached?.(cached);
    return new Promise(resolve => { finish = resolve; });
  });
  render(<App />);
  expect(await screen.findByText("Updating with the latest numbers…")).toBeInTheDocument();
  expect(screen.getByLabelText("Market overview")).toHaveAttribute("aria-busy", "true");
  const live = { ...cached, provenance: { ...cached.provenance, mode: "live" as const } };
  await act(async () => finish(live));
  expect(screen.queryByText("Updating with the latest numbers…")).not.toBeInTheDocument();
  expect(screen.getAllByText("Live · Yahoo Finance · as of 2026-09-28").length).toBeGreaterThan(0);
  expect(screen.getByLabelText("Market overview")).toHaveAttribute("aria-busy", "false");
});

it("retains last data on failure and automatically retries with increasing delays", async () => {
  vi.useFakeTimers();
  const cached = { ...demoDashboardData, sourceMode: "api" as const, selectedDate: "2026-09-28", provenance: { ...demoDashboardData.provenance!, mode: "snapshot" as const } };
  mockedFetchDashboardData.mockImplementation((_date, _range, options) => {
    options?.onCached?.(cached);
    return Promise.reject(new Error("offline"));
  });
  render(<App />);
  await act(async () => {});
  expect(screen.getByText(/Showing close of 2026-09-28; live refresh unavailable/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Refresh data" })).toBeEnabled();
  expect(screen.getByLabelText("Market overview")).toBeInTheDocument();
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(5000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
  await act(async () => { vi.advanceTimersByTime(9999); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
  await act(async () => { vi.advanceTimersByTime(1); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(3);
  vi.useRealTimers();
});

it("respects the server cooldown for a rate-limited snapshot", async () => {
  vi.useFakeTimers();
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData, retryAfterSeconds: 900, provenance: { ...demoDashboardData.provenance!, mode: "snapshot" } });
  render(<App />);
  await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(899_999); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(1); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
