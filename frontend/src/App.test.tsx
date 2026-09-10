import { act, cleanup, render, screen, fireEvent } from "@testing-library/react";
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
      await screen.findByRole("heading", { name: "Mixed transition" }),
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
      screen.getByRole("heading", { name: "Historical regime scores" }),
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
      await screen.findByRole("heading", { name: "Mixed transition" }),
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
  const label = mode === "live" ? "Live · Yahoo Finance · as of Sep 28, 2026" : "Snapshot · as of Sep 28, 2026";
  expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
  expect(screen.getByText(/Official FRED Treasury/)).toBeInTheDocument();
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
  expect(screen.getAllByText("Live · Yahoo Finance · as of Sep 28, 2026").length).toBeGreaterThan(0);
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
  expect(screen.getByText(/Showing close of Sep 28, 2026; live refresh unavailable/)).toBeInTheDocument();
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

it("renders dated FRED cards, retains snapshot values and isolates unavailable cards", async () => {
  mockedFetchDashboardData.mockResolvedValue({
    ...demoDashboardData,
    macro: {
      FEDFUNDS: { value: 3.88, source: "fred", fred_series_id: "DFF", observation_label: "2026-09-25", mode: "live" },
      FEDFUNDS_MONTHLY: { value: 3.63, observation_label: "Aug 2026", mode: "snapshot" },
      CPI_YOY: { value: 3.353, source: "fred", observation_label: "Aug 2026", mode: "snapshot" },
      CORE_CPI_YOY: null,
      UNRATE: { value: 4.1, observation_label: "Aug 2026", mode: "live" },
    },
  });
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Macro indicators" })).toBeInTheDocument();
  expect(screen.getByText("3.88%")).toBeInTheDocument();
  expect(screen.getByText("Sep 25, 2026")).toBeInTheDocument();
  expect(screen.getByText("3.35%")).toBeInTheDocument();
  expect(screen.getByText("Snapshot · Aug 2026; live refresh unavailable, retrying.")).toBeInTheDocument();
  expect(screen.getByText("Unavailable")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "FRED: DFF" })).toHaveAttribute("href", "https://fred.stlouisfed.org/series/DFF");
  expect(screen.getByRole("button", { name: "Refresh macro data" })).toBeEnabled();
  expect(screen.getByRole("heading", { name: "Yield curve" })).toBeInTheDocument();
});

it("keeps FRED cards visible and busy during background refresh", async () => {
  mockedFetchDashboardData.mockImplementation((_date, _range, options) => {
    options?.onCached?.({ ...demoDashboardData, macro: { FEDFUNDS: { value: 3.88, observation_label: "2026-09-25", mode: "snapshot" } } });
    return new Promise(() => {});
  });
  render(<App />);
  expect(await screen.findByText("3.88%")).toBeInTheDocument();
  expect(screen.getByText("Updating macro observations…")).toBeInTheDocument();
  expect(screen.getByRole("article", { name: "Macro indicators" })).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("button", { name: "Refresh macro data" })).toBeDisabled();
});

it("polls live quotes each minute, pauses hidden tabs and resumes on visibility", async () => {
  vi.useFakeTimers();
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData,
    marketStatus: { is_open: true, session_date: "2026-09-29", refresh_seconds: 60, next_open: "2026-09-30" },
    quoteStatus: { cache: "hit", refresh_seconds: 60 }, intraday: true,
    provenance: { ...demoDashboardData.provenance!, mode: "live" } });
  render(<App />);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(screen.getByText("Market open · Live intraday")).toBeInTheDocument();
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  document.dispatchEvent(new Event("visibilitychange"));
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(3);
});


it("inspects all four historical scores and opens the selected snapshot", async () => {
  const points = demoDashboardData.historicalRegimes!;
  mockedFetchDashboardData.mockResolvedValue(demoDashboardData);
  render(<App />);
  const slider = await screen.findByRole("slider", { name: "Historical regime date" });
  const chart = screen.getByRole("img", { name: "Historical regime scores chart" });
  expect(chart.querySelectorAll(".score-line")).toHaveLength(4);
  expect(chart.querySelectorAll(".score-panel")).toHaveLength(4);
  expect(chart.querySelectorAll(".regime-strip").length).toBeGreaterThan(0);
  expect(screen.getByRole("checkbox", { name: "5-day smoothing" })).not.toBeChecked();
  fireEvent.change(slider, { target: { value: "0" } });
  const tooltip = document.querySelector(".history-tooltip")!;
  expect(tooltip.textContent).toContain(points[0].displayLabel);
  expect(tooltip.textContent).toContain(`Risk ${points[0].riskScore}`);
  HTMLElement.prototype.scrollIntoView = vi.fn();
  await userEvent.click(screen.getByRole("button", { name: /View snapshot/ }));
  expect(mockedFetchDashboardData).toHaveBeenLastCalledWith(points[0].date, "1M", expect.any(Object));
});


it("fetches once on an initially hidden tab and resumes only when refresh is due", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData,
    marketStatus: { is_open: true, session_date: "2026-09-29", refresh_seconds: 60, next_open: "2026-09-30" },
    provenance: { ...demoDashboardData.provenance!, mode: "live" } });
  render(<App />);
  await act(async () => {});
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Market overview")).toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  await act(async () => { await vi.advanceTimersByTimeAsync(90_000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
});

it("arms the slow-loading notice even when the initial tab is hidden", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  mockedFetchDashboardData.mockImplementation(() => new Promise(() => {}));
  render(<App />);
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status")).toHaveTextContent("Still fetching");
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});


