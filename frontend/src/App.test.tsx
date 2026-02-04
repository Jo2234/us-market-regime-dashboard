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
  it("renders stale, partial, and optional-provider status states", async () => {
    mockedFetchDashboardData.mockResolvedValue(demoDashboardData);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Mixed Transition" })).toBeInTheDocument();
    expect(screen.getByText("Partial freshness")).toBeInTheDocument();
    expect(screen.getByText("Partial snapshot: at least one feed is delayed or missing latest observations.")).toBeInTheDocument();
    expect(screen.getByText("Optional provider not configured: CBOE VIX direct feed.")).toBeInTheDocument();
    expect(screen.getByText("Optional provider not configured: premium options sentiment.")).toBeInTheDocument();
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
