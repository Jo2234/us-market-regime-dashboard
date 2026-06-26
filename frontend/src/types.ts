export type RangeKey = "1D" | "1W" | "1M" | "3M" | "YTD" | "1Y";

export type FreshnessStatus = "fresh" | "stale" | "partial" | "error" | "no_key";

export interface FreshnessSource {
  name: string;
  latestDate: string | null;
  status: FreshnessStatus;
  lagDays: number | null;
  note?: string;
}

export interface RegimeSnapshot {
  label: string;
  displayLabel: string;
  confidence: "low" | "medium" | "high";
  asOf: string;
  riskScore: number;
  growthScore: number;
  inflationScore: number;
  ratesPressureScore: number;
  changedSincePrevious: string;
  positiveSignals: string[];
  negativeSignals: string[];
  limitations: string[];
}

export interface IndexReturn {
  symbol: string;
  name: string;
  price: number;
  dayReturn: number;
  monthReturn: number;
  ytdReturn: number;
  oneYearReturn: number;
  drawdown52w: number;
  volatility20d: number;
}

export interface SectorPerformance {
  symbol: string;
  name: string;
  relativeToSpy1m: number;
  returns: Record<RangeKey, number>;
}

export interface ChartPoint {
  date: string;
  SPY: number;
  QQQ: number;
  IWM: number;
  DIA: number;
}

export interface YieldPoint {
  maturity: string;
  years: number;
  yield: number;
  previousYield: number;
}

export interface RatesSummary {
  fedFundsRate: number;
  cpiYoY: number;
  unemploymentRate: number;
  tenTwoSpread: number;
  points: YieldPoint[];
}

export interface RiskAssetMetric {
  symbol: string;
  name: string;
  value: number;
  dayChange: number;
  monthReturn: number;
  signal: string;
}

export interface RegimeSignal {
  name: string;
  category: "risk" | "growth" | "inflation" | "rates" | "volatility";
  value: string;
  direction: "positive" | "negative" | "neutral";
  weight: number;
  evidence: string;
}

export interface AnalystNote {
  title: string;
  bullets: string[];
  watchItems: string[];
}

export interface DashboardData {
  generatedAt: string;
  selectedDate: string;
  sourceMode: "api" | "demo";
  apiBaseUrl: string | null;
  stale: boolean;
  partial: boolean;
  optionalProvidersMissing: string[];
  errors: string[];
  freshness: FreshnessSource[];
  regime: RegimeSnapshot;
  indices: IndexReturn[];
  sectors: SectorPerformance[];
  performanceSeries: ChartPoint[];
  rates: RatesSummary;
  commodities: RiskAssetMetric[];
  volatility: RiskAssetMetric[];
  breadth: RiskAssetMetric[];
  signals: RegimeSignal[];
  analystNote: AnalystNote;
}
