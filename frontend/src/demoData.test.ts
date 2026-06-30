import { describe, expect, it } from "vitest";
import { demoDashboardData } from "./demoData";
import { ranges } from "./utils";

describe("demo dashboard data", () => {
  it("covers required market dashboard sections", () => {
    expect(demoDashboardData.indices.map((item) => item.symbol)).toEqual(["SPY", "QQQ", "IWM", "DIA"]);
    expect(demoDashboardData.sectors).toHaveLength(11);
    expect(demoDashboardData.rates.points.length).toBeGreaterThanOrEqual(5);
    expect(demoDashboardData.commodities.length).toBeGreaterThanOrEqual(3);
    expect(demoDashboardData.volatility.length).toBeGreaterThanOrEqual(1);
    expect(demoDashboardData.signals.length).toBeGreaterThanOrEqual(6);
    expect(demoDashboardData.historicalRegimes?.length).toBeGreaterThanOrEqual(6);
    expect(demoDashboardData.provenance?.sources).toContain("demo_seed ETF closes");
    expect(demoDashboardData.analystNote.bullets.length).toBeGreaterThanOrEqual(5);
  });

  it("has heatmap returns for every selectable range", () => {
    for (const sector of demoDashboardData.sectors) {
      expect(Object.keys(sector.returns)).toEqual(ranges);
    }
  });
});
