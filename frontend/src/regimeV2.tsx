import type { DashboardData, RegimeV2, V2Signal } from './types';
import { formatDate } from './utils';

export function rawSignalValue(signal: V2Signal): string {
  const n=signal.raw_value;
  const signed=(value:number,digits=2)=>`${value>0?'+':''}${value.toFixed(digits)}`;
  if (signal.unit==='claims') return `${Math.round(n).toLocaleString()} claims`;
  if (signal.unit==='breadth') return `${Math.round(n*11)}/11 · ${(n*100).toFixed(0)}%`;
  if (['return','ratio_trend','return_difference'].includes(signal.unit)) return `${signed(n*100)}${signal.unit==='return_difference'?' pp':'%'}`;
  if (signal.unit==='percent') return `${n.toFixed(2)}%`;
  if (signal.unit==='percentage_points') return `${signed(n)} pp`;
  if (signal.unit==='ratio') return `${n.toFixed(3)}×`;
  return `${n.toFixed(2)} points`;
}

export function applyV2(data:DashboardData, model:RegimeV2):DashboardData {
  data.regimeV2=model;
  data.optionalProvidersMissing=[];
  data.signals=model.signals.map(signal=>({
    name:signal.name,category:signal.axis.toLowerCase() as 'growth',value:String(signal.raw_value),
    rawUnit:signal.unit,displayValue:rawSignalValue(signal),percentile:signal.percentile,
    direction:signal.percentile>=50?'positive':'negative',
    directionText:`${signal.axis} ${signal.percentile>=50?'↑':'↓'}`, weight:signal.weight,
    evidence:`${signal.held_for_missing_month ? "Last computable observation retained because a comparison month is missing. " : ""}${signal.direction}. ${Object.entries(signal.observations).map(([s,d])=>`${s}: ${formatDate(d)}`).join('; ')}. Available by ${formatDate(signal.available_on)}.`
  }));
  const scores=model.axis_scores;
  data.regime={...data.regime,label:model.quadrant,displayLabel:model.quadrant,
    confidence:model.confidence.label.toLowerCase() as 'low'|'medium'|'high',
    growthScore:scores.Growth,inflationScore:scores.Inflation,riskScore:scores.Stress,ratesPressureScore:scores.Rates,
    daysInRegime:model.days_in_regime,rawLabel:model.raw_quadrant,emergingLabel:model.emerging_label,emergingDays:model.emerging_days,
    changedSincePrevious:model.emerging_label?`Emerging: ${model.emerging_label} (${model.emerging_days} of 5 days). Official: ${model.quadrant}, day ${model.days_in_regime}.`:`Official: ${model.quadrant}, day ${model.days_in_regime}. No emerging quadrant.`,
    positiveSignals:model.signals.filter(s=>['Growth','Inflation'].includes(s.axis)&&s.percentile>=50).sort((a,b)=>b.percentile-a.percentile).slice(0,3).map(s=>s.name),
    negativeSignals:model.signals.filter(s=>['Growth','Inflation'].includes(s.axis)&&s.percentile<50).sort((a,b)=>a.percentile-b.percentile).slice(0,3).map(s=>s.name),
    limitations:['Latest revised macro vintage with approximate release lags; not point-in-time data.','Percentiles describe historical position, not forecasts or probabilities.','ETF ratios are proxies; growth does not measure GDP. Rates and the dollar are context only.']};
  const breadth=model.signals.find(s=>s.key==='sector_breadth');
  if(breadth) data.breadth=[{symbol:'BREADTH',name:'Sectors above 200-day MA',value:Math.round(breadth.raw_value*100),dayChange:null,monthReturn:null,observationDate:model.date,signal:`${Math.round(breadth.raw_value*11)} of 11 sector ETFs · ${breadth.percentile.toFixed(0)}/100 percentile`}];
  data.analystNote={title:model.headline,bullets:[model.driver_sentence,`Growth ${scores.Growth.toFixed(1)} and Inflation ${scores.Inflation.toFixed(1)} determine the quadrant; Stress ${scores.Stress.toFixed(1)} is an independent daily overlay.`, `Rates context ${scores.Rates.toFixed(1)}/100 and dollar trend ${scores.Dollar.toFixed(1)}/100 do not drive the label. Research software, not investment advice.`],watchItems:model.nearest_flips.map(x=>x.text)};
  return data;
}

export function BottomLine({model}:{model:RegimeV2}) {
 return <section className="panel bottom-line" aria-labelledby="bottom-line-title">
  <span className="eyebrow">Bottom line · Daily research model</span>
  <div className="bottom-line-heading"><h2 id="bottom-line-title">{model.headline}</h2><span className={`confidence ${model.confidence.label.toLowerCase()}`}>{model.confidence.label} confidence</span></div>
  <p className="bottom-line-driver">{model.driver_sentence}</p>
  {model.emerging_label&&<p className="emerging-read">Emerging: {model.emerging_label} ({model.emerging_days} of 5 days)</p>}
  <dl className="confidence-components"><div><dt>Axis magnitude</dt><dd>{model.confidence.magnitude.toFixed(1)}/100</dd></div><div><dt>Signal agreement</dt><dd>{model.confidence.agreement.toFixed(1)}%</dd></div><div><dt>Confidence score</dt><dd>{model.confidence.score.toFixed(1)}/100</dd></div></dl>
  <p className="chart-note">Completed closes · {formatDate(model.date)}. Growth and Inflation define the quadrant; Stress can change daily. Confidence describes agreement, not a probability.</p>
  <div className="nearest-flips"><h3>What would change the call</h3>{model.nearest_flips.length?<ul>{model.nearest_flips.map(item=><li key={item.key}>{item.text}</li>)}</ul>:<p>No single input can cross the nearest boundary on its own.</p>}<p className="chart-note">{model.nearest_flip_note}</p></div>
 </section>;
}
