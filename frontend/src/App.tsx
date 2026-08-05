import {
  Activity,
  ArrowDown,
  ArrowUpRight,
  AlertTriangle,
  CalendarDays,
  Download,
  RefreshCw,
  ServerCrash,
  WifiOff,
} from "lucide-react";
import { useEffect, useState } from "react";
import { fetchDashboardData } from "./api";
import type {
  ChartPoint,
  DashboardData,
  FreshnessSource,
  HistoricalRegimePoint,
  RangeKey,
  RegimeSignal,
  RiskAssetMetric,
  YieldPoint,
} from "./types";
import {
  downloadDashboardCsv,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  heatColor,
  performanceClass,
  ranges,
  scoreClass,
} from "./utils";

type SeriesKey = Exclude<keyof ChartPoint, "date">;

const seriesColors: Record<SeriesKey, string> = {
  SPY: "var(--chart-spy)",
  QQQ: "var(--chart-qqq)",
  IWM: "var(--chart-iwm)",
  DIA: "var(--chart-dia)",
};

const metricTooltips = {
  spyMonth: "SPY one-month price return for the selected market date.",
  qqqVsSpy:
    "QQQ one-month return minus SPY one-month return, in percentage points.",
  tenTwo:
    "10-year Treasury yield minus 2-year Treasury yield, shown in basis points.",
  vix: "Current VIX level; falling VIX is treated as supportive for risk appetite.",
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
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Unable to load dashboard data.",
        );
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
    return (
      <FatalErrorState
        message={error}
        onRetry={() => setReloadTick((value) => value + 1)}
      />
    );
  }

  if (!data) {
    return (
      <EmptyState
        title="No dashboard data"
        body="No market snapshot is available for the selected date."
      />
    );
  }

  return (
    <main className="app-shell">
      <Masthead />
      <TopBar
        data={data}
        selectedDate={selectedDate}
        loading={loading}
        onDateChange={setSelectedDate}
        onRefresh={() => setReloadTick((value) => value + 1)}
        onExport={() => downloadDashboardCsv(data)}
      />
      {!loading && selectedDate && selectedDate !== data.selectedDate && (
        <p className="resolved-date" role="status">
          Requested {formatDate(selectedDate)}. Showing the available snapshot
          for {formatDate(data.selectedDate)}.
        </p>
      )}
      <nav className="section-nav" aria-label="Dashboard sections">
        <a href="#overview">Overview</a>
        <a href="#markets">Markets</a>
        <a href="#rules">Signals & rules</a>
        <a href="#history">History</a>
        <a href="#sources">
          Data sources <ArrowDown size={13} />
        </a>
      </nav>
      <div className="data-notice">
        <span
          className={`mode-chip ${data.provenance?.mode ?? data.sourceMode}`}
        >
          {
            {
              api: "API data",
              demo: "Generated demo data",
              mixed: "Mixed sources",
              fallback: "Demo fallback",
            }[data.provenance?.mode ?? data.sourceMode]
          }
        </span>
        <p>
          {data.provenance?.mode === "demo" || data.sourceMode === "demo"
            ? "Generated examples for exploring the model. These are not live market observations."
            : (data.provenance?.description ??
              "Source metadata is unavailable. Live market provenance is unverified.")}
        </p>
        <a href="#sources">
          Source details <ArrowUpRight size={14} />
        </a>
      </div>
      <section
        id="overview"
        className="dashboard-grid first-row"
        aria-label="Market overview"
        aria-busy={loading}
      >
        <RegimeCard data={data} />
        <MarketSummary data={data} />
      </section>
      <IndexCards data={data} />
      <section
        id="markets"
        className="section-block"
        aria-labelledby="markets-title"
      >
        <SectionHeading
          number="01"
          title="Across the market"
          id="markets-title"
          description="Compare index performance, sector rotation and the signals beyond equities."
        />
        <div className="dashboard-grid second-row">
          <PerformanceChart
            data={data}
            range={range}
            onRangeChange={setRange}
          />
          <YieldCurvePanel data={data} />
        </div>
        <div className="dashboard-grid third-row">
          <SectorHeatmap data={data} />
          <div className="cross-asset-stack">
            <RiskPanel title="Commodities" items={data.commodities} />
            <RiskPanel
              title="Volatility & Breadth"
              items={[...data.volatility, ...data.breadth]}
            />
          </div>
        </div>
      </section>
      <section
        id="rules"
        className="section-block"
        aria-labelledby="rules-title"
      >
        <SectionHeading
          number="02"
          title="Behind the classification"
          id="rules-title"
          description="Trace the model’s reading back to each input and its evidence."
        />
        <div className="dashboard-grid fourth-row">
          <SignalTable signals={data.signals} />
          <AnalystNote data={data} />
        </div>
      </section>
      <section
        id="history"
        className="section-block"
        aria-labelledby="history-title"
      >
        <SectionHeading
          number="03"
          title="How the regime evolved"
          id="history-title"
          description="Stored classifications, with scores shown on a 0–100 scale."
        />
        <RegimeHistoryChart
          data={data.historicalRegimes ?? []}
          onDateSelect={setSelectedDate}
        />
      </section>
      <section
        id="sources"
        className="section-block"
        aria-labelledby="sources-title"
      >
        <SectionHeading
          number="04"
          title="Know your data"
          id="sources-title"
          description="Observation dates, source coverage and the provenance of this snapshot."
        />
        <ProvenancePanel data={data} />
        <StatusStrip data={data} error={error} />
      </section>

      <SiteFooter />
    </main>
  );
}

