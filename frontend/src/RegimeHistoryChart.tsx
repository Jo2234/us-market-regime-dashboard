import { useEffect, useRef, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import type { HistoricalRegimePoint } from "./types";
import { formatDate, formatShortDate } from "./utils";

const legacyMetrics = [
  ["riskScore", "Risk", "var(--positive)"],
  ["growthScore", "Growth", "var(--chart-qqq)"],
  ["inflationScore", "Inflation", "var(--chart-iwm)"],
  ["ratesPressureScore", "Rates", "var(--negative)"],
] as const;
const regimeColors: Record<string, string> = {
  Goldilocks: "#42724c", Reflation: "#b17a21", Stagflation: "#994b5e", Slowdown: "#54728c",
  "Risk-on growth led": "#42724c", "Risk-on broadening": "#317f84",
  "Risk-off defensive": "#994b5e", "Inflation pressure": "#b17a21",
  "Rates pressure": "#b5533a", "Commodity shock": "#7b5c96", "Mixed transition": "#727f8a",
};

export function trailingMean(values: number[], window = 5): number[] {
  return values.map((_, index) => {
    const slice = values.slice(Math.max(0, index - window + 1), index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / slice.length;
  });
}

export default function RegimeHistoryChart({ data, onDateSelect }: { data: HistoricalRegimePoint[]; onDateSelect: (date: string) => void }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [smooth, setSmooth] = useState(false);
  const [width, setWidth] = useState(window.innerWidth < 600 ? 295 : 900);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => { if (entry.contentRect.width > 0) setWidth(entry.contentRect.width); });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [data.length]);
  if (!data.length) return <article className="panel"><h2>Regime history unavailable</h2><p>No completed daily observations are available for this history window.</p></article>;
  const metrics = data[0].stressScore !== undefined ? [
    ["growthScore", "Growth", "var(--chart-qqq)"], ["inflationScore", "Inflation", "var(--chart-iwm)"], ["stressScore", "Stress", "var(--negative)"]
  ] as const : legacyMetrics;
  const left = 32, right = width - 12, height = 60 + metrics.length * 90, rowHeight = 90, plotHeight = 55;
  const xFor = (index: number) => left + index / Math.max(1, data.length - 1) * (right - left);
  const topFor = (row: number) => 54 + row * rowHeight;
  const yFor = (value: number, row: number) => topFor(row) + plotHeight * (1 - value / 100);
  const active = Math.min(activeIndex ?? data.length - 1, data.length - 1);
  const point = data[active];
  const bands = data.reduce<Array<{ start: number; end: number; label: string }>>((result, item, i) => {
    const previous = result[result.length - 1];
    if (previous?.label === item.displayLabel) previous.end = i;
    else result.push({ start: i, end: i, label: item.displayLabel });
    return result;
  }, []);
  const labels = [...new Set(bands.map(band => band.label))];
  const plotted = metrics.map(([key]) => smooth ? trailingMean(data.map(item => (item[key] ?? 0))) : data.map(item => (item[key] ?? 0)));
  const pathFor = (row: number) => plotted[row].map((value, i) =>
    i === 0 ? `M ${xFor(i)} ${yFor(value, row)}` : smooth ? `L ${xFor(i)} ${yFor(value, row)}` : `H ${xFor(i)} V ${yFor(value, row)}`
  ).join(" ");
  const inspect = (event: React.PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width * width;
    setActiveIndex(Math.max(0, Math.min(data.length - 1, Math.round((x - left) / (right - left) * (data.length - 1)))));
  };
  return <article className="panel history-panel">
    <div className="panel-header"><div><span className="eyebrow">Explainability</span><h2>Historical regime scores</h2></div>
      <label className="history-smoothing"><input type="checkbox" checked={smooth} onChange={event => setSmooth(event.target.checked)} />5-day smoothing</label>
    </div>
    <p className="chart-caption" id="history-summary">{data.length} daily classifications · {bands.length - 1} regime changes · {formatDate(data[0].date)} – {formatDate(data[data.length - 1].date)}. Current: {data[data.length - 1].displayLabel}.</p>
    <p className="chart-note">Completed closes. {smooth ? "Trailing 5-trading-day means are for display only; classifications and inspector scores are unchanged." : "Unsmoothed daily scores; steps show each trading day's reading."} Dots below the ribbon mark emerging quadrants. Hover, tap or drag to inspect.</p>
    {data.length === 1 && <p className="chart-caption">A trend needs at least two observations.</p>}
    <div className="history-regime-legend" aria-label="Regime timeline legend">{labels.map(label => <span key={label}><i style={{ background: regimeColors[label] ?? "#727f8a" }} />{label}</span>)}</div>
    <div ref={container}>
      <svg className="history-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historical regime scores chart" aria-describedby="history-summary"
        onPointerMove={event => { if (event.pointerType !== "touch" || event.buttons) inspect(event); }}
        onPointerDown={event => { event.currentTarget.setPointerCapture?.(event.pointerId); inspect(event); }}>
        <title>Synchronized score panels and official regime timeline; explore exact values with the date slider below.</title>
        {bands.map(band => {
          const start = band.start ? (xFor(band.start - 1) + xFor(band.start)) / 2 : left;
          const end = band.end === data.length - 1 ? right : (xFor(band.end) + xFor(band.end + 1)) / 2;
          return <rect className="regime-strip" key={band.start} x={start} y={8} width={Math.max(0.5, end - start)} height={13} fill={regimeColors[band.label] ?? "#727f8a"}><title>{band.label}: {formatDate(data[band.start].date)} – {formatDate(data[band.end].date)}</title></rect>;
        })}
        {data.map((p,i)=>p.emergingLabel?<circle key={`emerging-${i}`} className="emerging-marker" cx={xFor(i)} cy={27} r={1.5} fill="var(--soft)"><title>{formatDate(p.date)}: Emerging {p.emergingLabel}</title></circle>:null)}
        {metrics.map(([key, label, color], row) => <g className="score-panel" key={key}>
          <text x={left} y={topFor(row) - 10} className="history-series-label" fill={color}>{label}</text>
          <text x={right} y={topFor(row) - 10} textAnchor="end" className="history-series-label" fill={color}>{smooth ? plotted[row][active].toFixed(1) : (point[key] ?? 0).toFixed(1)}</text>
          {[0, 50, 100].map(tick => <g key={tick}><line x1={left} x2={right} y1={yFor(tick, row)} y2={yFor(tick, row)} className={`grid-line ${tick === 50 ? "midline" : "boundary-line"}`} /><text x={left - 8} y={yFor(tick, row) + 4} textAnchor="end" className="axis-label">{tick}</text></g>)}
          <path className="score-line" fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" aria-label={`${label} score history`} d={pathFor(row)} />
          <circle cx={xFor(active)} cy={yFor(plotted[row][active], row)} r="3" fill={color}><title>{formatDate(point.date)}: {label} {(point[key] ?? 0)}</title></circle>
        </g>)}
        <line className="history-crosshair" x1={xFor(active)} x2={xFor(active)} y1={6} y2={yFor(0, metrics.length - 1)} strokeDasharray="3 3" />
        {[0, Math.floor((data.length - 1) / 2), data.length - 1].filter((n, i, a) => a.indexOf(n) === i).map(i => <text key={i} x={xFor(i)} y={height - 13} textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"} className="axis-label">{formatShortDate(data[i].date)}</text>)}
      </svg>
    </div>
    <label className="history-date-control">Explore a trading date<input aria-label="Historical regime date" aria-valuetext={`${formatDate(point.date)}, ${point.displayLabel}`} type="range" min="0" max={data.length - 1} value={active} onChange={event => setActiveIndex(Number(event.target.value))} /></label>
    <div className="history-tooltip" aria-live="polite">
      <strong>{formatDate(point.date)} · {point.displayLabel}</strong>
      <p>{metrics.map(([key, label]) => `${label} ${(point[key] ?? 0).toFixed(1)}`).join(" · ")}</p>
      <p>{point.note}</p>
      <button type="button" className="text-link" onClick={() => {
        onDateSelect(point.date);
        document.getElementById("overview")?.scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      }}>View snapshot <ArrowUpRight size={14} /></button>
    </div>
  </article>;
}
