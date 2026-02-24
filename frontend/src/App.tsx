import { AlertTriangle, BarChart3, CalendarDays, Download, RefreshCw, ServerCrash, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchDashboardData } from "./api";
import type { ChartPoint, DashboardData, FreshnessSource, RangeKey, RegimeSignal, RiskAssetMetric, YieldPoint } from "./types";
import {
  downloadDashboardCsv,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  heatColor,
  performanceClass,
  ranges,
  scoreClass
} from "./utils";

type SeriesKey = Exclude<keyof ChartPoint, "date">;

const seriesColors: Record<SeriesKey, string> = {
  SPY: "#2563eb",
  QQQ: "#7c3aed",
  IWM: "#b45309",
  DIA: "#0f766e"
};

const metricTooltips = {
  spyMonth: "SPY one-month price return for the selected market date.",
  qqqVsSpy: "QQQ one-month return minus SPY one-month return, in percentage points.",
  tenTwo: "10-year Treasury yield minus 2-year Treasury yield, shown in basis points.",
  vix: "Current VIX level; falling VIX is treated as supportive for risk appetite."
};

export default function App() {
  const [range, setRange] = useState<RangeKey>("1M");
  const [selectedDate, setSelectedDate] = useState("");
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchDashboardData(selectedDate, range)
      .then((nextData) => {
        if (!isMounted) return;
        setData(nextData);
        if (!selectedDate) {
          setSelectedDate(nextData.selectedDate);
        }
      })
      .catch((requestError) => {
        if (!isMounted) return;
        setError(requestError instanceof Error ? requestError.message : "Unable to load dashboard data.");
        setData(null);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [range, selectedDate, reloadTick]);

  if (loading && !data) {
    return <LoadingState />;
  }

  if (error && !data) {
    return <FatalErrorState message={error} onRetry={() => setReloadTick((value) => value + 1)} />;
  }

  if (!data) {
    return <EmptyState title="No dashboard data" body="No market snapshot is available for the selected date." />;
  }

  return (
    <main className="app-shell">
      <TopBar
        data={data}
        range={range}
        selectedDate={selectedDate}
        loading={loading}
        onRangeChange={setRange}
        onDateChange={setSelectedDate}
        onRefresh={() => setReloadTick((value) => value + 1)}
        onExport={() => downloadDashboardCsv(data)}
      />

      <StatusStrip data={data} error={error} />

      <section className="dashboard-grid first-row">
        <RegimeCard data={data} />
        <MarketSummary data={data} />
        <IndexCards data={data} />
      </section>

      <section className="dashboard-grid second-row">
        <SectorHeatmap data={data} />
        <PerformanceChart data={data} />
      </section>

      <section className="dashboard-grid third-row">
        <YieldCurvePanel data={data} />
        <RiskPanel title="Commodities" items={data.commodities} />
        <RiskPanel title="Volatility & Breadth" items={[...data.volatility, ...data.breadth]} />
      </section>

      <section className="dashboard-grid fourth-row">
        <SignalTable signals={data.signals} />
        <AnalystNote data={data} />
      </section>
    </main>
  );
}

function TopBar({
  data,
  range,
  selectedDate,
  loading,
  onRangeChange,
  onDateChange,
  onRefresh,
  onExport
}: {
  data: DashboardData;
  range: RangeKey;
  selectedDate: string;
  loading: boolean;
  onRangeChange: (range: RangeKey) => void;
  onDateChange: (date: string) => void;
  onRefresh: () => void;
  onExport: () => void;
}) {
  const freshnessLabel = summarizeFreshness(data.freshness);

  return (
    <header className="top-bar">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <BarChart3 size={18} />
        </div>
        <div>
          <h1>US Market Regime</h1>
          <p>{data.sourceMode === "api" ? `API: ${data.apiBaseUrl}` : "Demo fallback data"}</p>
        </div>
      </div>

      <div className="top-controls">
        <div className={`freshness-pill ${freshnessLabel.className}`} title="Latest available source status">
          {freshnessLabel.text}
        </div>
        <label className="date-control">
          <CalendarDays size={15} />
          <input type="date" value={selectedDate} onChange={(event) => onDateChange(event.target.value)} />
        </label>
        <div className="segmented" aria-label="Selected return range">
          {ranges.map((item) => (
            <button key={item} className={item === range ? "active" : ""} type="button" onClick={() => onRangeChange(item)}>
              {item}
            </button>
          ))}
        </div>
        <button className="icon-button" type="button" onClick={onRefresh} title="Refresh data" aria-label="Refresh data">
          <RefreshCw size={16} className={loading ? "spinning" : ""} />
        </button>
        <button className="command-button" type="button" onClick={onExport}>
          <Download size={16} />
          CSV
        </button>
      </div>
    </header>
  );
}

function StatusStrip({ data, error }: { data: DashboardData; error: string | null }) {
  const items = [
    ...data.errors.map((message) => ({ kind: "error", message })),
    ...(error ? [{ kind: "error", message: error }] : []),
    ...(data.stale ? [{ kind: "stale", message: "Some source data is stale relative to the selected market date." }] : []),
    ...(data.partial ? [{ kind: "partial", message: "Partial snapshot: at least one feed is delayed or missing latest observations." }] : []),
    ...data.optionalProvidersMissing.map((provider) => ({
      kind: "no-key",
      message: `Optional provider not configured: ${provider}.`
    }))
  ];

  return (
    <section className="status-strip" aria-label="Dashboard data status">
      <div className="source-grid">
        {data.freshness.length > 0 ? (
          data.freshness.map((source) => <FreshnessBadge key={source.name} source={source} />)
        ) : (
          <div className="source-badge empty-source" title="The API did not return source freshness metadata.">
            <span>Data freshness</span>
            <strong>No source dates returned</strong>
          </div>
        )}
      </div>
      {items.length > 0 && (
        <div className="banner-list">
          {items.map((item, index) => (
            <div className={`status-banner ${item.kind}`} key={`${item.kind}-${index}`} role="status">
              {item.kind === "error" ? <ServerCrash size={16} /> : item.kind === "no-key" ? <WifiOff size={16} /> : <AlertTriangle size={16} />}
              <span>{item.message}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function FreshnessBadge({ source }: { source: FreshnessSource }) {
  return (
    <div className={`source-badge ${source.status}`} title={source.note}>
      <span>{source.name}</span>
      <strong>{formatDate(source.latestDate)}</strong>
    </div>
  );
}

function RegimeCard({ data }: { data: DashboardData }) {
  const scores = [
    ["Risk", data.regime.riskScore],
    ["Growth", data.regime.growthScore],
    ["Inflation", data.regime.inflationScore],
    ["Rates", data.regime.ratesPressureScore]
  ] as const;

  return (
    <article className="panel regime-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Regime</span>
          <h2>{data.regime.displayLabel}</h2>
        </div>
        <span className={`confidence ${data.regime.confidence}`}>{data.regime.confidence}</span>
      </div>
      <p className="regime-change">{data.regime.changedSincePrevious}</p>
      <div className="score-grid">
        {scores.map(([label, value]) => (
          <div className="score-item" key={label} title={`${label} score from transparent regime rules`}>
            <div className="score-top">
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
            <div className="score-track">
              <span className={scoreClass(value)} style={{ width: `${value}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="signal-split">
        <SignalList title="Support" items={data.regime.positiveSignals} />
        <SignalList title="Pressure" items={data.regime.negativeSignals} />
      </div>
    </article>
  );
}

function SignalList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return <EmptyState title={title} body="No signals available." compact />;
  }

  return (
    <div className="mini-list">
      <h3>{title}</h3>
      <ul>
        {items.slice(0, 3).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function MarketSummary({ data }: { data: DashboardData }) {
  const spy = data.indices.find((item) => item.symbol === "SPY");
  const qqq = data.indices.find((item) => item.symbol === "QQQ");
  const vix = data.volatility.find((item) => item.symbol === "VIX");

  return (
    <article className="panel summary-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Snapshot</span>
          <h2>{formatDate(data.selectedDate)}</h2>
        </div>
      </div>
      <dl className="metric-list">
        <div>
          <dt title={metricTooltips.spyMonth}>SPY 1M</dt>
          <dd className={performanceClass(spy?.monthReturn ?? 0)}>{formatPercent(spy?.monthReturn ?? 0)}</dd>
        </div>
        <div>
          <dt title={metricTooltips.qqqVsSpy}>QQQ vs SPY 1M</dt>
          <dd className={performanceClass((qqq?.monthReturn ?? 0) - (spy?.monthReturn ?? 0))}>
            {formatPercent((qqq?.monthReturn ?? 0) - (spy?.monthReturn ?? 0))}
          </dd>
        </div>
        <div>
          <dt title={metricTooltips.tenTwo}>10Y - 2Y</dt>
          <dd className={performanceClass(data.rates.tenTwoSpread)}>{formatNumber(data.rates.tenTwoSpread * 100, 0)} bps</dd>
        </div>
        <div>
          <dt title={metricTooltips.vix}>VIX</dt>
          <dd className={performanceClass(-(vix?.monthReturn ?? 0))}>{formatNumber(vix?.value ?? 0, 1)}</dd>
        </div>
      </dl>
      <p className="timestamp">Generated {formatDateTime(data.generatedAt)}</p>
    </article>
  );
}

function IndexCards({ data }: { data: DashboardData }) {
  if (data.indices.length === 0) {
    return <EmptyState title="Index data unavailable" body="Major index cards will appear when index returns are returned by the API." />;
  }

  return (
    <div className="index-card-grid">
      {data.indices.map((item) => (
        <article className="index-card" key={item.symbol}>
          <div className="index-card-top">
            <div>
              <strong>{item.symbol}</strong>
              <span>{item.name}</span>
            </div>
            <span className={performanceClass(item.dayReturn)}>{formatPercent(item.dayReturn)}</span>
          </div>
          <div className="price">${formatNumber(item.price, 2)}</div>
          <dl>
            <div>
              <dt>1M</dt>
              <dd className={performanceClass(item.monthReturn)}>{formatPercent(item.monthReturn)}</dd>
            </div>
            <div>
              <dt>YTD</dt>
              <dd className={performanceClass(item.ytdReturn)}>{formatPercent(item.ytdReturn)}</dd>
            </div>
            <div>
              <dt>DD</dt>
              <dd className={performanceClass(item.drawdown52w)}>{formatPercent(item.drawdown52w, 1)}</dd>
            </div>
            <div>
              <dt>RV20</dt>
              <dd>{formatNumber(item.volatility20d, 1)}%</dd>
            </div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function SectorHeatmap({ data }: { data: DashboardData }) {
  if (data.sectors.length === 0) {
    return <EmptyState title="Sector heatmap unavailable" body="No sector performance rows were returned." />;
  }

  return (
    <article className="panel heatmap-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Sector Rotation</span>
          <h2>Performance Heatmap</h2>
        </div>
        <span className="header-note">ETF proxies</span>
      </div>
      <div className="table-wrap">
        <table className="heatmap-table">
          <thead>
            <tr>
              <th>Sector</th>
              {ranges.map((range) => (
                <th key={range}>{range}</th>
              ))}
              <th>Rel 1M</th>
            </tr>
          </thead>
          <tbody>
            {data.sectors.map((sector) => (
              <tr key={sector.symbol}>
                <th>
                  <span>{sector.name}</span>
                  <small>{sector.symbol}</small>
                </th>
                {ranges.map((range) => (
                  <td key={range} style={{ background: heatColor(sector.returns[range]) }}>
                    {formatPercent(sector.returns[range], 1)}
                  </td>
                ))}
                <td className={performanceClass(sector.relativeToSpy1m)}>{formatPercent(sector.relativeToSpy1m, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function PerformanceChart({ data }: { data: DashboardData }) {
  const keys: SeriesKey[] = ["SPY", "QQQ", "IWM", "DIA"];

  if (data.performanceSeries.length === 0) {
    return <EmptyState title="Performance chart unavailable" body="No index time series points were returned." />;
  }

  const values = data.performanceSeries.flatMap((point) => keys.map((key) => point[key])).filter(Number.isFinite);
  if (values.length === 0) {
    return <EmptyState title="Performance chart unavailable" body="No numeric index time series values were returned." />;
  }

  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = rawMax === rawMin ? 1 : 0.8;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const width = 640;
  const height = 260;
  const pad = 34;

  const xFor = (index: number) => pad + (index / Math.max(1, data.performanceSeries.length - 1)) * (width - pad * 2);
  const yFor = (value: number) => height - pad - ((value - min) / (max - min)) * (height - pad * 2);

  return (
    <article className="panel chart-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Indexed Return</span>
          <h2>Major Indices</h2>
        </div>
        <div className="legend">
          {keys.map((key) => (
            <span key={key}>
              <i style={{ background: seriesColors[key] }} />
              {key}
            </span>
          ))}
        </div>
      </div>
      <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Indexed performance chart">
        <text x={width - pad} y={18} textAnchor="end" className="axis-label axis-title">
          Indexed level, base 100
        </text>
        {[min, (min + max) / 2, max].map((tick) => (
          <g key={tick}>
            <line x1={pad} x2={width - pad} y1={yFor(tick)} y2={yFor(tick)} className="grid-line" />
            <text x={8} y={yFor(tick) + 4} className="axis-label">
              {tick.toFixed(0)}
            </text>
          </g>
        ))}
        {keys.map((key) => (
          <polyline
            key={key}
            fill="none"
            stroke={seriesColors[key]}
            strokeWidth="2.6"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={data.performanceSeries.map((point, index) => `${xFor(index)},${yFor(point[key])}`).join(" ")}
          />
        ))}
        {data.performanceSeries.map((point, index) => (
          <text key={point.date} x={xFor(index)} y={height - 8} textAnchor="middle" className="axis-label">
            {index === 0 || index === data.performanceSeries.length - 1 ? point.date.slice(5) : ""}
          </text>
        ))}
      </svg>
    </article>
  );
}

function YieldCurvePanel({ data }: { data: DashboardData }) {
  const points = data.rates.points;

  if (points.length === 0) {
    return <EmptyState title="Yield curve unavailable" body="No Treasury maturity points were returned." />;
  }

  return (
    <article className="panel yield-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Rates</span>
          <h2>Yield Curve</h2>
        </div>
        <span className={performanceClass(data.rates.tenTwoSpread)}>{formatNumber(data.rates.tenTwoSpread * 100, 0)} bps 10Y-2Y</span>
      </div>
      <YieldCurve points={points} />
      <dl className="compact-kpis">
        <div>
          <dt>Fed Funds</dt>
          <dd>{formatNumber(data.rates.fedFundsRate, 2)}%</dd>
        </div>
        <div>
          <dt>CPI YoY</dt>
          <dd>{formatNumber(data.rates.cpiYoY, 1)}%</dd>
        </div>
        <div>
          <dt>Unemp.</dt>
          <dd>{formatNumber(data.rates.unemploymentRate, 1)}%</dd>
        </div>
      </dl>
    </article>
  );
}

function YieldCurve({ points }: { points: YieldPoint[] }) {
  const width = 480;
  const height = 190;
  const pad = 30;
  const values = points.flatMap((point) => [point.yield, point.previousYield]).filter(Number.isFinite);
  if (values.length === 0) {
    return <EmptyState title="Yield curve unavailable" body="No numeric Treasury yield values were returned." compact />;
  }

  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = rawMax === rawMin ? 0.5 : 0.2;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const xFor = (index: number) => pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2);
  const yFor = (value: number) => height - pad - ((value - min) / (max - min)) * (height - pad * 2);
  const lineFor = (field: "yield" | "previousYield") => points.map((point, index) => `${xFor(index)},${yFor(point[field])}`).join(" ");

  return (
    <svg className="yield-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Treasury yield curve">
      <text x={width - pad} y={18} textAnchor="end" className="axis-label axis-title">
        Yield (%)
      </text>
      <polyline points={lineFor("previousYield")} fill="none" stroke="#94a3b8" strokeWidth="2" strokeDasharray="4 4" />
      <polyline points={lineFor("yield")} fill="none" stroke="#0f766e" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((point, index) => (
        <g key={point.maturity}>
          <circle cx={xFor(index)} cy={yFor(point.yield)} r="4" fill="#0f766e" />
          <text x={xFor(index)} y={height - 8} textAnchor="middle" className="axis-label">
            {point.maturity}
          </text>
        </g>
      ))}
    </svg>
  );
}

function RiskPanel({ title, items }: { title: string; items: RiskAssetMetric[] }) {
  if (items.length === 0) {
    return <EmptyState title={title} body="No metrics available." />;
  }

  return (
    <article className="panel risk-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Cross-Asset</span>
          <h2>{title}</h2>
        </div>
      </div>
      <div className="asset-list">
        {items.map((item) => (
          <div className="asset-row" key={item.symbol}>
            <div>
              <strong>{item.symbol}</strong>
              <span>{item.name}</span>
            </div>
            <div>
              <strong>{formatNumber(item.value, item.value > 50 ? 2 : 1)}</strong>
              <span className={performanceClass(item.dayChange)}>{formatPercent(item.dayChange, 1)} 1D</span>
              <span className={performanceClass(item.monthReturn)}>{formatPercent(item.monthReturn, 1)} 1M</span>
            </div>
            <p>{item.signal}</p>
          </div>
        ))}
      </div>
    </article>
  );
}

function SignalTable({ signals }: { signals: RegimeSignal[] }) {
  if (signals.length === 0) {
    return <EmptyState title="Signal table unavailable" body="No regime signals were returned." />;
  }

  return (
    <article className="panel signal-table-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Rules</span>
          <h2>Regime Signal Table</h2>
        </div>
      </div>
      <div className="table-wrap">
        <table className="signal-table">
          <thead>
            <tr>
              <th>Signal</th>
              <th>Category</th>
              <th>Value</th>
              <th>Read</th>
              <th>Weight</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((signal) => (
              <tr key={signal.name}>
                <th>{signal.name}</th>
                <td>{signal.category}</td>
                <td>{signal.value}</td>
                <td>
                  <span className={`direction ${signal.direction}`}>{signal.direction}</span>
                </td>
                <td>{formatNumber(signal.weight * 100, 0)}%</td>
                <td>{signal.evidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function AnalystNote({ data }: { data: DashboardData }) {
  return (
    <article className="panel note-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Analyst Note</span>
          <h2>{data.analystNote.title}</h2>
        </div>
      </div>
      <ul className="note-list">
        {data.analystNote.bullets.map((bullet) => (
          <li key={bullet}>{bullet}</li>
        ))}
      </ul>
      <div className="watch-list">
        <h3>Watch</h3>
        {data.analystNote.watchItems.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
      <div className="limitations">
        <h3>Data Limits</h3>
        {data.regime.limitations.map((item) => (
          <p key={item}>{item}</p>
        ))}
      </div>
    </article>
  );
}

function LoadingState() {
  return (
    <main className="app-shell loading-shell">
      <div className="top-bar skeleton-block" />
      <div className="loading-grid">
        {Array.from({ length: 9 }, (_, index) => (
          <div className="panel skeleton-block" key={index} />
        ))}
      </div>
    </main>
  );
}

function FatalErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="app-shell centered-state">
      <ServerCrash size={30} />
      <h1>Data source error</h1>
      <p>{message}</p>
      <button className="command-button" type="button" onClick={onRetry}>
        <RefreshCw size={16} />
        Retry
      </button>
    </main>
  );
}

function EmptyState({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return (
    <div className={compact ? "empty-state compact" : "panel empty-state"}>
      <AlertTriangle size={compact ? 14 : 20} />
      <strong>{title}</strong>
      <span>{body}</span>
    </div>
  );
}

function summarizeFreshness(sources: FreshnessSource[]) {
  if (sources.some((source) => source.status === "error")) {
    return { text: "Source error", className: "bad" };
  }
  if (sources.some((source) => source.status === "stale" || source.status === "partial")) {
    return { text: "Partial freshness", className: "warn" };
  }
  if (sources.some((source) => source.status === "no_key")) {
    return { text: "Optional gaps", className: "warn" };
  }
  return { text: "Fresh", className: "good" };
}
