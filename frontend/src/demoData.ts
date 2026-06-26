import type { DashboardData } from "./types";

export const demoDashboardData: DashboardData = {
  generatedAt: "2026-06-25T08:30:00-04:00",
  selectedDate: "2026-06-24",
  sourceMode: "demo",
  apiBaseUrl: null,
  stale: true,
  partial: true,
  optionalProvidersMissing: ["CBOE VIX direct feed", "premium options sentiment"],
  errors: ["Backend API unavailable; rendering deterministic demo snapshot."],
  freshness: [
    { name: "ETF prices", latestDate: "2026-06-24", status: "fresh", lagDays: 1, note: "Stooq/Yahoo proxy feed" },
    { name: "FRED macro", latestDate: "2026-06-01", status: "stale", lagDays: 24, note: "Monthly CPI and unemployment cadence" },
    { name: "CBOE volatility", latestDate: null, status: "no_key", lagDays: null, note: "Optional provider not configured" },
    { name: "Commodities", latestDate: "2026-06-23", status: "partial", lagDays: 2, note: "Copper proxy missing latest close" }
  ],
  regime: {
    label: "mixed_transition",
    displayLabel: "Mixed Transition",
    confidence: "medium",
    asOf: "2026-06-24",
    riskScore: 58,
    growthScore: 64,
    inflationScore: 54,
    ratesPressureScore: 61,
    changedSincePrevious: "Rates pressure increased as the 2Y and 10Y both moved higher while small caps lagged.",
    positiveSignals: [
      "S&P 500 remains above its 50-day moving average.",
      "Nasdaq 100 is outperforming the S&P 500 over one month.",
      "VIX remains below its 3-month average."
    ],
    negativeSignals: [
      "Russell 2000 is lagging large caps over one month.",
      "10Y Treasury yield is up 22 bps over the month.",
      "Energy and copper strength keep inflation pressure elevated."
    ],
    limitations: [
      "CBOE direct volatility data is using a proxy in demo mode.",
      "Macro indicators update monthly and may lag market prices."
    ]
  },
  indices: [
    { symbol: "SPY", name: "S&P 500", price: 642.18, dayReturn: 0.42, monthReturn: 3.28, ytdReturn: 9.84, oneYearReturn: 14.21, drawdown52w: -2.8, volatility20d: 11.6 },
    { symbol: "QQQ", name: "Nasdaq 100", price: 548.62, dayReturn: 0.68, monthReturn: 4.91, ytdReturn: 12.44, oneYearReturn: 18.76, drawdown52w: -1.9, volatility20d: 14.3 },
    { symbol: "IWM", name: "Russell 2000", price: 218.77, dayReturn: -0.16, monthReturn: 0.74, ytdReturn: 3.26, oneYearReturn: 7.14, drawdown52w: -7.6, volatility20d: 18.9 },
    { symbol: "DIA", name: "Dow Industrials", price: 459.35, dayReturn: 0.21, monthReturn: 2.16, ytdReturn: 6.72, oneYearReturn: 10.58, drawdown52w: -3.5, volatility20d: 10.8 }
  ],
  sectors: [
    { symbol: "XLK", name: "Technology", relativeToSpy1m: 1.18, returns: { "1D": 0.86, "1W": 1.92, "1M": 4.46, "3M": 8.7, YTD: 15.4, "1Y": 24.9 } },
    { symbol: "XLF", name: "Financials", relativeToSpy1m: -0.22, returns: { "1D": 0.18, "1W": 0.74, "1M": 3.06, "3M": 5.8, YTD: 8.2, "1Y": 13.1 } },
    { symbol: "XLE", name: "Energy", relativeToSpy1m: 0.58, returns: { "1D": 1.12, "1W": 2.38, "1M": 3.86, "3M": 6.4, YTD: 10.3, "1Y": 11.8 } },
    { symbol: "XLV", name: "Health Care", relativeToSpy1m: -1.64, returns: { "1D": -0.12, "1W": -0.28, "1M": 1.64, "3M": 1.9, YTD: 2.7, "1Y": 4.3 } },
    { symbol: "XLY", name: "Cons. Disc.", relativeToSpy1m: 0.34, returns: { "1D": 0.51, "1W": 1.24, "1M": 3.62, "3M": 7.1, YTD: 11.2, "1Y": 17.6 } },
    { symbol: "XLP", name: "Staples", relativeToSpy1m: -2.26, returns: { "1D": -0.08, "1W": -0.52, "1M": 1.02, "3M": 0.8, YTD: 1.9, "1Y": 5.1 } },
    { symbol: "XLI", name: "Industrials", relativeToSpy1m: -0.72, returns: { "1D": 0.14, "1W": 0.48, "1M": 2.56, "3M": 4.2, YTD: 6.4, "1Y": 10.9 } },
    { symbol: "XLB", name: "Materials", relativeToSpy1m: -1.18, returns: { "1D": 0.24, "1W": 0.18, "1M": 2.1, "3M": 2.9, YTD: 4.8, "1Y": 7.3 } },
    { symbol: "XLU", name: "Utilities", relativeToSpy1m: -1.92, returns: { "1D": -0.35, "1W": -0.76, "1M": 1.36, "3M": 2.4, YTD: 5.2, "1Y": 9.7 } },
    { symbol: "XLRE", name: "Real Estate", relativeToSpy1m: -2.74, returns: { "1D": -0.44, "1W": -1.16, "1M": 0.54, "3M": -0.8, YTD: -1.4, "1Y": 1.6 } },
    { symbol: "XLC", name: "Comm. Svcs.", relativeToSpy1m: 0.92, returns: { "1D": 0.73, "1W": 1.58, "1M": 4.2, "3M": 8.1, YTD: 13.8, "1Y": 20.4 } }
  ],
  performanceSeries: [
    { date: "2026-05-24", SPY: 100, QQQ: 100, IWM: 100, DIA: 100 },
    { date: "2026-05-31", SPY: 100.8, QQQ: 101.2, IWM: 99.4, DIA: 100.2 },
    { date: "2026-06-07", SPY: 101.9, QQQ: 102.6, IWM: 99.8, DIA: 101.1 },
    { date: "2026-06-14", SPY: 102.7, QQQ: 103.9, IWM: 100.3, DIA: 101.7 },
    { date: "2026-06-21", SPY: 103.0, QQQ: 104.4, IWM: 100.5, DIA: 102.0 },
    { date: "2026-06-24", SPY: 103.28, QQQ: 104.91, IWM: 100.74, DIA: 102.16 }
  ],
  rates: {
    fedFundsRate: 4.62,
    cpiYoY: 3.1,
    unemploymentRate: 4.0,
    tenTwoSpread: -0.22,
    points: [
      { maturity: "3M", years: 0.25, yield: 4.88, previousYield: 4.86 },
      { maturity: "2Y", years: 2, yield: 4.28, previousYield: 4.12 },
      { maturity: "5Y", years: 5, yield: 4.12, previousYield: 3.98 },
      { maturity: "10Y", years: 10, yield: 4.06, previousYield: 3.84 },
      { maturity: "30Y", years: 30, yield: 4.38, previousYield: 4.2 }
    ]
  },
  commodities: [
    { symbol: "USO", name: "Crude oil proxy", value: 83.42, dayChange: 1.28, monthReturn: 6.4, signal: "Inflation-sensitive tailwind" },
    { symbol: "GLD", name: "Gold", value: 221.16, dayChange: 0.34, monthReturn: 2.7, signal: "Risk hedge bid intact" },
    { symbol: "CPER", name: "Copper", value: 28.94, dayChange: -0.18, monthReturn: 5.1, signal: "Growth and inflation confirmation" }
  ],
  volatility: [
    { symbol: "VIX", name: "CBOE VIX proxy", value: 14.8, dayChange: -0.42, monthReturn: -8.6, signal: "Complacency below 3M average" },
    { symbol: "SPY RV20", name: "20D realized vol", value: 11.6, dayChange: 0.2, monthReturn: -1.9, signal: "Realized volatility contained" }
  ],
  breadth: [
    { symbol: "SPX>50D", name: "S&P 500 above 50D", value: 63, dayChange: 1.1, monthReturn: 7.4, signal: "Positive but not broad risk-on" },
    { symbol: "RSP/SPY", name: "Equal weight relative", value: 94.2, dayChange: -0.1, monthReturn: -1.3, signal: "Narrow leadership" }
  ],
  signals: [
    { name: "S&P 500 vs 50D MA", category: "risk", value: "+3.2%", direction: "positive", weight: 0.18, evidence: "SPY remains above trend." },
    { name: "Nasdaq vs S&P 500 1M", category: "growth", value: "+1.6 pp", direction: "positive", weight: 0.14, evidence: "Growth leadership is still present." },
    { name: "Russell 2000 vs S&P 500 1M", category: "growth", value: "-2.5 pp", direction: "negative", weight: 0.12, evidence: "Small caps are not confirming broad risk appetite." },
    { name: "VIX vs 3M average", category: "volatility", value: "-2.1 pts", direction: "positive", weight: 0.12, evidence: "Volatility is below its recent average." },
    { name: "10Y yield 1M change", category: "rates", value: "+22 bps", direction: "negative", weight: 0.16, evidence: "Long yields are rising fast enough to pressure duration." },
    { name: "Oil 1M return", category: "inflation", value: "+6.4%", direction: "negative", weight: 0.1, evidence: "Energy is adding to inflation-sensitive signals." },
    { name: "Defensives vs cyclicals", category: "risk", value: "-1.9 pp", direction: "positive", weight: 0.09, evidence: "Defensives are lagging cyclical groups." },
    { name: "Yield curve 10Y-2Y", category: "rates", value: "-22 bps", direction: "neutral", weight: 0.09, evidence: "Curve remains inverted but less deeply than last quarter." }
  ],
  analystNote: {
    title: "Market tone is constructive but rate-sensitive.",
    bullets: [
      "Large-cap growth is leading: QQQ is up 4.91% over one month versus 3.28% for SPY.",
      "Sector leadership is cyclical and technology-heavy, while staples, utilities, and real estate trail.",
      "Rates are the main counterweight: the 10Y yield rose to 4.06% and the 10Y-2Y spread remains inverted at -22 bps.",
      "Commodity proxies are firm, led by oil and copper, keeping inflation pressure from falling into the background.",
      "Volatility remains contained, but breadth is only moderate because small caps and equal weight lag."
    ],
    watchItems: [
      "Whether Russell 2000 relative performance improves.",
      "Whether 10Y yields keep rising alongside technology leadership.",
      "Whether energy strength passes through to inflation expectations."
    ]
  }
};
