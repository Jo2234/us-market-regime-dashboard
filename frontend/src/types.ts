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
  daysInRegime?: number;
  rawLabel?: string;
  emergingLabel?: string | null;
  emergingDays?: number;
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

export interface DataProvenance {
  mode: "api" | "demo" | "mixed" | "fallback" | "live" | "snapshot";
  observations?: Array<{ symbol: string; name?: string; ticker: string; date: string | null; url?: string; isStale?: boolean }>;
  description: string;
  generatedAt: string;
  selectedDate: string;
  sources: string[];
  freshnessPolicy: string;
}

export interface HistoricalRegimePoint {
  stressScore?: number;
  emergingLabel?: string | null;
  date: string;
  displayLabel: string;
  riskScore: number;
  growthScore: number;
  inflationScore: number;
  ratesPressureScore: number;
  note: string;
}

export interface IndexReturn {
  observationDate?: string;
  symbol: string;
  name: string;
  price: number | null;
  dayReturn: number | null;
  monthReturn: number | null;
  ytdReturn: number | null;
  oneYearReturn: number | null;
  drawdown52w: number | null;
  volatility20d: number | null;
}

export interface SectorPerformance {
  observationDate?: string;
  symbol: string;
  name: string;
  relativeToSpy1m: number | null;
  returns: Record<RangeKey, number | null>;
}

export interface ChartPoint {
  date: string;
  SPY: number;
  QQQ: number;
  IWM: number;
  DIA: number;
}

export interface YieldPoint {
  isStale?: boolean;
  date?: string;
  ticker?: string;
  maturity: string;
  years: number;
  yield: number;
  previousYield?: number;
}

export interface RatesSummary {
  fedFundsRate: number | null;
  cpiYoY: number | null;
  unemploymentRate: number | null;
  tenTwoSpread: number | null;
  points: YieldPoint[];
}

export interface RiskAssetMetric {
  observationDate?: string;
  symbol: string;
  name: string;
  value: number | null;
  dayChange: number | null;
  monthReturn: number | null;
  signal: string;
}

export interface RegimeSignal {
  percentile?: number;
  directionText?: string;
  displayValue?: string;
  rawUnit?: string;
  name: string;
  category: "risk" | "growth" | "inflation" | "rates" | "volatility" | "stress" | "dollar";
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

export interface MacroValue {
  value: number;
  source?: string;
  fred_series_id?: string;
  observation_date?: string;
  observation_label?: string;
  source_url?: string;
  frequency?: string;
  mode?: "live" | "snapshot" | "unavailable";
  scheduled?: boolean;
  fetched_at?: string;
  is_stale?: boolean;
}

export interface DashboardData {
  regimeV2?: RegimeV2;
  scheduledFresh?: boolean;
  marketStatus?: { is_open: boolean; session_date: string; refresh_seconds: number; next_open: string };
  quoteStatus?: { cache?: string; fetched_at?: string; refresh_seconds?: number; retry_after_seconds?: number };
  intraday?: boolean;
  macro?: Record<string, MacroValue | null>;
  fetchedAt?: string;
  cache?: "hit" | "miss" | "stale";
  retryAfterSeconds?: number;
  generatedAt: string;
  selectedDate: string;
  sourceMode: "api" | "demo";
  apiBaseUrl: string | null;
  stale: boolean;
  partial: boolean;
  optionalProvidersMissing: string[];
  errors: string[];
  freshness: FreshnessSource[];
  provenance?: DataProvenance;
  historicalRegimes?: HistoricalRegimePoint[];
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

export interface V2Signal {
 key:string; name:string; axis:string; raw_value:number; unit:string; percentile:number; direction:string;
 held_for_missing_month?:boolean; weight:number; observations:Record<string,string>; available_on:string; baseline_count:number;
}
export interface RegimeV2 {
 date:string; quadrant:string; raw_quadrant:string; stress_label:string; headline:string;
 axis_scores:Record<string,number>; days_in_regime:number; emerging_label:string|null; emerging_days:number;
 confidence:{label:string; score:number; magnitude:number; agreement:number};
 signals:V2Signal[]; driver_sentence:string; nearest_flip_note:string;
 nearest_flips:Array<{key:string; text:string}>;
}