it("smooths only display paths and keeps classifications and inspector scores unchanged", async () => {
  mockedFetchDashboardData.mockResolvedValue(demoDashboardData);
  render(<App />);
  const toggle = await screen.findByRole("checkbox", { name: "5-day smoothing" });
  const path = document.querySelector(".score-line")!;
  expect(path.getAttribute("d")).toContain("H ");
  const inspector = document.querySelector(".history-tooltip")!.textContent;
  const strips = document.querySelectorAll(".regime-strip").length;
  await userEvent.click(toggle);
  expect(path.getAttribute("d")).toContain("L ");
  expect(path.getAttribute("d")).not.toContain("H ");
  expect(document.querySelector(".history-tooltip")!.textContent).toBe(inspector);
  expect(document.querySelectorAll(".regime-strip")).toHaveLength(strips);
  expect(screen.getByText(/for display only; classifications and inspector scores are unchanged/)).toBeInTheDocument();
});

it("merges update times and shows formatted values with raw tooltips and named evidence", async () => {
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData,
    fetchedAt: new Date().toISOString(),
    regime: { ...demoDashboardData.regime, positiveSignals: ["Nasdaq 100 outperforming S&P 500 (1M)"] },
    signals: [{ name: "Nasdaq 100 outperforming S&P 500 (1M)", value: "0.035311", displayValue: "+3.53 pp", rawUnit: "return fraction difference", category: "growth", direction: "positive", weight: 1, evidence: "QQQ outperformed SPY by 3.53 percentage points." }],
  });
  render(<App />);
  expect(await screen.findByText("+3.53 pp")).toHaveAttribute("title", "Raw: 0.035311 return fraction difference");
  expect(document.querySelector(".updated-age")?.textContent).toMatch(/Updated .* ago \(.*\)/);
  expect(document.querySelector(".refresh-status")?.textContent).not.toContain("Last updated");
  expect(document.querySelector(".mini-list strong")?.textContent).toBe("Nasdaq 100 outperforming S&P 500 (1M)");
  expect(document.querySelector(".mini-list li span")?.textContent).toBe("QQQ outperformed SPY by 3.53 percentage points.");
});

it("treats a fresh scheduled artifact as normal and avoids failure retries", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData, scheduledFresh:true,
    provenance:{...demoDashboardData.provenance!,mode:"snapshot"},
    marketStatus:{is_open:false,session_date:"2026-09-30",refresh_seconds:900,next_open:"2026-10-01"}});
  render(<App/>);
  await act(async()=>{await Promise.resolve();});
  await act(async()=>{vi.advanceTimersByTime(60_000);});
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/live refresh unavailable, retrying/i)).not.toBeInTheDocument();
});

it("shows pending research and stale dates without a false failure banner or fast retry", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData, scheduledFresh: true, stale: true, partial: true,
    selectedDate: "2026-10-02", provenance: { ...demoDashboardData.provenance!, mode: "snapshot" },
    artifactDelivery: { status: "pending", fresh: true, view: "latest", as_of: "2026-10-02", expected_session: "2026-10-05", delivery_deadline: "2026-10-05T22:00:00Z" },
    freshness: [{ name: "Equity indices", latestDate: "2026-10-02", status: "stale", lagDays: 3, deliveryState: "pending" }],
    marketStatus: { is_open: false, session_date: "2026-10-05", refresh_seconds: 900, next_open: "2026-10-06" },
  });
  render(<App />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText("Awaiting scheduled delivery")).toBeInTheDocument();
  expect(screen.getByText(/Awaiting scheduled research snapshot for Oct 5, 2026/)).toHaveTextContent("Showing Oct 2, 2026 observations");
  expect(screen.getByText("Stale · Awaiting scheduled delivery")).toBeInTheDocument();
  expect(screen.getByText("Previous completed daily close · awaiting research delivery")).toBeInTheDocument();
  expect(screen.queryByText("Partial snapshot: at least one feed is delayed or missing latest observations.")).not.toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(60_000); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(1);
});

it("warns research is overdue while continuing minute intraday quote polling", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData, scheduledFresh: false, intraday: true,
    retryAfterSeconds: 900, selectedDate: "2026-10-02", provenance: { ...demoDashboardData.provenance!, mode: "snapshot" },
    artifactDelivery: { status: "overdue", fresh: false, view: "latest", as_of: "2026-10-02", expected_session: "2026-10-05", delivery_deadline: "2026-10-05T22:00:00Z" },
    marketStatus: { is_open: true, session_date: "2026-10-06", refresh_seconds: 60, next_open: "2026-10-07" },
    quoteStatus: { cache: "hit", refresh_seconds: 60 },
  });
  render(<App />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText("Research overdue")).toBeInTheDocument();
  expect(screen.getByText(/Research update overdue. Latest completed session: Oct 5, 2026/)).toHaveTextContent("Showing Oct 2, 2026 observations");
  expect(screen.queryByText(/live refresh unavailable, retrying automatically/)).not.toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
  expect(mockedFetchDashboardData).toHaveBeenCalledTimes(2);
});

it("labels historical view separately from latest artifact delivery", async () => {
  mockedFetchDashboardData.mockResolvedValue({ ...demoDashboardData,
    artifactDelivery: { status: "pending", view: "historical", requested_date: "2026-09-15" },
  });
  render(<App />);
  expect(await screen.findByText("Historical snapshot")).toBeInTheDocument();
  expect(screen.getByText("Latest stored artifact source dates · Historical prices use the selected snapshot.")).toBeInTheDocument();
  expect(screen.queryByText(/Awaiting scheduled research snapshot for/)).not.toBeInTheDocument();
});