function SectionHeading({
  number,
  title,
  id,
  description,
}: {
  number: string;
  title: string;
  id: string;
  description: string;
}) {
  return (
    <div className="section-heading">
      <span>{number}</span>
      <div>
        <h2 id={id}>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}

function Masthead() {
  return (
    <div className="masthead" aria-label="Vaz Research publication">
      <a href="#overview" className="publication-brand">
        <Activity size={22} strokeWidth={1.8} /> Vaz Research
      </a>
      <span className="masthead-note">Market research / United States</span>
    </div>
  );
}

function SiteFooter() {
  return (
    <footer className="site-footer">
      <span>Johan Vaz</span>
      <span aria-hidden="true">·</span>
      <a
        href="https://johan-vaz-site.vercel.app"
        target="_blank"
        rel="noreferrer"
      >
        johan-vaz-site.vercel.app
      </a>
      <span aria-hidden="true">·</span>
      <a
        href="https://github.com/Jo2234/us-market-regime-dashboard"
        target="_blank"
        rel="noreferrer"
      >
        source on GitHub
      </a>
    </footer>
  );
}

function TopBar({
  data,
  selectedDate,
  loading,
  onDateChange,
  onRefresh,
  onExport,
}: {
  data: DashboardData;
  selectedDate: string;
  loading: boolean;
  onDateChange: (date: string) => void;
  onRefresh: () => void;
  onExport: () => void;
}) {
  const freshnessLabel = summarizeFreshness(data.freshness);

  return (
    <header className="top-bar">
      <div className="brand-block">
        <div>
          <span className="publication-kicker">The market, in context</span>
          <h1>US Market Regime</h1>
          <p>A clear view of the market. Every signal explained.</p>
        </div>
      </div>

      <div className="top-controls">
        <div
          className={`freshness-pill ${freshnessLabel.className}`}
          title="Latest available source status"
        >
          {freshnessLabel.text}
        </div>
        <label className="date-control">
          <span>Snapshot date</span>
          <span className="date-input">
            <CalendarDays size={16} />
            <input
              aria-label="Snapshot date"
              type="date"
              value={selectedDate}
              onChange={(event) => onDateChange(event.target.value)}
            />
          </span>
        </label>
        <button
          className="icon-button"
          type="button"
          onClick={onRefresh}
          title="Refresh data"
          aria-label="Refresh data"
          disabled={loading}
        >
          <RefreshCw size={16} className={loading ? "spinning" : ""} />
        </button>
        <button className="command-button" type="button" onClick={onExport}>
          <Download size={16} />
          Export CSV
        </button>
      </div>
    </header>
  );
}

function StatusStrip({
  data,
  error,
}: {
  data: DashboardData;
  error: string | null;
}) {
  const items = [
    ...data.errors.map((message) => ({ kind: "error", message })),
    ...(error ? [{ kind: "error", message: error }] : []),
    ...(data.stale
      ? [
          {
            kind: "stale",
            message:
              "Some source data is stale relative to the selected market date.",
          },
        ]
      : []),
    ...(data.partial
      ? [
          {
            kind: "partial",
            message:
              "Partial snapshot: at least one feed is delayed or missing latest observations.",
          },
        ]
      : []),
    ...data.optionalProvidersMissing.map((provider) => ({
      kind: "no-key",
      message: `Optional provider not configured: ${provider}.`,
    })),
  ];

  return (
    <section className="status-strip" aria-label="Dashboard data status">
      <div className="source-grid">
        {data.freshness.length > 0 ? (
          data.freshness.map((source) => (
            <FreshnessBadge key={source.name} source={source} />
          ))
        ) : (
          <div
            className="source-badge empty-source"
            title="The API did not return source freshness metadata."
          >
            <span>Data freshness</span>
            <strong>No source dates returned</strong>
          </div>
        )}
      </div>
      {items.length > 0 && (
        <div className="banner-list">
          {items.map((item, index) => (
            <div
              className={`status-banner ${item.kind}`}
              key={`${item.kind}-${index}`}
              role="status"
            >
              {item.kind === "error" ? (
                <ServerCrash size={16} />
              ) : item.kind === "no-key" ? (
                <WifiOff size={16} />
              ) : (
                <AlertTriangle size={16} />
              )}
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
      <span className="source-status">{source.status.replace("_", " ")}</span>
    </div>
  );
}

function ProvenancePanel({ data }: { data: DashboardData }) {
  const provenance = data.provenance;
  if (!provenance) {
    return null;
  }

  return (
    <section
      className="provenance-panel"
      aria-label="Data provenance and freshness policy"
    >
      <div>
        <span className={`mode-chip ${provenance.mode}`}>
          {
            {
              api: "API data",
              demo: "Demo data",
              mixed: "Mixed sources",
              fallback: "Demo fallback",
            }[provenance.mode]
          }
        </span>
        <strong>Data provenance</strong>
        <p className="transport-label">
          {data.sourceMode === "api"
            ? `API: ${data.apiBaseUrl}`
            : "Demo fallback data"}
        </p>
        <p>{provenance.description}</p>
      </div>
      <div>
        <span>Selected {formatDate(provenance.selectedDate)}</span>
        <span>Generated {formatDateTime(provenance.generatedAt)}</span>
        <span>{provenance.freshnessPolicy}</span>
      </div>
      {provenance.sources.length > 0 && (
        <ul>
          {provenance.sources.map((source) => (
            <li key={source}>{source}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RegimeCard({ data }: { data: DashboardData }) {
  const scores = [
    ["Risk", data.regime.riskScore],
    ["Growth", data.regime.growthScore],
    ["Inflation", data.regime.inflationScore],
    ["Rates", data.regime.ratesPressureScore],
  ] as const;

  return (
    <article className="panel regime-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Current classification</span>
          <h2>{data.regime.displayLabel}</h2>
        </div>
        <span className={`confidence ${data.regime.confidence}`}>
          {data.regime.confidence} confidence
        </span>
      </div>
      <p className="regime-change">{data.regime.changedSincePrevious}</p>
      <p className="score-caption">
        Model scores <span>0–100</span>
      </p>
      <div className="score-grid">
        {scores.map(([label, value]) => (
          <div
            className="score-item"
            key={label}
            title={`${label} score from transparent regime rules`}
          >
            <div className="score-top">
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
            <div className="score-track">
              <span
                className={scoreClass(value)}
                style={{ width: `${value}%` }}
              />
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
  const relativeReturn =
    qqq?.monthReturn != null && spy?.monthReturn != null
      ? qqq.monthReturn - spy.monthReturn
      : null;

  return (
    <article className="panel summary-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Snapshot at a glance</span>
          <h2>{formatDate(data.selectedDate)}</h2>
        </div>
      </div>
      <dl className="metric-list">
        <div>
          <dt title={metricTooltips.spyMonth}>SPY 1M</dt>
          <dd className={performanceClass(spy?.monthReturn ?? null)}>
            {formatPercent(spy?.monthReturn ?? null)}
          </dd>
        </div>
        <div>
          <dt title={metricTooltips.qqqVsSpy}>QQQ vs SPY 1M</dt>
          <dd className={performanceClass(relativeReturn)}>
            {formatNumber(relativeReturn, 2)} pp
          </dd>
        </div>
        <div>
          <dt title={metricTooltips.tenTwo}>10Y - 2Y</dt>
          <dd className={performanceClass(data.rates.tenTwoSpread)}>
            {formatNumber(
              data.rates.tenTwoSpread === null
                ? null
                : data.rates.tenTwoSpread * 100,
              0,
            )}{" "}
            bps
          </dd>
        </div>
        <div>
          <dt title={metricTooltips.vix}>VIX</dt>
          <dd
            className={performanceClass(
              vix?.monthReturn == null ? null : -vix.monthReturn,
            )}
          >
            {formatNumber(vix?.value ?? null, 1)}
          </dd>
        </div>
      </dl>
      <p className="timestamp">Generated {formatDateTime(data.generatedAt)}</p>
      <a className="text-link" href="#rules">
        Explore the underlying signals <ArrowUpRight size={15} />
      </a>
    </article>
  );
}

function IndexCards({ data }: { data: DashboardData }) {
  if (data.indices.length === 0) {
    return (
      <EmptyState
        title="Index data unavailable"
        body="Major index cards will appear when index returns are returned by the API."
      />
    );
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
            <span className={performanceClass(item.dayReturn)}>
              {formatPercent(item.dayReturn)} <small>1D</small>
            </span>
          </div>
          <div className="price">${formatNumber(item.price, 2)}</div>
          <dl>
            <div>
              <dt>1M</dt>
              <dd className={performanceClass(item.monthReturn)}>
                {formatPercent(item.monthReturn)}
              </dd>
            </div>
            <div>
              <dt>YTD</dt>
              <dd className={performanceClass(item.ytdReturn)}>
                {formatPercent(item.ytdReturn)}
              </dd>
            </div>
            <div>
              <dt title="Drawdown from the 52-week high">52W drawdown</dt>
              <dd className={performanceClass(item.drawdown52w)}>
                {formatPercent(item.drawdown52w, 1)}
              </dd>
            </div>
            <div>
              <dt title="Realized volatility over 20 trading days">
                20D volatility
              </dt>
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
    return (
      <EmptyState
        title="Sector heatmap unavailable"
        body="No sector performance rows were returned."
      />
    );
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
      <p className="table-scroll-hint">Scroll sideways for all periods →</p>
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label="Sector returns, scroll horizontally for all periods"
      >
        <table className="heatmap-table">
          <thead>
            <tr>
              <th>Sector</th>
              {ranges.map((range) => (
                <th key={range}>{range}</th>
              ))}
              <th title="One-month return minus SPY, in percentage points">
                vs SPY 1M
              </th>
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
                  <td
                    key={range}
                    style={{ background: heatColor(sector.returns[range]) }}
                  >
                    {formatPercent(sector.returns[range], 1)}
                  </td>
                ))}
                <td className={performanceClass(sector.relativeToSpy1m)}>
                  {formatPercent(sector.relativeToSpy1m, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="chart-caption">
        Returns in %. “vs SPY 1M” is the one-month difference in percentage
        points.
      </p>
    </article>
  );
}

function PerformanceChart({
  data,
  range,
  onRangeChange,
}: {
  data: DashboardData;
  range: RangeKey;
  onRangeChange: (range: RangeKey) => void;
}) {
  const allKeys: SeriesKey[] = ["SPY", "QQQ", "IWM", "DIA"];
  const [keys, setKeys] = useState<SeriesKey[]>(allKeys);

  const values = data.performanceSeries
    .flatMap((point) => keys.map((key) => point[key]))
    .filter(Number.isFinite);
  const rawMin = values.length ? Math.min(...values) : 0;
  const rawMax = values.length ? Math.max(...values) : 100;
  const padding = rawMax === rawMin ? 1 : 0.8;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const width = 640;
  const height = 260;
  const pad = 34;

  const xFor = (index: number) =>
    pad +
    (index / Math.max(1, data.performanceSeries.length - 1)) *
      (width - pad * 2);
  const yFor = (value: number) =>
    height - pad - ((value - min) / (max - min)) * (height - pad * 2);

  return (
    <article className="panel chart-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Indexed Return</span>
          <h2>Major Indices</h2>
        </div>
        <span className="header-note">Base 100</span>
      </div>
      <div className="chart-controls">
        <div className="segmented" aria-label="Chart period">
          {ranges.map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={item === range}
              className={item === range ? "active" : ""}
              onClick={() => onRangeChange(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <div
          className="legend interactive-legend"
          aria-label="Visible index series"
        >
          {allKeys.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={keys.includes(key)}
              onClick={() =>
                setKeys((current) =>
                  current.includes(key)
                    ? current.length > 1
                      ? current.filter((value) => value !== key)
                      : current
                    : [...current, key],
                )
              }
            >
              <i style={{ background: seriesColors[key] }} />
              {key}
            </button>
          ))}
        </div>
      </div>
      {values.length === 0 ? (
        <EmptyState
          title="Performance chart unavailable"
          body="No numeric observations are available for this selection. Try another period or enable another index."
        />
      ) : (
        <>
          <p className="chart-caption">
            {formatDate(data.performanceSeries[0].date)} –{" "}
            {formatDate(
              data.performanceSeries[data.performanceSeries.length - 1].date,
            )}
            {data.sourceMode === "demo"
              ? " · Fixed demo series; period selection does not change the embedded fixture."
              : " · Select an index to show or hide it."}
          </p>
          <svg
            className="line-chart"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Indexed performance chart"
          >
            <text
              x={width - pad}
              y={18}
              textAnchor="end"
              className="axis-label axis-title"
            >
              Indexed level, base 100
            </text>
            {[min, (min + max) / 2, max].map((tick) => (
              <g key={tick}>
                <line
                  x1={pad}
                  x2={width - pad}
                  y1={yFor(tick)}
                  y2={yFor(tick)}
                  className="grid-line"
                />
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
                points={data.performanceSeries
                  .map((point, index) => `${xFor(index)},${yFor(point[key])}`)
                  .join(" ")}
              />
            ))}
            {data.performanceSeries.map((point, index) => (
              <text
                key={point.date}
                x={xFor(index)}
                y={height - 8}
                textAnchor="middle"
                className="axis-label"
              >
                {index === 0 || index === data.performanceSeries.length - 1
                  ? point.date.slice(5)
                  : ""}
              </text>
            ))}
          </svg>
        </>
      )}
    </article>
  );
}

function YieldCurvePanel({ data }: { data: DashboardData }) {
  const points = data.rates.points;

  if (points.length === 0) {
    return (
      <EmptyState
        title="Yield curve unavailable"
        body="No Treasury maturity points were returned."
      />
    );
  }

  return (
    <article className="panel yield-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Rates</span>
          <h2>Yield Curve</h2>
        </div>
        <span className={performanceClass(data.rates.tenTwoSpread)}>
          {formatNumber(
            data.rates.tenTwoSpread === null
              ? null
              : data.rates.tenTwoSpread * 100,
            0,
          )}{" "}
          bps 10Y-2Y
        </span>
      </div>
      <YieldCurve points={points} />
      <div className="legend yield-legend">
        <span>
          <i style={{ background: "var(--positive)" }} />
          Selected snapshot
        </span>
        {points.every((point) => point.previousYield !== undefined) && (
          <span>
            <i className="dashed" />
            Previous supplied curve
          </span>
        )}
      </div>
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
  const values = points
    .flatMap((point) => [point.yield, point.previousYield])
    .filter(
      (value): value is number => value !== undefined && Number.isFinite(value),
    );
  if (values.length === 0) {
    return (
      <EmptyState
        title="Yield curve unavailable"
        body="No numeric Treasury yield values were returned."
        compact
      />
    );
  }

  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = rawMax === rawMin ? 0.5 : 0.2;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const xFor = (index: number) =>
    pad + (index / Math.max(1, points.length - 1)) * (width - pad * 2);
  const yFor = (value: number) =>
    height - pad - ((value - min) / (max - min)) * (height - pad * 2);
  const lineFor = (field: "yield" | "previousYield") =>
    points
      .flatMap((point, index) => {
        const value = point[field];
        return value === undefined ? [] : [`${xFor(index)},${yFor(value)}`];
      })
      .join(" ");

  return (
    <svg
      className="yield-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Treasury yield curve"
    >
      <text
        x={width - pad}
        y={18}
        textAnchor="end"
        className="axis-label axis-title"
      >
        Yield (%)
      </text>
      {[min, (min + max) / 2, max].map((tick) => (
        <g key={tick}>
          <line
            x1={pad}
            x2={width - pad}
            y1={yFor(tick)}
            y2={yFor(tick)}
            className="grid-line"
          />
          <text x={0} y={yFor(tick) + 4} className="axis-label">
            {tick.toFixed(1)}
          </text>
        </g>
      ))}
      {points.every((point) => point.previousYield !== undefined) && (
        <polyline
          points={lineFor("previousYield")}
          fill="none"
          stroke="var(--chart-previous)"
          strokeWidth="2"
          strokeDasharray="4 4"
        />
      )}
      <polyline
        points={lineFor("yield")}
        fill="none"
        stroke="var(--positive)"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.map((point, index) => (
        <g key={point.maturity}>
          <circle
            cx={xFor(index)}
            cy={yFor(point.yield)}
            r="4"
            fill="var(--positive)"
          />
          <text
            x={xFor(index)}
            y={height - 8}
            textAnchor="middle"
            className="axis-label"
          >
            {point.maturity}
          </text>
        </g>
      ))}
    </svg>
  );
}

function RiskPanel({
  title,
  items,
}: {
  title: string;
  items: RiskAssetMetric[];
}) {
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
              <strong>
                {formatNumber(
                  item.value,
                  item.value !== null && item.value > 50 ? 2 : 1,
                )}
              </strong>
              <span className={performanceClass(item.dayChange)}>
                {formatPercent(item.dayChange, 1)} 1D
              </span>
              <span className={performanceClass(item.monthReturn)}>
                {formatPercent(item.monthReturn, 1)} 1M
              </span>
            </div>
            <p>{item.signal}</p>
          </div>
        ))}
      </div>
    </article>
  );
}

function SignalTable({ signals }: { signals: RegimeSignal[] }) {
  const [category, setCategory] = useState("all");
  const filteredSignals = signals.filter(
    (signal) => category === "all" || signal.category === category,
  );
  if (signals.length === 0) {
    return (
      <EmptyState
        title="Signal table unavailable"
        body="No regime signals were returned."
      />
    );
  }

  return (
    <article className="panel signal-table-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Rules</span>
          <h2>Regime Signal Table</h2>
        </div>
        <label className="filter-label">
          Category
          <select
            aria-label="Category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="all">All signals</option>
            {[...new Set(signals.map((signal) => signal.category))].map(
              (value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ),
            )}
          </select>
        </label>
      </div>
      <p className="chart-caption">
        {filteredSignals.length} of {signals.length} signals · Raw values and
        rule weights as supplied by the model.
      </p>
      <p className="table-scroll-hint">
        Scroll sideways to read every rule’s evidence →
      </p>
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label="Regime signals, scroll horizontally for evidence"
      >
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
            {filteredSignals.map((signal) => (
              <tr key={signal.name}>
                <th>{signal.name}</th>
                <td>{signal.category}</td>
                <td>{signal.value}</td>
                <td>
                  <span className={`direction ${signal.direction}`}>
                    {signal.direction}
                  </span>
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

function RegimeHistoryChart({
  data,
  onDateSelect,
}: {
  data: HistoricalRegimePoint[];
  onDateSelect: (date: string) => void;
}) {
  if (data.length === 0) {
    return (
      <EmptyState
        title="Regime history unavailable"
        body="Historical regime points will appear when the API returns backfilled classifications."
      />
    );
  }

  const metrics = [
    ["riskScore", "Risk", "var(--positive)"],
    ["growthScore", "Growth", "var(--chart-qqq)"],
    ["inflationScore", "Inflation", "var(--chart-iwm)"],
    ["ratesPressureScore", "Rates", "var(--negative)"],
  ] as const;
  const width = 900;
  const height = 260;
  const pad = 36;
  const xFor = (index: number) =>
    pad + (index / Math.max(1, data.length - 1)) * (width - pad * 2);
  const yFor = (value: number) =>
    height - pad - (value / 100) * (height - pad * 2);

  return (
    <article className="panel history-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Explainability</span>
          <h2>Historical Regime Scores</h2>
        </div>
        <div className="legend">
          {metrics.map(([, label, color]) => (
            <span key={label}>
              <i style={{ background: color }} />
              {label}
            </span>
          ))}
        </div>
      </div>
      {data.length === 1 && (
        <p className="chart-caption">
          One stored classification is available. Dots show its scores; a trend
          needs at least two observations.
        </p>
      )}
      <div
        className="chart-scroll"
        tabIndex={0}
        role="region"
        aria-label="Historical score chart, scroll horizontally on small screens"
      >
        <svg
          className="history-chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Historical regime scores chart"
        >
          {[0, 50, 100].map((tick) => (
            <g key={tick}>
              <line
                x1={pad}
                x2={width - pad}
                y1={yFor(tick)}
                y2={yFor(tick)}
                className="grid-line"
              />
              <text x={8} y={yFor(tick) + 4} className="axis-label">
                {tick}
              </text>
            </g>
          ))}
          {metrics.map(([key, label, color]) => (
            <polyline
              key={key}
              fill="none"
              stroke={color}
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-label={`${label} score history`}
              points={data
                .map((point, index) => `${xFor(index)},${yFor(point[key])}`)
                .join(" ")}
            />
          ))}
          {data.map((point, index) => (
            <g key={point.date}>
              {metrics.map(([key, label, color]) => (
                <circle
                  key={key}
                  cx={xFor(index)}
                  cy={yFor(point[key])}
                  r={data.length === 1 ? 5 : 3}
                  fill={color}
                >
                  <title>
                    {formatDate(point.date)}: {label} {point[key]}
                  </title>
                </circle>
              ))}
              <text
                x={xFor(index)}
                y={height - 10}
                textAnchor="middle"
                className="axis-label"
              >
                {data.length <= 8 ||
                index === 0 ||
                index === data.length - 1 ||
                index % Math.ceil(data.length / 6) === 0
                  ? point.date.slice(5)
                  : ""}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <div className="history-notes">
        {data.slice(-3).map((point) => (
          <div key={point.date}>
            <strong>{point.displayLabel}</strong>
            <span>{formatDate(point.date)}</span>
            <p>{point.note}</p>
            <p>
              Risk {point.riskScore} · Growth {point.growthScore} · Inflation{" "}
              {point.inflationScore} · Rates {point.ratesPressureScore}
            </p>
            <button
              type="button"
              className="text-link"
              onClick={() => {
                onDateSelect(point.date);
                document
                  .getElementById("overview")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              View snapshot <ArrowUpRight size={14} />
            </button>
          </div>
        ))}
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
      <Masthead />
      <p role="status">Loading the market snapshot and source details…</p>
      <div className="top-bar skeleton-block" />
      <div className="loading-grid">
        {Array.from({ length: 9 }, (_, index) => (
          <div className="panel skeleton-block" key={index} />
        ))}
      </div>
      <SiteFooter />
    </main>
  );
}

function FatalErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="app-shell centered-state">
      <Masthead />
      <section className="fatal-card">
        <ServerCrash size={30} />
        <h1>Data source error</h1>
        <p>{message}</p>
        <button className="command-button" type="button" onClick={onRetry}>
          <RefreshCw size={16} />
          Retry
        </button>
      </section>
      <SiteFooter />
    </main>
  );
}

function EmptyState({
  title,
  body,
  compact = false,
}: {
  title: string;
  body: string;
  compact?: boolean;
}) {
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
  if (
    sources.some(
      (source) => source.status === "stale" || source.status === "partial",
    )
  ) {
    return { text: "Partial freshness", className: "warn" };
  }
  if (sources.some((source) => source.status === "no_key")) {
    return { text: "Optional gaps", className: "warn" };
  }
  return { text: "Fresh", className: "good" };
}
